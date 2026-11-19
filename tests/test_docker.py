import os
import re
from unittest import mock

from flask.testing import FlaskClient

from support import ROOT, TemporaryDataTest, MockPrices
from app import server


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


class NetworkMode(TemporaryDataTest):

    def setUp(self):
        super().setUp()
        self.patches = [mock.patch.object(server, "DATA_DIR", self.directory), MockPrices(),
                        mock.patch.dict(os.environ, {"PATRIMONIO_HOST": "0.0.0.0", "PATRIMONIO_DOCKER": "1"})]
        for p in self.patches:
            p.__enter__()
        server._ACCESS_KEYS.clear()
        self.web = server.app.test_client()
        self.extrano = FlaskClient(server.app)

    def tearDown(self):
        for p in reversed(self.patches):
            p.__exit__(None, None, None)
        server._ACCESS_KEYS.clear()
        super().tearDown()

    def test_accepts_local_network_hosts(self):
        for host in ("192.168.1.50:8765", "10.0.0.7:8765", "172.20.1.2:8765", "100.101.102.103:8765",
                     "nas:8765", "raspberrypi.local:8765", "finappgo.lan:8765", "minas.tail1234.ts.net:8765",
                     "[fd00::1]:8765", "localhost:8765"):
            with self.subTest(host=host):
                self.assertTrue(server.valid_host(host))
                if not host.startswith("["):
                    self.assertEqual(self.web.get("/api/cartera", headers={"Host": host}).status_code, 200)

    def test_rejects_public_hosts(self):
        for host in ("evil.com", "finappgo.evil.com:8765", "8.8.8.8:8765", "nas.example.org"):
            with self.subTest(host=host):
                self.assertFalse(server.valid_host(host))
                self.assertEqual(self.web.get("/api/cartera", headers={"Host": host}).status_code, 403)

    def test_explicitly_allows_custom_hostname(self):
        with mock.patch.dict(os.environ, {"PATRIMONIO_HOSTS_PERMITIDOS": "finappgo.midominio.com"}):
            self.assertTrue(server.valid_host("finappgo.midominio.com:8765"))

    def test_network_mode_requires_access_key(self):
        cab = {"Host": "192.168.1.50:8765"}
        self.assertEqual(self.extrano.get("/api/cartera", headers=cab).status_code, 403)
        self.assertEqual(self.extrano.post("/api/reiniciar", json={"a": "vacia"}, headers=cab).status_code, 403)
        r = self.extrano.get("/?acceso=" + server.access_token(), headers=cab)
        self.assertEqual(r.status_code, 302)

    def test_accepts_same_origin_form_on_lan(self):
        cab = {"Host": "192.168.1.50:8765", "Origin": "http://192.168.1.50:8765", "Sec-Fetch-Site": "same-origin"}
        self.assertEqual(self.web.post("/api/empezar", json={"desde": "vacia"}, headers=cab).status_code, 200)
        cab_mala = {"Host": "192.168.1.50:8765", "Origin": "https://evil.com"}
        self.assertEqual(self.web.post("/api/reiniciar", json={"a": "vacia"}, headers=cab_mala).status_code, 403)

    def test_version_endpoint_reports_docker_mode(self):
        self.assertTrue(self.web.get("/api/version").get_json()["docker"])


class WithoutDocker(TemporaryDataTest):
    def test_local_mode_accepts_only_loopback(self):
        with mock.patch.dict(os.environ, {"PATRIMONIO_HOST": ""}):
            self.assertFalse(server.on_network())
            self.assertFalse(server.valid_host("192.168.1.50:8765"))
            self.assertFalse(server.valid_host("nas:8765"))
            self.assertTrue(server.valid_host("127.0.0.1:8765"))


class DockerFiles(TemporaryDataTest):
    def test_dockerfile(self):
        d = read("Dockerfile")
        for portion in ("PATRIMONIO_DATOS=/data", "PATRIMONIO_HOST=0.0.0.0", "PATRIMONIO_NO_ABRIR=1",
                      "PATRIMONIO_DOCKER=1", 'VOLUME ["/data"]', "EXPOSE 8765", "HEALTHCHECK", "/api/ping",
                      "requirements.txt", "COPY app ./app", "COPY demo ./demo"):
            self.assertIn(portion, d)
        self.assertRegex(d, r"\nUSER finappgo\n")
        self.assertLess(d.index("USER finappgo"), d.index("CMD"))

    def test_compose(self):
        c = read("docker-compose.yml")
        self.assertIn("8765:8765", c)
        self.assertRegex(c, r"finappgo_datos:/data")
        self.assertIn("restart: unless-stopped", c)

    def test_excludes_local_data_from_image(self):
        ignora = read(".dockerignore").split()
        for x in ("mis_datos", ".venv", ".git", "tests"):
            self.assertIn(x, ignora)

    def test_github_builds_pull_requests_and_publishes_main(self):
        workflow = read(os.path.join(".github", "workflows", "container.yml"))
        self.assertIn("pull_request:", workflow)
        self.assertIn("platforms: linux/amd64", workflow)
        self.assertIn("github.event_name == 'push' && github.ref == 'refs/heads/main'", workflow)

    def test_docker_python_version_and_port(self):
        self.assertRegex(read("Dockerfile"), r"FROM python:3\.1[0-9]")
        self.assertEqual(int(re.search(r"PATRIMONIO_PUERTO=(\d+)", read("Dockerfile")).group(1)), 8765)

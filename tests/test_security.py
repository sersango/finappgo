import json
import os
from unittest import mock

from support import TemporaryDataTest, MockPrices, portfolio, etf, read_demo, mov
from app import engine, server


class RequestGuard(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        self.patches = [mock.patch.object(server, "DATA_DIR", self.directory), MockPrices()]
        for p in self.patches:
            p.__enter__()
        self.web = server.app.test_client()
        self.web.post("/api/empezar", json={"desde": "vacia"})

    def tearDown(self):
        for p in reversed(self.patches):
            p.__exit__(None, None, None)
        super().tearDown()

    def test_cross_origin_page_cannot_read_portfolio(self):
        r = self.web.get("/datos.js", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"})
        self.assertEqual(r.status_code, 403)
        self.assertNotIn(b"window.DATOS", r.data)

    def test_other_local_app_cannot_access_portfolio(self):
        r = self.web.get("/api/cartera", headers={"Sec-Fetch-Site": "same-site"})
        self.assertEqual(r.status_code, 403)

    def test_same_origin_can_load_dashboard(self):
        r = self.web.get("/datos.js", headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.web.get("/api/cartera").status_code, 200)

    def test_access_url_opens_dashboard(self):
        r = self.web.get("/", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"})
        self.assertEqual(r.status_code, 200)
        r = self.web.get("/datos.js", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"})
        self.assertEqual(r.status_code, 403)

    def test_dns_rebinding(self):
        r = self.web.get("/datos.js", headers={"Host": "evil.com:8765"})
        self.assertEqual(r.status_code, 403)
        r = self.web.get("/api/cartera", base_url="http://127.0.0.1:8765")
        self.assertEqual(r.status_code, 200)
        r = self.web.get("/api/cartera", base_url="http://[::1]:8765")
        self.assertEqual(r.status_code, 200)

    def test_cross_origin_form_cannot_write(self):
        for cab in ({"Origin": "https://evil.com"}, {"Referer": "https://evil.com/trampa.html"},
                    {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(header=cab):
                r = self.web.post("/api/reiniciar", json={"a": "vacia"}, headers=cab)
                self.assertEqual(r.status_code, 403)
                r = self.web.post("/api/productos", json={"nombre": "X", "tipo": "otro"}, headers=cab)
                self.assertEqual(r.status_code, 403)
        self.assertEqual(self.web.get("/api/cartera").get_json()["cartera"]["productos"], [])

    def test_accepts_same_origin_form(self):
        r = self.web.post("/api/productos", json={"nombre": "Oro", "tipo": "commodity", "fuente": "manual"},
                          headers={"Origin": "http://127.0.0.1:8765", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(r.status_code, 200, r.get_json())

    def test_ping_is_always_available(self):
        r = self.web.get("/api/ping", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status_code, 200)

    def test_security_headers(self):
        r = self.web.get("/datos.js")
        self.assertEqual(r.headers.get("Cross-Origin-Resource-Policy"), "same-origin")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")

    def test_allows_configured_hosts(self):
        with mock.patch.dict(os.environ, {"PATRIMONIO_HOSTS_PERMITIDOS": "finappgo.casa"}):
            self.assertEqual(self.web.get("/api/cartera", headers={"Host": "finappgo.casa:8765"}).status_code, 200)
        self.assertEqual(self.web.get("/api/cartera", headers={"Host": "finappgo.casa:8765"}).status_code, 403)


class SanitizedText(TemporaryDataTest):
    def test_strips_html_from_dashboard_names(self):
        malo = '<img src=x onerror="fetch(1)">Fondo'
        cfg = portfolio([etf("a", nombre=malo, corto=malo)], [mov("2024-01-02", "a", "compra", 10, 100)])
        cfg["titular"] = "<script>alert(1)</script>Yo"
        with MockPrices():
            data = engine.build_dashboard(cfg, self.directory, fetch_prices=False)
        text = json.dumps(data, ensure_ascii=False)
        self.assertNotIn("<img", text)
        self.assertNotIn("<script", text)
        self.assertIn("Fondo", data["productos"][0]["nombre"])

    def test_saving_sanitizes_input(self):
        from app import storage
        cfg = portfolio()
        p, _ = storage.save_product(cfg, {"nombre": "<b>Piso</b>", "tipo": "inmueble", "fuente": "manual"})
        self.assertEqual(p["nombre"], "bPiso/b")

    def test_demo_is_unchanged(self):
        with MockPrices():
            data = engine.build_dashboard(read_demo(), self.directory, fetch_prices=False)
        self.assertGreater(data["total"]["patrimonio"], 0)


class ReleaseNotes(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        server._RELEASE_NOTES_CACHE.clear()
        self.web = server.app.test_client()

    def tearDown(self):
        server._RELEASE_NOTES_CACHE.clear()
        super().tearDown()

    def test_validates_remote_release_notes(self):
        n = server.validate_release_notes({"version": "2.0.0", "titulo": "<b>FinAppGo 2.0</b>",
                                       "novedades": ["Traspasos", "<script>x</script>", 7],
                                       "video": "javascript:alert(1)"})
        self.assertEqual(n["titulo"], "bFinAppGo 2.0/b")
        self.assertEqual(n["novedades"], ["Traspasos", "scriptx/script"])
        self.assertIsNone(n["video"])
        self.assertEqual(server.validate_release_notes({"version": "2.0.0", "video": "https://youtu.be/abc_12-X"})["video"],
                         "https://youtu.be/abc_12-X")
        self.assertIsNone(server.validate_release_notes({"version": "dos"}))

    def test_works_offline(self):
        r = self.web.get("/api/novedades")
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertIsNone(j["nueva"])

    def test_newer_version_on_github(self):
        server._RELEASE_NOTES_CACHE.update(remota={"version": "99.0.0", "titulo": "FinAppGo 99", "novedades": ["X"],
                                           "video": "https://youtu.be/abc"},
                                   cuando=server.dt.datetime.now())
        j = self.web.get("/api/novedades").get_json()
        self.assertEqual(j["nueva"]["version"], "99.0.0")
        self.assertEqual(j["nueva"]["video"], "https://youtu.be/abc")


class SupportDiagnostics(TemporaryDataTest):
    def test_omits_portfolio_data(self):
        with mock.patch.object(server, "DATA_DIR", self.directory), MockPrices():
            web = server.app.test_client()
            web.post("/api/empezar", json={"desde": "vacia"})
            web.post("/api/productos", json={"nombre": "Mi piso secreto", "tipo": "inmueble", "fuente": "manual"})
            j = web.get("/api/diagnostico").get_json()
        self.assertIn("FinAppGo ", j["texto"])
        self.assertIn("productos: 1", j["texto"])
        self.assertNotIn("secreto", j["texto"])

import base64
import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.parse
from unittest import mock

from flask.testing import FlaskClient

from support import TemporaryDataTest, MockPrices, portfolio, mov
from app import search, exposure, engine, network, server


class ServerTest(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        self.patches = [mock.patch.object(server, "DATA_DIR", self.directory), MockPrices()]
        for p in self.patches:
            p.__enter__()
        server._ACCESS_KEYS.clear()
        self.web = server.app.test_client()
        self.extrano = FlaskClient(server.app)
        self.web.post("/api/empezar", json={"desde": "vacia"})

    def tearDown(self):
        for p in reversed(self.patches):
            p.__exit__(None, None, None)
        server._ACCESS_KEYS.clear()
        super().tearDown()


class AccessKey(ServerTest):
    def test_missing_key_prevents_reads_and_writes(self):
        for url in ("/", "/datos.js", "/api/cartera", "/api/copia/descargar", "/api/exportar-web",
                    "/api/exportar-excel", "/api/diagnostico", "/app.js"):
            with self.subTest(url=url):
                self.assertEqual(self.extrano.get(url).status_code, 403)
        for url, data in (("/api/productos", {"nombre": "X", "tipo": "otro"}), ("/api/reiniciar", {"a": "vacia"}),
                           ("/api/perfiles", {"nombre": "Intruso"})):
            with self.subTest(url=url):
                self.assertEqual(self.extrano.post(url, json=data).status_code, 403)
        self.assertEqual(self.web.get("/api/cartera").get_json()["cartera"]["productos"], [])

    def test_protected_routes_require_key_and_same_origin(self):
        before = json.dumps(self.web.get("/api/cartera").get_json()["cartera"], sort_keys=True)
        rutas = 0
        for regla in server.app.url_map.iter_rules():
            if regla.endpoint == "static" or regla.rule == "/api/ping":
                continue
            url = re.sub(r"<(?:[^:>]+:)?([^>]+)>", lambda m: "x" + m.group(1), regla.rule)
            for metodo in sorted(regla.methods - {"HEAD", "OPTIONS"}):
                rutas += 1
                with self.subTest(path=f"{metodo} {regla.rule}"):
                    r = self.extrano.open(url, method=metodo, json={})
                    self.assertEqual(r.status_code, 403, "sin llave")
                    if metodo != "GET":
                        r = self.web.open(url, method=metodo, json={},
                                          headers={"Origin": "https://evil.com", "Sec-Fetch-Site": "cross-site"})
                        self.assertEqual(r.status_code, 403, "desde otra web")
        self.assertGreater(rutas, 40)
        self.assertEqual(json.dumps(self.web.get("/api/cartera").get_json()["cartera"], sort_keys=True), before)

    def test_access_required_page_explains_login(self):
        r = self.extrano.get("/")
        self.assertIn("Abre FinAppGo con el enlace de acceso", r.get_data(as_text=True))
        self.assertNotIn("window.DATOS", r.get_data(as_text=True))

    def test_access_key_sets_cookie(self):
        url = server.access_url(8765)
        access_key = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["acceso"][0]
        r = self.extrano.get(f"/?acceso={access_key}")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(urllib.parse.urlsplit(r.headers["Location"]).query, "")
        cookie = r.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertEqual(self.extrano.get("/api/cartera").status_code, 200)

    def test_rejects_invalid_access_key(self):
        self.assertEqual(self.extrano.get("/?acceso=" + "x" * 43).status_code, 403)
        self.extrano.set_cookie(server.COOKIE, "y" * 43)
        self.assertEqual(self.extrano.get("/api/cartera").status_code, 403)

    def test_access_key_is_persisted_and_recovers_from_corruption(self):
        access_key = server.access_token()
        self.assertGreaterEqual(len(access_key), 40)
        path = os.path.join(self.directory, ".acceso")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), access_key)
        server._ACCESS_KEYS.clear()
        self.assertEqual(server.access_token(), access_key)
        with open(path, "w", encoding="utf-8") as f:
            f.write("corta")
        server._ACCESS_KEYS.clear()
        self.assertNotEqual(server.access_token(), "corta")

    def test_ping_is_public_and_contains_no_portfolio_data(self):
        r = self.extrano.get("/api/ping")
        self.assertEqual(r.get_json(), {"app": "patrimonio"})


class PagePolicy(ServerTest):
    def test_csp(self):
        csp = self.web.get("/").headers["Content-Security-Policy"]
        for portion in ("default-src 'self'", "object-src 'none'", "frame-ancestors 'none'", "base-uri 'none'",
                      "img-src 'self' data:"):
            self.assertIn(portion, csp)
        self.assertNotIn("unsafe-eval", csp)
        script = re.search(r"script-src ([^;]+)", csp).group(1)
        self.assertNotIn("unsafe-inline", script)
        with open(os.path.join(server.WEB, "index.html"), encoding="utf-8") as f:
            code = re.findall(r'<script id="script-loader">(.*?)</script>', f.read(), flags=re.S)
        self.assertEqual(len(code), 1)
        huella = base64.b64encode(hashlib.sha256(code[0].encode()).digest()).decode()
        self.assertIn(f"'sha256-{huella}'", script)

    def test_no_inline_event_handlers(self):
        for name in os.listdir(server.WEB):
            if name.endswith((".js", ".html")):
                with open(os.path.join(server.WEB, name), encoding="utf-8") as f:
                    text = f.read()
                with self.subTest(file=name):
                    self.assertIsNone(re.search(r"\son[a-z]+=[\"']", text))
                    self.assertNotIn("javascript:", text)
                    self.assertNotIn("eval(", text)

    def test_response_headers(self):
        r = self.web.get("/datos.js")
        for k, v in (("X-Frame-Options", "DENY"), ("X-Content-Type-Options", "nosniff"),
                     ("Referrer-Policy", "no-referrer"), ("Cross-Origin-Resource-Policy", "same-origin"),
                     ("Cross-Origin-Opener-Policy", "same-origin")):
            self.assertEqual(r.headers.get(k), v)


class Uploads(ServerTest):
    def sube_copia(self, cfg):
        data = json.dumps(cfg).encode()
        return self.web.post("/api/copia/subir", data={"archivo": (io.BytesIO(data), "copia.json")},
                             content_type="multipart/form-data")

    def test_rejects_tampered_backup(self):
        buena = portfolio([{"id": "a", "nombre": "A", "tipo": "otro", "fuente": "manual"}])
        malas = [
            {**buena, "productos": [{"id": 'a" onmouseover="x', "nombre": "A"}]},
            {**buena, "movimientos": [{"fecha": "2024-01-02", "producto": "otro", "tipo": "compra", "importe": 1}]},
            {**buena, "movimientos": [{"fecha": "2024-01-02", "producto": "a", "tipo": "compra", "importe": "1e9"}]},
            {**buena, "valoraciones": [{"fecha": "ayer", "producto": "a", "valor": 1}]},
            {**buena, "productos": ["no soy un producto"]},
        ]
        for mala in malas:
            with self.subTest(mala=json.dumps(mala)[:80]):
                self.assertEqual(self.sube_copia(mala).status_code, 400)
        self.assertEqual(self.sube_copia(buena).status_code, 200)

    def test_oversized_file(self):
        grande = io.BytesIO(b"x" * (server.UPLOAD_LIMIT + 1))
        r = self.web.post("/api/copia/subir", data={"archivo": (grande, "copia.json")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 413)

    def test_ignores_invalid_profile_id(self):
        with open(os.path.join(self.directory, "perfiles.json"), "w", encoding="utf-8") as f:
            json.dump({"activo": "../../fuera", "lista": [{"id": "../../fuera", "nombre": "X"}]}, f)
        self.assertEqual(server.profiles()["activo"], "principal")
        self.assertEqual([x["id"] for x in server.profiles()["lista"]], ["principal"])


class OutboundRequests(TemporaryDataTest):

    IMPORTE, UNIDADES, VALOR = 73519.37, 98.7654, 41267.83

    def setUp(self):
        super().setUp()
        self.salidas = []

        def apunta(req, timeout=None, *a, **k):
            self.salidas.append({"url": req.full_url, "metodo": req.get_method(), "cuerpo": req.data,
                                 "cabeceras": dict(req.header_items())})
            raise urllib.error.URLError("sin red en los tests")
        self.patches = [mock.patch("urllib.request.urlopen", apunta), mock.patch.object(search.time, "sleep")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def test_sends_only_instrument_ids_to_allowed_hosts(self):
        cfg = portfolio(
            [{"id": "w", "nombre": "Mi fondo World", "tipo": "fondo", "fuente": "morningstar", "codigo": "0P0001CLDK",
              "identificador": "IE00BYX5NX33", "slot": 1},
             {"id": "e", "nombre": "Mi ETF", "tipo": "etf", "fuente": "yahoo", "codigo": "IWDA.AS", "moneda": "USD",
              "identificador": "IE00B4L5Y983", "slot": 2},
             {"id": "b", "nombre": "Bitcoin", "tipo": "cripto", "fuente": "coingecko", "codigo": "bitcoin", "slot": 3},
             {"id": "p", "nombre": "Plan", "tipo": "pension", "fuente": "morningstar", "codigo": "F000016CB6", "slot": 4},
             {"id": "c", "nombre": "Cuenta", "tipo": "efectivo", "fuente": "manual", "slot": 5}],
            [mov("2024-01-02", "w", "compra", self.UNIDADES, self.IMPORTE), mov("2024-01-02", "e", "compra", 3, 999.11),
             mov("2024-01-02", "b", "compra", 0.123456, 5555.55), mov("2024-01-02", "p", "compra", 12, 3333.33)],
            [{"id": "v1", "producto": "c", "fecha": "2024-06-03", "valor": self.VALOR}])
        engine.build_dashboard(cfg, self.directory, fetch_prices=True)
        for p in cfg["productos"]:
            exposure.product_exposure({**p, "tipoClave": p["tipo"]}, os.path.join(self.directory, "cache"))
        search.search("IE00BYX5NX33")
        search.search("MyInvestor Indexado Global")
        with mock.patch.object(server, "DATA_DIR", self.directory):
            server._VERSION.clear()
            server._RELEASE_NOTES_CACHE.clear()
            web = server.app.test_client()
            web.get("/api/version")
            web.get("/api/novedades")

        self.assertGreater(len(self.salidas), 10)
        hosts = {urllib.parse.urlsplit(s["url"]).hostname for s in self.salidas}
        self.assertLessEqual(hosts, set(network.PERMITIDOS), hosts - set(network.PERMITIDOS))
        cifras = ("73519", "7351937", "98.7654", "98,7654", "41267", "5555", "3333", "999.11", "0.123456")
        for s in self.salidas:
            with self.subTest(url=s["url"]):
                self.assertTrue(s["url"].startswith("https://"))
                self.assertEqual(s["metodo"], "GET")
                self.assertIsNone(s["cuerpo"])
                self.assertNotIn("Cookie", s["cabeceras"])
                for c in cifras:
                    self.assertNotIn(c, s["url"])
                for name in ("Mi fondo World", "Mi ETF", "Mi+fondo", "Mi%20fondo"):
                    self.assertNotIn(name, s["url"])

    def test_network_disallows_unknown_hosts(self):
        for url in ("http://lt.morningstar.com/x", "https://evil.com/robar?datos=1", "ftp://raw.githubusercontent.com/x",
                    "https://lt.morningstar.com.evil.com/x"):
            with self.subTest(url=url), self.assertRaises(network.DisallowedHost):
                network.open_url(url)
        self.assertEqual(self.salidas, [])

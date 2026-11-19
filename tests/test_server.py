import io
import json
import os
import unittest
from unittest import mock

from support import TemporaryDataTest, MockPrices
from app import server


class PortfolioApi(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        self.patches = [mock.patch.object(server, "DATA_DIR", self.directory), MockPrices()]
        for p in self.patches:
            p.__enter__()
        self.web = server.app.test_client()

    def tearDown(self):
        for p in reversed(self.patches):
            p.__exit__(None, None, None)
        super().tearDown()

    def post(self, url, data=None):
        r = self.web.post(url, json=data or {})
        return r.status_code, r.get_json()

    def empieza(self):
        self.assertEqual(self.post("/api/empezar", {"desde": "vacia"})[0], 200)

    def test_demo_is_read_only(self):
        self.assertEqual(self.web.get("/").status_code, 200)
        self.assertEqual(self.web.get("/datos.js").status_code, 200)
        self.assertEqual(server.mode(), "demo")
        code, j = self.post("/api/productos", {"nombre": "X", "tipo": "otro"})
        self.assertEqual(code, 403)
        self.assertIn("Empezar con mis datos", j["errores"][0])
        self.assertFalse(os.path.exists(os.path.join(self.directory, "cartera.json")))

    def test_builds_demo_dashboard(self):
        data = server.recalculate(fetch_prices=False)
        self.assertEqual(data["modo"], "demo")
        self.assertGreater(data["total"]["patrimonio"], 0)

    def test_initialize_save_and_delete(self):
        self.empieza()
        self.assertEqual(server.mode(), "propio")
        code, j = self.post("/api/productos", {"nombre": "Piso", "tipo": "inmueble", "fuente": "manual"})
        self.assertEqual(code, 200, j)
        pid = j["item"]["id"]
        code, j = self.post("/api/valoraciones", {"producto": pid, "fecha": "2025-01-02", "valor": "150.000"})
        self.assertEqual(code, 200, j)
        cfg = self.web.get("/api/cartera").get_json()["cartera"]
        self.assertEqual(cfg["valoraciones"][0]["valor"], 150000)
        code, j = self.post("/api/movimientos", {"producto": pid, "tipo": "compra", "fecha": "2999-01-01"})
        self.assertEqual(code, 400)
        self.assertEqual(self.web.delete(f"/api/productos/{pid}").status_code, 200)
        self.assertEqual(self.web.get("/api/cartera").get_json()["cartera"]["productos"], [])

    def test_cannot_initialize_twice(self):
        self.empieza()
        self.assertEqual(self.post("/api/empezar", {"desde": "vacia"})[0], 400)

    def test_backup_round_trip(self):
        self.empieza()
        self.post("/api/productos", {"nombre": "Oro", "tipo": "commodity", "fuente": "manual"})
        backup = self.web.get("/api/copia/descargar").data
        self.post("/api/reiniciar", {"a": "vacia"})
        self.assertEqual(self.web.get("/api/cartera").get_json()["cartera"]["productos"], [])
        r = self.web.post("/api/copia/subir", data={"archivo": (io.BytesIO(backup), "copia.json")},
                          content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.web.get("/api/cartera").get_json()["cartera"]["productos"][0]["nombre"], "Oro")
        backups = os.listdir(os.path.join(self.directory, "copias"))
        self.assertTrue(any(n.startswith("antes_de_reiniciar") for n in backups))

    def test_rejects_non_backup_upload(self):
        self.empieza()
        r = self.web.post("/api/copia/subir", data={"archivo": (io.BytesIO(b'{"hola": 1}'), "x.json")},
                          content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)

    def test_private_export_hides_original_amounts(self):
        self.empieza()
        _, j = self.post("/api/productos", {"nombre": "Piso", "tipo": "inmueble", "fuente": "manual"})
        self.post("/api/valoraciones", {"producto": j["item"]["id"], "fecha": "2025-01-02", "valor": 123456.78})
        normal = self.web.get("/api/exportar-web").data.decode()
        oculto = self.web.get("/api/exportar-web?ocultar=1").data.decode()
        self.assertIn("123456.78", normal)
        self.assertNotIn("123456.78", oculto)
        self.assertNotIn("123.456", oculto)
        self.assertIn("OCULTAR_IMPORTES", oculto)

    def test_version_check_works_offline(self):
        server._VERSION.clear()
        j = self.web.get("/api/version").get_json()
        self.assertFalse(j["hayNueva"])
        self.assertEqual(j["actual"], server.current_version())

    def test_templates_and_import_prompt(self):
        self.assertEqual(self.web.get("/api/plantilla.xlsx").status_code, 200)
        self.assertTrue(self.web.get("/api/plantilla.csv").data.startswith(b"\xef\xbb\xbffecha;"))
        self.assertIn("BORRA", self.web.get("/api/prompt").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

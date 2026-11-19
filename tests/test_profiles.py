import json
import os
from unittest import mock

from support import TemporaryDataTest, MockPrices
from app import server


class Profiles(TemporaryDataTest):
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

    def mi_cartera_con(self, nombre_producto, value):
        code, j = self.post("/api/productos", {"nombre": nombre_producto, "tipo": "inmueble", "fuente": "manual"})
        self.assertEqual(code, 200, j)
        code, j = self.post("/api/valoraciones", {"producto": j["item"]["id"], "fecha": "2025-01-02", "valor": value})
        self.assertEqual(code, 200, j)

    def test_legacy_single_portfolio_still_loads(self):
        self.assertEqual(server.profiles()["activo"], "principal")
        self.assertEqual(server.directory(), self.directory)
        self.assertEqual(server.mode(), "demo")
        self.assertFalse(os.path.exists(os.path.join(self.directory, "perfiles.json")))

    def test_create_and_switch_profile(self):
        self.post("/api/empezar", {"desde": "vacia"})
        self.mi_cartera_con("Piso", 200000)
        code, j = self.post("/api/perfiles", {"nombre": "Ana"})
        self.assertEqual(code, 200, j)
        self.assertEqual(server.profiles()["activo"], "ana")
        self.assertEqual(server.mode(), "propio")
        self.assertEqual(self.web.get("/api/cartera").get_json()["cartera"]["productos"], [])
        self.mi_cartera_con("Fondo de Ana", 5000)
        self.assertTrue(os.path.exists(os.path.join(self.directory, "perfiles", "ana", "cartera.json")))
        with open(os.path.join(self.directory, "cartera.json"), encoding="utf-8") as f:
            self.assertEqual([p["nombre"] for p in json.load(f)["productos"]], ["Piso"])
        self.assertEqual(self.post("/api/perfiles/activar", {"id": "principal"})[0], 200)
        self.assertEqual([p["nombre"] for p in self.web.get("/api/cartera").get_json()["cartera"]["productos"]], ["Piso"])

    def test_combined_view_sums_profiles_and_is_read_only(self):
        self.post("/api/empezar", {"desde": "vacia"})
        self.mi_cartera_con("Piso", 200000)
        self.post("/api/perfiles", {"nombre": "Ana"})
        self.mi_cartera_con("Piso", 5000)
        self.assertEqual(self.post("/api/perfiles/activar", {"id": "todos"})[0], 200)
        data = server.recalculate(fetch_prices=False)
        self.assertEqual(data["total"]["patrimonio"], 205000)
        self.assertEqual(data["modo"], "todos")
        names = sorted(p["nombre"] for p in data["productos"])
        self.assertEqual(names, ["Piso (Ana)", "Piso (Yo)"])
        code, j = self.post("/api/productos", {"nombre": "X", "tipo": "otro"})
        self.assertEqual(code, 403)
        self.assertIn("Todos juntos", j["errores"][0])
        self.assertEqual(self.post("/api/reiniciar", {"a": "vacia"})[0], 400)
        with open(os.path.join(self.directory, "historico.json"), encoding="utf-8") as f:
            self.assertNotIn(205000, [h["patrimonio"] for h in json.load(f)])

    def test_combined_view_requires_two_populated_profiles(self):
        self.post("/api/empezar", {"desde": "vacia"})
        self.assertEqual(self.post("/api/perfiles/activar", {"id": "todos"})[0], 400)
        self.assertFalse(self.web.get("/api/perfiles").get_json()["todos"])

    def test_rename_and_delete_profile(self):
        self.post("/api/empezar", {"desde": "vacia"})
        self.post("/api/perfiles", {"nombre": "Hijo"})
        self.assertEqual(self.post("/api/perfiles/renombrar", {"id": "hijo", "nombre": "Lucas"})[0], 200)
        self.assertEqual(self.post("/api/perfiles/renombrar", {"id": "principal", "nombre": "Dani"})[0], 200)
        names = [x["nombre"] for x in self.web.get("/api/perfiles").get_json()["lista"]]
        self.assertEqual(names, ["Dani", "Lucas"])
        self.assertEqual(self.post("/api/perfiles/borrar", {"id": "principal"})[0], 400)
        self.assertEqual(self.post("/api/perfiles/borrar", {"id": "hijo"})[0], 200)
        self.assertEqual(server.profiles()["activo"], "principal")
        self.assertFalse(os.path.exists(os.path.join(self.directory, "perfiles", "hijo")))
        borrados = [n for n in os.listdir(os.path.join(self.directory, "copias")) if n.startswith("perfil_borrado_hijo")]
        self.assertEqual(len(borrados), 1)

    def test_rejects_duplicate_or_empty_names(self):
        self.post("/api/empezar", {"desde": "vacia"})
        self.assertEqual(self.post("/api/perfiles", {"nombre": ""})[0], 400)
        self.post("/api/perfiles", {"nombre": "Ana"})
        self.assertEqual(self.post("/api/perfiles", {"nombre": "ana"})[0], 400)

    def test_profiles_have_separate_backups(self):
        self.post("/api/empezar", {"desde": "vacia"})
        self.mi_cartera_con("Piso", 1)
        self.post("/api/perfiles", {"nombre": "Ana"})
        self.mi_cartera_con("Coche", 1)
        backup = self.web.get("/api/copia/descargar").data
        self.assertIn(b"Coche", backup)
        self.assertNotIn(b"Piso", backup)

    def test_dashboard_script_includes_profiles(self):
        self.post("/api/empezar", {"desde": "vacia"})
        self.post("/api/perfiles", {"nombre": "Ana"})
        self.assertIn(b'window.PERFILES = {"activo": "ana"', self.web.get("/datos.js").data)


class StaleProfileTabs(Profiles):

    def test_stale_tab_cannot_write_to_another_profile(self):
        self.post("/api/empezar", {"desde": "vacia"})
        self.assertEqual(self.post("/api/perfiles", {"nombre": "Irmita"})[0], 200)
        active = server.profiles()["activo"]
        r = self.web.post("/api/productos", json={"nombre": "Piso", "tipo": "inmueble", "fuente": "manual"},
                          headers={"X-FinAppGo-Perfil": "principal" if active != "principal" else "irmita"})
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.get_json()["perfilCambiado"])
        self.assertIn("Recarga esta página", r.get_json()["errores"][0])
        r = self.web.post("/api/productos", json={"nombre": "Piso", "tipo": "inmueble", "fuente": "manual"},
                          headers={"X-FinAppGo-Perfil": active})
        self.assertEqual(r.status_code, 200)
        r = self.web.post("/api/productos", json={"nombre": "Coche", "tipo": "otro", "fuente": "manual"})
        self.assertEqual(r.status_code, 200)

    def test_can_always_switch_profiles(self):
        self.post("/api/empezar", {"desde": "vacia"})
        self.post("/api/perfiles", {"nombre": "Irmita"})
        r = self.web.post("/api/perfiles/activar", json={"id": "principal"}, headers={"X-FinAppGo-Perfil": "otro"})
        self.assertEqual(r.status_code, 200)

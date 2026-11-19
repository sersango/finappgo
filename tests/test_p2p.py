import json
import os
import shutil
import subprocess

from support import ROOT, TemporaryDataTest, MockPrices, portfolio, manual, mov
from app import storage, tax, imports, engine, spreadsheet


def plataforma():
    return portfolio([manual("mintos", kind="p2p")], [
        mov("2024-01-02", "mintos", "compra", 0, 1000),
        mov("2024-06-03", "mintos", "compra", 0, 500),
        mov("2025-03-31", "mintos", "dividendo", 0, 42.5),
    ], [
        {"id": "v1", "fecha": "2024-01-02", "producto": "mintos", "valor": 1000},
        {"id": "v2", "fecha": "2025-06-30", "producto": "mintos", "valor": 1560},
    ])


class PeerToPeerType(TemporaryDataTest):
    def test_has_dedicated_asset_category(self):
        self.assertIn("p2p", engine.PRODUCT_TYPES)
        self.assertEqual(engine.CLASE_DEFECTO["p2p"], "P2P y crowdfunding")
        self.assertIn("p2p", spreadsheet.TIPOS_PRODUCTO)
        p, _ = storage.save_product(portfolio(), {"nombre": "Urbanitae", "tipo": "p2p", "fuente": "manual"})
        self.assertEqual(p["tipo"], "p2p")

    def test_importer_recognizes_type(self):
        for text in ("p2p", "P2P", "Crowdfunding", "crowdlending", "préstamos P2P"):
            with self.subTest(text=text):
                self.assertEqual(imports.TIPO_PROD.get(imports.strip_accents(text)), "p2p")
        self.assertEqual(imports.TIPO_PROD.get("prestamo"), "deuda")

    def test_included_in_dashboard(self):
        with MockPrices():
            D = engine.build_dashboard(plataforma(), self.directory, fetch_prices=False)
        [p] = [x for x in D["productos"] if x["id"] == "mintos"]
        self.assertEqual(p["clase"], "P2P y crowdfunding")
        self.assertEqual(p["tipoClave"], "p2p")
        self.assertEqual(p["aportado"], 1500)
        self.assertEqual(p["valor"], 1560)
        self.assertEqual(p["cobros"]["dividendos"], 42.5)
        self.assertEqual(p["gananciaTotal"], 102.5)

    def test_income_report_lists_interest_separately(self):
        inf = tax.report(plataforma(), "2025")
        self.assertEqual(inf["totales"]["intereses"], 42.5)
        self.assertEqual(inf["totales"]["dividendos"], 0)
        self.assertEqual(inf["cobros"][0]["clase"], "Intereses")


NODE = shutil.which("node")


class NonEquityExposure(TemporaryDataTest):
    def test_excludes_asset_from_equity_exposure(self):
        if NODE is None:
            self.skipTest("Node.js is unavailable")
        code = ("const C = require(process.argv[1]);"
                  "console.log(JSON.stringify(C.FUERA_DE_BOLSA.includes('p2p')))")
        r = subprocess.run([NODE, "-e", code, os.path.join(ROOT, "app", "web", "calculations.js")],
                           capture_output=True, text=True)
        self.assertEqual(json.loads(r.stdout), True, r.stderr)

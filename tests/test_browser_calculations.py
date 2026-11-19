import glob
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from support import ROOT, TemporaryDataTest, MockPrices, read_demo
from app import engine

NODE = shutil.which("node")


@unittest.skipIf(NODE is None, "Node.js is unavailable: no se pueden probar las cuentas del navegador")
class BrowserCalculations(TemporaryDataTest):
    def test_runs_node_tests(self):
        files = sorted(glob.glob(os.path.join(ROOT, "tests", "js", "*.test.js")))
        self.assertGreaterEqual(len(files), 2)
        r = subprocess.run([NODE, "--test", *files],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])

    def test_share_summary_matches_dashboard(self):
        with MockPrices():
            D = engine.build_dashboard(read_demo(), self.directory, fetch_prices=False)
        path = os.path.join(self.directory, "datos.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(D, f, ensure_ascii=False)
        code = ("const C = require(process.argv[1]); const D = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));"
                  "console.log(JSON.stringify(C.resumenParaCompartir(D)));")
        r = subprocess.run([NODE, "-e", code, os.path.join(ROOT, "app", "web", "calculations.js"), path],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        ult = D["resumenMensual"][-1]
        self.assertEqual(d["mes"], ult["mes"])
        self.assertAlmostEqual(d["rentMes"], ult["rentabilidad"], places=4)
        ra = D["rentabilidadAnual"]
        self.assertEqual(ra["anos"][-1], str(d["ano"]))
        self.assertAlmostEqual(d["anoPct"], ra["cartera"][-1], places=3)
        self.assertAlmostEqual(d["tir"], D["total"]["tir"], places=4)

    def test_browser_and_engine_calculations_match(self):
        with MockPrices():
            D = engine.build_dashboard(read_demo(), self.directory, fetch_prices=False)
        path = os.path.join(self.directory, "datos.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(D, f, ensure_ascii=False)
        code = (
            "const C = require(process.argv[1]); const D = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));"
            "const todos = D.productos.concat(D.otrosActivos || [], D.pasivos || []);"
            "const m = C.metricas(todos, D);"
            "console.log(JSON.stringify({valor: m.valor, aportado: m.aportado, plusvalia: m.plusvalia, tir: m.tir,"
            " ritmo: m.ritmo, racha: m.racha, caida: m.caida, ultimo: m.serie[m.serie.length - 1]}));")
        r = subprocess.run([NODE, "-e", code, os.path.join(ROOT, "app", "web", "calculations.js"), path],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        js = json.loads(r.stdout)
        t = D["total"]
        self.assertAlmostEqual(js["valor"], t["patrimonio"], places=1)
        self.assertAlmostEqual(js["ultimo"], t["patrimonio"], places=1)
        self.assertAlmostEqual(js["aportado"], t["aportado"], places=1)
        self.assertAlmostEqual(js["plusvalia"], t["plusvalia"], places=1)
        self.assertAlmostEqual(js["tir"], t["tir"], places=3)
        self.assertAlmostEqual(js["ritmo"], t["ritmoMensual"], places=1)
        self.assertEqual(js["racha"], t["racha"])
        self.assertAlmostEqual(js["caida"], t["caidaMaxima"], places=3)


class ShareOnlyInApp(TemporaryDataTest):
    def test_share_script_is_excluded_from_exports(self):
        from app import export
        with open(os.path.join(ROOT, "app", "web", "index.html"), encoding="utf-8") as f:
            self.assertIn('"share.js"', f.read())
        with MockPrices():
            D = engine.build_dashboard(read_demo(), self.directory, fetch_prices=False)
        html = export.render_page(os.path.join(ROOT, "app", "web"), D)
        self.assertNotIn("raiz.Compartir = M", html)
        self.assertNotIn("QR: descargar FinAppGo", html)

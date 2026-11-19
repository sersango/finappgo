import datetime as dt
import io
import json
import os
import unittest
from unittest import mock

from support import ROOT, TemporaryDataTest, MockPrices, portfolio, etf, manual, mov, mock_series
from app import export, imports, engine, spreadsheet, server


class Dividends(TemporaryDataTest):
    def calcula(self):
        today = dt.date.today()
        hace = lambda dias: (today - dt.timedelta(days=dias)).isoformat()
        cfg = portfolio([etf("ko", "KO", tipo="accion"), etf("vti", "VTI.DE")], [
            mov("2023-01-02", "ko", "compra", 10, 1000), mov("2023-01-02", "vti", "compra", 10, 1000),
            mov(hace(500), "ko", "dividendo", 0, 20), mov(hace(200), "ko", "dividendo", 0, 25),
            mov(hace(30), "ko", "dividendo", 0, 15), mov(hace(100), "vti", "dividendo", 0, 10)])
        series = {"KO": mock_series(100, "2022-12-01", step=0), "VTI.DE": mock_series(100, "2022-12-01", step=0)}
        with MockPrices(series):
            return engine.build_dashboard(cfg, self.directory, fetch_prices=False)

    def test_income_summary(self):
        dv = self.calcula()["dividendos"]
        self.assertEqual(dv["total"], 70)
        self.assertEqual(dv["ultimos12"], 50)
        self.assertAlmostEqual(dv["rentabilidad"], 50 / 2000)
        ko = dv["porProducto"][0]
        self.assertEqual((ko["id"], ko["total"], ko["ultimos12"], ko["cobros"]), ("ko", 60, 40, 3))
        self.assertAlmostEqual(ko["sobreCoste"], 40 / 1000)
        self.assertEqual(dv["porAno"][-1][0], str(dt.date.today().year))
        self.assertEqual(sum(v for _, v in dv["porAno"]), 70)

    def test_without_dividends(self):
        cfg = portfolio([etf()], [mov("2024-01-02", "etf", "compra", 1, 10)])
        with MockPrices():
            dv = engine.build_dashboard(cfg, self.directory, fetch_prices=False)["dividendos"]
        self.assertEqual((dv["total"], dv["porProducto"], dv["porAno"]), (0, [], []))

    def test_private_export_hides_original_dividends(self):
        data = self.calcula()
        oculto = export.hide_amounts(data)["dividendos"]
        k = oculto["total"] / data["dividendos"]["total"]
        self.assertNotAlmostEqual(k, 1, places=3)
        self.assertAlmostEqual(oculto["ultimos12"], round(data["dividendos"]["ultimos12"] * k, 2), places=1)
        self.assertEqual([a for a, _ in oculto["porAno"]], [a for a, _ in data["dividendos"]["porAno"]])
        self.assertEqual(oculto["rentabilidad"], data["dividendos"]["rentabilidad"])
        self.assertNotIn(str(data["dividendos"]["porProducto"][0]["total"]), json.dumps(oculto["porProducto"]))


class ExportWorkbook(TemporaryDataTest):
    def test_export_can_be_reimported(self):
        cfg = portfolio([etf(identificador="IE0000000001"), manual("cuenta", "efectivo", nombre="Cuenta del banco")],
                      [mov("2024-01-02", "etf", "compra", 2, 40, comision=1, nota="primera"),
                       mov("2024-03-01", "etf", "dividendo", 0, 3)],
                      [{"id": "v1", "fecha": "2024-03-31", "producto": "cuenta", "valor": 2500}])
        xlsx = spreadsheet.portfolio_workbook(cfg)
        from openpyxl import load_workbook
        libro = load_workbook(io.BytesIO(xlsx))
        self.assertEqual(libro.sheetnames, ["Movimientos", "Productos"])
        self.assertEqual(libro["Productos"].max_row, 3)
        rows, error = imports.read_table("mis_datos.xlsx", xlsx)
        self.assertIsNone(error)
        self.assertEqual(len(rows), 3)
        with MockPrices({"TEST.DE": mock_series(20, "2024-01-01", step=0)}):
            report = imports.preview(cfg, imports.prepare_table(cfg, rows, self.directory))
        self.assertEqual(report["errores"], [])
        self.assertEqual(report["repetidos"], 2)
        self.assertEqual(report["productosNuevos"], [])

    def test_endpoint(self):
        with mock.patch.object(server, "DATA_DIR", self.directory):
            r = server.app.test_client().get("/api/exportar-excel")
        self.assertEqual(r.status_code, 200)
        self.assertIn("finappgo_mis_datos_", r.headers["Content-Disposition"])
        self.assertTrue(r.data.startswith(b"PK"))


class ForeignCurrency(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        fx = mock_series(0.9, "2024-01-01", step=0)
        self.patches = [mock.patch.object(server, "DATA_DIR", self.directory),
                        mock.patch.object(engine, "exchange_rate_series", lambda currency, directory, refresh=False:
                                          fx if currency == "USD" else {})]
        for p in self.patches:
            p.start()
        self.web = server.app.test_client()
        self.web.post("/api/empezar", json={"desde": "vacia"})
        cfg = json.load(open(os.path.join(self.directory, "cartera.json"), encoding="utf-8"))
        cfg["productos"].append(etf("aapl", "AAPL", "USD", tipo="accion"))
        json.dump(cfg, open(os.path.join(self.directory, "cartera.json"), "w", encoding="utf-8"))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def test_usd_purchase_is_saved_in_eur(self):
        with MockPrices():
            r = self.web.post("/api/movimientos", json={"producto": "aapl", "tipo": "compra", "fecha": "2025-04-02",
                                                        "unidades": "5", "importe": "1.000", "comision": "2",
                                                        "moneda": "USD", "nota": "Mi compra"})
        j = r.get_json()
        self.assertEqual(r.status_code, 200, j)
        self.assertEqual(j["item"]["importe"], 900)
        self.assertEqual(j["item"]["comision"], 1.8)
        self.assertEqual(j["item"]["nota"], "Mi compra · 1.000 USD (1 USD = 0,9 €)")

    def test_missing_exchange_rate(self):
        r = self.web.post("/api/movimientos", json={"producto": "aapl", "tipo": "compra", "fecha": "2025-04-02",
                                                    "unidades": "5", "importe": "1000", "moneda": "CHF"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("No encuentro el cambio de CHF", r.get_json()["errores"][0])

    def test_eur_needs_no_conversion(self):
        with MockPrices():
            j = self.web.post("/api/movimientos", json={"producto": "aapl", "tipo": "compra", "fecha": "2025-04-02",
                                                        "unidades": "5", "importe": "1000", "moneda": "EUR"}).get_json()
        self.assertEqual(j["item"]["importe"], 1000)
        self.assertNotIn("nota", j["item"])

    def test_exchange_rate_lookup(self):
        self.assertEqual(self.web.get("/api/cambio?moneda=USD&fecha=2025-04-02").get_json(), {"ok": True, "cambio": 0.9})
        self.assertEqual(self.web.get("/api/cambio?moneda=usd&fecha=hoy").status_code, 400)


class DisplayCurrency(TemporaryDataTest):
    def test_current_exchange_rates(self):
        cfg = portfolio([etf()], [mov("2024-01-02", "etf", "compra", 1, 10)])
        with MockPrices({"USDEUR=X": mock_series(0.8, "2024-01-01", step=0)}):
            m = engine.build_dashboard(cfg, self.directory, fetch_prices=False)["monedas"]
        self.assertEqual(set(m), set(engine.MONEDAS_VISTA))
        self.assertAlmostEqual(m["USD"]["porEuro"], 1.25)
        self.assertEqual(m["USD"]["nombre"], "Dólares")
        self.assertLessEqual((dt.date.today() - dt.date.fromisoformat(m["USD"]["fecha"])).days, 3)


if __name__ == "__main__":
    unittest.main()

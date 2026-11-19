import datetime as dt
import json
import os
from unittest import mock

from support import TemporaryDataTest, MockPrices, portfolio, etf, manual, mov
from app import storage, export, tax, engine, server
from test_transfers import traspaso


def fondo(pid, **extra):
    return etf(pid, "MS" + pid.upper(), tipo="fondo", isin="ES0000000" + pid[:3].upper().ljust(3, "X"), **extra)


class Sales(TemporaryDataTest):
    def test_fifo_keeps_lot_dates_and_costs(self):
        cfg = portfolio([etf("a")], [
            mov("2023-01-10", "a", "compra", 100, 1000),
            mov("2024-03-01", "a", "compra", 100, 1200),
            mov("2025-05-05", "a", "venta", 150, 2100),
        ])
        inf = tax.report(cfg, "2025")
        [v] = inf["ventas"]
        self.assertEqual((v["transmision"], v["adquisicion"], v["ganancia"]), (2100, 1600, 500))
        self.assertEqual([c["fecha"] for c in v["compras"]], ["2023-01-10", "2024-03-01"])
        self.assertEqual(v["avisos"], [])
        self.assertEqual(inf["totales"]["saldo"], 500)
        self.assertEqual(v["isin"], "")
        self.assertEqual(tax.product_isin({"identificador": "ie00byx5nx33"}), "IE00BYX5NX33")
        self.assertEqual(tax.product_isin({"identificador": "0P0001CLDK"}), "")
        self.assertEqual(tax.report(cfg, "2024")["ventas"], [])

    def test_fund_transfer_preserves_cost_and_date(self):
        cfg = portfolio([fondo("a"), fondo("b")], [
            mov("2022-02-01", "a", "compra", 100, 1000),
            traspaso("2023-06-01", "a", "b", 100, 1150, 50, total=True),
            mov("2025-03-03", "b", "venta", 50, 1300),
        ])
        inf = tax.report(cfg, "2025")
        [v] = inf["ventas"]
        self.assertEqual(v["producto"], "b")
        self.assertEqual((v["adquisicion"], v["ganancia"]), (1000, 300))
        self.assertEqual([c["fecha"] for c in v["compras"]], ["2022-02-01"])
        self.assertEqual(tax.report(cfg, "2023")["avisos"], [])

    def test_warns_about_non_fund_transfer(self):
        cfg = portfolio([etf("a"), etf("b", "OTRO.DE")], [
            mov("2024-01-02", "a", "compra", 10, 1000),
            traspaso("2025-02-03", "a", "b", 10, 1100, 20, total=True),
        ])
        warnings = tax.report(cfg, "2025")["avisos"]
        self.assertTrue(any("solo se puede traspasar entre fondos" in a for a in warnings), warnings)

    def test_two_month_loss_rule(self):
        def con_recompra(kind, fecha_recompra):
            p = etf("a", tipo=kind)
            cfg = portfolio([p], [mov("2024-01-02", "a", "compra", 10, 1000),
                                mov("2025-05-05", "a", "venta", 10, 800),
                                mov(fecha_recompra, "a", "compra", 1, 80)])
            return tax.report(cfg, "2025")["ventas"][0]["avisos"]
        self.assertTrue(any("dos meses" in a for a in con_recompra("etf", "2025-06-20")))
        self.assertTrue(any("dos meses" in a for a in con_recompra("accion", "2025-03-10")))
        self.assertEqual(con_recompra("etf", "2025-08-01"), [])
        self.assertTrue(any("un año" in a for a in con_recompra("fondo", "2026-01-15")))
        self.assertEqual(con_recompra("cripto", "2025-05-20"), [])

    def test_gains_are_exempt_from_loss_rule(self):
        cfg = portfolio([etf("a")], [mov("2024-01-02", "a", "compra", 10, 1000),
                                   mov("2025-05-05", "a", "venta", 10, 1200),
                                   mov("2025-05-20", "a", "compra", 1, 120)])
        self.assertEqual(tax.report(cfg, "2025")["ventas"][0]["avisos"], [])

    def test_sale_without_recorded_purchases(self):
        cfg = portfolio([fondo("a")], [mov("2024-01-02", "a", "compra", 10, 1000),
                                     mov("2025-01-10", "a", "venta", 0, 110.65)])
        [v] = tax.report(cfg, "2025")["ventas"]
        self.assertIsNone(v["adquisicion"])
        self.assertEqual(v["ganancia"], 110.65)
        self.assertIn("Solo está anotada la ganancia", v["avisos"][0])
        cfg = portfolio([etf("b")], [mov("2025-01-10", "b", "venta", 5, 300)])
        [v] = tax.report(cfg, "2025")["ventas"]
        self.assertIn("No hay compras anotadas", v["avisos"][0])

    def test_pension_withdrawal_is_reported_separately(self):
        cfg = portfolio([etf("plan", "MSPLAN", tipo="pension"), etf("a")], [
            mov("2020-01-02", "plan", "compra", 100, 1000),
            mov("2025-06-02", "plan", "venta", 100, 1500),
            mov("2024-01-02", "a", "compra", 10, 1000),
            mov("2025-06-02", "a", "venta", 10, 1100),
        ])
        inf = tax.report(cfg, "2025")
        self.assertEqual([v["producto"] for v in inf["ventas"]], ["a"])
        self.assertEqual([v["producto"] for v in inf["rescates"]], ["plan"])
        self.assertEqual(inf["totales"]["saldo"], 100)
        self.assertEqual(inf["totales"]["rescates"], 1500)
        self.assertTrue(any("rendimiento del trabajo" in a for a in inf["avisos"]))


class Income(TemporaryDataTest):
    def test_annual_dividends_interest_and_fees(self):
        cfg = portfolio([etf("a"), manual("cuenta", kind="efectivo")], [
            mov("2024-01-02", "a", "compra", 10, 1000),
            mov("2024-12-30", "a", "dividendo", 0, 99),
            mov("2025-03-01", "a", "dividendo", 0, 10),
            mov("2025-09-01", "a", "dividendo", 0, 12.5),
            mov("2025-12-31", "cuenta", "dividendo", 0, 40),
            mov("2025-06-30", "a", "comision", 0, 3),
        ])
        inf = tax.report(cfg, "2025")
        self.assertEqual(inf["totales"]["dividendos"], 22.5)
        self.assertEqual(inf["totales"]["intereses"], 40)
        self.assertEqual(inf["totales"]["comisiones"], 3)
        self.assertEqual({x["producto"]: x["cobros"] for x in inf["cobros"]}, {"a": 2, "cuenta": 1})
        self.assertTrue(any("importe bruto" in a for a in inf["avisos"]), inf["avisos"])
        self.assertIn("Importe anotado", tax.report_csv(inf))

    def test_proceeds_match_dashboard(self):
        cfg = portfolio([etf("a")], [
            mov("2023-01-02", "a", "compra", 100, 1000),
            mov("2024-02-01", "a", "venta", 30, 400),
            mov("2024-06-01", "a", "dividendo", 0, 15),
            mov("2025-02-03", "a", "venta", 20, 180),
            mov("2025-03-03", "a", "comision", 0, 2),
        ])
        add = 0
        for year in ("2024", "2025"):
            inf = tax.report(cfg, year)
            t = inf["totales"]
            add += t["saldo"] + t["dividendos"] + t["intereses"] - t["comisiones"]
        with MockPrices():
            D = engine.build_dashboard(cfg, self.directory, fetch_prices=False)
        self.assertAlmostEqual(add, D["productos"][0]["realizado"], places=2)


class TaxYears(TemporaryDataTest):
    def test_default_year_is_last_completed_year(self):
        self.assertEqual(tax.default_year(["2026", "2025", "2023"], dt.date(2026, 4, 1)), "2025")
        self.assertEqual(tax.default_year(["2026"], dt.date(2026, 4, 1)), "2026")
        self.assertEqual(tax.default_year([], dt.date(2026, 4, 1)), "2026")

    def test_month_arithmetic(self):
        self.assertEqual(tax.add_months("2025-03-31", -1), "2025-02-28")
        self.assertEqual(tax.add_months("2025-12-31", 2), "2026-02-28")
        self.assertEqual(tax.add_months("2024-01-15", -12), "2023-01-15")


class Api(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        cfg = portfolio([etf("a", nombre="Fondo <b>raro</b>")], [
            mov("2024-01-02", "a", "compra", 10, 1000.5),
            mov("2025-05-05", "a", "venta", 5, 600.25),
        ])
        storage.save(os.path.join(self.directory, "cartera.json"), cfg)
        self.patch = mock.patch.object(server, "DATA_DIR", self.directory)
        self.patch.start()
        self.web = server.app.test_client()

    def tearDown(self):
        self.patch.stop()
        super().tearDown()

    def test_api_and_csv(self):
        j = self.web.get("/api/fiscal?ano=2025").get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["ano"], "2025")
        self.assertEqual(j["ventas"][0]["ganancia"], 100)
        self.assertNotIn("<", j["ventas"][0]["nombre"])
        self.assertIn("Valor de transmisión", j["csv"])
        self.assertIn("600,25", j["csv"])
        self.assertEqual(self.web.get("/api/fiscal?ano=20x5").status_code, 400)

    def test_rejects_writes_in_combined_view(self):
        with mock.patch.object(server, "mode", lambda: "todos"):
            r = self.web.get("/api/fiscal")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cada persona", r.get_json()["errores"][0])

    def test_does_not_contact_network(self):
        with mock.patch("app.network.open_url", side_effect=AssertionError("no debería salir a internet")):
            self.assertTrue(self.web.get("/api/fiscal").get_json()["ok"])


class ExcludedFromStaticExport(TemporaryDataTest):
    def test_export_excludes_tax_section(self):
        with MockPrices():
            D = engine.build_dashboard(portfolio([etf("a")], [mov("2024-01-02", "a", "compra", 10, 1000),
                                                     mov("2025-05-05", "a", "venta", 5, 600)]),
                                self.directory, fetch_prices=False)
        html = export.render_page(os.path.join(server.ROOT, "app", "web"), D)
        self.assertIn('id="seccionFiscal" hidden', html)
        self.assertNotIn("window.Editor = {", html)
        self.assertNotIn("ventasDetalle", json.dumps(D))

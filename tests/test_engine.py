import datetime as dt
import json
import os
import unittest

from support import (ROOT, TemporaryDataTest, MockPrices, portfolio, etf, read_demo, manual, mov,
                   mock_series)
from app import engine


def add(r):
    return sum(e[1] for e in r["eventos"]), sum(e[2] for e in r["eventos"])


class Fifo(unittest.TestCase):
    P = {"id": "x", "corto": "X"}

    def test_sale_draws_from_oldest_lots(self):
        r = engine.apply_movements(self.P, [
            mov("2024-01-02", "x", "compra", 10, 100),
            mov("2024-06-03", "x", "compra", 10, 200),
            mov("2025-01-02", "x", "venta", 15, 300),
        ])
        units, aportado = add(r)
        self.assertAlmostEqual(units, 5)
        self.assertAlmostEqual(aportado, 100)
        self.assertAlmostEqual(r["realizado"], 100)
        self.assertEqual(len(r["vendidas"]), 2)

    def test_purchase_precedes_sale_on_same_date(self):
        r = engine.apply_movements(self.P, [
            mov("2024-01-02", "x", "venta", 5, 60),
            mov("2024-01-02", "x", "compra", 10, 100),
        ])
        self.assertAlmostEqual(add(r)[0], 5)
        self.assertAlmostEqual(r["realizado"], 10)

    def test_warns_when_selling_too_many_units(self):
        engine.WARNINGS.clear()
        engine.apply_movements(self.P, [mov("2024-01-02", "x", "compra", 1, 10),
                                           mov("2024-02-02", "x", "venta", 2, 30)])
        self.assertTrue(any("vendes más" in a for a in engine.WARNINGS))

    def test_dividends_fees_and_cash_flows(self):
        r = engine.apply_movements(self.P, [
            mov("2024-01-02", "x", "compra", 10, 100, comision=1),
            mov("2024-03-01", "x", "dividendo", 0, 5),
            mov("2024-04-01", "x", "comision", 0, 2),
        ])
        self.assertAlmostEqual(r["realizado"], 3)
        self.assertAlmostEqual(r["comisiones"], 3)
        self.assertEqual([f[1] for f in r["flujos"]], [-100, 5, -2])


class InternalRateOfReturn(unittest.TestCase):
    def test_ten_percent_over_one_year(self):
        t = engine.xirr([(dt.date(2023, 1, 1), -100), (dt.date(2024, 1, 1), 110)])
        self.assertAlmostEqual(t, 0.10, places=3)

    def test_losses(self):
        t = engine.xirr([(dt.date(2023, 1, 1), -100), (dt.date(2024, 1, 1), 80)])
        self.assertAlmostEqual(t, -0.20, places=3)


class Dashboard(TemporaryDataTest):
    def test_eur_etf_with_sale_and_cash_account(self):
        price_series = mock_series(base=10, start="2024-01-01", step=0)
        cfg = portfolio([etf(), manual("cuenta", "efectivo")],
                      [mov("2024-01-02", "etf", "compra", 10, 100), mov("2025-01-02", "etf", "venta", 4, 60)],
                      [{"id": "v1", "fecha": "2024-06-03", "producto": "cuenta", "valor": 1000}])
        with MockPrices({"TEST.DE": price_series}):
            D = engine.build_dashboard(cfg, self.directory, fetch_prices=False)
        p = D["productos"][0]
        self.assertAlmostEqual(p["participaciones"], 6)
        self.assertAlmostEqual(p["aportado"], 60)
        self.assertAlmostEqual(p["realizado"], 20)
        self.assertAlmostEqual(p["valor"], 60)
        self.assertAlmostEqual(D["total"]["patrimonio"], 1060)
        self.assertEqual(D["avisos"], [])

    def test_usd_stock_is_converted_to_eur(self):
        price_series = mock_series(base=100, start="2024-01-01", step=0)
        fx = mock_series(base=0.9, start="2024-01-01", step=0)
        cfg = portfolio([etf("aapl", "AAPL", "USD", tipo="accion")],
                      [mov("2024-01-02", "aapl", "compra", 2, 180)])
        with MockPrices({"AAPL": price_series, "USDEUR=X": fx}):
            D = engine.build_dashboard(cfg, self.directory, fetch_prices=False)
        p = D["productos"][0]
        self.assertAlmostEqual(p["valor"], 2 * 100 * 0.9)
        self.assertIn("convertido de USD", p["fuenteTexto"])
        self.assertEqual(p["etqPrecio"], "Precio de la acción")

    def test_prices_extend_through_today_with_daily_fx(self):
        today = dt.date.today().isoformat()
        price_series = mock_series(base=100, start="2024-01-01", step=0.001)
        fx = mock_series(base=0.9, start="2024-01-01", step=0)
        cfg = portfolio([etf("aapl", "AAPL", "USD", tipo="accion")], [mov("2024-01-02", "aapl", "compra", 1, 90)])
        with MockPrices({"AAPL": price_series, "USDEUR=X": fx}):
            D = engine.build_dashboard(cfg, self.directory, fetch_prices=False)
        last = max(price_series)
        self.assertEqual(D["productos"][0]["navFecha"], last)
        self.assertLessEqual((dt.date.fromisoformat(today) - dt.date.fromisoformat(last)).days, 3)

    def test_manual_valuation(self):
        cfg = portfolio([manual("piso")], [], [
            {"id": "v1", "fecha": "2023-01-02", "producto": "piso", "valor": 150000, "aportado": 140000},
            {"id": "v2", "fecha": "2025-01-02", "producto": "piso", "valor": 180000, "aportado": 140000}])
        with MockPrices():
            D = engine.build_dashboard(cfg, self.directory, fetch_prices=False)
        p = next(x for x in D["productos"] + D["otrosActivos"] if x["id"] == "piso")
        self.assertAlmostEqual(p["valor"], 180000)
        self.assertAlmostEqual(D["total"]["patrimonio"], 180000)


class DemoPortfolio(TemporaryDataTest):

    def test_preserves_units_contributions_and_realized_gain(self):
        with open(os.path.join(ROOT, "tests", "fixtures", "expected-demo.json"), encoding="utf-8") as f:
            expected = json.load(f)
        from regenerate_expected import foto_demo
        current = foto_demo()
        self.assertEqual(set(current), set(expected))
        for pid, e in expected.items():
            for campo, v in e.items():
                with self.subTest(product=pid, campo=campo):
                    self.assertAlmostEqual(current[pid][campo], v, places=4)

    def test_calculates_entire_dashboard(self):
        with MockPrices():
            D = engine.build_dashboard(read_demo(), self.directory, fetch_prices=False)
        self.assertGreater(D["total"]["patrimonio"], 0)
        self.assertEqual(len(D["comparacion"]["referencias"]), 4)
        for r in D["comparacion"]["referencias"]:
            self.assertIsNotNone(r["valor"], r["id"])
        ids = {p["id"] for p in D["productos"] + D["otrosActivos"] + D["pasivos"]}
        self.assertEqual(ids, {p["id"] for p in read_demo()["productos"]})
        self.assertEqual(len(D["fechas"]), len(D["total"]["serie"]))


if __name__ == "__main__":
    unittest.main()

from support import TemporaryDataTest, MockPrices, portfolio, etf, manual, mov, mock_series
from app import export, engine
from test_transfers import traspaso

PRECIOS = {"TEST.DE": {**mock_series(10, "2024-12-02", "2025-05-31", step=0),
                       **mock_series(12, "2025-06-01", step=0)}}


class TotalGain(TemporaryDataTest):
    def construye(self, products, movements, valuations=()):
        with MockPrices(PRECIOS):
            D = engine.build_dashboard(portfolio(products, movements, valuations), self.directory, fetch_prices=False)
        return D, {p["id"]: p for p in D["productos"]}

    def test_partial_sale_dividend_and_fee(self):
        D, p = self.construye([etf("a")], [
            mov("2025-01-02", "a", "compra", 100, 1000),
            mov("2025-03-03", "a", "compra", 50, 500),
            mov("2025-07-01", "a", "venta", 60, 720),
            mov("2025-08-01", "a", "dividendo", 0, 30),
            mov("2025-09-01", "a", "comision", 0, 5),
        ])
        a = p["a"]
        self.assertEqual(a["aportado"], 900)
        self.assertEqual(a["valor"], 1080)
        self.assertEqual(a["plusvalia"], 180)
        self.assertEqual(a["cobros"], {"ventas": 120, "dividendos": 30, "gastos": 5})
        self.assertEqual(a["realizado"], 145)
        self.assertEqual(a["costeVendido"], 600)
        self.assertEqual(a["gananciaTotal"], 325)
        self.assertAlmostEqual(a["rentabilidadTotal"], 325 / 1500, places=4)
        self.assertAlmostEqual(a["gananciaTotal"], sum(v for _, v in a["flujos"]) + a["valor"], places=2)
        self.assertEqual(D["total"]["realizado"], 145)

    def test_includes_fully_sold_position(self):
        _, p = self.construye([etf("a")], [
            mov("2025-01-02", "a", "compra", 100, 1000),
            mov("2025-02-03", "a", "dividendo", 0, 50),
            mov("2025-07-01", "a", "venta", 100, 1200),
        ])
        a = p["a"]
        self.assertIsNone(a["plusvalia"])
        self.assertEqual(a["gananciaTotal"], 250)
        self.assertAlmostEqual(a["rentabilidadTotal"], 0.25, places=4)

    def test_total_gain_matches_capital_gain_without_income(self):
        _, p = self.construye([etf("a")], [mov("2025-01-02", "a", "compra", 100, 1000)])
        a = p["a"]
        self.assertEqual(a["gananciaTotal"], a["plusvalia"])
        self.assertEqual(a["rentabilidadTotal"], a["rentabilidad"])
        self.assertEqual(a["cobros"], {"ventas": 0, "dividendos": 0, "gastos": 0})

    def test_unknown_contributions_remain_unknown(self):
        _, p = self.construye([manual("piso")], [], [{"fecha": "2025-01-31", "producto": "piso", "valor": 200000}])
        self.assertIsNone(p["piso"]["gananciaTotal"])
        self.assertIsNone(p["piso"]["rentabilidadTotal"])

    def test_transfer_is_not_counted_twice(self):
        _, p = self.construye([etf("a"), etf("b", "OTRO.DE")], [
            mov("2025-01-02", "a", "compra", 100, 1000),
            traspaso("2025-03-03", "a", "b", 100, 1000, 40, total=True),
        ])
        self.assertIsNone(p["a"]["gananciaTotal"])
        self.assertEqual(p["b"]["costeVendido"], 0)
        self.assertEqual(p["b"]["gananciaTotal"], p["b"]["plusvalia"])
        self.assertEqual(p["b"]["aportado"], 1000)

    def test_export_omits_original_eur_amounts(self):
        D, p = self.construye([etf("a")], [
            mov("2025-01-02", "a", "compra", 100, 1000),
            mov("2025-07-01", "a", "venta", 60, 720),
            mov("2025-08-01", "a", "dividendo", 0, 30),
        ])
        web = {x["id"]: x for x in export.hide_amounts(D)["productos"]}["a"]
        k = web["valor"] / p["a"]["valor"]
        self.assertNotAlmostEqual(k, 1.0, places=3)
        for campo in ("gananciaTotal", "costeVendido"):
            self.assertAlmostEqual(web[campo], p["a"][campo] * k, places=1)
        self.assertAlmostEqual(web["cobros"]["dividendos"], 30 * k, places=1)
        self.assertEqual(web["rentabilidadTotal"], p["a"]["rentabilidadTotal"])

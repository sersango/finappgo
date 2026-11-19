import datetime as dt

from support import TemporaryDataTest, MockPrices, portfolio, etf, manual, mov
from app import export, tax, engine


def piso_alquilado(con_etf=True):
    rentas = [mov(f"2025-{m:02d}-05", "piso", "dividendo", 0, 800, mid=f"r{m}") for m in range(1, 13)]
    rentas.append(mov("2024-12-05", "piso", "dividendo", 0, 750, mid="r0"))
    cfg = portfolio([manual("piso"), etf("a")], rentas + [
        mov("2025-03-01", "piso", "comision", 0, 600, mid="g1"),
        mov("2025-06-01", "piso", "comision", 0, 1200, mid="g2"),
        mov("2025-01-02", "a", "compra", 10, 1000, mid="c1"),
        mov("2025-02-03", "a", "dividendo", 0, 12, mid="d1"),
    ], [
        {"id": "v1", "fecha": "2024-01-31", "producto": "piso", "valor": 200000, "aportado": 180000},
        {"id": "v2", "fecha": "2025-12-31", "producto": "piso", "valor": 210000, "aportado": 180000},
    ])
    if not con_etf:
        cfg["productos"] = [x for x in cfg["productos"] if x["id"] != "a"]
        cfg["movimientos"] = [m for m in cfg["movimientos"] if m["producto"] != "a"]
    return cfg


class RentalIncome(TemporaryDataTest):
    def test_rental_income_calculations(self):
        movs = piso_alquilado()["movimientos"]
        al = engine.rental_income([m for m in movs if m["producto"] == "piso"], dt.date(2025, 12, 31))
        self.assertEqual(al, {"cobrado": 10350, "gastos": 1800, "cobrado12": 9600, "gastos12": 1800})
        self.assertIsNone(engine.rental_income([], dt.date(2025, 12, 31)))

    def test_included_in_product_details(self):
        with MockPrices():
            D = engine.build_dashboard(piso_alquilado(con_etf=False), self.directory, fetch_prices=False)
        self.assertEqual(D["fechaExtracto"], "2025-12-31")
        piso = {x["id"]: x for x in D["productos"]}["piso"]
        self.assertEqual(piso["alquiler"]["cobrado12"], 9600)
        self.assertEqual(piso["alquiler"]["gastos12"], 1800)
        self.assertEqual(piso["plusvalia"], 30000)
        self.assertEqual(piso["gananciaTotal"], 30000 + 10350 - 1800)

    def test_rolling_year_ends_at_latest_data(self):
        with MockPrices():
            D = engine.build_dashboard(piso_alquilado(), self.directory, fetch_prices=False)
        p = {x["id"]: x for x in D["productos"]}
        one_year_ago = (dt.date.fromisoformat(D["fechaExtracto"]) - dt.timedelta(days=365)).isoformat()
        expected = sum(m["importe"] for m in piso_alquilado()["movimientos"]
                       if m["producto"] == "piso" and m["tipo"] == "dividendo" and m["fecha"] > one_year_ago)
        self.assertEqual(p["piso"]["alquiler"]["cobrado12"], expected)
        self.assertNotIn("alquiler", p["a"])

    def test_export_scales_rental_income(self):
        with MockPrices():
            D = engine.build_dashboard(piso_alquilado(con_etf=False), self.directory, fetch_prices=False)
        piso = {x["id"]: x for x in D["productos"]}["piso"]
        web = {x["id"]: x for x in export.hide_amounts(D)["productos"]}["piso"]
        k = web["valor"] / piso["valor"]
        self.assertAlmostEqual(web["alquiler"]["cobrado12"], 9600 * k, places=1)
        self.assertAlmostEqual(web["alquiler"]["cobrado12"] / web["valor"], 9600 / 210000, places=6)


class TaxReport(TemporaryDataTest):
    def test_rental_income_is_reported_separately(self):
        inf = tax.report(piso_alquilado(), "2025")
        t = inf["totales"]
        self.assertEqual(t["alquileres"], 9600)
        self.assertEqual(t["gastosAlquiler"], 1800)
        self.assertEqual(t["dividendos"], 12)
        self.assertEqual(t["comisiones"], 0)
        self.assertEqual({x["clase"] for x in inf["cobros"]}, {"Alquileres", "Dividendos y cupones"})
        self.assertTrue(any("capital inmobiliario" in a for a in inf["avisos"]))
        csv = tax.report_csv(inf)
        self.assertIn("Gastos de inmuebles anotados", csv)
        self.assertIn("1800,00", csv)

    def test_rent_only_omits_dividend_withholding_warning(self):
        cfg = piso_alquilado()
        cfg["movimientos"] = [m for m in cfg["movimientos"] if m["producto"] == "piso"]
        warnings = tax.report(cfg, "2025")["avisos"]
        self.assertFalse(any("importe bruto" in a for a in warnings), warnings)


class AccountInterest(TemporaryDataTest):

    def cuenta_con_intereses(self):
        return portfolio([manual("cuenta", kind="efectivo")], [
            mov("2025-06-30", "cuenta", "dividendo", 0, 40, mid="i1"),
            mov("2025-12-31", "cuenta", "dividendo", 0, 60, mid="i2"),
            mov("2025-12-31", "cuenta", "comision", 0, 5, mid="g1"),
        ], [
            {"id": "v1", "fecha": "2025-01-31", "producto": "cuenta", "valor": 10000},
            {"id": "v2", "fecha": "2025-12-31", "producto": "cuenta", "valor": 10100},
        ])

    def test_counts_as_income(self):
        with MockPrices():
            D = engine.build_dashboard(self.cuenta_con_intereses(), self.directory, fetch_prices=False)
        account = {x["id"]: x for x in D["otrosActivos"]}["cuenta"]
        self.assertEqual(account["intereses"]["cobrado12"], 100)
        self.assertEqual(account["realizado"], 95)
        self.assertEqual(D["total"]["realizado"], 95)

    def test_export_scales_amounts(self):
        with MockPrices():
            D = engine.build_dashboard(self.cuenta_con_intereses(), self.directory, fetch_prices=False)
        web = {x["id"]: x for x in export.hide_amounts(D)["otrosActivos"]}["cuenta"]
        orig = {x["id"]: x for x in D["otrosActivos"]}["cuenta"]
        k = web["valor"] / orig["valor"]
        self.assertAlmostEqual(web["intereses"]["cobrado12"], 100 * k, places=1)

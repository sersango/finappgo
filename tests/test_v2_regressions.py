from unittest import mock

from support import TemporaryDataTest, MockPrices, portfolio, etf, manual, mov, mock_series
from app import storage, engine, server


class Goal(TemporaryDataTest):
    def test_new_portfolio_has_no_default_goal(self):
        self.assertFalse(storage.CARTERA_VACIA["objetivo"]["activo"])
        self.assertIsNone(engine.custom_goal(portfolio()))

    def test_ignores_legacy_default_goal(self):
        cfg = portfolio()
        cfg["objetivo"] = {"activo": True, "importe": 100000, "etiqueta": "Próximo objetivo"}
        self.assertIsNone(engine.custom_goal(cfg))
        cfg["objetivo"] = {"activo": True, "importe": 30000, "etiqueta": "Próximo objetivo"}
        self.assertEqual(engine.custom_goal(cfg)["importe"], 30000)

    def test_set_custom_goal(self):
        cfg = portfolio()
        storage.save_goal(cfg, {"activo": True, "importe": "100.000", "etiqueta": "Libertad"})
        o = engine.custom_goal(cfg)
        self.assertEqual((o["importe"], o["etiqueta"]), (100000, "Libertad"))
        storage.save_goal(cfg, {"activo": False})
        self.assertIsNone(engine.custom_goal(cfg))
        with self.assertRaises(storage.ValidationError):
            storage.save_goal(cfg, {"activo": True, "importe": ""})


class SellAll(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        self.cfg = portfolio([etf("a")], [mov("2024-01-02", "a", "compra", 12.3456789, 1000)])

    def test_sell_all_tolerates_rounding(self):
        m = storage.save_movement(self.cfg, {"producto": "a", "tipo": "venta", "fecha": "2024-06-03",
                                                 "unidades": "12,3457", "importe": "1100"})
        self.assertAlmostEqual(m["unidades"], 12.3456789, places=8)
        self.assertAlmostEqual(storage.units_at(self.cfg, "a", "2024-06-03"), 0.0, places=9)

    def test_overselling_is_still_an_error(self):
        with self.assertRaises(storage.ValidationError) as e:
            storage.save_movement(self.cfg, {"producto": "a", "tipo": "venta", "fecha": "2024-06-03",
                                                 "unidades": "12,4", "importe": "1100"})
        self.assertIn("12,3456789", e.exception.errors[0])
        self.assertIn("Todas", e.exception.errors[0])

    def test_units_endpoint(self):
        with mock.patch.object(server, "DATA_DIR", self.directory):
            storage.save(f"{self.directory}/cartera.json", self.cfg)
            web = server.app.test_client()
            j = web.get("/api/unidades?producto=a&fecha=2024-03-01").get_json()
            self.assertAlmostEqual(j["unidades"], 12.3456789)
            self.assertEqual(web.get("/api/unidades?producto=zz&fecha=2024-03-01").status_code, 404)


class AccountInterest(TemporaryDataTest):
    def test_account_only_accepts_interest_movements(self):
        cfg = portfolio([manual("cuenta", kind="efectivo")])
        m = storage.save_movement(cfg, {"producto": "cuenta", "tipo": "dividendo", "fecha": "2025-01-31",
                                            "importe": "12,50"})
        self.assertEqual(m["importe"], 12.5)
        with self.assertRaises(storage.ValidationError):
            storage.save_movement(cfg, {"producto": "cuenta", "tipo": "compra", "fecha": "2025-01-31",
                                            "importe": "100"})

    def test_interest_counts_as_return_without_changing_balance(self):
        cfg = portfolio([manual("cuenta", kind="efectivo")],
                      [mov("2025-01-31", "cuenta", "dividendo", 0, 12.5), mov("2025-02-28", "cuenta", "dividendo", 0, 11)],
                      [{"id": "v1", "producto": "cuenta", "fecha": "2025-01-01", "valor": 5000},
                       {"id": "v2", "producto": "cuenta", "fecha": "2025-03-01", "valor": 5023.5}])
        with MockPrices():
            data = engine.build_dashboard(cfg, self.directory, fetch_prices=False)
        self.assertEqual(data["total"]["patrimonio"], 5023.5)
        self.assertEqual(data["dividendos"]["total"], 23.5)
        self.assertEqual(data["dividendos"]["porProducto"][0]["id"], "cuenta")

    def test_debt_has_no_movements(self):
        cfg = portfolio([manual("hipoteca", kind="deuda")])
        with self.assertRaises(storage.ValidationError):
            storage.save_movement(cfg, {"producto": "hipoteca", "tipo": "dividendo", "fecha": "2025-01-31",
                                            "importe": "10"})


class RealizedLoss(TemporaryDataTest):
    def test_realized_losses_reduce_total_gain(self):
        prices = {"TEST.DE": {**mock_series(10, "2025-01-01", "2025-06-30", step=0),
                               **mock_series(8, "2025-07-01", step=0)}}
        cfg = portfolio([etf("a")], [mov("2025-03-03", "a", "compra", 100, 1000),
                                   mov("2025-09-01", "a", "venta", 100, 800)])
        with MockPrices(prices):
            data = engine.build_dashboard(cfg, self.directory, fetch_prices=False)
        self.assertEqual(data["productos"][0]["realizado"], -200)
        self.assertEqual(data["total"]["realizado"], -200)
        self.assertLess(data["total"]["tir"], 0)


class TargetAllocation(TemporaryDataTest):
    def test_validates_and_saves_product(self):
        cfg = portfolio()
        o = storage.save_allocation(cfg, {"por": "clase", "pesos": {"Renta variable": "80", "Renta fija": "20,0", "Oro": ""}})
        self.assertEqual(o["pesos"], {"Renta variable": 80, "Renta fija": 20})
        self.assertEqual((o["vigilar"], o["rebalancear"]), (3, 5))
        self.assertEqual(engine.target_allocation(cfg)["pesos"]["Renta fija"], 20)
        with self.assertRaises(storage.ValidationError) as e:
            storage.save_allocation(cfg, {"pesos": {"A": "70", "B": "20"}})
        self.assertIn("suman 90", e.exception.errors[0])
        with self.assertRaises(storage.ValidationError):
            storage.save_allocation(cfg, {"pesos": {"A": "100"}, "vigilar": "6", "rebalancear": "4"})
        storage.save_allocation(cfg, {"borrar": True})
        self.assertIsNone(engine.target_allocation(cfg))

    def test_manually_selects_eligible_products(self):
        cfg = portfolio()
        o = storage.save_allocation(cfg, {"pesos": {"Renta variable": "100"}, "cuenta": {"bitcoin": False, "cuenta": 1}})
        self.assertEqual(o["cuenta"], {"bitcoin": False, "cuenta": True})
        self.assertEqual(engine.target_allocation(cfg)["cuenta"], {"bitcoin": False, "cuenta": True})
        o = storage.save_allocation(cfg, {"pesos": {"Renta variable": "100"}, "cuenta": "basura"})
        self.assertNotIn("cuenta", o)
        self.assertEqual(engine.target_allocation(cfg)["cuenta"], {})


class EmergencyFund(TemporaryDataTest):
    def test_emergency_fund_accepts_months_or_amount(self):
        cfg = portfolio()
        storage.save_emergency_fund(cfg, {"modo": "meses", "meses": "6", "gastoMensual": "2.000"})
        self.assertEqual(engine.emergency_fund(cfg), {"modo": "meses", "meses": 6, "gastoMensual": 2000, "importe": 12000})
        storage.save_emergency_fund(cfg, {"modo": "importe", "importe": "10.000"})
        self.assertEqual(engine.emergency_fund(cfg)["importe"], 10000)
        with self.assertRaises(storage.ValidationError):
            storage.save_emergency_fund(cfg, {"modo": "meses", "meses": "", "gastoMensual": "2000"})
        storage.save_emergency_fund(cfg, {"borrar": True})
        self.assertIsNone(engine.emergency_fund(cfg))

    def test_mark_product_as_liquid(self):
        cfg = portfolio()
        p, _ = storage.save_product(cfg, {"nombre": "Monetario", "tipo": "fondo", "fuente": "manual", "liquidez": True})
        self.assertIs(p["liquidez"], True)
        p, _ = storage.save_product(cfg, {"id": p["id"], "nombre": "Monetario", "tipo": "fondo", "fuente": "manual",
                                             "liquidez": False})
        self.assertIs(p["liquidez"], False)

    def test_private_export_hides_original_expenses(self):
        from app import export
        data = {"total": {"hitos": []}, "colchon": {"modo": "meses", "meses": 6, "gastoMensual": 2000, "importe": 12000}}
        out = export.hide_amounts(data)
        self.assertNotEqual(out["colchon"]["gastoMensual"], 2000)
        self.assertEqual(out["colchon"]["meses"], 6)


class MissingMarketPrice(TemporaryDataTest):

    def construye(self, prices):
        cfg = portfolio([etf("app", "APP", tipo="accion")],
                      [mov("2025-03-03", "app", "compra", 100, 1000, mid="m1"), mov("2025-09-01", "app", "venta", 100, 1200, mid="m2")])
        with MockPrices(prices):
            return engine.build_dashboard(cfg, self.directory, fetch_prices=False)

    def test_prices_available_only_after_transfer(self):
        D = self.construye({"APP": mock_series(50, "2026-10-01", step=0)})
        ra = D["rentabilidadAnual"]
        row = dict(zip(ra["anos"], ra["porProducto"]["app"]))
        vendido = dict(zip(ra["anos"], ra["vendido"]["app"]))
        self.assertAlmostEqual(row["2025"], 0.20, places=2)
        self.assertIsNone(row["2026"])
        self.assertTrue(vendido["2026"])
        p = D["productos"][0]
        self.assertEqual(p["realizado"], 200)
        self.assertEqual(p["valor"], 0)
        self.assertTrue(any("no tiene precios antes del 01/10/2026" in a for a in D["avisos"]))

    def test_product_remains_visible_without_prices(self):
        D = self.construye({"APP": {}})
        self.assertEqual([p["id"] for p in D["productos"]], ["app"])
        self.assertEqual(D["total"]["realizado"], 200)
        self.assertTrue(any("lo valoro al precio de tus compras y ventas" in a for a in D["avisos"]))

    def test_ordinary_prices_are_unchanged(self):
        D = self.construye({"APP": mock_series(10, "2024-01-02", step=0)})
        self.assertEqual(D["avisos"], [])
        self.assertNotIn("preciosDeOperaciones", D["productos"][0])

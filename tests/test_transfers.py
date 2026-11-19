import unittest

from support import TemporaryDataTest, MockPrices, portfolio, etf, manual, mov, mock_series
from app import storage, engine


def fondo(pid, code):
    return {"id": pid, "nombre": pid.upper(), "corto": pid.upper(), "tipo": "fondo", "fuente": "morningstar",
            "codigo": code, "moneda": "EUR", "slot": 1, "largoPlazo": True}


def traspaso(date, source, destination, units, amount, unidades_destino, mid="t1", **extra):
    return {"id": mid, "fecha": date, "producto": source, "destino": destination, "tipo": "traspaso",
            "unidades": units, "unidadesDestino": unidades_destino, "importe": amount, **extra}


PRECIOS = {"MS:A": mock_series(10, "2020-01-01", "2023-12-31", step=0) | mock_series(20, "2024-01-01", step=0),
           "MS:B": mock_series(50, "2020-01-01", step=0),
           "MS:C": mock_series(25, "2020-01-01", step=0)}


class Fifo(unittest.TestCase):
    P = [fondo("a", "A"), fondo("b", "B")]

    def calcula(self, movs):
        movements_by_product = {}
        for m in engine.expand_transfers(movs):
            movements_by_product.setdefault(m["producto"], []).append(m)
        return engine.apply_all_movements(self.P, movements_by_product)

    def test_full_transfer_is_not_a_sale(self):
        r = self.calcula([mov("2020-01-02", "a", "compra", 100, 1000), mov("2021-01-04", "a", "compra", 50, 500),
                          traspaso("2024-03-01", "a", "b", 150, 3000, 60)])
        a, b = r["a"], r["b"]
        self.assertEqual(a["realizado"], 0)
        self.assertAlmostEqual(sum(e[1] for e in a["eventos"]), 0)
        self.assertAlmostEqual(sum(e[2] for e in a["eventos"]), 0)
        self.assertAlmostEqual(sum(e[1] for e in b["eventos"]), 60)
        self.assertAlmostEqual(sum(e[2] for e in b["eventos"]), 1500)
        self.assertEqual(b["traspasos"][0]["coste"], 1500)
        self.assertIn(("2024-03-01", 3000.0), a["flujos"])
        self.assertIn(("2024-03-01", -3000.0), b["flujos"])

    def test_partial_transfer_takes_oldest_lots(self):
        r = self.calcula([mov("2020-01-02", "a", "compra", 100, 1000), mov("2021-01-04", "a", "compra", 100, 1500),
                          traspaso("2024-03-01", "a", "b", 150, 3000, 60)])
        self.assertAlmostEqual(r["b"]["traspasos"][0]["coste"], 1000 + 750)
        self.assertAlmostEqual(sum(e[1] for e in r["a"]["eventos"]), 50)
        self.assertAlmostEqual(sum(e[2] for e in r["a"]["eventos"]), 750)

    def test_transfer_preserves_acquisition_date(self):
        r = self.calcula([mov("2020-01-02", "a", "compra", 100, 1000), mov("2022-01-03", "b", "compra", 10, 400),
                          traspaso("2024-03-01", "a", "b", 100, 2000, 40),
                          mov("2025-01-02", "b", "venta", 40, 2000)])
        self.assertAlmostEqual(r["b"]["realizado"], 2000 - 1000)
        self.assertAlmostEqual(sum(e[2] for e in r["b"]["eventos"]), 400)

    def test_chained_transfers(self):
        P = self.P + [fondo("c", "C")]
        movs = [mov("2020-01-02", "a", "compra", 100, 1000),
                traspaso("2023-01-02", "a", "b", 100, 1500, 30, mid="t1"),
                traspaso("2024-01-02", "b", "c", 30, 1500, 60, mid="t2")]
        movements_by_product = {}
        for m in engine.expand_transfers(movs):
            movements_by_product.setdefault(m["producto"], []).append(m)
        r = engine.apply_all_movements(P, movements_by_product)
        self.assertAlmostEqual(sum(e[2] for e in r["c"]["eventos"]), 1000)
        self.assertAlmostEqual(sum(e[1] for e in r["c"]["eventos"]), 60)
        self.assertEqual(r["a"]["realizado"] + r["b"]["realizado"] + r["c"]["realizado"], 0)


class DashboardTransfers(TemporaryDataTest):
    def construye(self, cfg):
        with MockPrices(PRECIOS):
            return engine.build_dashboard(cfg, self.directory, fetch_prices=False)

    def test_transfer_preserves_assets_contributions_and_irr(self):
        purchases = [mov("2020-01-02", "a", "compra", 100, 1000), mov("2021-01-04", "a", "compra", 100, 1000)]
        sin = self.construye(portfolio([fondo("a", "A"), fondo("b", "B")], purchases))
        con = self.construye(portfolio([fondo("a", "A"), fondo("b", "B")],
                                     purchases + [traspaso("2024-03-01", "a", "b", 200, 4000, 80)]))
        for k in ("patrimonio", "aportado", "plusvalia", "realizado"):
            self.assertAlmostEqual(sin["total"][k], con["total"][k], places=2, msg=k)
        self.assertAlmostEqual(sin["total"]["tir"], con["total"]["tir"], places=4)
        b = next(p for p in con["productos"] if p["id"] == "b")
        self.assertAlmostEqual(b["aportado"], 2000)
        self.assertAlmostEqual(b["participaciones"], 80)
        self.assertEqual(b["traspasos"][0]["otroNombre"], "A")
        self.assertEqual(sum(con["aportacionesMensuales"]["total"]), 2000)
        month = next(m for m in con["resumenMensual"] if m["mes"] == "2024-03")
        self.assertAlmostEqual(month["aportado"], 0)
        self.assertEqual(con["avisos"], [])

    def test_full_manual_plan_transfer(self):
        cfg = portfolio([manual("viejo", kind="pension"), manual("nuevo", kind="pension")],
                      [mov("2020-01-02", "viejo", "compra", 0, 5000),
                       traspaso("2024-03-01", "viejo", "nuevo", 0, 6200, 0, total=True)],
                      [{"id": "v1", "producto": "viejo", "fecha": "2023-12-31", "valor": 6000}])
        D = self.construye(cfg)
        old = next(p for p in D["productos"] if p["id"] == "viejo")
        new_entry = next(p for p in D["productos"] if p["id"] == "nuevo")
        self.assertEqual(old["valor"], 0)
        self.assertEqual(new_entry["valor"], 6200)
        self.assertEqual(new_entry["aportado"], 5000)
        self.assertEqual(D["total"]["patrimonio"], 6200)
        i = D["fechas"].index("2024-02-29")
        self.assertEqual(old["serie"][i], 6000)


class SaveTransfers(unittest.TestCase):
    def setUp(self):
        self.cfg = portfolio([fondo("a", "A"), fondo("b", "B"), manual("cuenta", kind="efectivo")],
                           [mov("2020-01-02", "a", "compra", 100, 1000, mid="m1")])

    def test_saves_movement_and_updates_units(self):
        m = storage.save_movement(self.cfg, {"tipo": "traspaso", "producto": "a", "destino": "b",
                                                 "fecha": "2024-03-01", "unidades": "40", "importe": "800",
                                                 "unidadesDestino": "16"})
        self.assertEqual((m["producto"], m["destino"], m["unidades"], m["unidadesDestino"]), ("a", "b", 40, 16))
        self.assertAlmostEqual(storage.units_at(self.cfg, "a", "2024-03-01"), 60)
        self.assertAlmostEqual(storage.units_at(self.cfg, "b", "2024-03-01"), 16)
        self.assertNotIn("total", m)

    def test_sell_all_marks_full_sale(self):
        m = storage.save_movement(self.cfg, {"tipo": "traspaso", "producto": "a", "destino": "b",
                                                 "fecha": "2024-03-01", "unidades": "100", "importe": "2000",
                                                 "unidadesDestino": "40"})
        self.assertTrue(m["total"])

    def test_rejects_invalid_inputs(self):
        casos = [({"destino": "a"}, "mismo producto"), ({"destino": "cuenta"}, "cuenta"),
                 ({"unidades": "101"}, "solo tenías"), ({"unidadesDestino": ""}, "entran")]
        for cambio, text in casos:
            with self.subTest(text=text):
                data = {"tipo": "traspaso", "producto": "a", "destino": "b", "fecha": "2024-03-01",
                         "unidades": "40", "importe": "800", "unidadesDestino": "16", **cambio}
                with self.assertRaises(storage.ValidationError) as e:
                    storage.save_movement(self.cfg, data)
                self.assertIn(text, " ".join(e.exception.errors))

    def test_sell_transferred_units(self):
        storage.save_movement(self.cfg, {"tipo": "traspaso", "producto": "a", "destino": "b", "fecha": "2024-03-01",
                                             "unidades": "100", "importe": "2000", "unidadesDestino": "40"})
        storage.save_movement(self.cfg, {"tipo": "venta", "producto": "b", "fecha": "2024-05-02",
                                             "unidades": "40", "importe": "2100"})
        with self.assertRaises(storage.ValidationError):
            storage.save_movement(self.cfg, {"tipo": "venta", "producto": "a", "fecha": "2024-05-02",
                                                 "unidades": "1", "importe": "20"})

    def test_deleting_destination_removes_transfer(self):
        storage.save_movement(self.cfg, {"tipo": "traspaso", "producto": "a", "destino": "b", "fecha": "2024-03-01",
                                             "unidades": "100", "importe": "2000", "unidadesDestino": "40"})
        storage.delete_product(self.cfg, "b")
        self.assertEqual([m["tipo"] for m in self.cfg["movimientos"]], ["compra"])


class ImportTransfers(TemporaryDataTest):
    def cfg(self):
        return portfolio([fondo("a", "A") | {"identificador": "IE00AAAAAAA1"}, fondo("b", "B") | {"identificador": "IE00BBBBBBB2"}],
                       [mov("2020-01-02", "a", "compra", 100, 1000, mid="m1")])

    def test_pairs_transfer_rows(self):
        from app import imports
        text = ("fecha;identificador;nombre;tipo_producto;tipo_movimiento;unidades;importe;moneda;comision;nota\n"
                 "2024-03-01;IE00AAAAAAA1;A;fondo;traspaso_salida;100;2000;EUR;;\n"
                 "2024-03-01;IE00BBBBBBB2;B;fondo;traspaso_entrada;40;2000;EUR;;\n")
        rows, error = imports.read_table("pegado.csv", text)
        self.assertIsNone(error)
        cfg = self.cfg()
        preview_plan = imports.prepare_table(cfg, rows, self.directory)
        report = imports.apply(cfg, preview_plan)
        self.assertEqual(report["errores"], [])
        t = [m for m in cfg["movimientos"] if m["tipo"] == "traspaso"]
        self.assertEqual(len(t), 1)
        self.assertEqual((t[0]["producto"], t[0]["destino"], t[0]["unidades"], t[0]["unidadesDestino"]), ("a", "b", 100, 40))
        report = imports.apply(cfg, imports.prepare_table(cfg, rows, self.directory))
        self.assertEqual(report["añadidos"], 0)

    def test_outgoing_transfer_requires_matching_incoming_leg(self):
        from app import imports
        text = ("fecha;identificador;nombre;tipo_producto;tipo_movimiento;unidades;importe\n"
                 "2024-03-01;IE00AAAAAAA1;A;fondo;traspaso_salida;100;2000\n")
        rows, _ = imports.read_table("pegado.csv", text)
        preview_plan = imports.prepare_table(self.cfg(), rows, self.directory)
        self.assertIn("sin su entrada", preview_plan.errors[0]["mensaje"])

    def test_workbook_round_trip(self):
        from app import imports, spreadsheet
        cfg = self.cfg()
        storage.save_movement(cfg, {"tipo": "traspaso", "producto": "a", "destino": "b", "fecha": "2024-03-01",
                                        "unidades": "100", "importe": "2000", "unidadesDestino": "40"})
        rows, error = imports.read_table("mis_datos.xlsx", spreadsheet.portfolio_workbook(cfg))
        self.assertIsNone(error)
        limpia = self.cfg()
        limpia["movimientos"] = []
        report = imports.apply(limpia, imports.prepare_table(limpia, rows, self.directory))
        self.assertEqual(report["errores"], [])
        self.assertEqual(sorted(m["tipo"] for m in limpia["movimientos"]), ["compra", "traspaso"])


class UnitReconciliation(TemporaryDataTest):

    def test_adjustment_preserves_cost_basis(self):
        cfg = portfolio([fondo("a", "A")], [mov("2020-01-02", "a", "compra", 100, 1000, mid="m1"),
                                          mov("2021-01-04", "a", "compra", 100, 1500, mid="m2")])
        storage.save_movement(cfg, {"tipo": "ajuste", "producto": "a", "fecha": "2024-01-02", "unidades": "180"})
        self.assertAlmostEqual(storage.units_at(cfg, "a", "2024-01-02"), 180)
        self.assertAlmostEqual(storage.units_at(cfg, "a", "2023-12-29"), 200)
        with MockPrices(PRECIOS):
            D = engine.build_dashboard(cfg, self.directory, fetch_prices=False)
        a = D["productos"][0]
        self.assertAlmostEqual(a["participaciones"], 180)
        self.assertAlmostEqual(a["aportado"], 2500)
        self.assertAlmostEqual(a["valor"], 180 * 20)
        self.assertEqual(a["ajustes"][0]["antes"], 200)
        self.assertIn("FinAppGo calculaba 200", cfg["movimientos"][-1]["nota"])

    def test_sale_after_reconciliation(self):
        cfg = portfolio([fondo("a", "A")], [mov("2020-01-02", "a", "compra", 100, 1000, mid="m1")])
        storage.save_movement(cfg, {"tipo": "ajuste", "producto": "a", "fecha": "2023-01-02", "unidades": "90"})
        with self.assertRaises(storage.ValidationError):
            storage.save_movement(cfg, {"tipo": "venta", "producto": "a", "fecha": "2024-01-02",
                                            "unidades": "95", "importe": "1900"})
        storage.save_movement(cfg, {"tipo": "venta", "producto": "a", "fecha": "2024-01-02",
                                        "unidades": "90", "importe": "1800"})
        with MockPrices(PRECIOS):
            D = engine.build_dashboard(cfg, self.directory, fetch_prices=False)
        self.assertAlmostEqual(D["productos"][0]["realizado"], 800)

    def test_manual_assets_cannot_reconcile_units(self):
        cfg = portfolio([manual("piso")])
        with self.assertRaises(storage.ValidationError):
            storage.save_movement(cfg, {"tipo": "ajuste", "producto": "piso", "fecha": "2024-01-02", "unidades": "1"})


class ManualPlanWithContributions(TemporaryDataTest):

    VALORES = [{"id": "v1", "producto": "viejo", "fecha": "2022-12-30", "valor": 5200, "aportado": 4800},
               {"id": "v2", "producto": "viejo", "fecha": "2023-12-29", "valor": 6000, "aportado": 5000}]

    def construye(self, products, movements):
        with MockPrices(PRECIOS):
            return engine.build_dashboard(portfolio(products, movements, self.VALORES), self.directory, fetch_prices=False)

    def test_full_transfer_to_quoted_plan(self):
        D = self.construye([manual("viejo", kind="pension"), fondo("nuevo", "C") | {"tipo": "pension"}],
                           [traspaso("2024-03-01", "viejo", "nuevo", 0, 6200, 248, total=True)])
        old = next(p for p in D["productos"] if p["id"] == "viejo")
        new_entry = next(p for p in D["productos"] if p["id"] == "nuevo")
        self.assertEqual(old["valor"], 0)
        self.assertIsNone(old["aportado"])
        self.assertAlmostEqual(new_entry["aportado"], 5000)
        self.assertAlmostEqual(new_entry["participaciones"], 248)
        self.assertAlmostEqual(D["total"]["aportado"], 5000)
        self.assertEqual(D["total"]["realizado"], 0)
        i = D["fechas"].index("2024-02-29")
        self.assertEqual(old["serie"][i], 6000)

    def test_full_transfer_to_manual_plan(self):
        D = self.construye([manual("viejo", kind="pension"), manual("nuevo", kind="pension")],
                           [traspaso("2024-03-01", "viejo", "nuevo", 0, 6200, 0, total=True)])
        new_entry = next(p for p in D["productos"] if p["id"] == "nuevo")
        self.assertAlmostEqual(new_entry["aportado"], 5000)
        self.assertAlmostEqual(new_entry["valor"], 6200)
        self.assertAlmostEqual(D["total"]["patrimonio"], 6200)

    def test_partial_transfer(self):
        D = self.construye([manual("viejo", kind="pension"), manual("nuevo", kind="pension")],
                           [traspaso("2024-03-01", "viejo", "nuevo", 0, 3000, 0)])
        old = next(p for p in D["productos"] if p["id"] == "viejo")
        new_entry = next(p for p in D["productos"] if p["id"] == "nuevo")
        self.assertAlmostEqual(old["valor"], 3000)
        self.assertAlmostEqual(old["aportado"], 2500)
        self.assertAlmostEqual(new_entry["aportado"], 2500)
        self.assertAlmostEqual(D["total"]["aportado"], 5000)

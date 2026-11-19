import os
import unittest
from unittest import mock

from support import TemporaryDataTest, portfolio, etf, manual, mov
from app import storage


class Products(unittest.TestCase):
    def test_validation_errors_are_readable(self):
        with self.assertRaises(storage.ValidationError) as e:
            storage.save_product(portfolio(), {"nombre": "", "tipo": "nada", "moneda": "EUROS", "riesgo": 9})
        text = " ".join(e.exception.errors)
        for portion in ("Ponle un nombre", "Elige de qué tipo", "moneda", "riesgo va de 1 a 7"):
            self.assertIn(portion, text)

    def test_quoted_product_requires_provider_code(self):
        with self.assertRaises(storage.ValidationError):
            storage.save_product(portfolio(), {"nombre": "Apple", "tipo": "accion", "fuente": "yahoo"})

    def test_uses_least_used_color_and_keeps_it_on_edit(self):
        cfg = portfolio()
        slots = [storage.save_product(cfg, {"nombre": f"P{i}", "tipo": "otro"})[0]["slot"] for i in range(13)]
        self.assertEqual(slots[:12], list(range(1, 13)))
        p = cfg["productos"][2]
        storage.save_product(cfg, {"id": p["id"], "nombre": "Otro nombre", "tipo": "otro"})
        self.assertEqual(p["slot"], 3)
        self.assertEqual(p["nombre"], "Otro nombre")

    def test_cash_uses_manual_valuations(self):
        p, cambio = storage.save_product(portfolio(), {"nombre": "Cuenta", "tipo": "efectivo",
                                                        "fuente": "yahoo", "codigo": "X"})
        self.assertEqual(p["fuente"], "manual")
        self.assertFalse(cambio)
        self.assertNotIn("codigo", p)

    def test_expense_ratio_as_percentage(self):
        p, _ = storage.save_product(portfolio(), {"nombre": "F", "tipo": "otro", "ter": "0,12"})
        self.assertAlmostEqual(p["ter"], 0.0012)

    def test_deleting_product_removes_related_data(self):
        cfg = portfolio([etf(), manual()], [mov("2024-01-02", "etf", "compra", 1, 10)],
                      [{"id": "v1", "fecha": "2024-01-02", "producto": "piso", "valor": 5}])
        storage.delete_product(cfg, "etf")
        self.assertEqual(cfg["movimientos"], [])
        self.assertEqual(len(cfg["valoraciones"]), 1)


class Movements(unittest.TestCase):
    def setUp(self):
        self.cfg = portfolio([etf(), manual("cuenta", "efectivo")])

    def test_rejects_overselling(self):
        storage.save_movement(self.cfg, {"producto": "etf", "tipo": "compra", "fecha": "2024-01-02",
                                             "unidades": "10", "importe": "100"})
        with self.assertRaises(storage.ValidationError) as e:
            storage.save_movement(self.cfg, {"producto": "etf", "tipo": "venta", "fecha": "2024-01-03",
                                                 "unidades": "10,5", "importe": "120"})
        self.assertIn("solo tenías 10 unidades", e.exception.errors[0])

    def test_sale_before_purchase(self):
        storage.save_movement(self.cfg, {"producto": "etf", "tipo": "compra", "fecha": "2024-06-02",
                                             "unidades": 10, "importe": 100})
        with self.assertRaises(storage.ValidationError):
            storage.save_movement(self.cfg, {"producto": "etf", "tipo": "venta", "fecha": "2024-01-03",
                                                 "unidades": 1, "importe": 12})

    def test_accounts_use_balance_snapshots(self):
        with self.assertRaises(storage.ValidationError) as e:
            storage.save_movement(self.cfg, {"producto": "cuenta", "tipo": "compra", "fecha": "2024-01-02",
                                                 "importe": 100})
        self.assertIn("Saldos y valores", e.exception.errors[0])

    def test_rejects_fee_above_amount(self):
        with self.assertRaises(storage.ValidationError):
            storage.save_movement(self.cfg, {"producto": "etf", "tipo": "compra", "fecha": "2024-01-02",
                                                 "unidades": 1, "importe": 10, "comision": 10})

    def test_editing_preserves_id(self):
        m = storage.save_movement(self.cfg, {"producto": "etf", "tipo": "compra", "fecha": "2024-01-02",
                                                 "unidades": 1, "importe": 10})
        storage.save_movement(self.cfg, {"id": m["id"], "producto": "etf", "tipo": "compra",
                                             "fecha": "2024-01-02", "unidades": 2, "importe": "1.000"})
        self.assertEqual(len(self.cfg["movimientos"]), 1)
        self.assertEqual(self.cfg["movimientos"][0]["importe"], 1000)


class Valuations(unittest.TestCase):
    def test_one_valuation_per_date(self):
        cfg = portfolio([manual()])
        storage.save_valuation(cfg, {"producto": "piso", "fecha": "2024-01-02", "valor": "100.000"})
        storage.save_valuation(cfg, {"producto": "piso", "fecha": "2024-01-02", "valor": "120.000"})
        self.assertEqual(len(cfg["valoraciones"]), 1)
        self.assertEqual(cfg["valoraciones"][0]["valor"], 120000)


class Persistence(TemporaryDataTest):
    def test_automatic_backup_retention(self):
        path = os.path.join(self.directory, "cartera.json")
        with mock.patch.object(storage, "MAX_BACKUPS", 3):
            for i in range(6):
                storage.save(path, portfolio([manual(f"p{i}")]))
        backups = os.listdir(os.path.join(self.directory, "copias"))
        self.assertEqual(len(backups), 3)
        self.assertEqual(storage.load(path)["productos"][0]["id"], "p5")
        self.assertFalse(os.path.exists(path + ".tmp"))


if __name__ == "__main__":
    unittest.main()

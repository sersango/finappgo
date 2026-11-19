import io
import unittest

from support import TemporaryDataTest, MockPrices, portfolio, etf, manual, mock_series
from app import imports, spreadsheet

CSV_MYINVESTOR = """Fecha fiscal;Inversión;Valor de mercado;Resultado fiscal
02/01/2024;1000;1200;200
01/02/2024;500,5;590,1;89,6
28/08/2023;0;0;11,26
"""


class ReadMyInvestor(unittest.TestCase):
    def test_parses_lots_and_redemptions(self):
        lots, redemptions = imports.read_myinvestor_csv(CSV_MYINVESTOR.encode("utf-8"))
        self.assertEqual(lots, [["2024-01-02", 1000.0, 1200.0], ["2024-02-01", 500.5, 590.1]])
        self.assertEqual(redemptions, [["2023-08-28", 11.26]])

    def test_windows_encoding(self):
        lots, _ = imports.read_myinvestor_csv(CSV_MYINVESTOR.encode("cp1252"))
        self.assertEqual(len(lots), 2)

    def test_unrelated_file_produces_no_lots(self):
        lots, redemptions = imports.read_myinvestor_csv("Concepto;Importe\nNómina;1500\n".encode())
        self.assertEqual((lots, redemptions), ([], []))

    def test_units_use_transaction_date_price(self):
        price_series = {"2024-01-02": 10.0, "2024-02-01": 11.0, "2024-09-02": 12.0}
        lots = [["2024-01-02", 1000.0, 1200.0], ["2024-02-01", 550.0, 600.0]]
        movs, missing_nav, transfers = imports.myinvestor_movements("f", lots, [], price_series)
        self.assertEqual((missing_nav, transfers), (0, 0))
        self.assertAlmostEqual(movs[0]["unidades"], 100)
        self.assertAlmostEqual(movs[1]["unidades"], 50)
        self.assertTrue(all(m["tipo"] == "compra" for m in movs))

    def test_falls_back_to_statement_nav(self):
        price_series = {"2023-01-02": 9.0, "2024-01-02": 10.0, "2024-09-02": 12.0}
        lots = [["2024-01-02", 1000.0, 1200.0], ["2023-05-05", 100.0, 120.0]]
        movs, missing_nav, _ = imports.myinvestor_movements("f", sorted(lots), [], price_series)
        self.assertEqual(missing_nav, 1)
        self.assertAlmostEqual(sum(m["unidades"] for m in movs), 110)

    def test_transfer_keeps_original_cost_and_date(self):
        price_series = {"2020-03-02": 8.0, "2023-06-01": 10.0, "2024-01-02": 10.0, "2024-02-01": 11.0,
                 "2024-09-02": 12.0, "2024-09-03": 12.1}
        lots = [["2020-03-02", 3000.0, 400 * 12.0],
                 ["2024-01-02", 1000.0, 1200.0],
                 ["2024-02-01", 550.0, 600.0]]
        movs, missing_nav, transfers = imports.myinvestor_movements("f", lots, [], price_series)
        self.assertEqual((missing_nav, transfers), (0, 1))
        self.assertAlmostEqual(movs[0]["unidades"], 400)
        self.assertIn("traspaso", movs[0]["nota"])
        self.assertEqual(movs[0]["importe"], 3000)
        self.assertAlmostEqual(movs[1]["unidades"], 100)
        self.assertAlmostEqual(movs[2]["unidades"], 50)

    def test_identifies_statement_nav(self):
        price_series = {"2024-01-02": 10.0, "2024-02-01": 11.0, "2024-09-02": 12.0, "2024-09-03": 12.04}
        lots = [["2024-01-02", 1000.0, 1200.0], ["2024-02-01", 550.0, 600.0]]
        self.assertEqual(imports.statement_nav(lots, price_series), (12.0, 2))

    def test_redemption_is_sale_with_zero_units(self):
        movs, _, _ = imports.myinvestor_movements("f", [], [["2023-08-28", 11.26]], {})
        self.assertEqual((movs[0]["tipo"], movs[0]["unidades"], movs[0]["importe"]), ("venta", 0, 11.26))


class PrepareMyInvestor(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        self.cfg = portfolio([etf("fondo", "0PTEST", fuente="morningstar", tipo="fondo",
                                identificador="IE00BYX5NX33")])
        self.prices = MockPrices({"MS:0PTEST": mock_series(10, "2023-01-02", step=0)})

    def test_rejects_filename_without_isin(self):
        with self.prices:
            preview_plan = imports.prepare_myinvestor(self.cfg, [("extracto.csv", CSV_MYINVESTOR.encode())], self.directory)
        self.assertIn("ISIN", preview_plan.errors[0]["mensaje"])

    def test_rejects_non_statement_file(self):
        with self.prices:
            preview_plan = imports.prepare_myinvestor(
                self.cfg, [("Plusvalías y minusvalías fondo IE00BYX5NX33.csv", b"Concepto;Importe\nA;1\n")],
                self.directory)
        self.assertIn("No parece un extracto", preview_plan.errors[0]["mensaje"])

    def test_repeat_import_replaces_existing_lots(self):
        name = "Plusvalías y minusvalías fondo IE00BYX5NX33 (1).csv"
        with self.prices:
            preview_plan = imports.prepare_myinvestor(self.cfg, [(name, CSV_MYINVESTOR.encode())], self.directory)
            inf1 = imports.apply(self.cfg, preview_plan)
            preview_plan = imports.prepare_myinvestor(self.cfg, [(name, CSV_MYINVESTOR.encode())], self.directory)
            inf2 = imports.apply(self.cfg, preview_plan)
        self.assertEqual(inf1["añadidos"], 3)
        self.assertEqual((inf2["añadidos"], inf2["sustituidos"]), (3, 3))
        self.assertEqual(len(self.cfg["movimientos"]), 3)


class ReadTable(unittest.TestCase):
    CAB = ";".join(imports.COLUMNS)

    def test_imports_fenced_csv(self):
        text = f"```csv\n{self.CAB}\n2025-03-10;AAPL;Apple;accion;compra;5;1050;USD;;\n```"
        rows, error = imports.read_table("", text)
        self.assertIsNone(error)
        self.assertEqual(rows[0][1]["identificador"], "AAPL")

    def test_reports_source_row_number_after_blank_rows(self):
        text = f"{self.CAB}\n\n2025-03-10;AAPL;;;compra;1;10;;;\n\n2025-03-11;AAPL;;;compra;1;10;;;"
        rows, _ = imports.read_table("x.csv", text.encode())
        self.assertEqual([n for n, _ in rows], [3, 5])

    def test_header_only(self):
        _, error = imports.read_table("x.csv", (self.CAB + "\n").encode())
        self.assertIn("Solo hay cabecera", error)

    def test_incorrect_header(self):
        _, error = imports.read_table("x.csv", "a;b;c\n1;2;3\n".encode())
        self.assertIn("No encuentro las columnas", error)

    def test_accepts_column_aliases(self):
        rows, error = imports.read_table("x.csv", "Date;ISIN;Operación;Importe\n10/03/2025;X;buy;5\n".encode())
        self.assertIsNone(error)
        self.assertEqual(rows[0][1]["tipo_movimiento"], "buy")

    def test_empty_spreadsheet_template(self):
        _, error = imports.read_table("plantilla.xlsx", spreadsheet.workbook())
        self.assertIn("«Movimientos» está vacía", error)

    def test_populated_spreadsheet_template(self):
        from openpyxl import load_workbook
        libro = load_workbook(io.BytesIO(spreadsheet.workbook()))
        for row in spreadsheet.EJEMPLO:
            libro["Movimientos"].append(list(row))
        buf = io.BytesIO()
        libro.save(buf)
        rows, error = imports.read_table("mia.xlsx", buf.getvalue())
        self.assertIsNone(error)
        self.assertEqual(len(rows), len(spreadsheet.EJEMPLO))
        self.assertEqual(imports.parse_date(rows[0][1]["fecha"]), "2025-03-10")


class PrepareTable(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        self.cfg = portfolio([etf(identificador="IE0000000001"), manual("cuenta", "efectivo", nombre="Cuenta del banco")])
        self.prices = MockPrices({"TEST.DE": mock_series(20, "2024-01-01", step=0)})

    def prepare(self, text):
        rows, error = imports.read_table("", ";".join(imports.COLUMNS) + "\n" + text)
        self.assertIsNone(error)
        with self.prices:
            return imports.prepare_table(self.cfg, rows, self.directory)

    def test_computed_units_and_balances(self):
        preview_plan = self.prepare("2025-03-10;IE0000000001;;etf;compra;;1000;EUR;;\n"
                            "2025-03-31;;Cuenta del banco;efectivo;saldo;;2.500;EUR;;")
        self.assertEqual(preview_plan.errors, [])
        self.assertAlmostEqual(preview_plan.movements[0]["unidades"], 50)
        self.assertIn("unidades calculadas", preview_plan.movements[0]["marcas"])
        self.assertEqual(preview_plan.valuations[0]["valor"], 2500)

    def test_validation_errors_include_row(self):
        preview_plan = self.prepare("2025-13-45;IE0000000001;;etf;compra;1;10;;;\n"
                            "2025-03-10;IE0000000001;;etf;regalo;1;10;;;\n"
                            "2025-03-10;IE0000000001;;etf;compra;1;;;;\n"
                            "2025-03-10;;;etf;compra;1;10;;;")
        self.assertEqual([e["fila"] for e in preview_plan.errors], [2, 3, 4, 5])
        self.assertIn("no es válida", preview_plan.errors[0]["mensaje"])

    def test_repeat_import_is_idempotent(self):
        text = "2025-03-10;IE0000000001;;etf;compra;2;40;EUR;;"
        imports.apply(self.cfg, self.prepare(text))
        report = imports.apply(self.cfg, self.prepare(text))
        self.assertEqual((report["añadidos"], report["repetidos"]), (0, 1))
        self.assertEqual(len(self.cfg["movimientos"]), 1)

    def test_preview_leaves_portfolio_unchanged(self):
        preview_plan = self.prepare("2025-03-10;IE0000000001;;etf;compra;2;40;EUR;;")
        report = imports.preview(self.cfg, preview_plan)
        self.assertEqual(report["añadidos"], 1)
        self.assertEqual(self.cfg["movimientos"], [])

    def test_creates_manual_product_from_name(self):
        preview_plan = self.prepare("2025-03-31;;Piso de la playa;inmueble;saldo;;200.000;EUR;;")
        report = imports.apply(self.cfg, preview_plan)
        self.assertEqual(report["productosNuevos"][0]["tipo"], "inmueble")
        self.assertEqual(report["saldos"], 1)


if __name__ == "__main__":
    unittest.main()

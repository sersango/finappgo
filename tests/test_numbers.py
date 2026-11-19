import datetime as dt
import unittest

import support  # noqa: F401  (corta internet y prepara la ruta de la app)
from app import storage, imports, engine


class Numbers(unittest.TestCase):
    def test_parses_spanish_notation(self):
        casos = {"1.000": 1000, "1.234,56": 1234.56, "1234,5": 1234.5, "1,5": 1.5,
                 "13.25": 13.25, "3352,6": 3352.6, "1.000.000": 1e6, "-2,5": -2.5,
                 " 1.399,89 € ": 1399.89, "": 0.0, "abc": 0.0}
        for text, expected in casos.items():
            with self.subTest(text=text):
                self.assertAlmostEqual(engine.parse_spanish_number(text), expected)

    def test_parses_import_amount(self):
        self.assertIsNone(imports.parse_number(""))
        self.assertIsNone(imports.parse_number(None))
        self.assertEqual(imports.parse_number("abc"), "error")
        self.assertAlmostEqual(imports.parse_number("1.000 €"), 1000)
        self.assertAlmostEqual(imports.parse_number("-5,5"), 5.5)
        self.assertAlmostEqual(imports.parse_number(12.5), 12.5)

    def test_formats_amount_for_messages(self):
        self.assertEqual(storage.format_number(12345.6), "12.345,6")
        self.assertEqual(storage.format_number(3), "3")
        self.assertEqual(storage.format_number(0.123456), "0,1235")
        self.assertEqual(storage.format_date("2025-03-10"), "10/03/2025")


class Dates(unittest.TestCase):
    def test_accepts_supported_formats(self):
        casos = {"2025-03-10": "2025-03-10", "10/03/2025": "2025-03-10", "10-03-2025": "2025-03-10",
                 "1/3/25": "2025-03-01", "2025-3-1": "2025-03-01", "10.03.2025": "2025-03-10"}
        for text, expected in casos.items():
            with self.subTest(text=text):
                self.assertEqual(imports.parse_date(text), expected)

    def test_rejects_impossible_dates(self):
        for text in ("2025-13-45", "31/02/2025", "ayer", "", None, "32/01/2025"):
            with self.subTest(text=text):
                self.assertIsNone(imports.parse_date(text))

    def test_spreadsheet_cells(self):
        self.assertEqual(imports.parse_date(dt.datetime(2025, 3, 10, 0, 0)), "2025-03-10")
        self.assertEqual(imports.parse_date(dt.date(2025, 3, 10)), "2025-03-10")

    def test_storage_validation(self):
        errors = []
        manana = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        self.assertEqual(storage.date("2024-02-29", errors), "2024-02-29")
        storage.date(manana, errors)
        storage.date("1900-01-01", errors)
        storage.date("no", errors)
        self.assertEqual(len(errors), 3)
        self.assertIn("futura", errors[0])


if __name__ == "__main__":
    unittest.main()

import datetime as dt
import json
import os
from unittest import mock

from support import TemporaryDataTest, MockPrices, portfolio, etf, manual, mov, mock_series
from app import storage, recurring, server

HOY = dt.date(2026, 10, 16)
SERIE = {**mock_series(10, "2025-01-01", "2026-06-30", step=0), **mock_series(12.5, "2026-07-01", "2026-10-16", step=0)}


def fetch(**extra):
    return {"producto": "a", "importe": "200", "dia": "5", "desde": "2026-01-01", "hasta": "2026-10-16", **extra}


class Dates(TemporaryDataTest):
    def test_selects_one_day_per_month(self):
        self.assertEqual(recurring.contribution_dates("2026-01-01", "2026-04-30", 5),
                         ["2026-01-05", "2026-02-05", "2026-03-05", "2026-04-05"])

    def test_short_months_and_range_boundaries(self):
        self.assertEqual(recurring.contribution_dates("2026-01-31", "2026-04-30", 31),
                         ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"])
        self.assertEqual(recurring.contribution_dates("2026-01-06", "2026-03-04", 5), ["2026-02-05"])
        self.assertEqual(recurring.contribution_dates("2025-12-01", "2026-01-31", 1), ["2025-12-01", "2026-01-01"])


class Plan(TemporaryDataTest):
    def test_contribution_price_and_units_by_date(self):
        pl = recurring.preview_plan(portfolio([etf("a")]), fetch(), SERIE, HOY)
        self.assertEqual(len(pl["lineas"]), 10)
        self.assertEqual(pl["nuevas"], 10)
        ene, sep = pl["lineas"][0], pl["lineas"][8]
        self.assertEqual((ene["precio"], ene["unidades"]), (10, 20))
        self.assertEqual((sep["precio"], sep["unidades"]), (12.5, 16))
        abr = pl["lineas"][3]
        self.assertEqual((abr["fecha"], abr["fechaPrecio"]), ("2026-04-05", "2026-04-03"))

    def test_skips_existing_contributions(self):
        cfg = portfolio([etf("a")], [mov("2026-03-04", "a", "compra", 20, 199.5),
                                   mov("2026-05-05", "a", "compra", 50, 500)])
        pl = recurring.preview_plan(cfg, fetch(), SERIE, HOY)
        estados = {x["fecha"]: x["estado"] for x in pl["lineas"]}
        self.assertEqual(estados["2026-03-05"], "repetida")
        self.assertEqual(estados["2026-05-05"], "nueva")
        self.assertEqual(pl["nuevas"], 9)

    def test_marks_contribution_without_price(self):
        pl = recurring.preview_plan(portfolio([etf("a")]), fetch(desde="2024-06-01", hasta="2025-02-28"), SERIE, HOY)
        estados = [x["estado"] for x in pl["lineas"]]
        self.assertEqual(estados.count("sinPrecio"), 7)
        self.assertEqual(pl["nuevas"], 2)

    def test_reports_missing_prices(self):
        with self.assertRaises(storage.ValidationError) as e:
            recurring.preview_plan(portfolio([etf("a")]), fetch(), {}, HOY)
        self.assertIn("Actualizar precios", e.exception.errors[0])

    def test_manual_product_has_no_units(self):
        pl = recurring.preview_plan(portfolio([manual("plan", kind="pension")]), fetch(producto="plan"), {}, HOY)
        self.assertTrue(pl["aMano"])
        self.assertEqual(pl["nuevas"], 10)
        self.assertIsNone(pl["lineas"][0]["unidades"])

    def test_rejects_invalid_contribution_schedules(self):
        cfg = portfolio([etf("a"), manual("cuenta", kind="efectivo")])
        malos = {"futuro": fetch(hasta="2026-12-01"), "al_reves": fetch(desde="2026-09-01", hasta="2026-08-01"),
                 "dia_0": fetch(dia="0"), "dia_32": fetch(dia="32"), "dia_raro": fetch(dia="5,5"),
                 "importe_0": fetch(importe="0"), "cuenta": fetch(producto="cuenta"), "no_existe": fetch(producto="zz"),
                 "fecha_mala": fetch(desde="2026-02-30"), "demasiadas": fetch(desde="1950-01-01")}
        for name, data in malos.items():
            with self.subTest(name):
                with self.assertRaises(storage.ValidationError):
                    recurring.preview_plan(cfg, data, SERIE, HOY)


class CreateContributions(TemporaryDataTest):
    def test_adds_only_new_contributions_and_saves_schedule(self):
        cfg = portfolio([etf("a")], [mov("2026-03-05", "a", "compra", 20, 200)])
        res = recurring.create(cfg, fetch(), SERIE, HOY)
        self.assertEqual(res, {"anadidas": 9, "saltadas": 1})
        purchases = sorted((m for m in cfg["movimientos"] if m["tipo"] == "compra"), key=lambda m: m["fecha"])
        self.assertEqual(len(purchases), 10)
        abr = [m for m in purchases if m["fecha"] == "2026-04-05"][0]
        self.assertEqual((abr["importe"], abr["unidades"]), (200, 20))
        self.assertIn("estimada con el cierre del 03/04/2026", abr["nota"])
        self.assertEqual(cfg["periodicas"], [{"producto": "a", "importe": 200, "dia": 5, "ultima": "2026-10-05"}])
        with self.assertRaises(storage.ValidationError):
            recurring.create(cfg, fetch(), SERIE, HOY)
        self.assertEqual(len([m for m in cfg["movimientos"] if m["tipo"] == "compra"]), 10)

    def test_forget_removes_schedule(self):
        cfg = portfolio([etf("a")])
        recurring.create(cfg, fetch(desde="2026-10-01"), SERIE, HOY)
        recurring.forget(cfg, {"producto": "a", "dia": "5"})
        self.assertEqual(cfg["periodicas"], [])
        self.assertEqual(len(cfg["movimientos"]), 1)
        with self.assertRaises(storage.ValidationError):
            recurring.forget(cfg, {"producto": "a", "dia": 5})


class Api(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        storage.save(os.path.join(self.directory, "cartera.json"), portfolio([etf("a")]))
        self.patches = [mock.patch.object(server, "DATA_DIR", self.directory), MockPrices({"TEST.DE": SERIE})]
        for p in self.patches:
            p.__enter__()
        self.web = server.app.test_client()

    def tearDown(self):
        for p in reversed(self.patches):
            p.__exit__(None, None, None)
        super().tearDown()

    def read(self):
        with open(os.path.join(self.directory, "cartera.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_preview_is_read_only_and_create_persists(self):
        data = fetch(desde="2026-07-01", hasta="2026-09-30")
        r = self.web.post("/api/periodicas/ver", json=data)
        j = r.get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual([x["fecha"] for x in j["plan"]["lineas"]], ["2026-07-05", "2026-08-05", "2026-09-05"])
        self.assertEqual(self.read()["movimientos"], [])
        j = self.web.post("/api/periodicas/crear", json=data).get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["item"]["anadidas"], 3)
        self.assertEqual(len(self.read()["movimientos"]), 3)
        self.assertEqual(len(j["cartera"]["periodicas"]), 1)
        j = self.web.post("/api/periodicas/olvidar", json={"producto": "a", "dia": 5}).get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(self.read()["periodicas"], [])

    def test_failed_contribution_batch_leaves_portfolio_unchanged(self):
        r = self.web.post("/api/periodicas/crear", json=fetch(hasta="2030-01-01"))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.read()["movimientos"], [])

    def test_combined_profile_is_read_only(self):
        with mock.patch.object(server, "mode", lambda: "todos"):
            self.assertNotEqual(self.web.post("/api/periodicas/ver", json=fetch()).status_code, 200)
            self.assertNotEqual(self.web.post("/api/periodicas/crear", json=fetch()).status_code, 200)
        self.assertEqual(self.read()["movimientos"], [])

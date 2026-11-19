import glob
import json
import os

from support import ROOT, TemporaryDataTest, MockPrices, portfolio
from app import imports

CARPETA = os.path.join(ROOT, "tests", "fixtures", "myinvestor_transfers")


def fixture():
    with open(os.path.join(CARPETA, "funds-and-prices.json"), encoding="utf-8") as f:
        return json.load(f)


def fondo(pid, code, isin):
    return {"id": pid, "nombre": pid, "corto": pid, "tipo": "fondo", "fuente": "morningstar",
            "codigo": code, "identificador": isin, "moneda": "EUR", "slot": 1, "largoPlazo": True}


class RealStatements(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        fx = fixture()
        self.names = {"FR0000447823": "monetario", "IE00BYX5M476": "emergentes", "IE00BYX5NX33": "world"}
        self.cfg = portfolio([fondo(self.names[f["isin"]], f["codigo"], f["isin"]) for f in fx["fondos"]])
        self.prices = MockPrices(fx["series"])
        self.prices.__enter__()
        files = sorted(glob.glob(os.path.join(CARPETA, "*.csv")))
        self.files = [(os.path.basename(a), open(a, "rb").read()) for a in files]
        self.preview_plan = imports.prepare_myinvestor(self.cfg, self.files, self.directory)

    def tearDown(self):
        self.prices.__exit__(None, None, None)
        super().tearDown()

    def test_detects_transfers_and_requests_source(self):
        t = {it["ref"]: it for it in self.preview_plan.myinvestor_transfers}
        self.assertEqual(set(t), {"emergentes", "world"})
        self.assertEqual(t["emergentes"]["lotes"], 2)
        self.assertEqual(t["world"]["lotes"], 1)
        marcados = [(m["producto"], m["fecha"]) for m in self.preview_plan.movements if m.get("_traspaso")]
        self.assertEqual(sorted(marcados), [("emergentes", "2024-09-12"), ("emergentes", "2024-09-12"),
                                            ("world", "2024-09-12")])

    def test_units_reproduce_statement_value(self):
        fx = fixture()
        for f in fx["fondos"]:
            ref = self.names[f["isin"]]
            with self.subTest(fondo=ref):
                content = dict(self.files)[f["archivo"]]
                lots, _ = imports.read_myinvestor_csv(content)
                price_series = fx["series"]["MS:" + f["codigo"]]
                vl, _ = imports.statement_nav(lots, price_series)
                purchases = [m for m in self.preview_plan.movements if m["producto"] == ref]
                self.assertEqual(len(purchases), len(lots))
                for m, (date, cost_basis, value) in zip(sorted(purchases, key=lambda m: (m["fecha"], m["importe"])),
                                                    sorted(lots, key=lambda l: (l[0], l[1]))):
                    self.assertAlmostEqual(m["unidades"] * vl / value, 1, delta=0.01, msg=f"{ref} {date} {cost_basis}")

    def test_missing_transfer_answer_preserves_import_behavior(self):
        inf = imports.apply(self.cfg, self.preview_plan, None)
        self.assertEqual(len(inf["traspasosMyInvestor"]), 2)
        self.assertFalse(any(t["hecho"] for t in inf["traspasosMyInvestor"]))
        purchases = [m for m in self.cfg["movimientos"] if m["tipo"] == "compra"]
        self.assertEqual(len(purchases), 4 + 10 + 22)


class TransferFromMoneyMarketFund(RealStatements):
    FECHA = "2025-01-15"

    def contesta(self):
        resp = {it["ref"]: {"origen": "monetario", "fecha": self.FECHA} for it in self.preview_plan.myinvestor_transfers}
        return imports.apply(self.cfg, self.preview_plan, resp)

    def test_reconstructs_source_and_creates_both_transfers(self):
        inf = self.contesta()
        self.assertTrue(all(t["hecho"] for t in inf["traspasosMyInvestor"]), inf["traspasosMyInvestor"])
        self.assertTrue(all("reconstru" not in (t["error"] or "") for t in inf["traspasosMyInvestor"]))
        rec = [m for m in self.cfg["movimientos"] if m.get("origen") == "myinvestor-traspaso"]
        self.assertEqual(sorted(m["producto"] for m in rec), ["monetario"] * 3)
        self.assertEqual({m["fecha"] for m in rec}, {"2024-09-12"})
        k = fixture()["escala"]
        self.assertEqual(sorted(round(m["importe"] / k) for m in rec), [951, 951, 2864])
        tr = [m for m in self.cfg["movimientos"] if m["tipo"] == "traspaso"]
        self.assertEqual(sorted(m["destino"] for m in tr), ["emergentes", "world"])

    def test_money_market_balance_reconciles_with_statement(self):
        from app import storage
        compras_extracto = sum(m["unidades"] for m in self.preview_plan.movements if m["producto"] == "monetario")
        self.contesta()
        before = storage.units_at(self.cfg, "monetario", "2025-01-14")
        despues = storage.units_at(self.cfg, "monetario", "2025-01-16")
        today = storage.units_at(self.cfg, "monetario", "2026-10-19")
        self.assertGreater(before, despues)
        self.assertAlmostEqual(today, compras_extracto, places=4)

    def test_repeat_import_does_not_duplicate_reconstruction(self):
        self.contesta()
        preview_plan = imports.prepare_myinvestor(self.cfg, self.files, self.directory)
        resp = {it["ref"]: {"origen": "monetario", "fecha": self.FECHA} for it in preview_plan.myinvestor_transfers}
        imports.apply(self.cfg, preview_plan, resp)
        rec = [m for m in self.cfg["movimientos"] if m.get("origen") == "myinvestor-traspaso"]
        self.assertEqual(len(rec), 3)
        self.assertEqual(len([m for m in self.cfg["movimientos"] if m["tipo"] == "traspaso"]), 2)

    def test_rejects_transfer_before_purchase(self):
        resp = {it["ref"]: {"origen": "monetario", "fecha": "2024-09-01"} for it in self.preview_plan.myinvestor_transfers}
        inf = imports.apply(self.cfg, self.preview_plan, resp)
        self.assertTrue(all("anterior a la compra" in (t["error"] or "") for t in inf["traspasosMyInvestor"]))
        self.assertFalse(any(m.get("origen") == "myinvestor-traspaso" for m in self.cfg["movimientos"]))


class DatePerLot(RealStatements):

    def item(self, ref):
        return next(it for it in self.preview_plan.myinvestor_transfers if it["ref"] == ref)

    def test_accepts_individual_lot_dates(self):
        self.assertEqual(len(self.item("emergentes")["detalle"]), 2)
        resp = {"emergentes": {"origen": "monetario", "fechas": ["2026-05-12", "2026-05-29"]},
                "world": {"origen": "monetario", "fechas": ["2026-09-03"]}}
        inf = imports.apply(self.cfg, self.preview_plan, resp)
        self.assertTrue(all(t["hecho"] for t in inf["traspasosMyInvestor"]), inf["traspasosMyInvestor"])
        tr = sorted((m["destino"], m["fecha"]) for m in self.cfg["movimientos"] if m["tipo"] == "traspaso")
        self.assertEqual(tr, [("emergentes", "2026-05-12"), ("emergentes", "2026-05-29"), ("world", "2026-09-03")])

    def test_requires_date_for_each_lot(self):
        it = self.item("emergentes")
        self.assertIsNone(imports.valid_answer(it, {"origen": "monetario", "fechas": ["2026-05-12", ""]}, None))
        r = imports.valid_answer(it, {"origen": "monetario", "fecha": "2026-05-12"}, None)
        self.assertEqual(r["fechas"], ["2026-05-12", "2026-05-12"])

    def test_marks_estimated_transfer_dates(self):
        from app import engine
        resp = {"emergentes": {"origen": "monetario", "fechas": ["estimar", "2026-05-29"]},
                "world": {"origen": "monetario", "fechas": ["estimar"]}}
        inf = imports.apply(self.cfg, self.preview_plan, resp)
        self.assertTrue(all(t["hecho"] for t in inf["traspasosMyInvestor"]), inf["traspasosMyInvestor"])
        self.assertTrue(any("Fecha estimada" in (t["aviso"] or "") for t in inf["traspasosMyInvestor"]))
        tr = [m for m in self.cfg["movimientos"] if m["tipo"] == "traspaso"]
        self.assertEqual(sum(1 for m in tr if m.get("fechaEstimada")), 2)
        self.assertTrue(all(m["fecha"] >= "2024-09-12" for m in tr))
        est, _, _ = engine.portfolio_fifo(self.cfg)
        markers = [t["estimada"] for t in est["monetario"]["traspasos"]]
        self.assertEqual(sorted(markers), [False, True, True])

    def test_estimates_transfer_date_from_prices(self):
        serie_o = {f"2025-{m:02d}-01": 10.0 for m in range(1, 13)}
        serie_d = {**{f"2025-{m:02d}-01": 20.0 for m in (1, 2)}, **{f"2025-{m:02d}-01": 25.0 for m in range(3, 13)}}
        self.assertEqual(imports.estimate_transfer_date(serie_o, serie_d, ["2025-01-01", 1000, 40]), "2025-03-01")
        self.assertIsNone(imports.estimate_transfer_date({}, serie_d, ["2025-01-01", 1000, 40]))

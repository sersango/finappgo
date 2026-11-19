import io
import json
import os
from unittest import mock

from support import TemporaryDataTest, MockPrices, portfolio, mov, mock_series
from app import storage, imports, engine, server


def fondo(pid, code, isin):
    return {"id": pid, "nombre": pid.upper(), "corto": pid.upper(), "tipo": "fondo", "fuente": "morningstar",
            "codigo": code, "identificador": isin, "moneda": "EUR", "slot": 1, "largoPlazo": True}


SERIE_B = {**mock_series(10, "2023-01-02", "2024-08-30", step=0), "2020-03-02": 8.0, "2024-02-01": 11.0,
           **mock_series(12, "2024-09-02", step=0)}
SERIE_A = {**mock_series(8, "2019-01-02", "2022-12-30", step=0), **mock_series(10, "2023-01-02", step=0)}
PRECIOS = {"MS:0PB": SERIE_B, "MS:0PA": SERIE_A}

CSV_B = """Fecha fiscal;Inversión;Valor de mercado;Resultado fiscal
02/03/2020;3000;4800;1800
02/01/2024;1000;1200;200
01/02/2024;550;600;50
"""
ARCHIVO_B = "Plusvalías y minusvalías fondo IE00BBBBBBB2.csv"


class ConvertTransfer(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        self.cfg = portfolio([fondo("a", "0PA", "IE00AAAAAAA1"), fondo("b", "0PB", "IE00BBBBBBB2")],
                           [mov("2020-03-02", "a", "compra", 375, 3000, mid="m1", origen="myinvestor")])
        self.prices = MockPrices(PRECIOS)
        self.prices.__enter__()

    def tearDown(self):
        self.prices.__exit__(None, None, None)
        super().tearDown()

    def importa(self, answers=None, cfg=None):
        cfg = cfg or self.cfg
        preview_plan = imports.prepare_myinvestor(cfg, [(ARCHIVO_B, CSV_B.encode())], self.directory)
        return preview_plan, imports.apply(cfg, preview_plan, answers)

    def panel(self):
        return engine.build_dashboard(self.cfg, self.directory, fetch_prices=False)

    def test_unanswered_transfer_keeps_existing_behavior(self):
        _, inf = self.importa()
        t = inf["traspasosMyInvestor"]
        self.assertEqual(len(t), 1)
        self.assertEqual((t[0]["ref"], t[0]["lotes"], t[0]["coste"], t[0]["hecho"]), ("b", 1, 3000, False))
        self.assertAlmostEqual(t[0]["unidades"], 400)
        self.assertIn({"id": "a", "nombre": "A"}, t[0]["origenes"])
        self.assertNotIn("b", [o["id"] for o in t[0]["origenes"]])
        compras_b = [m for m in self.cfg["movimientos"] if m["producto"] == "b"]
        self.assertEqual(len(compras_b), 3)

    def test_confirmed_transfer_is_counted_once(self):
        _, inf = self.importa({"b": {"origen": "a", "fecha": "2023-06-01"}})
        t = inf["traspasosMyInvestor"][0]
        self.assertTrue(t["hecho"], t)
        self.assertIsNone(t["aviso"])
        transfers = [m for m in self.cfg["movimientos"] if m["tipo"] == "traspaso"]
        self.assertEqual(len(transfers), 1)
        tr = transfers[0]
        self.assertEqual((tr["producto"], tr["destino"], tr["fecha"], tr["origen"]), ("a", "b", "2023-06-01", "myinvestor"))
        self.assertAlmostEqual(tr["unidades"], 375)
        self.assertAlmostEqual(tr["unidadesDestino"], 400)
        self.assertAlmostEqual(tr["importe"], 4000)
        self.assertEqual(len([m for m in self.cfg["movimientos"] if m["producto"] == "b"]), 2)
        D = self.panel()
        a = next(p for p in D["productos"] if p["id"] == "a")
        b = next(p for p in D["productos"] if p["id"] == "b")
        self.assertEqual(a["valor"], 0)
        self.assertAlmostEqual(b["participaciones"], 550)
        self.assertAlmostEqual(b["aportado"], 4550)
        self.assertAlmostEqual(D["total"]["aportado"], 4550)
        self.assertAlmostEqual(D["total"]["patrimonio"], 550 * 12)
        self.assertEqual(D["total"]["realizado"], 0)

    def test_repeat_import_reuses_transfer_answer(self):
        self.importa({"b": {"origen": "a", "fecha": "2023-06-01"}})
        preview_plan, inf = self.importa({"b": {"origen": "a", "fecha": "2023-06-01"}})
        self.assertEqual(preview_plan.myinvestor_transfers[0]["sugerencia"], {"origen": "a", "fecha": "2023-06-01"})
        self.assertEqual(len([m for m in self.cfg["movimientos"] if m["tipo"] == "traspaso"]), 1)
        self.assertEqual(len([m for m in self.cfg["movimientos"] if m["producto"] == "b"]), 2)
        self.assertEqual(inf["sustituidos"], 3)

    def test_partial_transfer_takes_oldest_lots(self):
        cfg = portfolio([fondo("a", "0PA", "IE00AAAAAAA1"), fondo("b", "0PB", "IE00BBBBBBB2")],
                      [mov("2019-03-01", "a", "compra", 250, 2000, mid="m1"),
                       mov("2020-03-02", "a", "compra", 125, 1000, mid="m2"),
                       mov("2021-03-01", "a", "compra", 100, 800, mid="m3")])
        csv = CSV_B.replace("02/03/2020;3000;4800;1800", "01/03/2019;2000;3200;1200")
        preview_plan = imports.prepare_myinvestor(cfg, [(ARCHIVO_B, csv.encode())], self.directory)
        imports.apply(cfg, preview_plan, {"b": {"origen": "a", "fecha": "2023-06-01"}})
        tr = next(m for m in cfg["movimientos"] if m["tipo"] == "traspaso")
        self.assertAlmostEqual(tr["unidades"], 250)
        self.assertAlmostEqual(storage.units_at(cfg, "a", "2024-01-01"), 225)

    def test_source_balance_was_empty_on_transfer_date(self):
        _, inf = self.importa({"b": {"origen": "a", "fecha": "2019-06-01"}})
        t = inf["traspasosMyInvestor"][0]
        self.assertFalse(t["hecho"])
        self.assertIn("anterior a la compra", t["error"])
        self.assertEqual(len([m for m in self.cfg["movimientos"] if m["producto"] == "b"]), 3)

    def test_warns_on_cost_mismatch(self):
        cfg = portfolio([fondo("a", "0PA", "IE00AAAAAAA1"), fondo("b", "0PB", "IE00BBBBBBB2")],
                      [mov("2020-03-02", "a", "compra", 250, 2000, mid="m1")])
        preview_plan = imports.prepare_myinvestor(cfg, [(ARCHIVO_B, CSV_B.encode())], self.directory)
        inf = imports.apply(cfg, preview_plan, {"b": {"origen": "a", "fecha": "2023-06-01"}})
        self.assertIn("Revisa que esté completo", inf["traspasosMyInvestor"][0]["aviso"])

    def test_rejects_same_fund_and_invalid_date(self):
        _, inf = self.importa({"b": {"origen": "b", "fecha": "2023-06-01"}})
        self.assertIn("distinto", inf["traspasosMyInvestor"][0]["error"])
        _, inf = self.importa({"b": {"origen": "a", "fecha": "ayer"}})
        self.assertFalse(inf["traspasosMyInvestor"][0]["hecho"])
        self.assertIsNone(inf["traspasosMyInvestor"][0]["error"])

    def test_preview_is_read_only(self):
        before = json.dumps(self.cfg, sort_keys=True)
        preview_plan = imports.prepare_myinvestor(self.cfg, [(ARCHIVO_B, CSV_B.encode())], self.directory)
        imports.preview(self.cfg, preview_plan, {"b": {"origen": "a", "fecha": "2023-06-01"}})
        self.assertEqual(json.dumps(self.cfg, sort_keys=True), before)


class Api(TemporaryDataTest):
    def test_preview_revise_and_confirm(self):
        cfg = portfolio([fondo("a", "0PA", "IE00AAAAAAA1"), fondo("b", "0PB", "IE00BBBBBBB2")],
                      [mov("2020-03-02", "a", "compra", 375, 3000, mid="m1")])
        with mock.patch.object(server, "DATA_DIR", self.directory), MockPrices(PRECIOS):
            storage.save(os.path.join(self.directory, "cartera.json"), cfg)
            web = server.app.test_client()
            r = web.post("/api/importar/previsualizar", content_type="multipart/form-data",
                         data={"origen": "myinvestor", "archivos": (io.BytesIO(CSV_B.encode()), ARCHIVO_B)})
            j = r.get_json()
            self.assertTrue(j["ok"], j)
            self.assertFalse(j["informe"]["traspasosMyInvestor"][0]["hecho"])
            resp = {"b": {"origen": "a", "fecha": "2023-06-01"}}
            j2 = web.post("/api/importar/revisar", json={"token": j["token"], "respuestas": resp}).get_json()
            self.assertTrue(j2["informe"]["traspasosMyInvestor"][0]["hecho"])
            self.assertEqual(web.get("/api/cartera").get_json()["cartera"]["movimientos"][0]["tipo"], "compra")
            j3 = web.post("/api/importar/confirmar", json={"token": j["token"], "respuestas": resp}).get_json()
            self.assertTrue(j3["ok"], j3)
            self.assertEqual(j3["informe"]["traspasos"], 1)
            kinds = sorted(m["tipo"] for m in web.get("/api/cartera").get_json()["cartera"]["movimientos"])
            self.assertEqual(kinds, ["compra", "compra", "compra", "traspaso"])


class Detection(TemporaryDataTest):
    def test_flags_lot_predating_fund_as_transfer(self):
        price_series = {"2022-01-03": 10.0, "2024-01-02": 10.0, "2024-09-02": 12.0}
        lots = [["2019-05-06", 2000.0, 3000.0], ["2024-01-02", 1000.0, 1200.0]]
        movs, missing_nav, transfers = imports.myinvestor_movements("f", lots, [], price_series)
        self.assertEqual((missing_nav, transfers), (0, 1))
        self.assertTrue(movs[0]["_traspaso"])
        self.assertAlmostEqual(movs[0]["unidades"], 250)

    def test_missing_price_does_not_imply_transfer(self):
        price_series = {"2022-01-03": 10.0, "2024-01-02": 10.0, "2024-09-02": 12.0}
        lots = [["2023-05-05", 100.0, 120.0], ["2024-01-02", 1000.0, 1200.0]]
        _, missing_nav, transfers = imports.myinvestor_movements("f", lots, [], price_series)
        self.assertEqual((missing_nav, transfers), (1, 0))

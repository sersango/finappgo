import json
import os
from unittest import mock

from support import TemporaryDataTest, MockPrices, portfolio, mov
from app import exposure, engine

DETALLE_WORLD = [{"Portfolios": [{
    "Date": "2026-10-09T00:00:00",
    "AssetAllocations": [{"SalePosition": "N", "BreakdownValues": [{"Type": "1", "Value": 98.7}, {"Type": "3", "Value": 0.0}]}],
    "CountryExposure": [{"SalePosition": "N", "Type": "Equity", "BreakdownValues": [
        {"Type": "USA", "Value": 73.4}, {"Type": "JPN", "Value": 5.8}, {"Type": "XXX", "Value": 20.8}]}],
    "GlobalStockSectorBreakdown": [{"SalePosition": "N", "BreakdownValues": [
        {"Type": "311", "Value": 32.7}, {"Type": "103", "Value": 15.3}, {"Type": "206", "Value": 52.0}]}],
    "PortfolioHoldings": [{"SecurityName": "NVIDIA Corp", "Weighting": 5.6}, {"SecurityName": "<b>Apple</b>", "Weighting": 5.3}],
}]}]
DETALLE_MONETARIO = [{"Portfolios": [{
    "Date": "2026-08-31T00:00:00",
    "AssetAllocations": [{"SalePosition": "N", "BreakdownValues": [{"Type": "1", "Value": 0.0}, {"Type": "3", "Value": 73.4}]}],
    "CountryExposure": [{"SalePosition": "N", "Type": "Bond", "BreakdownValues": [{"Type": "FRA", "Value": 66.4}]}],
    "GlobalStockSectorBreakdown": [],
}]}]


def falso_get(answers):
    def _get(url, headers=None, timeout=20):
        for portion, r in answers.items():
            if portion in url:
                return r
        raise AssertionError("URL inesperada: " + url)
    return _get


class ReadExposure(TemporaryDataTest):
    def test_finds_fund_by_isin(self):
        with mock.patch.object(exposure, "_get", falso_get({
                "screener": {"rows": [{"SecId": "F00001019E", "isin": "IE00BYX5NX33", "Universe": "FOESP$$ALL"}]},
                "security_details/F00001019E": DETALLE_WORLD})):
            p = {"tipoClave": "fondo", "identificador": "IE00BYX5NX33", "fuente": "morningstar", "codigo": "0P0001CLDK"}
            r = exposure.product_exposure(p, self.directory)
        self.assertEqual(r["paises"][0], ["Estados Unidos", 73.4])
        self.assertEqual(r["sectores"][0], ["Salud", 52.0])
        self.assertEqual(r["rv"], 0.987)
        self.assertEqual(r["actualizado"], "2026-10-09")
        self.assertEqual(r["top10"][1][0], "bApple/b")
        self.assertAlmostEqual(sum(x[1] for x in r["paises"]), 100, places=1)

    def test_money_market_fund_has_no_equities(self):
        with mock.patch.object(exposure, "_get", falso_get({
                "screener": {"rows": [{"SecId": "F0GBR04EZP", "isin": "FR0000447823"}]},
                "security_details/F0GBR04EZP": DETALLE_MONETARIO})):
            r = exposure.product_exposure({"tipoClave": "fondo", "identificador": "FR0000447823"}, self.directory)
        self.assertEqual((r["rv"], r["paises"], r["sectores"]), (0.0, [], []))

    def test_stock_exposure(self):
        with mock.patch.object(exposure, "_get", falso_get({"screener": {"rows": [
                {"SecId": "0P0000CK1N", "SectorName": "Productos de consumo cíclicos", "Domicile": "ESP"}]}})):
            r = exposure.product_exposure({"tipoClave": "accion", "identificador": "ES0148396007"}, self.directory)
        self.assertEqual((r["paises"], r["sectores"]), ([["España", 100.0]], [["Consumo discrecional", 100.0]]))

    def test_exposure_lookup_key_by_product_type(self):
        self.assertIsNone(exposure.key({"tipoClave": "efectivo"}))
        self.assertIsNone(exposure.key({"tipoClave": "fondo", "fuente": "manual"}))
        self.assertEqual(exposure.key({"tipoClave": "pension", "fuente": "morningstar", "codigo": "F000016CB6"}),
                         "MS:F000016CB6")
        self.assertEqual(exposure.key({"tipoClave": "pension", "fuente": "manual", "expoComo": "ie00byx5nx33"}),
                         "ISIN:IE00BYX5NX33")


class Cache(TemporaryDataTest):
    P = {"tipoClave": "fondo", "identificador": "IE00BYX5NX33"}
    RESP = {"screener": {"rows": [{"SecId": "F1", "isin": "IE00BYX5NX33"}]}, "security_details/F1": DETALLE_WORLD}

    def test_caches_exposure_for_offline_use(self):
        with mock.patch.object(exposure, "_get", falso_get(self.RESP)):
            exposure.product_exposure(self.P, self.directory)
        with mock.patch.object(exposure, "_get", side_effect=AssertionError("no debía salir a internet")):
            self.assertIsNotNone(exposure.product_exposure(self.P, self.directory))
            self.assertIsNotNone(exposure.product_exposure(self.P, self.directory, network=False))

    def test_keeps_last_data_when_offline(self):
        with mock.patch.object(exposure, "_get", falso_get(self.RESP)):
            exposure.product_exposure(self.P, self.directory)
        path = os.path.join(self.directory, "EXPO_ISIN_IE00BYX5NX33.json")
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
        old["consulta"] = "2020-01-01"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(old, f)
        with mock.patch.object(exposure, "_get", side_effect=OSError("sin red")):
            r = exposure.product_exposure(self.P, self.directory)
        self.assertEqual(r["paises"][0][0], "Estados Unidos")

    def test_engine_attaches_exposure_to_products(self):
        with mock.patch.object(exposure, "_get", falso_get(self.RESP)):
            exposure.product_exposure(self.P, os.path.join(self.directory, "cache"))
        cfg = portfolio([{"id": "w", "nombre": "World", "tipo": "fondo", "fuente": "morningstar", "codigo": "0P0001CLDK",
                        "identificador": "IE00BYX5NX33", "slot": 1}], [mov("2024-01-02", "w", "compra", 10, 100)])
        with MockPrices():
            D = engine.build_dashboard(cfg, self.directory, fetch_prices=False)
        self.assertEqual(D["productos"][0]["exposicion"]["paises"][0][0], "Estados Unidos")


class BackgroundFetch(TemporaryDataTest):

    def test_worker_uses_its_own_data_directory(self):
        from app import server
        otra = os.path.join(self.directory, "otra")
        os.makedirs(otra)
        cfg = portfolio([{"id": "w", "nombre": "World", "tipo": "fondo", "fuente": "morningstar", "codigo": "0P0001CLDK",
                        "identificador": "IE00BYX5NX33", "slot": 1}], [mov("2024-01-02", "w", "compra", 10, 100)])
        with open(os.path.join(self.directory, "cartera.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        hilo = {}
        with mock.patch.object(server, "DATA_DIR", self.directory), \
                mock.patch.object(server.threading, "Thread", lambda target, daemon: hilo.setdefault("t", target) and mock.Mock()):
            server.fetch_missing_exposures()
        with mock.patch.object(server, "DATA_DIR", otra), \
                mock.patch.object(exposure, "_get", falso_get(Cache.RESP)), MockPrices():
            hilo["t"]()
        self.assertTrue(os.path.exists(os.path.join(self.directory, "cache", "EXPO_ISIN_IE00BYX5NX33.json")))
        self.assertEqual(os.listdir(otra), [])

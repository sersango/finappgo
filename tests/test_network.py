import io
import json
import os
import time
import unittest
import urllib.error
from unittest import mock

from support import TemporaryDataTest, portfolio
from app import search, imports, engine


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def yahoo(fechas_cierres, granularidad="1d"):
    ts = [int(time.mktime(time.strptime(f, "%Y-%m-%d"))) + 12 * 3600 for f, _ in fechas_cierres]
    cuerpo = {"chart": {"result": [{"meta": {"dataGranularity": granularidad}, "timestamp": ts,
                                    "indicators": {"quote": [{"close": [c for _, c in fechas_cierres]}]}}]}}
    return FakeResponse(json.dumps(cuerpo).encode())


class YahooFetch(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        engine.CACHE = os.path.join(self.directory, "cache")
        engine.OFFLINE, engine.MISSING_ONLY = False, False
        self.urls = []

    def descarga(self, answer, symbol="AAPL"):
        def fake(req, timeout=None):
            self.urls.append(req.full_url)
            return answer
        with mock.patch("urllib.request.urlopen", fake):
            return engine.fetch_yahoo_prices(symbol)

    def test_requests_daily_prices_by_date(self):
        self.descarga(yahoo([("2025-01-02", 10.0)]))
        self.assertIn("interval=1d", self.urls[0])
        self.assertIn("period1=", self.urls[0])
        self.assertNotIn("range=max", self.urls[0])

    def test_rejects_monthly_prices(self):
        price_series = self.descarga(yahoo([("2025-01-01", 10.0), ("2025-02-01", 11.0)], granularidad="1mo"))
        self.assertEqual(price_series, {})
        self.assertTrue(any("1mo" in a for a in engine.WARNINGS))

    def test_handles_corrupt_cache(self):
        os.makedirs(engine.CACHE)
        with open(os.path.join(engine.CACHE, "AAPL.json"), "w") as f:
            json.dump({"1999-01-04": 1.0, "2025-02-01": 999.0}, f)
        price_series = self.descarga(yahoo([("2025-01-02", 10.0), ("2025-02-03", 11.0)]))
        self.assertEqual(price_series, {"1999-01-04": 1.0, "2025-01-02": 10.0, "2025-02-03": 11.0})

    def test_uses_cache_when_offline(self):
        os.makedirs(engine.CACHE)
        with open(os.path.join(engine.CACHE, "AAPL.json"), "w") as f:
            json.dump({"2025-01-02": 10.0}, f)
        def unavailable(*a, **k):
            raise urllib.error.URLError("sin red")
        with mock.patch("urllib.request.urlopen", unavailable):
            price_series = engine.fetch_yahoo_prices("AAPL")
        self.assertEqual(price_series, {"2025-01-02": 10.0})
        self.assertTrue(any("sin conexion" in a for a in engine.WARNINGS))

    def test_missing_only_fetch_reuses_cache(self):
        os.makedirs(engine.CACHE)
        with open(os.path.join(engine.CACHE, "AAPL.json"), "w") as f:
            json.dump({"2025-01-02": 10.0}, f)
        engine.MISSING_ONLY = True
        self.assertEqual(self.descarga(yahoo([("2025-01-03", 11.0)])), {"2025-01-02": 10.0})
        self.assertEqual(self.urls, [])


class Retry(unittest.TestCase):
    def setUp(self):
        self.dormir = mock.patch("time.sleep", lambda s: None)
        self.dormir.start()

    def tearDown(self):
        self.dormir.stop()

    def test_logs_failure_after_three_attempts(self):
        llamadas = []
        def unavailable(*a, **k):
            llamadas.append(1)
            raise urllib.error.URLError("timeout")
        n = len(search.FETCH_FAILURES)
        with mock.patch("urllib.request.urlopen", unavailable), self.assertRaises(urllib.error.URLError):
            search._get("https://query2.finance.yahoo.com/v1/finance/search?q=x")
        self.assertEqual(len(llamadas), 3)
        self.assertIn("query2.finance.yahoo.com", search.fetch_error_since(n))

    def test_does_not_retry_not_found(self):
        llamadas = []
        def no_existe(req, timeout=None):
            llamadas.append(1)
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        with mock.patch("urllib.request.urlopen", no_existe), self.assertRaises(urllib.error.HTTPError):
            search._get("https://query1.finance.yahoo.com/v8/finance/chart/NOEXISTE")
        self.assertEqual(len(llamadas), 1)

    def test_retries_rate_limits(self):
        answers = [urllib.error.HTTPError("u", 429, "Too Many", {}, None), FakeResponse(b'{"ok": 1}')]
        def a_veces(req, timeout=None):
            r = answers.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch("urllib.request.urlopen", a_veces):
            self.assertEqual(search._get("https://query2.finance.yahoo.com/x"), {"ok": 1})


class ImporterMessages(TemporaryDataTest):
    def resolver(self, simula):
        preview_plan = imports.Plan()
        with mock.patch.object(search, "search", simula):
            imports.ProductResolver(portfolio(), preview_plan, self.directory).product(7, "IE00BYX5NX33", "", "fondo")
        return preview_plan.errors[0]["mensaje"]

    def test_separates_connection_errors_from_missing_quotes(self):
        def unavailable(text):
            search.FETCH_FAILURES.append("lt.morningstar.com: timeout")
            return []
        self.assertIn("No he podido consultar", self.resolver(unavailable))

    def test_reports_missing_quote(self):
        self.assertIn("No encuentro «IE00BYX5NX33»", self.resolver(lambda text: []))


if __name__ == "__main__":
    unittest.main()

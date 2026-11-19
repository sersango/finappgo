"""Isolate test portfolios and prevent accidental calls to external providers."""
import copy
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.request
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["PATRIMONIO_DATOS"] = tempfile.mkdtemp(prefix="finappgo_tests_")

from app import storage, engine  # noqa: E402


class OfflineAccess(Exception):
    pass


def _prohibido(*args, **kwargs):
    url = getattr(args[0], "full_url", args[0]) if args else "?"
    raise OfflineAccess(f"Los tests no pueden salir a internet ({url})")


urllib.request.urlopen = _prohibido


from flask.testing import FlaskClient  # noqa: E402

from app import server  # noqa: E402


class AuthenticatedClient(FlaskClient):
    """Use the same access cookie as an authenticated browser."""

    def open(self, *args, **kwargs):
        dominios = {"localhost", "127.0.0.1", "::1", "finappgo.casa"}
        headers = kwargs.get("headers")
        if isinstance(headers, dict) and headers.get("Host"):
            dominios.add(server._without_port(headers["Host"]).strip("[]"))
        for dominio in dominios:
            self.set_cookie(server.COOKIE, server.access_token(), domain=dominio)
        return super().open(*args, **kwargs)


server.app.test_client_class = AuthenticatedClient


def dias(start, end=None, finde=False):
    d, final_index = dt.date.fromisoformat(start), dt.date.fromisoformat(end) if end else dt.date.today()
    while d <= final_index:
        if finde or d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


def mock_series(base=10.0, start="2015-01-02", end=None, step=0.0003):
    return {d.isoformat(): round(base * (1 + step) ** i, 6) for i, d in enumerate(dias(start, end))}


class MockPrices:

    def __init__(self, series=None):
        self.series = dict(series or {})
        self.pedidos = []

    def price_series(self, key):
        self.pedidos.append(key)
        if key in self.series:
            return dict(self.series[key])
        if key.endswith(".F"):
            return {}
        if key.endswith("EUR=X"):
            return mock_series(base=0.9, step=0)
        h = int(hashlib.md5(key.encode()).hexdigest()[:6], 16)
        return mock_series(base=5 + h % 200, step=0.0002)

    def __enter__(self):
        self._parches = [
            mock.patch.object(engine, "fetch_yahoo_prices", lambda s, years=None: self.price_series(s)),
            mock.patch.object(engine, "fetch_morningstar_prices", lambda s, *a, **k: self.price_series("MS:" + s)),
            mock.patch.object(engine, "fetch_coingecko_prices", lambda s, *a, **k: self.price_series("CG:" + s)),
        ]
        for p in self._parches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._parches:
            p.stop()


def portfolio(products=(), movements=(), valuations=()):
    cfg = copy.deepcopy(storage.CARTERA_VACIA)
    cfg["productos"] = [dict(p) for p in products]
    cfg["movimientos"] = [dict(m) for m in movements]
    cfg["valoraciones"] = [dict(v) for v in valuations]
    return cfg


def etf(pid="etf", code="TEST.DE", currency="EUR", **extra):
    return {"id": pid, "nombre": pid.upper(), "tipo": "etf", "fuente": "yahoo", "codigo": code,
            "moneda": currency, "slot": 1, "largoPlazo": True, **extra}


def manual(pid="piso", kind="inmueble", **extra):
    return {"id": pid, "nombre": pid.capitalize(), "tipo": kind, "fuente": "manual", "slot": 2,
            "largoPlazo": kind not in storage.BALANCE_ONLY, **extra}


def mov(date, product, kind, units, amount, mid=None, **extra):
    return {"id": mid or f"m{abs(hash((date, product, kind, units, amount))) % 10**8}",
            "fecha": date, "producto": product, "tipo": kind, "unidades": units,
            "importe": amount, **extra}


def read_demo():
    with open(os.path.join(ROOT, "demo", "portfolio.json"), encoding="utf-8") as f:
        return json.load(f)


class TemporaryDataTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="finappgo_test_")
        engine.WARNINGS.clear()

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

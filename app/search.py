"""Find an instrument by ISIN, ticker, or name and verify candidate prices."""

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import network
from .engine import UA

ES_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")

ATAJOS = {
    "oro": ("GC=F", "Oro (onza troy, futuro COMEX)"),
    "gold": ("GC=F", "Oro (onza troy, futuro COMEX)"),
    "plata": ("SI=F", "Plata (onza troy, futuro COMEX)"),
    "silver": ("SI=F", "Plata (onza troy, futuro COMEX)"),
    "platino": ("PL=F", "Platino (onza troy, futuro NYMEX)"),
    "cobre": ("HG=F", "Cobre (libra, futuro COMEX)"),
    "petroleo": ("BZ=F", "Petróleo Brent (barril)"),
    "petróleo": ("BZ=F", "Petróleo Brent (barril)"),
}
YAHOO_TYPES = {"EQUITY": "accion", "ETF": "etf", "MUTUALFUND": "fondo",
              "CRYPTOCURRENCY": "cripto", "FUTURE": "commodity"}
BOLSAS = {"XETR": ("Xetra", ".DE"), "XFRA": ("Fráncfort", ".F"), "XSTU": ("Stuttgart", ".SG"),
          "XPAR": ("París", ".PA"), "XAMS": ("Ámsterdam", ".AS"), "XMIL": ("Milán", ".MI"),
          "XMAD": ("Madrid", ".MC"), "XBRU": ("Bruselas", ".BR"), "XSWX": ("Suiza", ".SW"),
          "XLON": ("Londres", ".L"), "XWBO": ("Viena", ".VI"), "XLIS": ("Lisboa", ".LS")}
MS_SERIE = "https://lt.morningstar.com/api/rest.svc/timeseries_price/t92wz0sj7c?"
MS_SEARCH = "https://lt.morningstar.com/api/rest.svc/klr5zyak8x/security/screener?"


FETCH_FAILURES = []


def _is_network_address(e):
    if isinstance(e, urllib.error.HTTPError):
        return e.code == 429 or e.code >= 500
    return isinstance(e, (urllib.error.URLError, TimeoutError, OSError))


def _get(url, timeout=15):
    for attempt in (1, 2, 3):
        try:
            with network.open_url(url, UA, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            if not _is_network_address(e):
                raise
            if attempt == 3:
                motivo = getattr(e, "reason", None) or getattr(e, "code", None) or e
                FETCH_FAILURES.append(f"{url.split('/')[2]}: {motivo}")
                print(f"  (sin respuesta de {url.split('/')[2]}: {motivo})")
                raise
            time.sleep(1.5 * attempt)


def fetch_error_since(n):
    return FETCH_FAILURES[-1] if len(FETCH_FAILURES) > n else None


def _try_fetch(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return []


def yahoo_search(q, n=8):
    url = ("https://query2.finance.yahoo.com/v1/finance/search?"
           + urllib.parse.urlencode({"q": q, "quotesCount": n, "newsCount": 0}))
    return [x for x in _get(url).get("quotes", []) if x.get("symbol")]


def morningstar_search(isin):
    q = {"page": 1, "pageSize": 10, "outputType": "json", "version": 1, "languageId": "es-ES",
         "currencyId": "EUR", "universeIds": "FOESP$$ALL|ETEUR$$ALL",
         "securityDataPoints": "SecId|Name|isin|Universe|PriceCurrency|ExchangeId|Ticker|"
                               "OngoingCharge|CollectedSRRI|CategoryName|BrandingCompanyName",
         "term": isin}
    return _get(MS_SEARCH + urllib.parse.urlencode(q)).get("rows", [])


ES_PLAN = re.compile(r"(\bPP\b|\bPPI\b|\bPPES\b|\bPPA\b|\bEPSV\b|pensi)", re.I)


def morningstar_search_name(text):
    data = "SecId|Name|isin|Universe|OngoingCharge|CollectedSRRI|CategoryName|BrandingCompanyName"
    q = {"page": 1, "pageSize": 8, "outputType": "json", "version": 1, "languageId": "es-ES",
         "currencyId": "EUR", "universeIds": "FOESP$$ALL", "securityDataPoints": data, "term": text}
    fondos = _get(MS_SEARCH + urllib.parse.urlencode(q)).get("rows", [])
    q.update(universeIds="FOALL$$ALL", pageSize=30)
    pension_plans = [f for f in _get(MS_SEARCH + urllib.parse.urlencode(q)).get("rows", [])
              if str(f.get("CategoryName") or "").endswith("PP") or ES_PLAN.search(f.get("Name") or "")]
    for f in pension_plans:
        f["_plan"] = True
    return pension_plans[:8] + [f for f in fondos if f.get("SecId") not in {x.get("SecId") for x in pension_plans}][:6]


def coingecko_search(q):
    url = "https://api.coingecko.com/api/v3/search?" + urllib.parse.urlencode({"query": q})
    return _get(url).get("coins", [])


def probe_price(provider, code):
    """Return a provider quote or None if a quote is unavailable."""
    try:
        if provider == "yahoo":
            url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
                   f"{urllib.parse.quote(code)}?range=1mo&interval=1d")
            res = _get(url)["chart"]["result"][0]
            meta = res["meta"]
            closes = [(ts, c) for ts, c in zip(res.get("timestamp", []),
                                                 res["indicators"]["quote"][0].get("close", []))
                       if c is not None]
            if not closes:
                return None
            ts, c = closes[-1]
            return {"precio": round(c, 4), "fecha": dt.date.fromtimestamp(ts).isoformat(),
                    "moneda": meta.get("currency") or "EUR",
                    "nombre": meta.get("longName") or meta.get("shortName"),
                    "mercado": meta.get("fullExchangeName") or meta.get("exchangeName")}
        if provider == "morningstar":
            today = dt.date.today()
            q = {"currencyId": "EUR", "idtype": "Morningstar", "frequency": "daily",
                 "startDate": (today - dt.timedelta(days=20)).isoformat(), "endDate": today.isoformat(),
                 "outputType": "COMPACTJSON", "id": code + "]2]0]FOESP$$ALL"}
            data = [x for x in _get(MS_SERIE + urllib.parse.urlencode(q, safe="]$")) if x and x[1]]
            if not data:
                return None
            ts, v = data[-1][:2]
            return {"precio": round(v, 4), "moneda": "EUR", "mercado": "Morningstar",
                    "fecha": dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date().isoformat()}
        if provider == "coingecko":
            url = ("https://api.coingecko.com/api/v3/simple/price?"
                   + urllib.parse.urlencode({"ids": code, "vs_currencies": "eur"}))
            v = _get(url).get(code, {}).get("eur")
            if not v:
                return None
            return {"precio": v, "moneda": "EUR", "fecha": dt.date.today().isoformat(),
                    "mercado": "CoinGecko"}
    except Exception:
        return None
    return None


def search(text):
    """Find an instrument by ISIN, ticker, or name and verify candidate prices."""
    q = (text or "").strip()
    if not q:
        return []
    cands = []

    def append(provider, code, name, kind, instrument_id=None, live_quote=None, mercado=None):
        if not any(c["fuente"] == provider and c["codigo"] == code for c in cands):
            cands.append({"fuente": provider, "codigo": code, "nombre": name, "tipo": kind,
                          "identificador": instrument_id or ("" if kind == "pension" else code),
                          "vivo": live_quote, "bolsa": mercado})

    if q.lower() in ATAJOS:
        cod, name = ATAJOS[q.lower()]
        append("yahoo", cod, name, "commodity")

    if ES_ISIN.match(q.upper()):
        isin = q.upper()
        rows = _try_fetch(morningstar_search, isin)
        quotes = _try_fetch(yahoo_search, isin)
        zero_price = next((x["symbol"].split(".")[0] for x in quotes
                       if x["symbol"].startswith("0P")), None)
        for f in rows:
            if f.get("Universe", "").startswith("FO"):
                append("morningstar", zero_price or f["SecId"], f.get("Name"), "fondo", isin)
                zero_price = None
        if zero_price:
            append("morningstar", zero_price, None, "fondo", isin)
        for x in quotes:
            sym, kind = x["symbol"], x.get("quoteType")
            if sym.startswith("0P") or (kind == "MUTUALFUND" and cands):
                continue
            append("yahoo", sym, x.get("longname") or x.get("shortname"), YAHOO_TYPES.get(kind, "otro"), isin)
            if kind in ("ETF", "EQUITY"):
                base = sym.split(".")[0]
                for y in _try_fetch(yahoo_search, base):
                    if y["symbol"].split(".")[0] == base and y.get("quoteType") == kind:
                        append("yahoo", y["symbol"], y.get("longname") or y.get("shortname"),
                              YAHOO_TYPES.get(kind, "otro"), isin)
        for f in rows:
            if f.get("Universe", "").startswith("FO") or f.get("PriceCurrency") != "EUR":
                continue
            bolsa, sufijo = BOLSAS.get((f.get("ExchangeId") or "")[-4:], (None, None))
            if sufijo and f.get("Ticker"):
                append("yahoo", f["Ticker"] + sufijo, f.get("Name"), "etf", isin)
            append("morningstar", f["SecId"], f.get("Name"), "etf", isin, mercado=bolsa)
    else:
        if len(q) >= 4:
            for f in _try_fetch(morningstar_search_name, q):
                kind = "pension" if f.get("_plan") else "fondo"
                append("morningstar", f["SecId"], f.get("Name"), kind, f.get("isin") or None)
                product_details = {"ter": f.get("OngoingCharge"), "riesgo": f.get("CollectedSRRI"),
                         "clase": f.get("CategoryName"), "gestora": f.get("BrandingCompanyName")}
                cands[-1]["ficha"] = {k: v for k, v in product_details.items() if v not in (None, "")}
        currencies = _try_fetch(coingecko_search, q)
        for x in _try_fetch(yahoo_search, q):
            sym, kind = x["symbol"], x.get("quoteType")
            if kind not in YAHOO_TYPES:
                continue
            if kind == "CRYPTOCURRENCY":
                base = sym.split("-")[0]
                cg = next((c["id"] for c in currencies if (c.get("symbol") or "").upper() == base), None)
                append("yahoo", f"{base}-EUR", (x.get("shortname") or base).replace(" USD", ""),
                      "cripto", base, live_quote=cg)
            else:
                append("yahoo", sym, x.get("longname") or x.get("shortname"), YAHOO_TYPES[kind])
        if not any(c["tipo"] == "cripto" for c in cands):
            for c in [c for c in currencies if c.get("market_cap_rank")][:3]:
                append("coingecko", c["id"], c.get("name"), "cripto",
                      (c.get("symbol") or "").upper(), live_quote=c["id"])

    if ES_ISIN.match(q.upper()):
        f = next((f for f in rows if f.get("OngoingCharge") is not None or f.get("CollectedSRRI")), None)
        if f:
            product_details = {"ter": f.get("OngoingCharge"), "riesgo": f.get("CollectedSRRI"),
                     "clase": f.get("CategoryName"), "gestora": f.get("BrandingCompanyName")}
            for c in cands:
                c["ficha"] = {k: v for k, v in product_details.items() if v not in (None, "")}

    cands = cands[:12]
    with ThreadPoolExecutor(max_workers=8) as ex:
        prices = list(ex.map(lambda c: probe_price(c["fuente"], c["codigo"]), cands))
    output = []
    for c, p in zip(cands, prices):
        if not p:
            continue
        c.update({k: v for k, v in p.items() if v is not None and (k != "nombre" or not c["nombre"])})
        c["mercado"] = c.pop("bolsa") or c.get("mercado")
        output.append(c)
    exacto = q.upper()
    output.sort(key=lambda c: (c["fuente"] != "morningstar" or c["tipo"] not in ("fondo", "pension"),
                               c["codigo"].upper() != exacto, c.get("moneda") != "EUR"))
    return output

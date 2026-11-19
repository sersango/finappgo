"""Calculate portfolio value, cash flows, returns, and benchmark series."""

import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import datetime as dt
from collections import defaultdict

from . import network

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CACHE = "cache"
OFFLINE = False
MISSING_ONLY = False
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

PALETTE = {
    1: ("#2a78d6", "#3987e5"),
    2: ("#eb6834", "#d95926"),
    3: ("#1baf7a", "#199e70"),
    4: ("#eda100", "#c98500"),
    5: ("#e87ba4", "#d55181"),
    6: ("#008300", "#008300"),
    7: ("#4a3aa7", "#9085e9"),
    8: ("#e34948", "#e66767"),
    9: ("#0e8fb0", "#2bb0d1"),
    10: ("#9a6a3a", "#c08a55"),
    11: ("#5d6b8a", "#93a1c2"),
    12: ("#7c9a00", "#9cc21a"),
}

WARNINGS = []


def notice(txt):
    WARNINGS.append(txt)
    print("  [!] " + txt)


def today():
    return dt.date.today()


def d(s):
    return dt.date.fromisoformat(s)


def date_range(start, end):
    out, x = [], start
    while x <= end:
        out.append(x)
        x += dt.timedelta(days=1)
    return out


def parse_spanish_number(txt):
    t = (txt or "").strip().replace(" ", "").replace(" ", "").replace("€", "")
    if not t:
        return 0.0
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return 0.0


def r2(x):
    return None if x is None else round(float(x), 2)


def r4(x):
    return None if x is None else round(float(x), 4)


def fetch_yahoo_prices(symbol, years=None):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9._-]", "_", symbol) + ".json")
    previous_value = read_cache(path)
    if OFFLINE or (MISSING_ONLY and previous_value):
        return previous_value

    start = int(time.time()) - years * 365 * 86400 if years else 0
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(symbol)}?period1={start}&period2={int(time.time())}&interval=1d")
    try:
        with network.open_url(url, UA, timeout=30) as resp:
            bruto = json.loads(resp.read().decode("utf-8", "replace"))
        res = bruto["chart"]["result"][0]
        granularidad = (res.get("meta") or {}).get("dataGranularity", "1d")
        if granularidad != "1d":
            notice(f"{symbol}: Yahoo ha devuelto precios cada {granularidad} en vez de diarios; uso la cache.")
            return previous_value
        closes = res["indicators"]["quote"][0].get("close", [])
        new_entry = {}
        for ts, c in zip(res.get("timestamp", []), closes):
            if c is not None:
                new_entry[dt.date.fromtimestamp(ts).isoformat()] = float(c)
        if new_entry:
            previous_value = {k: v for k, v in previous_value.items() if k < min(new_entry)}
            previous_value.update(new_entry)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(previous_value, f)
            print(f"  OK  {symbol:16s} {len(new_entry):5d} sesiones  "
                  f"ultimo {sorted(new_entry)[-1]} = {new_entry[sorted(new_entry)[-1]]:.4f}")
        else:
            notice(f"{symbol}: Yahoo no devolvio cotizaciones, uso la cache.")
    except Exception as e:
        if previous_value:
            notice(f"{symbol}: sin conexion ({type(e).__name__}), uso la cache guardada.")
        else:
            notice(f"{symbol}: sin conexion y sin cache ({type(e).__name__}).")
    return previous_value


def fetch_morningstar_prices(secid, universo="]2]0]FOESP$$ALL", years=30):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "MS_" + re.sub(r"[^A-Za-z0-9]", "_", secid) + ".json")
    previous_value = read_cache(path)
    if OFFLINE or (MISSING_ONLY and previous_value):
        return adjust_weekend(previous_value)
    hoy_ = dt.date.today()
    q = {"currencyId": "EUR", "idtype": "Morningstar", "frequency": "daily",
         "startDate": (hoy_ - dt.timedelta(days=365 * years)).isoformat(),
         "endDate": hoy_.isoformat(), "outputType": "COMPACTJSON", "id": secid + universo}
    url = ("https://lt.morningstar.com/api/rest.svc/timeseries_price/t92wz0sj7c?"
           + urllib.parse.urlencode(q, safe="]$"))
    try:
        with network.open_url(url, UA, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        new_entry = {dt.datetime.fromtimestamp(x[0] / 1000, dt.timezone.utc).date().isoformat(): float(x[1])
                 for x in data if x and len(x) > 1 and x[1] is not None}
        if new_entry:
            previous_value.update(new_entry)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(previous_value, f)
            print(f"  OK  Morningstar {secid:12s} {len(new_entry):5d} VL  "
                  f"ultimo {max(new_entry)} = {new_entry[max(new_entry)]:.4f}")
        else:
            notice(f"Morningstar {secid}: sin datos, uso la cache.")
    except Exception as e:
        if previous_value:
            notice(f"Morningstar {secid}: sin conexion ({type(e).__name__}), uso la cache guardada.")
        else:
            notice(f"Morningstar {secid}: no disponible ({type(e).__name__}); solo Yahoo.")
    return adjust_weekend(previous_value)


def adjust_weekend(price_series):
    out = {k: v for k, v in price_series.items() if dt.date.fromisoformat(k).weekday() < 5}
    for k in sorted(price_series):
        d = dt.date.fromisoformat(k)
        if d.weekday() >= 5:
            out.setdefault((d - dt.timedelta(days=d.weekday() - 4)).isoformat(), price_series[k])
    return out


def merge_nav_series(ms, yahoo, name=""):
    """Use Morningstar NAVs where Yahoo omits trading days, while retaining Yahoo history."""
    out, diverge, cubiertos = {}, 0, 0
    for f in set(ms) | set(yahoo):
        m, y = ms.get(f), yahoo.get(f)
        if m and y:
            if abs(m - y) <= 0.0006:
                out[f] = y
            else:
                out[f] = m
                diverge += 1
        elif m:
            out[f] = m
            cubiertos += 1
        else:
            out[f] = y
    print(f"  ..  {name}: {len(out)} VL, {cubiertos} huecos de Yahoo cubiertos por Morningstar"
          + (f", {diverge} discrepancias resueltas a favor de Morningstar" if diverge else ""))
    return out


def forward_fill(price_series, timeline):
    keys = sorted(price_series)
    if not keys:
        return [None] * len(timeline)
    out, i, last = [], 0, None
    for f in timeline:
        fi = f.isoformat()
        while i < len(keys) and keys[i] <= fi:
            last = price_series[keys[i]]
            i += 1
        out.append(last)
    return out


def value_at(price_series, date, margen=10):
    """Return the latest known value on or before the requested date."""
    f = date if isinstance(date, dt.date) else d(date)
    for i in range(margen + 1):
        k = (f - dt.timedelta(days=i)).isoformat()
        if k in price_series:
            return price_series[k]
    return None


def date_at(price_series, date, margen=10):
    """Return the date of the latest observation on or before the requested date."""
    f = date if isinstance(date, dt.date) else d(date)
    for i in range(margen + 1):
        k = (f - dt.timedelta(days=i)).isoformat()
        if k in price_series:
            return k
    return None


def convert_closes_to_eur(price_series, serie_fx):
    if serie_fx is None:
        return dict(price_series)
    out = {}
    for k, v in price_series.items():
        x = value_at(serie_fx, k, margen=5)
        if x:
            out[k] = v * x
    return out


def read_cache(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def write_cache(path, price_series):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(price_series, f)


def exchange_rate_symbol(currency):
    """Return the Yahoo FX pair and the multiplier used for subunits such as pence."""
    m = (currency or "EUR").strip()
    if m in ("GBp", "GBX"):
        return "GBPEUR=X", 0.01
    m = m.upper()
    if m == "EUR":
        return None, 1.0
    return f"{m}EUR=X", 1.0


def convert_series_to_eur(price_series, currency, series):
    sim, factor = exchange_rate_symbol(currency)
    if sim:
        fx = series.get(sim) or {}
        if not fx:
            if price_series:
                notice(f"No tengo el cambio {sim}: no puedo pasar a euros los precios en {currency}.")
            return {}
        price_series = convert_closes_to_eur(price_series, fx)
    return {k: v * factor for k, v in price_series.items()} if factor != 1 else dict(price_series)


_PRICE_CACHE = {}


def price_in_eur(p, series, tolerancia=0.03):
    if p["id"] in _PRICE_CACHE:
        return _PRICE_CACHE[p["id"]]

    if p.get("fuente") == "yahoo":
        principal = convert_series_to_eur(series.get(p.get("codigo"), {}), p.get("moneda"), series)
    elif p.get("fuente") in ("morningstar", "coingecko"):
        principal = dict(series.get(series_key(p), {}))
    else:
        principal = {}
    fallback = (convert_series_to_eur(series.get(p["respaldo"], {}), p.get("respaldoMoneda"), series)
                if p.get("respaldo") else {})
    if not fallback:
        _PRICE_CACHE[p["id"]] = principal
        return principal

    out, replaced, last = {}, 0, None
    for f in sorted(set(principal) | set(fallback)):
        pr, rs = principal.get(f), fallback.get(f)
        if pr and rs:
            if abs(pr / rs - 1) <= tolerancia:
                v = pr
            else:
                v, replaced = rs, replaced + 1
        elif rs:
            v = rs
        else:
            if last and abs(pr / last - 1) > 0.15:
                replaced += 1
                continue
            v = pr
        out[f] = v
        last = v
    if replaced:
        print(f"  ..  {p.get('corto')}: {replaced} cierres de {p.get('codigo')} no cuadraban "
              f"y se han sustituido por {p['respaldo']}")
    _PRICE_CACHE[p["id"]] = out
    return out


def xirr(cash_flows):
    """Compute the annualized return of dated cash flows. Contributions are negative."""
    cash_flows = [(f, float(v)) for f, v in cash_flows if v]
    if len(cash_flows) < 2:
        return None
    if not (any(v < 0 for _, v in cash_flows) and any(v > 0 for _, v in cash_flows)):
        return None
    f0 = min(f for f, _ in cash_flows)

    def npv(rate):
        s = 0.0
        for f, v in cash_flows:
            t = (f - f0).days / 365.0
            base = 1.0 + rate
            if base <= 1e-9:
                return float("inf")
            s += v / (base ** t)
        return s

    lo, hi = -0.9999, 10.0
    try:
        vlo, vhi = npv(lo), npv(hi)
    except Exception:
        return None
    if not (math.isfinite(vlo) and math.isfinite(vhi)) or vlo * vhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        vm = npv(mid)
        if abs(vm) < 1e-7:
            return mid
        if vlo * vm <= 0:
            hi, vhi = mid, vm
        else:
            lo, vlo = mid, vm
    return (lo + hi) / 2


def fetch_coingecko_prices(coin, dias=365):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "CG_" + re.sub(r"[^A-Za-z0-9._-]", "_", coin) + ".json")
    previous_value = read_cache(path)
    if OFFLINE or (MISSING_ONLY and previous_value):
        return previous_value
    url = (f"https://api.coingecko.com/api/v3/coins/{urllib.parse.quote(coin)}/market_chart"
           f"?vs_currency=eur&days={dias}&interval=daily")
    try:
        with network.open_url(url, UA, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        new_entry = {dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date().isoformat(): float(v)
                 for ts, v in data.get("prices", []) if v is not None}
        if new_entry:
            previous_value.update(new_entry)
            write_cache(path, previous_value)
            print(f"  OK  CoinGecko {coin:14s} {len(new_entry):5d} dias  "
                  f"ultimo {max(new_entry)} = {new_entry[max(new_entry)]:.2f}")
        else:
            notice(f"CoinGecko {coin}: sin datos, uso los precios guardados.")
    except Exception as e:
        notice(f"CoinGecko {coin}: no responde ({type(e).__name__}), uso los precios guardados."
              if previous_value else f"CoinGecko {coin}: no responde y no tengo precios guardados.")
    return previous_value


PRODUCT_TYPES = {
    "fondo": "Fondo de inversión", "etf": "ETF", "accion": "Acción", "cripto": "Criptomoneda",
    "commodity": "Materia prima", "bono": "Bono", "pension": "Plan de pensiones",
    "efectivo": "Cuenta / efectivo", "inmueble": "Inmueble", "deuda": "Deuda / préstamo",
    "p2p": "Préstamos P2P / crowdfunding", "otro": "Otro",
}
CLASE_DEFECTO = {
    "fondo": "Fondos", "etf": "Renta variable", "accion": "Renta variable",
    "cripto": "Criptoactivos", "commodity": "Materias primas", "bono": "Renta fija",
    "pension": "Jubilación", "efectivo": "Efectivo", "inmueble": "Inmuebles",
    "deuda": "Deudas", "p2p": "P2P y crowdfunding", "otro": "Otros",
}
PRICE_SOURCES = {"morningstar": "Morningstar", "yahoo": "Yahoo Finance",
           "coingecko": "CoinGecko", "manual": "Valor anotado a mano"}
ORDEN_TIPO = {"compra": 0, "comision": 1, "dividendo": 2, "venta": 3, "traspaso_salida": 4, "traspaso_entrada": 5,
              "ajuste": 6}

REFERENCIAS = {
    "mundo": {"nombre": "MSCI World",
              "detalle": "ETF iShares Core MSCI World (IWDA), en euros: unas 1.400 empresas de 23 países desarrollados.",
              "piezas": [("IWDA.AS", 1.0)]},
    "sp500": {"nombre": "S&P 500",
              "detalle": "ETF iShares Core S&P 500 (SXR8), en euros: las 500 mayores empresas de EE. UU.",
              "piezas": [("SXR8.DE", 1.0)]},
    "6040": {"nombre": "Cartera 60/40",
             "detalle": "60 % MSCI World (IWDA) y 40 % bonos globales cubiertos a euros (EUNA), sin rebalancear.",
             "piezas": [("IWDA.AS", 0.6), ("EUNA.DE", 0.4)]},
    "sinriesgo": {"nombre": "Sin riesgo",
                  "detalle": "ETF monetario del euro (XEON): lo que da el dinero aparcado, sin sustos.",
                  "piezas": [("XEON.DE", 1.0)]},
}
ETIQUETAS = {
    "fondo": ("Valor liquidativo", "Participaciones", "El valor liquidativo del fondo"),
    "pension": ("Valor liquidativo", "Participaciones", "El valor liquidativo del plan"),
    "etf": ("Precio del ETF", "Participaciones", "El precio del ETF"),
    "accion": ("Precio de la acción", "Acciones", "El precio de la acción"),
    "cripto": ("Precio", "Unidades", "El precio de la criptomoneda"),
    "commodity": ("Precio por unidad", "Unidades", "El precio"),
    "bono": ("Precio del bono", "Títulos", "El precio del bono"),
}


TEXTOS_LIBRES = ("nombre", "corto", "entidad", "clase", "gestora", "tipoDetalle", "papel",
                 "identificador", "codigo", "indice", "indiceDetalle", "politica", "mercado", "isin")


def strip_html(text):
    return re.sub(r"[<>]", "", text) if isinstance(text, str) else text


def sanitize_text(p):
    for k in TEXTOS_LIBRES:
        if isinstance(p.get(k), str):
            p[k] = strip_html(p[k])
    return p


def format_spanish_date(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


def transaction_prices(movs):
    out = {}
    for m in sorted(movs, key=lambda m: m["fecha"]):
        u = float(m.get("unidades") or 0)
        if m.get("tipo") not in ("compra", "venta") or u <= 0:
            continue
        imp, benchmark = float(m.get("importe") or 0), float(m.get("comision") or 0)
        net = imp - benchmark if m.get("tipo") == "compra" else imp + benchmark
        if net > 0:
            out[m["fecha"]] = net / u
    return out


def rental_income(movs, statement_date):
    one_year_ago = (statement_date - dt.timedelta(days=365)).isoformat()
    out, exists = {"cobrado": 0.0, "gastos": 0.0, "cobrado12": 0.0, "gastos12": 0.0}, False
    for m in movs:
        if m.get("tipo") not in ("dividendo", "comision"):
            continue
        exists = True
        k = "cobrado" if m["tipo"] == "dividendo" else "gastos"
        imp = float(m.get("importe") or 0)
        out[k] += imp
        if m["fecha"] > one_year_ago:
            out[k + "12"] += imp
    return {k: r2(v) for k, v in out.items()} if exists else None


def custom_goal(cfg):
    o = cfg.get("objetivo")
    if not isinstance(o, dict) or not o.get("activo") or not o.get("importe"):
        return None
    if not o.get("elegido") and float(o["importe"]) == 100000:
        return None
    return {"activo": True, "importe": float(o["importe"]),
            "etiqueta": strip_html(o.get("etiqueta") or "Mi objetivo")}


def emergency_fund(cfg):
    c = cfg.get("colchon")
    if not isinstance(c, dict):
        return None
    try:
        if c.get("modo") == "importe":
            return {"modo": "importe", "importe": float(c["importe"])}
        return {"modo": "meses", "meses": float(c["meses"]), "gastoMensual": float(c["gastoMensual"]),
                "importe": round(float(c["meses"]) * float(c["gastoMensual"]), 2)}
    except (KeyError, TypeError, ValueError):
        return None


def target_allocation(cfg):
    o = cfg.get("objetivoReparto")
    if not isinstance(o, dict) or not o.get("pesos"):
        return None
    return {"por": "producto" if o.get("por") == "producto" else "clase",
            "pesos": {strip_html(str(k)): float(v) for k, v in o["pesos"].items() if isinstance(v, (int, float))},
            "vigilar": float(o.get("vigilar") or 3), "rebalancear": float(o.get("rebalancear") or 5),
            "conEfectivo": bool(o.get("conEfectivo")),
            "cuenta": {strip_html(str(k)): bool(v) for k, v in (o.get("cuenta") or {}).items()}
            if isinstance(o.get("cuenta"), dict) else {}}


def series_key(p):
    return {"morningstar": "MS:", "coingecko": "CG:"}.get(p.get("fuente"), "") + (p.get("codigo") or "")


def expand_transfers(movements):
    """Convert each stored transfer into an outgoing and an incoming leg."""
    out = []
    for m in movements:
        if m.get("tipo") != "traspaso":
            out.append(m)
            continue
        out.append({**m, "tipo": "traspaso_salida", "_tid": m.get("id")})
        out.append({**m, "tipo": "traspaso_entrada", "producto": m.get("destino"), "origen": m.get("producto"),
                    "unidades": m.get("unidadesDestino"), "_tid": m.get("id")})
    return out


def _take_fifo(lots, units):
    """Take units from the oldest lots first. Return the portions and the unfilled quantity."""
    remaining_lots, portions = units, []
    while remaining_lots > 1e-9 and lots:
        lu, lc, ref, lf = lots[0]
        take = min(lu, remaining_lots)
        parte = lc * take / lu if lu else 0.0
        portions.append([take, parte, ref, lf])
        remaining_lots -= take
        lots[0] = [lu - take, lc - parte, ref, lf]
        if lots[0][0] <= 1e-9:
            lots.pop(0)
    return portions, remaining_lots


def _take_proportionally(lots, fraction):
    """For assets without units, remove the same fraction from each lot."""
    portions = []
    for lot in lots:
        lu, lc, ref, lf = lot
        portions.append([lu * fraction, lc * fraction, ref, lf])
        lot[0], lot[1] = lu * (1 - fraction), lc * (1 - fraction)
    lots[:] = [l for l in lots if l[1] > 1e-9 or l[0] > 1e-9]
    return portions


def apply_all_movements(products, movements_by_product, manual_value=None, conservar_lotes=False, manual_contributions=None):
    """Apply transactions in date order across all products so transfers can carry lots forward."""
    est = {p["id"]: {"eventos": [], "flujos": [], "realizado": 0.0, "comisiones": 0.0, "vendidas": set(),
                     "lotes": [], "traspasos": [], "ajustes": [],
                     "ventas": 0.0, "dividendos": 0.0, "gastos": 0.0, "costeVendido": 0.0,
                     "ventasDetalle": []}
           for p in products}
    name = {p["id"]: p.get("corto") or p.get("nombre") or p["id"] for p in products}
    todos = [m for pid, movs in movements_by_product.items() if pid in est for m in movs
             if m.get("tipo") != "traspaso_entrada"]
    for m in sorted(todos, key=lambda x: (x["fecha"], ORDEN_TIPO.get(x.get("tipo"), 9))):
        pid, f, t = m["producto"], m["fecha"], m.get("tipo")
        e = est[pid]
        u, imp = float(m.get("unidades") or 0), float(m.get("importe") or 0)
        if t == "compra":
            e["lotes"].append([u, imp, id(m), f])
            e["eventos"].append((f, u, imp))
            e["flujos"].append((f, -imp))
            e["comisiones"] += float(m.get("comision") or 0)
        elif t == "venta":
            portions, remaining_lots = _take_fifo(e["lotes"], u)
            cost_basis = sum(x[1] for x in portions)
            e["vendidas"].update(x[2] for x in portions)
            if remaining_lots > 1e-6:
                notice(f"{name[pid]}: el {f} vendes más unidades de las que tienes. Revisa sus movimientos.")
            e["realizado"] += imp - cost_basis
            e["ventas"] += imp - cost_basis
            e["costeVendido"] += cost_basis
            e["ventasDetalle"].append({"fecha": f, "unidades": u - remaining_lots, "importe": imp, "coste": cost_basis,
                                       "compras": [[x[3], x[0], x[1]] for x in portions],
                                       "faltan": remaining_lots if remaining_lots > 1e-6 else 0.0})
            e["eventos"].append((f, -(u - remaining_lots), -cost_basis))
            e["flujos"].append((f, imp))
        elif t == "dividendo":
            e["realizado"] += imp
            e["dividendos"] += imp
            e["flujos"].append((f, imp))
        elif t == "comision":
            e["realizado"] -= imp
            e["gastos"] += imp
            e["comisiones"] += imp
            e["flujos"].append((f, -imp))
        elif t == "ajuste":
            held_units = sum(l[0] for l in e["lotes"])
            if held_units > 1e-12:
                factor = u / held_units
                for l in e["lotes"]:
                    l[0] *= factor
            elif u > 0:
                e["lotes"].append([u, 0.0, id(m), f])
            e["eventos"].append((f, u - held_units, 0.0))
            e["ajustes"].append({"fecha": f, "antes": r4(held_units), "despues": r4(u)})
        elif t == "traspaso_salida":
            dest = m.get("destino")
            ud = float(m.get("unidadesDestino") or 0)
            tracks_units = u > 0 and any(l[0] > 1e-9 for l in e["lotes"])
            if tracks_units:
                portions, remaining_lots = _take_fifo(e["lotes"], u)
                if remaining_lots > 1e-6:
                    notice(f"{name[pid]}: el {f} traspasas más participaciones de las que tienes. "
                          "Revisa sus movimientos.")
                outgoing = u - remaining_lots
            else:
                total_cost_basis = sum(l[1] for l in e["lotes"])
                if total_cost_basis <= 1e-9 and manual_contributions:
                    ap = manual_contributions(pid, f)
                    if ap and ap > 0:
                        e["lotes"] = [[0.0, float(ap), ("aportado", pid), f]]
                        total_cost_basis = float(ap)
                value = manual_value(pid, f) if manual_value else None
                if m.get("total"):
                    fraction = 1.0
                elif value:
                    fraction = min(1.0, imp / value)
                else:
                    fraction = min(1.0, imp / total_cost_basis) if total_cost_basis else 1.0
                portions, outgoing = _take_proportionally(e["lotes"], fraction), 0.0
            cost_basis = sum(x[1] for x in portions)
            e["vendidas"].update(x[2] for x in portions)
            e["eventos"].append((f, -outgoing, -cost_basis))
            e["flujos"].append((f, imp))
            e["traspasos"].append({"fecha": f, "tipo": "salida", "otro": dest, "importe": r2(imp),
                                   "unidades": r4(outgoing) if tracks_units else None, "coste": r2(cost_basis),
                                   "total": bool(m.get("total")), "estimada": bool(m.get("fechaEstimada"))})
            d_ = est.get(dest)
            if d_ is None:
                notice(f"{name[pid]}: el traspaso del {f} va a un producto que ya no existe o es una cuenta.")
                continue
            base = outgoing if tracks_units and outgoing > 1e-12 else cost_basis
            for tu, tc, ref, lf in portions:
                weight = (tu if tracks_units and outgoing > 1e-12 else tc) / base if base else 1.0 / len(portions)
                new_entry = [ud * weight, tc, ("t", m.get("_tid"), ref), lf]
                i = len(d_["lotes"])
                while i > 0 and d_["lotes"][i - 1][3] > lf:
                    i -= 1
                d_["lotes"].insert(i, new_entry)
            if not portions and ud:
                d_["lotes"].append([ud, 0.0, ("t", m.get("_tid")), f])
            d_["eventos"].append((f, ud, cost_basis))
            d_["flujos"].append((f, -imp))
            d_["traspasos"].append({"fecha": f, "tipo": "entrada", "otro": pid, "importe": r2(imp),
                                    "unidades": r4(ud) if ud else None, "coste": r2(cost_basis),
                                    "total": bool(m.get("total")), "estimada": bool(m.get("fechaEstimada"))})
    if not conservar_lotes:
        for e in est.values():
            e.pop("lotes")
    return est


def open_lots(cfg, pid, date):
    products = [p for p in cfg.get("productos", []) if p.get("tipo") not in ("efectivo", "deuda")]
    movements_by_product = defaultdict(list)
    for m in expand_transfers(m for m in cfg.get("movimientos", []) if m.get("fecha", "") <= date):
        movements_by_product[m.get("producto")].append(m)
    est = apply_all_movements(products, movements_by_product, conservar_lotes=True)
    return [l for l in (est.get(pid) or {}).get("lotes", []) if l[0] > 1e-9 or l[1] > 1e-9]


def interpolate(snaps, date):
    previous_value = None
    for f, v in snaps:
        if f == date:
            return v
        if f > date:
            if previous_value is None:
                return None
            f0, v0 = previous_value
            t = (d(date) - d(f0)).days / max((d(f) - d(f0)).days, 1)
            return v0 + (v - v0) * t
        previous_value = (f, v)
    return previous_value[1] if previous_value else None


def snapshots_with_transfers(snaps, transfers):
    """Insert the implied valuation change when a manual asset is transferred between snapshots."""
    snaps = [list(s) for s in snaps]
    for t in sorted(transfers, key=lambda t: t["fecha"]):
        f = t["fecha"]
        if any(s[0] == f for s in snaps):
            continue
        before = interpolate([(s[0], s[1]) for s in snaps], f)
        ap_antes = interpolate([(s[0], float(s[2])) for s in snaps if s[2] is not None], f)
        cost_basis = t.get("coste") or 0.0
        if t["tipo"] == "salida":
            new_entry = 0.0 if t.get("total") else max(0.0, (before or 0.0) - (t["importe"] or 0.0))
            new_contribution = None if ap_antes is None else (0.0 if t.get("total") else max(0.0, ap_antes - cost_basis))
        else:
            new_entry = (before or 0.0) + (t["importe"] or 0.0)
            new_contribution = None if ap_antes is None else ap_antes + cost_basis
        vispera = (d(f) - dt.timedelta(days=1)).isoformat()
        if before is not None and not any(s[0] == vispera for s in snaps):
            snaps.append([vispera, round(before, 2), None if ap_antes is None else round(ap_antes, 2)])
        snaps.append([f, round(new_entry, 2), None if new_contribution is None else round(new_contribution, 2)])
        snaps.sort(key=lambda s: s[0])
    return snaps


def apply_movements(p, movs):
    return apply_all_movements([p], {p["id"]: movs})[p["id"]]


def income_summary(movements, products, statement_date):
    by_id = {p["id"]: p for p in products}
    one_year_ago = (statement_date - dt.timedelta(days=365)).isoformat()
    income = sorted((m["fecha"], m["producto"], float(m.get("importe") or 0))
                    for m in movements if m.get("tipo") == "dividendo" and m.get("producto") in by_id)
    by_year, by_product = defaultdict(float), {}
    for f, pid, imp in income:
        by_year[f[:4]] += imp
        x = by_product.setdefault(pid, {"id": pid, "total": 0.0, "ultimos12": 0.0, "cobros": 0, "ultimo": None})
        x["total"] += imp
        x["cobros"] += 1
        x["ultimo"] = f
        if f > one_year_ago:
            x["ultimos12"] += imp
    lines = []
    for x in sorted(by_product.values(), key=lambda x: -x["total"]):
        p = by_id[x["id"]]
        lines.append({**x, "total": r2(x["total"]), "ultimos12": r2(x["ultimos12"]),
                       "sobreValor": r4(x["ultimos12"] / p["valor"]) if p.get("valor") else None,
                       "sobreCoste": r4(x["ultimos12"] / p["aportado"]) if p.get("aportado") else None})
    ultimos12 = sum(x["ultimos12"] for x in by_product.values())
    valor_pagadores = sum(by_id[x["id"]].get("valor") or 0 for x in by_product.values() if x["ultimos12"])
    years = [str(a) for a in range(int(min(by_year)), statement_date.year + 1)] if by_year else []
    return {"total": r2(sum(by_year.values())), "ultimos12": r2(ultimos12),
            "rentabilidad": r4(ultimos12 / valor_pagadores) if valor_pagadores else None,
            "porAno": [[a, r2(by_year.get(a, 0.0))] for a in years],
            "porProducto": lines,
            "ultimos": [{"fecha": f, "producto": pid, "importe": r2(imp)} for f, pid, imp in reversed(income[-12:])]}


MONEDAS_VISTA = {"USD": "Dólares", "GBP": "Libras", "CHF": "Francos suizos", "MXN": "Pesos mexicanos",
                 "ARS": "Pesos argentinos", "CLP": "Pesos chilenos", "COP": "Pesos colombianos"}


def display_exchange_rates(series):
    out = {}
    for code, name in MONEDAS_VISTA.items():
        sim = exchange_rate_symbol(code)[0]
        s = series.get(sim) or fetch_yahoo_prices(sim, years=1)
        valid_entries = {k: v for k, v in s.items() if v}
        if valid_entries:
            date = max(valid_entries)
            out[code] = {"nombre": name, "porEuro": round(1 / valid_entries[date], 6), "fecha": date}
    return out


def load_price_series(configured_products, series=None):
    series = {} if series is None else series

    def fetch(key, fn, *args):
        if key and key not in series:
            series[key] = fn(*args)

    def fetch_exchange_rate(currency):
        sim = exchange_rate_symbol(currency)[0]
        fetch(sim, fetch_yahoo_prices, sim)

    for p in configured_products:
        f, cod = p.get("fuente"), p.get("codigo")
        if cod and f == "yahoo":
            fetch(cod, fetch_yahoo_prices, cod)
            fetch_exchange_rate(p.get("moneda"))
        elif cod and f == "morningstar" and "MS:" + cod not in series:
            ms = fetch_morningstar_prices(cod)
            yh = fetch_yahoo_prices(cod + ".F") if cod.startswith("0P") else {}
            series["MS:" + cod] = merge_nav_series(ms, yh, p.get("corto", cod)) if ms else yh
        elif cod and f == "coingecko":
            fetch("CG:" + cod, fetch_coingecko_prices, cod)
        if p.get("respaldo"):
            fetch(p["respaldo"], fetch_yahoo_prices, p["respaldo"])
            fetch_exchange_rate(p.get("respaldoMoneda"))
        if p.get("vivo"):
            fetch("CG:" + p["vivo"], fetch_coingecko_prices, p["vivo"])
    return series


def product_price_series(p, directory, refresh=False):
    global CACHE, OFFLINE, MISSING_ONLY
    CACHE, OFFLINE, MISSING_ONLY = os.path.join(directory, "cache"), False, not refresh
    _PRICE_CACHE.pop(p.get("id"), None)
    p = dict(p, id=p.get("id") or "_suelto")
    s = price_in_eur(p, load_price_series([p]))
    _PRICE_CACHE.pop(p["id"], None)
    return s


def exchange_rate_series(currency, directory, refresh=False):
    global CACHE, OFFLINE, MISSING_ONLY
    CACHE, OFFLINE, MISSING_ONLY = os.path.join(directory, "cache"), False, not refresh
    sim = exchange_rate_symbol(currency)[0]
    return fetch_yahoo_prices(sim) if sim else {}


def portfolio_fifo(cfg, configured_products=None):
    if configured_products is None:
        configured_products = cfg.get("productos", [])
    movements_by_product, vals_por = defaultdict(list), defaultdict(list)
    for m in expand_transfers(cfg.get("movimientos", [])):
        movements_by_product[m.get("producto")].append(m)
    for v in cfg.get("valoraciones", []):
        vals_por[v.get("producto")].append(v)

    def manual_value(pid, date):
        snaps = [(v["fecha"], float(v["valor"])) for v in sorted(vals_por.get(pid, []), key=lambda v: v["fecha"])]
        return interpolate(snaps, date)

    def manual_contributions(pid, date):
        snaps = [(v["fecha"], float(v["aportado"])) for v in sorted(vals_por.get(pid, []), key=lambda v: v["fecha"])
                 if v.get("aportado") is not None]
        return interpolate(snaps, date)
    con_movs = [p for p in configured_products if p.get("tipo") not in ("efectivo", "deuda")]
    return apply_all_movements(con_movs, movements_by_product, manual_value, manual_contributions=manual_contributions), movements_by_product, vals_por


def build_dashboard(cfg, directory, fetch_prices=True, cache=None, historico=True):
    global CACHE, OFFLINE, MISSING_ONLY
    CACHE = cache or os.path.join(directory, "cache")
    OFFLINE = not fetch_prices
    MISSING_ONLY = fetch_prices == "faltan"
    WARNINGS.clear()
    _PRICE_CACHE.clear()

    configured_products = [dict(p) for p in cfg.get("productos", [])]
    for p in configured_products:
        sanitize_text(p)
        p.setdefault("fuente", "manual")
        p.setdefault("corto", (p.get("nombre") or p["id"])[:24])

    print("\n=== 1. Precios ===" if fetch_prices is True else "\n=== 1. Precios guardados ===")
    series = load_price_series(configured_products)
    if cfg.get("movimientos"):
        for sim in {s for r in REFERENCIAS.values() for s, _ in r["piezas"]}:
            if sim not in series:
                series[sim] = fetch_yahoo_prices(sim)

    movimientos_de, movements_by_product, vals_por = portfolio_fifo(cfg, configured_products)

    recent = [v["fecha"] for v in cfg.get("valoraciones", [])]
    recent += [m["fecha"] for m in cfg.get("movimientos", []) if m.get("tipo") == "traspaso"]
    for p in configured_products:
        s = price_in_eur(p, series) if p["fuente"] != "manual" else {}
        if s and movements_by_product.get(p["id"]):
            recent.append(max(s))
    statement_date = min(d(max(recent)), today()) if recent else today()
    print(f"  Datos valorados a {statement_date}")

    products, other_assets, liabilities, first_date = [], [], [], None

    for p in configured_products:
        key = p.get("tipo") if p.get("tipo") in PRODUCT_TYPES else "otro"
        p["tipoClave"] = key
        p["tipo"] = p.get("tipoDetalle") or PRODUCT_TYPES[key]
        p.setdefault("clase", CLASE_DEFECTO[key])
        p["fuentePrecio"] = PRICE_SOURCES.get(p["fuente"], p["fuente"])
        etq = ETIQUETAS.get(key, ("Precio", "Unidades", "El precio"))
        if "ETP" in (p.get("tipoDetalle") or "").upper():
            etq = ("Precio del ETP", "Títulos", "El precio del ETP")
        p["etqPrecio"], p["etqUnidades"], p["etqVentanas"] = etq
        p["fuenteTexto"] = " · ".join(x for x in (
            p["fuentePrecio"], p.get("codigo"),
            f"convertido de {p.get('moneda')}" if p["fuente"] == "yahoo" and
            (p.get("moneda") or "EUR").upper() != "EUR" else None) if x)
        p["aportaciones"] = []
        movs = movements_by_product.get(p["id"], [])
        snaps = [[v["fecha"], float(v["valor"]), v.get("aportado")]
                 for v in sorted(vals_por.get(p["id"], []), key=lambda v: v["fecha"])]
        fechas_p = [m["fecha"] for m in movs] + [s[0] for s in snaps]

        if key in ("efectivo", "deuda"):
            if not snaps:
                notice(f"{p['corto']}: todavía no tiene ningún saldo anotado.")
                continue
            p["snapshots"] = snaps
            (other_assets if key == "efectivo" else liabilities).append(p)
            first_date = d(snaps[0][0]) if first_date is None else min(first_date, d(snaps[0][0]))
            continue

        mv = movimientos_de[p["id"]]
        names = {x["id"]: x.get("corto") or x.get("nombre") for x in configured_products}
        p["traspasos"] = [{**t, "otroNombre": names.get(t["otro"], t["otro"])} for t in mv["traspasos"]]
        p["ajustes"] = mv["ajustes"]
        if mv["traspasos"]:
            snaps = snapshots_with_transfers(snaps, mv["traspasos"])
        p["realizado"] = round(mv["realizado"], 2)
        p["cobros"] = {k: round(mv[k], 2) for k in ("ventas", "dividendos", "gastos")}
        p["costeVendido"] = round(mv["costeVendido"], 2)
        p["_mv"] = mv
        has_market_price = p["fuente"] != "manual"
        price_series = price_in_eur(p, series) if has_market_price else {}
        if has_market_price:
            ops = transaction_prices(movs)
            home = min(price_series) if price_series else None
            huecos = {f: v for f, v in ops.items() if home is None or f < home}
            if huecos and (price_series or not snaps):
                if price_series:
                    notice(f"{p['corto']}: {p['fuentePrecio']} no tiene precios antes del {format_spanish_date(home)}; "
                          "hasta entonces lo valoro al precio de tus compras y ventas. Comprueba su código si no cuadra.")
                else:
                    notice(f"{p['corto']}: no encuentro su precio en {p['fuentePrecio']}; lo valoro al precio de tus "
                          "compras y ventas. Comprueba el identificador o anota su valor a mano.")
                price_series = {**huecos, **price_series}
                _PRICE_CACHE[p["id"]] = price_series
                p["preciosDeOperaciones"] = True
        if has_market_price and not price_series:
            if snaps:
                notice(f"{p['corto']}: no encuentro su precio en {p['fuentePrecio']}; "
                      "uso los valores que has anotado a mano.")
                has_market_price = False
            else:
                notice(f"{p['corto']}: no encuentro su precio en {p['fuentePrecio']}. "
                      "Comprueba el identificador o mete su valor a mano.")
                continue

        if has_market_price:
            if not mv["eventos"]:
                notice(f"{p['corto']}: no tiene compras anotadas, lo dejo fuera.")
                continue
            p["origen"] = "csv" if key in ("fondo", "pension") else "ordenes"
            nav_hoy = value_at(price_series, statement_date, margen=3650) or 0.0
            p["nav"] = nav_hoy
            p["navFecha"] = date_at(price_series, statement_date, 3650)
            if p["navFecha"] and (statement_date - d(p["navFecha"])).days > 7:
                notice(f"{p['corto']}: el último precio que tengo es del {p['navFecha']}.")
            for m in sorted(movs, key=lambda x: x["fecha"]):
                if m.get("tipo") != "compra":
                    continue
                u, imp = float(m.get("unidades") or 0), float(m.get("importe") or 0)
                benchmark = float(m.get("comision") or 0)
                p["aportaciones"].append({
                    "fecha": m["fecha"], "importe": round(imp, 2),
                    "participaciones": round(u, 6), "precio": r4((imp - benchmark) / u) if u else None,
                    "comision": benchmark, "tipoOrden": strip_html(m.get("nota")) or None,
                    "valor": None if id(m) in mv["vendidas"] else round(u * nav_hoy, 2),
                })
        else:
            p["origen"] = "manual"
            if not snaps:
                notice(f"{p['corto']}: todavía no tiene ningún valor anotado.")
                continue
            p["snapshots"] = snaps
            for m in movs:
                if m.get("tipo") == "compra":
                    p["aportaciones"].append({"fecha": m["fecha"], "importe": round(float(m.get("importe") or 0), 2)})

        pf = d(min(fechas_p))
        first_date = pf if first_date is None else min(first_date, pf)
        products.append(p)

    if not (products or other_assets or liabilities):
        print("\nLa cartera está vacía: todavía no hay nada que calcular.")
        return None

    if first_date is None or first_date > statement_date:
        first_date = statement_date
    timeline = date_range(first_date, statement_date)
    iso_days = [f.isoformat() for f in timeline]
    n = len(timeline)
    print(f"\n=== 2. Serie diaria: {iso_days[0]} -> {iso_days[-1]} ({n} dias) ===")

    for p in products:
        source = p.get("origen", "manual")
        p["slotColor"] = PALETTE.get(p.get("slot", 1), PALETTE[1])

        if source in ("csv", "ordenes"):
            nav_diario = forward_fill(price_in_eur(p, series), timeline)
            accumulated_units, ap_acum = [0.0] * n, [0.0] * n
            idx = {f: i for i, f in enumerate(iso_days)}
            for f, du, dap in p["_mv"]["eventos"]:
                i = idx.get(f)
                if i is None:
                    i = 0 if f < iso_days[0] else n - 1
                accumulated_units[i] += du
                ap_acum[i] += dap
            for i in range(1, n):
                accumulated_units[i] += accumulated_units[i - 1]
                ap_acum[i] += ap_acum[i - 1]

            last = None
            value_series = []
            for i in range(n):
                nv = nav_diario[i] or last
                last = nv or last
                value_series.append(round(accumulated_units[i] * nv, 2) if nv else None)

            i0 = next((i for i, v in enumerate(accumulated_units) if v > 1e-9), 0)
            contribution_series = [round(x, 2) for x in ap_acum]
            for i in range(i0):
                value_series[i] = None
                contribution_series[i] = None
            p["serie"] = value_series
            p["serieAportado"] = contribution_series
            p["navSerie"] = [r4(v) for v in nav_diario]
            p["participaciones"] = round(accumulated_units[-1], 6)
            p["valor"] = value_series[-1] or 0.0
            p["aportado"] = round(ap_acum[-1], 2)
            p["desde"] = min(e[0] for e in p["_mv"]["eventos"])
            if source == "ordenes":
                p["titulos"] = round(accumulated_units[-1], 4)
                p["precioMedio"] = r4(p["aportado"] / accumulated_units[-1]) if accumulated_units[-1] else None
                p["precioActual"] = r4(p["nav"])

        else:
            snaps = [(d(s[0]), float(s[1]), (s[2] if len(s) > 2 else None))
                     for s in p["snapshots"]]
            price_series, contribution_series = [], []
            for f in timeline:
                if f < snaps[0][0]:
                    price_series.append(None)
                    contribution_series.append(None)
                    continue
                v = ap = None
                for j in range(len(snaps)):
                    if j == len(snaps) - 1 or f <= snaps[j + 1][0]:
                        if j == len(snaps) - 1 or f == snaps[j][0]:
                            v, ap = snaps[j][1], snaps[j][2]
                        else:
                            f0, v0, a0 = snaps[j]
                            f1, v1, a1 = snaps[j + 1]
                            t = (f - f0).days / max((f1 - f0).days, 1)
                            v = v0 + (v1 - v0) * t
                            ap = (a0 + (a1 - a0) * t) if (a0 is not None and a1 is not None) else a0
                        break
                price_series.append(r2(v))
                contribution_series.append(r2(ap))
            p["serie"] = price_series
            p["serieAportado"] = contribution_series
            p["navSerie"] = None
            p["valor"] = snaps[-1][1]
            p["aportado"] = snaps[-1][2]
            p["desde"] = snaps[0][0].isoformat()
            events = p["_mv"]["eventos"]
            sin_compras = not any(m.get("tipo") == "compra" for m in movs)
            if events and not (sin_compras and any(s[2] is not None for s in snaps)):
                accumulated, contribution_series = 0.0, []
                pend = sorted(events)
                for f in iso_days:
                    while pend and pend[0][0] <= f:
                        accumulated += pend.pop(0)[2]
                    contribution_series.append(r2(accumulated))
                p["serieAportado"] = contribution_series
                p["aportado"] = round(accumulated + sum(e[2] for e in pend), 2)
                p["desde"] = min(p["desde"], min(e[0] for e in events))
            for f, v, a in snaps:
                p["aportaciones"].append({"fecha": f.isoformat(), "importe": None,
                                          "valor": v, "tipo": "snapshot"})

    from . import exposure
    pending = [p for p in products if not p.get("exposicion") and exposure.key(p)]
    if pending:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as ex:
            repartos = list(ex.map(lambda p: exposure.product_exposure(p, CACHE, network=fetch_prices is True), pending))
        for p, r in zip(pending, repartos):
            if r:
                p["exposicion"] = r

    print("\n=== 4. Metricas ===")
    global_cash_flows, known_value, valor_tir = [], 0.0, 0.0

    for p in products:
        val, ap = p.get("valor") or 0.0, p.get("aportado")
        p["valor"] = round(val, 2)
        cash_flows = [(d(f), v) for f, v in p["_mv"]["flujos"]]
        p["flujos"] = [[f, round(v, 2)] for f, v in p["_mv"]["flujos"]]
        if cash_flows:
            global_cash_flows.extend(cash_flows)
            valor_tir += val
        if ap is not None and ap > 0:
            p["aportado"] = round(ap, 2)
            p["plusvalia"] = round(val - ap, 2)
            p["rentabilidad"] = r4((val - ap) / ap)
            p["tir"] = r4(xirr(cash_flows + [(statement_date, val)])) if cash_flows else None
            known_value += val
        else:
            p["aportado"] = None
            p["plusvalia"] = None
            p["rentabilidad"] = None
            p["tir"] = None
        base = (p["aportado"] or 0) + p["costeVendido"]
        if p["plusvalia"] is not None or p["costeVendido"] > 0:
            p["gananciaTotal"] = round((p["plusvalia"] or 0) + p["realizado"], 2)
            p["rentabilidadTotal"] = r4(p["gananciaTotal"] / base) if base > 0 else None
        else:
            p["gananciaTotal"] = p["rentabilidadTotal"] = None
        if p["tipoClave"] == "inmueble":
            p["alquiler"] = rental_income(movements_by_product.get(p["id"], []), statement_date)

        if p.get("navSerie"):
            nav = p["navSerie"]
            ventanas = {"1m": 30, "3m": 91, "6m": 182, "1a": 365}
            p["ventanas"] = {}
            ult = next((v for v in reversed(nav) if v), None)
            for k, dias in ventanas.items():
                i = n - 1 - dias
                base = next((nav[j] for j in range(max(i, 0), n) if nav[j]), None) if i >= 0 else None
                p["ventanas"][k] = r4(ult / base - 1) if (base and ult) else None
            ini_ano = f"{statement_date.year}-01-01"
            iy = next((i for i, f in enumerate(iso_days) if f >= ini_ano), None)
            base = next((nav[j] for j in range(iy, n) if nav[j]), None) if iy is not None else None
            p["ventanas"]["ytd"] = r4(ult / base - 1) if (base and ult) else None

        etq = p["corto"]
        rr = f"{p['rentabilidad']*100:+6.2f}%" if p.get("rentabilidad") is not None else "    n/d"
        tt = f"{p['tir']*100:+6.2f}%" if p.get("tir") is not None else "    n/d"
        print(f"  {etq:22s} valor {p['valor']:10,.2f}  aportado "
              f"{(p['aportado'] or 0):10,.2f}  rent {rr}  TIR {tt}")


    def manual_total(entries, signo):
        total = 0.0
        series_extra = []
        for it in entries:
            snaps = sorted(it.get("snapshots", []), key=lambda s: s[0])
            if not snaps:
                continue
            total += signo * float(snaps[-1][1])
            price_series = []
            for f in timeline:
                v = None
                for j in range(len(snaps)):
                    if f >= d(snaps[j][0]):
                        v = float(snaps[j][1])
                price_series.append(r2(signo * v) if v is not None else None)
            series_extra.append({**it, "serie": price_series,
                                 "serieAportado": [None] * len(timeline),
                                 "aportaciones": [],
                                 "valor": round(signo * float(snaps[-1][1]), 2),
                                 "aportado": None, "plusvalia": None,
                                 "rentabilidad": None, "tir": None,
                                 "desde": snaps[0][0],
                                 "slotColor": PALETTE.get(it.get("slot", 8), PALETTE[8])})
        return total, series_extra

    tot_otros, other_series = manual_total(other_assets, 1)
    for e in other_series:
        c = rental_income(movements_by_product.get(e["id"], []), statement_date)
        if c:
            e["intereses"] = c
            e["realizado"] = round(c["cobrado"] - c["gastos"], 2)
    tot_pasivos, liability_series = manual_total(liabilities, -1)

    total_series, serie_ap_total = [], []
    for i in range(n):
        s = sum((p["serie"][i] or 0) for p in products)
        for e in other_series + liability_series:
            s += e["serie"][i] or 0
        total_series.append(round(s, 2))
        serie_ap_total.append(round(sum((p["serieAportado"][i] or 0) for p in products), 2))

    net_worth = round(total_series[-1], 2)
    total_contributions = round(sum(p["aportado"] or 0 for p in products), 2)
    total_gain = round(known_value - total_contributions, 2)
    global_cash_flows.append((statement_date, valor_tir))
    tir_total = r4(xirr(global_cash_flows))
    realizado_total = round(sum(p.get("realizado") or 0 for p in products + other_series), 2)

    for p in products + other_series + liability_series:
        p["peso"] = r4(p["valor"] / net_worth) if net_worth else 0

    def group(campo):
        acc = defaultdict(float)
        slot = {}
        for p in products:
            k = p.get(campo) or "Otros"
            acc[k] += p["valor"]
            slot.setdefault(k, p.get("slot", 8))
        for e in other_series:
            k = e.get(campo) or "Otros"
            acc[k] += e["valor"]
            slot.setdefault(k, e.get("slot", 8))
        return [{"nombre": k, "valor": round(v, 2),
                 "peso": r4(v / net_worth) if net_worth else 0,
                 "color": PALETTE.get(slot[k], PALETTE[8])}
                for k, v in sorted(acc.items(), key=lambda x: -x[1])]

    months = sorted({a["fecha"][:7] for p in products for a in p["aportaciones"]
                    if a.get("importe")})
    por_producto = {}
    for p in products:
        acc = defaultdict(float)
        for a in p["aportaciones"]:
            if a.get("importe"):
                acc[a["fecha"][:7]] += a["importe"]
        por_producto[p["id"]] = [round(acc.get(m, 0), 2) for m in months]
    monthly_total = [round(sum(por_producto[p["id"]][i] for p in products), 2)
                 for i in range(len(months))]

    hitos = []
    for h in cfg.get("hitos", []):
        idx = next((i for i, v in enumerate(total_series) if v >= h), None)
        hitos.append({"importe": h, "fecha": iso_days[idx] if idx is not None else None})

    racha = 0
    if months:
        ref = dt.date(int(months[-1][:4]), int(months[-1][5:7]), 1)
        seen = set(months)
        while True:
            k = f"{ref.year:04d}-{ref.month:02d}"
            if k in seen:
                racha += 1
                ref = (ref.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
            else:
                break
    ult12 = monthly_total[-12:] if len(monthly_total) >= 12 else monthly_total
    ritmo = round(sum(ult12) / max(len(ult12), 1), 2)

    peak, max_drawdown, dd_fecha = 0.0, 0.0, None
    for i, v in enumerate(total_series):
        peak = max(peak, v)
        if peak > 0:
            caida = v / peak - 1
            if caida < max_drawdown:
                max_drawdown, dd_fecha = caida, iso_days[i]


    todos_p = products + other_series + liability_series
    inv = [p for p in products if p.get("origen") in ("csv", "ordenes")]
    idx_fecha = {f: i for i, f in enumerate(iso_days)}

    for p in products:
        imp = sorted(x["importe"] for x in p["aportaciones"] if x.get("importe"))
        if not imp:
            continue
        q1 = imp[len(imp) // 3] if len(imp) >= 6 else None
        q2 = imp[2 * len(imp) // 3] if len(imp) >= 6 else None
        p["tramos"] = {"p33": r2(q1), "p67": r2(q2), "min": r2(imp[0]),
                       "max": r2(imp[-1]), "mediana": r2(imp[len(imp) // 2]),
                       "n": len(imp)}
        for x in p["aportaciones"]:
            if x.get("importe") is None:
                continue
            if q1 is None:
                x["nivel"] = 1
            else:
                x["nivel"] = 0 if x["importe"] < q1 else (2 if x["importe"] > q2 else 1)
        if p.get("origen") == "csv" and p.get("participaciones"):
            p["precioMedio"] = r4(p["aportado"] / p["participaciones"])

    benchmark_lines, benchmark_base = [], 0.0
    for p in products:
        if p.get("ter") and p.get("valor"):
            benchmark_lines.append({"id": p["id"], "nombre": p["corto"], "ter": p["ter"],
                               "valor": p["valor"], "anual": r2(p["valor"] * p["ter"]),
                               "color": p["slotColor"]})
            benchmark_base += p["valor"]
    total_com = round(sum(c["anual"] for c in benchmark_lines), 2)
    pagadas = round(sum(p["_mv"]["comisiones"] for p in products), 2)
    fees = {"lineas": benchmark_lines, "anual": total_com,
                  "base": round(benchmark_base, 2),
                  "terPonderado": r4(total_com / benchmark_base) if benchmark_base else None,
                  "compraventaPagada": pagadas}

    daily_flow = [0.0] * n
    product_flow = {p["id"]: [0.0] * n for p in products}
    flujo_inv = [0.0] * n
    ids_inv = {p["id"] for p in inv}
    for p in products:
        for f, v in p["_mv"]["flujos"]:
            i = idx_fecha.get(f)
            if i is None:
                continue
            daily_flow[i] -= v
            product_flow[p["id"]][i] -= v
            if p["id"] in ids_inv:
                flujo_inv[i] -= v

    serie_inv = [0.0] * n
    for p in inv:
        for i in range(n):
            v = p["serie"][i]
            if v is not None:
                serie_inv[i] += v

    def time_weighted_index(values, cash_flows):
        """Chain returns after removing the effect of external cash flows."""
        out, ant, level = [], None, 100.0
        for i in range(len(values)):
            v = values[i]
            f = cash_flows[i] if i < len(cash_flows) else 0.0
            if v is None:
                out.append(level)
                continue
            if ant is None or ant <= 1:
                if f > 0:
                    level *= max(v / f, 0.05)
            else:
                level *= 1.0 + max((v - f) / ant - 1.0, -0.95)
            out.append(level)
            ant = v
        return out

    portfolio_index = time_weighted_index(serie_inv, flujo_inv)

    def weighted_index(weights):
        """Build a buy-and-hold benchmark with fixed initial weights and base 100."""
        tot = sum(weights.values())
        if not tot:
            return None
        navs = {}
        for pid in weights:
            p = next((x for x in products if x["id"] == pid), None)
            if not p or not p.get("navSerie"):
                return None
            navs[pid] = p["navSerie"]
        i0 = next((i for i in range(n) if all(navs[k][i] for k in navs)), None)
        if i0 is None:
            return None
        out = [None] * n
        ult = {k: navs[k][i0] for k in navs}
        for i in range(i0, n):
            s = 0.0
            for k, weight in weights.items():
                v = navs[k][i] or ult[k]
                ult[k] = v
                s += (weight / tot) * v / navs[k][i0]
            out[i] = round(s * 100, 4)
        return out

    def index_metrics(idx, rf=None):
        pts = [i for i, v in enumerate(idx) if v]
        if len(pts) < 30:
            return None
        i0, i1 = pts[0], pts[-1]
        years = (d(iso_days[i1]) - d(iso_days[i0])).days / 365.25
        rent = idx[i1] / idx[i0] - 1
        cagr = (idx[i1] / idx[i0]) ** (1 / years) - 1 if years > 0.15 else None
        rs, ant = [], None
        for i in range(i0, i1 + 1):
            if d(iso_days[i]).weekday() >= 5 or not idx[i]:
                continue
            if ant:
                rs.append(idx[i] / ant - 1)
            ant = idx[i]
        vol = None
        if len(rs) > 20:
            mu = sum(rs) / len(rs)
            vol = math.sqrt(sum((x - mu) ** 2 for x in rs) / (len(rs) - 1)) * math.sqrt(252)
        peak, dd, ddf = 0.0, 0.0, None
        for i in range(i0, i1 + 1):
            if not idx[i]:
                continue
            peak = max(peak, idx[i])
            c = idx[i] / peak - 1
            if c < dd:
                dd, ddf = c, iso_days[i]
        return {"rentTotal": r4(rent), "cagr": r4(cagr), "vol": r4(vol),
                "sharpe": r4((cagr - rf) / vol) if (cagr is not None and vol and rf is not None) else None,
                "maxDD": r4(dd), "maxDDFecha": ddf, "desde": iso_days[i0], "hasta": iso_days[i1]}

    sin_riesgo = next((p["id"] for p in products if p.get("navSerie") and "monetari" in
                       " ".join(str(p.get(k, "")) for k in ("tipo", "clase", "nombre")).lower()), None)
    idx_mon = weighted_index({sin_riesgo: 1}) if sin_riesgo else None
    m_mon = index_metrics(idx_mon) if idx_mon else None
    rf = m_mon["cagr"] if m_mon else None

    comparador = []
    for c in cfg.get("comparador", []):
        idx = portfolio_index if c.get("real") else weighted_index(c.get("pesos", {}))
        if not idx:
            notice("Comparador: no puedo construir '%s'." % c.get("nombre"))
            continue
        met = index_metrics(idx, rf)
        if not met:
            continue
        comparador.append({"id": c["id"], "nombre": strip_html(c["nombre"]), "real": bool(c.get("real")),
                           "pesos": c.get("pesos"), "indice": [r2(v) for v in idx],
                           "metricas": met})

    idx_prod = {p["id"]: time_weighted_index(p["serie"], product_flow[p["id"]]) for p in inv}
    calendar_years = sorted({f[:4] for f in iso_days})
    annual_return = {"anos": calendar_years, "cartera": [], "parcial": [],
                  "porProducto": {p["id"]: [] for p in inv},
                  "desde": {p["id"]: [] for p in inv},
                  "vendido": {p["id"]: [] for p in inv}}
    primer_dia = {p["id"]: next((i for i, v in enumerate(p["serie"]) if v is not None), None)
                  for p in inv}
    for year in calendar_years:
        first_index = next(i for i, f in enumerate(iso_days) if f[:4] == year)
        final_index = max(i for i, f in enumerate(iso_days) if f[:4] == year)
        year_base = first_index - 1 if first_index > 0 else None
        b = portfolio_index[year_base] if year_base is not None else 100.0
        annual_return["cartera"].append(r4(portfolio_index[final_index] / b - 1) if b else None)
        annual_return["parcial"].append(year in (calendar_years[0], calendar_years[-1]))
        for p in inv:
            i0 = primer_dia[p["id"]]
            if i0 is None or i0 > final_index:
                annual_return["porProducto"][p["id"]].append(None)
                annual_return["desde"][p["id"]].append(None)
                annual_return["vendido"][p["id"]].append(False)
                continue
            sin_nada = all(not (p["serie"][i] or 0) for i in range(first_index, final_index + 1)) \
                and not any(product_flow[p["id"]][i] for i in range(first_index, final_index + 1))
            if sin_nada and i0 < first_index:
                annual_return["porProducto"][p["id"]].append(None)
                annual_return["desde"][p["id"]].append(None)
                annual_return["vendido"][p["id"]].append(True)
                continue
            annual_return["vendido"][p["id"]].append(False)
            ix = idx_prod[p["id"]]
            empieza_aqui = year_base is None or i0 > year_base
            bb = 100.0 if empieza_aqui else ix[year_base]
            annual_return["porProducto"][p["id"]].append(r4(ix[final_index] / bb - 1))
            annual_return["desde"][p["id"]].append(iso_days[i0] if empieza_aqui else None)

    meses_nat = sorted({f[:7] for f in iso_days})
    resumen_mensual = []
    for month in meses_nat:
        idxs = [i for i, f in enumerate(iso_days) if f[:7] == month]
        i_ini, end_index, ant = idxs[0], idxs[-1], idxs[0] - 1

        def add(i):
            return sum((p["serie"][i] or 0) for p in todos_p) if i >= 0 else 0.0

        v0, v1 = add(ant), add(end_index)
        ap = sum(daily_flow[i] for i in idxs)
        new_items, details = 0.0, {}
        for p in todos_p:
            s = p["serie"]
            pv0 = (s[ant] or 0) if ant >= 0 else 0.0
            pv1 = s[end_index] or 0.0
            pap = sum(product_flow.get(p["id"], [0.0] * n)[i] for i in idxs)
            estrena = (ant < 0 or s[ant] is None) and s[end_index] is not None
            pnuevo = pv1 if (estrena and p.get("aportado") is None) else 0.0
            new_items += pnuevo
            if pv1 or pv0 or pap:
                details[p["id"]] = {"inicio": r2(pv0), "fin": r2(pv1), "aportado": r2(pap),
                                    "nuevo": r2(pnuevo), "mercado": r2(pv1 - pv0 - pap - pnuevo)}
        b = portfolio_index[ant] if ant >= 0 else portfolio_index[i_ini]
        resumen_mensual.append({
            "mes": month, "inicio": r2(v0), "fin": r2(v1), "aportado": r2(ap),
            "nuevo": r2(new_items), "mercado": r2(v1 - v0 - ap - new_items),
            "rentabilidad": r4(portfolio_index[end_index] / b - 1) if b else None,
            "porProducto": details,
        })

    con_flujos = [p for p in products if p["_mv"]["flujos"]]
    comparacion = None
    if con_flujos and any(daily_flow):
        installed = [round(sum((p["serie"][i] or 0) for p in con_flujos), 2) for i in range(n)]
        i0 = next(i for i in range(n) if daily_flow[i] or installed[i])
        accumulated, aportado_c = 0.0, []
        for i in range(n):
            accumulated += daily_flow[i]
            aportado_c.append(round(accumulated, 2) if i >= i0 else None)
        flujos_c = [(d(iso_days[i]), -daily_flow[i]) for i in range(n) if daily_flow[i]]

        refs = []
        for rid, ref in REFERENCIAS.items():
            prices = [forward_fill(series.get(sim, {}), timeline) for sim, _ in ref["piezas"]]
            primeros = [next((v for v in pr if v), None) for pr in prices]
            if not all(primeros):
                continue
            units, return_series, before = [0.0] * len(prices), [], False
            for i in range(n):
                pr_hoy = [prices[k][i] or primeros[k] for k in range(len(prices))]
                if daily_flow[i]:
                    before = before or any(prices[k][i] is None for k in range(len(prices)))
                    for k, (_, weight) in enumerate(ref["piezas"]):
                        units[k] += daily_flow[i] * weight / pr_hoy[k]
                valor_r = sum(units[k] * pr_hoy[k] for k in range(len(prices)))
                return_series.append(round(valor_r, 2) if i >= i0 else None)
            refs.append({"id": rid, "nombre": ref["nombre"], "detalle": ref["detalle"],
                         "serie": return_series, "valor": return_series[-1],
                         "tir": r4(xirr(flujos_c + [(statement_date, return_series[-1])])),
                         "aviso": ("Tienes aportaciones anteriores a los precios de esta referencia: "
                                   "para esas se usa su primer precio conocido.") if before else None})
        if refs:
            comparacion = {"desde": iso_days[i0], "tuya": [v if i >= i0 else None for i, v in enumerate(installed)],
                           "aportado": aportado_c, "tuValor": installed[-1],
                           "tuTir": r4(xirr(flujos_c + [(statement_date, installed[-1])])),
                           "referencias": refs}

    prod_v = next((p for p in products if p.get("participaciones") and
                   (p.get("vivo") or p.get("fuente") == "coingecko")), None)
    live_quote = None
    if prod_v:
        coin = prod_v.get("vivo") or prod_v.get("codigo")
        ref = value_at(series.get("CG:" + coin, {}), prod_v.get("navFecha") or statement_date)
        if ref:
            live_quote = {"productoId": prod_v["id"], "coin": coin, "titulos": prod_v["participaciones"],
                    "precioRef": r4(prod_v["nav"]), "btcRef": r2(ref),
                    "fechaRef": prod_v.get("navFecha") or statement_date.isoformat()}

    data = {
        "generado": dt.datetime.now().replace(microsecond=0).isoformat(),
        "titular": strip_html(cfg.get("titular", "Mi patrimonio")),
        "moneda": cfg.get("moneda", "EUR"),
        "fechaExtracto": statement_date.isoformat(),
        "fechas": iso_days,
        "productos": products,
        "otrosActivos": other_series,
        "pasivos": liability_series,
        "total": {
            "patrimonio": net_worth,
            "aportado": total_contributions,
            "valorConCoste": round(known_value, 2),
            "plusvalia": total_gain,
            "rentabilidad": r4(total_gain / total_contributions) if total_contributions else None,
            "tir": tir_total,
            "realizado": realizado_total,
            "serie": total_series,
            "serieAportado": serie_ap_total,
            "porClase": group("clase"),
            "porEntidad": group("entidad"),
            "porTipo": group("tipo"),
            "hitos": hitos,
            "racha": racha,
            "ritmoMensual": ritmo,
            "numAportaciones": sum(1 for p in products for a in p["aportaciones"]
                                   if a.get("importe")),
            "diasInvertido": (statement_date - first_date).days,
            "caidaMaxima": r4(max_drawdown),
            "caidaMaximaFecha": dd_fecha,
        },
        "aportacionesMensuales": {"meses": months, "porProducto": por_producto,
                                  "total": monthly_total},
        "objetivo": custom_goal(cfg),
        "objetivoReparto": target_allocation(cfg),
        "colchon": emergency_fund(cfg),
        "comisiones": fees,
        "rentabilidadAnual": annual_return,
        "dividendos": income_summary(cfg.get("movimientos", []), products + other_series, statement_date),
        "monedas": display_exchange_rates(series),
        "resumenMensual": resumen_mensual,
        "comparador": comparador,
        "comparacion": comparacion,
        "indiceCartera": [r2(v) for v in portfolio_index],
        "vivo": live_quote,
        "avisos": [strip_html(a) for a in WARNINGS],
    }

    for p in products + other_assets + liabilities + other_series + liability_series:
        for k in [k for k in p if k.startswith("_")]:
            p.pop(k)

    if not historico:
        return data
    hist_ruta = os.path.join(directory, "historico.json")
    hist = read_cache(hist_ruta) or []
    hist = [h for h in hist if h.get("fecha") != statement_date.isoformat()]
    hist.append({"fecha": statement_date.isoformat(), "patrimonio": net_worth,
                 "aportado": total_contributions, "plusvalia": total_gain,
                 "porProducto": {p["id"]: p["valor"] for p in products}})
    hist.sort(key=lambda h: h["fecha"])
    with open(hist_ruta, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)

    print()
    print("=" * 62)
    print(f"  PATRIMONIO NETO      {net_worth:14,.2f} EUR")
    print(f"  Aportado             {total_contributions:14,.2f} EUR")
    print(f"  Plusvalia latente    {total_gain:14,.2f} EUR  "
          f"({(total_gain/total_contributions*100 if total_contributions else 0):+.2f}%)")
    if tir_total is not None:
        print(f"  TIR anualizada       {tir_total*100:13.2f} %")
    print("=" * 62)
    return data

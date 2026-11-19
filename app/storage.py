"""Validate and persist portfolios. Writes take a backup and replace the file atomically."""

import datetime as dt
import json
import os
import re
import unicodedata

from .engine import PRODUCT_TYPES, PRICE_SOURCES, parse_spanish_number

MAX_BACKUPS = 20
TIPOS_MOV = {"compra": "Compra", "venta": "Venta", "dividendo": "Dividendo, cupón o interés",
             "comision": "Comisión", "traspaso": "Traspaso", "ajuste": "Ajuste de participaciones"}
BALANCE_ONLY = ("efectivo", "deuda")

CARTERA_VACIA = {
    "version": 1, "titular": "Mi patrimonio",
    "productos": [], "movimientos": [], "valoraciones": [],
    "comparador": [{"id": "real", "nombre": "Mi cartera real", "real": True}],
    "hitos": [10000, 25000, 50000, 100000, 250000, 500000, 1000000],
    "objetivo": {"activo": False, "importe": None, "etiqueta": "Mi objetivo"},
}


class ValidationError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(path, cfg):
    """Save a backup before atomically replacing the portfolio file."""
    directory = os.path.dirname(path)
    backups = os.path.join(directory, "copias")
    if os.path.exists(path):
        os.makedirs(backups, exist_ok=True)
        sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        destination, n = os.path.join(backups, f"auto_{sello}.json"), 1
        while os.path.exists(destination):
            destination, n = os.path.join(backups, f"auto_{sello}_{n}.json"), n + 1
        with open(path, "rb") as f, open(destination, "wb") as g:
            g.write(f.read())
        viejas = sorted(n for n in os.listdir(backups) if n.startswith("auto_"))
        for n in viejas[:-MAX_BACKUPS]:
            os.remove(os.path.join(backups, n))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def format_date(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


def format_number(x):
    t = f"{x:,.4f}".rstrip("0").rstrip(".")
    return t.replace(",", "X").replace(".", ",").replace("X", ".")


def format_units(x):
    t = f"{x:,.8f}".rstrip("0").rstrip(".")
    return t.replace(",", "X").replace(".", ",").replace("X", ".")


def number(value, label, errors, obligatorio=True, minimo=None, mayor_que=None):
    """Parse a number in Spanish or decimal-point notation and return a float or None."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if obligatorio:
            errors.append(f"Falta {label}.")
        return None
    if isinstance(value, (int, float)):
        x = float(value)
    else:
        t = value.strip().replace("€", "").replace("%", "").replace(" ", "")
        if not re.fullmatch(r"-?[\d.,]+", t):
            errors.append(f"{label.capitalize()} no es un número: «{value}».")
            return None
        x = parse_spanish_number(t)
    if minimo is not None and x < minimo:
        errors.append(f"{label.capitalize()} no puede ser menor que {minimo:g}.")
    if mayor_que is not None and x <= mayor_que:
        errors.append(f"{label.capitalize()} tiene que ser mayor que {mayor_que:g}.")
    return x


def date(value, errors):
    try:
        f = dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        errors.append("Falta la fecha o no es válida.")
        return None
    if f > dt.date.today():
        errors.append(f"La fecha {format_date(f.isoformat())} es futura.")
    elif f.year < 1950:
        errors.append(f"La fecha {format_date(f.isoformat())} parece un error.")
    return f.isoformat()


def slug(text, existing_entries):
    base = unicodedata.normalize("NFKD", text or "producto").encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")[:30] or "producto"
    cand, i = base, 2
    while cand in existing_entries:
        cand, i = f"{base}_{i}", i + 1
    return cand


def next_id(entries, prefijo):
    nums = [int(x["id"][1:]) for x in entries if re.fullmatch(prefijo + r"\d+", str(x.get("id", "")))]
    return f"{prefijo}{max(nums, default=0) + 1}"


def product(cfg, pid):
    return next((p for p in cfg.get("productos", []) if p["id"] == pid), None)


def text(v, maximo=200):
    return re.sub(r"[<>]", "", str(v)).strip()[:maximo] if v is not None else ""


def save_goal(cfg, data):
    active = bool(data.get("activo"))
    errors = []
    amount = number(data.get("importe"), "el importe del objetivo", errors, obligatorio=active, mayor_que=0)
    if errors:
        raise ValidationError(errors)
    cfg["objetivo"] = {"activo": active, "importe": round(amount, 2) if amount else None,
                       "etiqueta": text(data.get("etiqueta"), 60) or "Mi objetivo", "elegido": True}
    return cfg["objetivo"]


def save_emergency_fund(cfg, data):
    if data.get("borrar"):
        cfg.pop("colchon", None)
        return None
    errors = []
    mode = "importe" if data.get("modo") == "importe" else "meses"
    if mode == "meses":
        months = number(data.get("meses"), "cuántos meses de gastos", errors, mayor_que=0)
        gasto = number(data.get("gastoMensual"), "lo que gastas al mes", errors, mayor_que=0)
        if months and months > 60:
            errors.append("Más de 60 meses no parece un fondo de emergencia: revisa el número.")
        if errors:
            raise ValidationError(errors)
        cfg["colchon"] = {"modo": "meses", "meses": round(months, 1), "gastoMensual": round(gasto, 2)}
    else:
        amount = number(data.get("importe"), "el importe del fondo de emergencia", errors, mayor_que=0)
        if errors:
            raise ValidationError(errors)
        cfg["colchon"] = {"modo": "importe", "importe": round(amount, 2)}
    return cfg["colchon"]


def save_allocation(cfg, data):
    errors = []
    por = data.get("por") if data.get("por") in ("clase", "producto") else "clase"
    weights = {}
    for k, v in (data.get("pesos") or {}).items():
        x = number(v, f"el % de «{text(k, 40)}»", errors, obligatorio=False, minimo=0)
        if x:
            weights[text(k, 80)] = round(x, 2)
    if not weights and not data.get("borrar"):
        errors.append("Pon el % que quieres en al menos un grupo.")
    elif weights and abs(sum(weights.values()) - 100) > 0.5:
        errors.append(f"Los porcentajes suman {format_number(sum(weights.values()))} %: tienen que sumar 100 %.")
    vigilar = number(data.get("vigilar"), "el margen para vigilar", errors, obligatorio=False, minimo=0) or 3
    rebalancear = number(data.get("rebalancear"), "el margen para rebalancear", errors, obligatorio=False, minimo=0) or 5
    if rebalancear < vigilar:
        errors.append("El margen para rebalancear tiene que ser mayor que el de vigilar.")
    if errors:
        raise ValidationError(errors)
    if data.get("borrar"):
        cfg.pop("objetivoReparto", None)
        return None
    account = data.get("cuenta") if isinstance(data.get("cuenta"), dict) else {}
    account = {text(k, 80): bool(v) for k, v in list(account.items())[:300]}
    cfg["objetivoReparto"] = {"por": por, "pesos": weights, "vigilar": vigilar, "rebalancear": rebalancear,
                              "conEfectivo": bool(data.get("conEfectivo")), **({"cuenta": account} if account else {})}
    return cfg["objetivoReparto"]


CAMPOS_TEXTO = ("nombre", "corto", "identificador", "codigo", "entidad", "clase", "gestora",
                "tipoDetalle", "respaldo", "respaldoMoneda", "vivo", "papel", "expoComo")


def save_product(cfg, data):
    errors = []
    new_entry = {k: text(data.get(k), 400 if k == "papel" else 200) for k in CAMPOS_TEXTO}
    if not new_entry["nombre"]:
        errors.append("Ponle un nombre al producto.")
    kind = data.get("tipo")
    if kind not in PRODUCT_TYPES:
        errors.append("Elige de qué tipo es el producto.")
    provider = "manual" if kind in BALANCE_ONLY else data.get("fuente") or "manual"
    if provider not in PRICE_SOURCES:
        errors.append("Elige de dónde sale el precio.")
    if provider != "manual" and not new_entry["codigo"]:
        errors.append(f"Falta el código del producto en {PRICE_SOURCES.get(provider, provider)}. "
                       "Búscalo con el buscador o elige «a mano».")
    currency = text(data.get("moneda")) or "EUR"
    currency = currency if currency in ("GBp", "GBX") else currency.upper()
    if not re.fullmatch(r"[A-Z]{3}|GBp|GBX", currency):
        errors.append(f"La moneda «{currency}» no es válida: usa un código de tres letras, como EUR o USD.")
    ter = number(data.get("ter"), "la comisión anual", errors, obligatorio=False, minimo=0)
    risk = number(data.get("riesgo"), "el nivel de riesgo", errors, obligatorio=False, minimo=1)
    if risk is not None and risk > 7:
        errors.append("El nivel de riesgo va de 1 a 7.")
    if errors:
        raise ValidationError(errors)

    new_entry.update(tipo=kind, fuente=provider, moneda=currency,
                 largoPlazo=bool(data.get("largoPlazo", True)),
                 liquidez=bool(data["liquidez"]) if "liquidez" in data else None,
                 slot=int(data["slot"]) if str(data.get("slot") or "").isdigit() else None,
                 ter=ter / 100 if ter is not None else None,
                 riesgo=int(risk) if risk is not None else None)
    if provider == "manual":
        new_entry.update(codigo="", respaldo="", respaldoMoneda="")
    new_entry["corto"] = new_entry["corto"] or new_entry["nombre"][:24]
    new_entry["expoComo"] = new_entry["expoComo"].replace(" ", "").upper()
    if new_entry["expoComo"] and not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", new_entry["expoComo"]):
        raise ValidationError([f"«{new_entry['expoComo']}» no parece un ISIN (12 caracteres, como IE00BYX5NX33)."])

    existing = product(cfg, data.get("id")) if data.get("id") else None
    if existing:
        cambio = (existing.get("fuente"), existing.get("codigo")) != (provider, new_entry["codigo"])
        destination = existing
        if new_entry["slot"] is None:
            new_entry.pop("slot")
    else:
        cambio = provider != "manual"
        destination = {"id": slug(new_entry["corto"], {p["id"] for p in cfg["productos"]})}
        if new_entry["slot"] is None:
            usos = [sum(1 for p in cfg["productos"] if p.get("slot") == s) for s in range(1, 13)]
            new_entry["slot"] = usos.index(min(usos)) + 1
        cfg["productos"].append(destination)
    for k, v in new_entry.items():
        if v in ("", None):
            destination.pop(k, None)
        else:
            destination[k] = v
    return destination, cambio


def assign_colors(cfg, order=None):
    ids = [p["id"] for p in cfg["productos"]]
    order = [i for i in (order or []) if i in ids] + [i for i in ids if i not in (order or [])]
    for n, pid in enumerate(order):
        product(cfg, pid)["slot"] = n % 12 + 1


def delete_product(cfg, pid):
    if not product(cfg, pid):
        raise ValidationError(["Ese producto ya no existe."])
    cfg["productos"] = [p for p in cfg["productos"] if p["id"] != pid]
    cfg["movimientos"] = [m for m in cfg.get("movimientos", []) if pid not in (m.get("producto"), m.get("destino"))]
    cfg["valoraciones"] = [v for v in cfg.get("valoraciones", []) if v.get("producto") != pid]
    for c in cfg.get("comparador", []):
        if c.get("pesos"):
            c["pesos"].pop(pid, None)
    cfg["comparador"] = [c for c in cfg.get("comparador", []) if c.get("real") or c.get("pesos")]


def units_at(cfg, pid, iso_date, exclude=None):
    total = 0.0
    order = {"compra": 0, "comision": 1, "dividendo": 2, "venta": 3, "traspaso": 4, "ajuste": 6}
    for m in sorted(cfg.get("movimientos", []), key=lambda m: (m["fecha"], order.get(m.get("tipo"), 9))):
        if m.get("id") == exclude or m["fecha"] > iso_date:
            continue
        t = m.get("tipo")
        if m.get("producto") == pid:
            u = float(m.get("unidades") or 0)
            if t == "ajuste":
                total = u
            else:
                total += u if t == "compra" else -u if t in ("venta", "traspaso") else 0
        if t == "traspaso" and m.get("destino") == pid:
            total += float(m.get("unidadesDestino") or 0)
    return total


def save_movement(cfg, data):
    if data.get("tipo") == "traspaso":
        return save_transfer(cfg, data)
    if data.get("tipo") == "ajuste":
        return save_adjustment(cfg, data)
    errors = []
    p = product(cfg, data.get("producto"))
    if not p:
        errors.append("Elige el producto.")
    kind = data.get("tipo")
    if p and p.get("tipo") == "efectivo" and kind != "dividendo":
        errors.append(f"«{p.get('corto') or p['nombre']}» es una cuenta: se sigue con saldos (en «Saldos y "
                       "valores»). Como movimiento solo se le pueden anotar los intereses que te paga.")
    elif p and p.get("tipo") in BALANCE_ONLY and p.get("tipo") != "efectivo":
        errors.append(f"«{p.get('corto') or p['nombre']}» se sigue con saldos, no con movimientos: "
                       "anótalo en «Saldos y valores».")
    if kind not in TIPOS_MOV:
        errors.append("Elige el tipo de movimiento: compra, venta, dividendo o comisión.")
    f = date(data.get("fecha"), errors)
    amount = number(data.get("importe"), "el importe", errors, mayor_que=0)
    has_market_price = bool(p and p.get("fuente") != "manual")
    units = 0.0
    if kind == "compra":
        units = number(data.get("unidades"), "cuántas unidades compraste", errors,
                          obligatorio=has_market_price, mayor_que=0 if has_market_price else None) or 0.0
    elif kind == "venta":
        units = number(data.get("unidades"), "cuántas unidades vendiste", errors,
                          obligatorio=has_market_price, minimo=0) or 0.0
    fee = number(data.get("comision"), "la comisión", errors, obligatorio=False, minimo=0)
    if fee and amount and fee >= amount:
        errors.append("La comisión no puede ser mayor que el importe total.")
    if not errors and kind == "venta" and has_market_price and units:
        held_units = units_at(cfg, p["id"], f, exclude=data.get("id"))
        if units > held_units and units - held_units <= max(1e-4, held_units * 1e-6):
            units = held_units
        elif units > held_units + 1e-9:
            errors.append(f"El {format_date(f)} solo tenías {format_units(held_units)} unidades de "
                           f"«{p.get('corto') or p['nombre']}» y estás vendiendo {format_units(units)}. "
                           "Para venderlo todo, pulsa «Todas».")
    if errors:
        raise ValidationError(errors)

    mov = {"fecha": f, "producto": p["id"], "tipo": kind, "unidades": round(units, 8),
           "importe": round(amount, 2)}
    if fee:
        mov["comision"] = round(fee, 2)
    if text(data.get("nota")):
        mov["nota"] = text(data.get("nota"))
    entries = cfg.setdefault("movimientos", [])
    existing = next((m for m in entries if m.get("id") == data.get("id")), None) if data.get("id") else None
    if existing:
        existing.clear()
        existing.update(id=data["id"], **mov)
        return existing
    mov = {"id": next_id(entries, "m"), **mov}
    entries.append(mov)
    entries.sort(key=lambda m: m["fecha"])
    return mov


def save_transfer(cfg, data):
    """Keep the acquisition cost and date when transferring between funds or pension plans."""
    errors = []
    source, destination = product(cfg, data.get("producto")), product(cfg, data.get("destino"))
    if not source:
        errors.append("Elige de qué producto sale el dinero.")
    if not destination:
        errors.append("Elige a qué producto va.")
    if source and destination and source["id"] == destination["id"]:
        errors.append("El origen y el destino son el mismo producto.")
    for p in (source, destination):
        if p and p.get("tipo") in BALANCE_ONLY:
            errors.append(f"«{p.get('corto') or p['nombre']}» es una cuenta o una deuda: no se puede traspasar. "
                           "Un traspaso es entre fondos, planes de pensiones u otros productos de inversión.")
    f = date(data.get("fecha"), errors)
    amount = number(data.get("importe"), "el importe traspasado", errors, mayor_que=0)
    source_has_market_price = bool(source and source.get("fuente") != "manual")
    cotiza_d = bool(destination and destination.get("fuente") != "manual")
    units = number(data.get("unidades"), "cuántas participaciones salen", errors,
                      obligatorio=source_has_market_price, minimo=0) or 0.0
    if source_has_market_price and not units and not errors:
        errors.append("Faltan las participaciones que salen. Para traspasarlo todo, pulsa «Todas».")
    unidades_d = number(data.get("unidadesDestino"), "cuántas participaciones entran", errors,
                        obligatorio=cotiza_d, minimo=0) or 0.0
    if cotiza_d and not unidades_d and not errors:
        errors.append("Faltan las participaciones que entran en el destino.")
    total = bool(data.get("total"))
    if not errors and source_has_market_price:
        held_units = units_at(cfg, source["id"], f, exclude=data.get("id"))
        if units > held_units and units - held_units <= max(1e-4, held_units * 1e-6):
            units = held_units
        elif units > held_units + 1e-9:
            errors.append(f"El {format_date(f)} solo tenías {format_units(held_units)} participaciones de "
                           f"«{source.get('corto') or source['nombre']}» y estás traspasando {format_units(units)}.")
        total = abs(units - held_units) <= 1e-9
    if errors:
        raise ValidationError(errors)

    mov = {"fecha": f, "producto": source["id"], "destino": destination["id"], "tipo": "traspaso",
           "unidades": round(units, 8), "unidadesDestino": round(unidades_d, 8), "importe": round(amount, 2)}
    if total:
        mov["total"] = True
    if text(data.get("nota")):
        mov["nota"] = text(data.get("nota"))
    entries = cfg.setdefault("movimientos", [])
    existing = next((m for m in entries if m.get("id") == data.get("id")), None) if data.get("id") else None
    if existing:
        existing.clear()
        existing.update(id=data["id"], **mov)
        return existing
    mov = {"id": next_id(entries, "m"), **mov}
    entries.append(mov)
    entries.sort(key=lambda m: m["fecha"])
    return mov


def save_adjustment(cfg, data):
    """Reconcile recorded units against a broker balance without changing the acquisition lots."""
    errors = []
    p = product(cfg, data.get("producto"))
    if not p:
        errors.append("Elige el producto.")
    elif p.get("fuente") == "manual" or p.get("tipo") in BALANCE_ONLY:
        errors.append(f"«{p.get('corto') or p['nombre']}» se valora a mano: no tiene participaciones que cuadrar.")
    f = date(data.get("fecha"), errors)
    units = number(data.get("unidades"), "cuántas participaciones tienes según tu banco", errors, minimo=0)
    if errors:
        raise ValidationError(errors)
    mov = {"fecha": f, "producto": p["id"], "tipo": "ajuste", "unidades": round(units, 8), "importe": 0}
    note = text(data.get("nota"))
    calculadas = units_at(cfg, p["id"], f, exclude=data.get("id"))
    mov["nota"] = note or f"FinAppGo calculaba {format_units(calculadas)}"
    entries = cfg.setdefault("movimientos", [])
    existing = next((m for m in entries if m.get("id") == data.get("id")), None) if data.get("id") else None
    if existing:
        existing.clear()
        existing.update(id=data["id"], **mov)
        return existing
    mov = {"id": next_id(entries, "m"), **mov}
    entries.append(mov)
    entries.sort(key=lambda m: m["fecha"])
    return mov


def delete_movement(cfg, mid):
    before = len(cfg.get("movimientos", []))
    cfg["movimientos"] = [m for m in cfg.get("movimientos", []) if m.get("id") != mid]
    if len(cfg["movimientos"]) == before:
        raise ValidationError(["Ese movimiento ya no existe."])


def save_valuation(cfg, data):
    errors = []
    p = product(cfg, data.get("producto"))
    if not p:
        errors.append("Elige el producto.")
    f = date(data.get("fecha"), errors)
    value = number(data.get("valor"), "el valor", errors, minimo=0)
    aportado = number(data.get("aportado"), "lo aportado", errors, obligatorio=False, minimo=0)
    if errors:
        raise ValidationError(errors)
    val = {"fecha": f, "producto": p["id"], "valor": round(value, 2)}
    if aportado is not None and p.get("tipo") not in BALANCE_ONLY:
        val["aportado"] = round(aportado, 2)
    entries = cfg.setdefault("valoraciones", [])
    existing = next((v for v in entries if v.get("id") == data.get("id")), None) if data.get("id") else None
    existing = existing or next((v for v in entries if v["producto"] == p["id"] and v["fecha"] == f), None)
    if existing:
        vid = existing["id"]
        existing.clear()
        existing.update(id=vid, **val)
        return existing
    val = {"id": next_id(entries, "v"), **val}
    entries.append(val)
    entries.sort(key=lambda v: (v["producto"], v["fecha"]))
    return val


def delete_valuation(cfg, vid):
    before = len(cfg.get("valoraciones", []))
    cfg["valoraciones"] = [v for v in cfg.get("valoraciones", []) if v.get("id") != vid]
    if len(cfg["valoraciones"]) == before:
        raise ValidationError(["Ese valor ya no existe."])

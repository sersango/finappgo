"""Preview and record recurring contributions using historical prices."""

import calendar
import datetime as dt
import re

from . import storage, engine

FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_APORTACIONES = 600
DIAS_REPETIDA = 5
NOTA = "Aportación periódica (estimada con el cierre del {})"


def contribution_dates(start, end, day):
    """Return the chosen day of each month in the inclusive range, capped at month end."""
    d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    out, year, month = [], d0.year, d0.month
    while (year, month) <= (d1.year, d1.month):
        f = dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))
        if d0 <= f <= d1:
            out.append(f.isoformat())
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def parse_request(cfg, data, today=None):
    today = today or dt.date.today()
    errors = []
    p = storage.product(cfg, str(data.get("producto") or ""))
    if not p or p.get("tipo") in storage.BALANCE_ONLY:
        errors.append("Elige un producto de los tuyos (un fondo, un ETF, un plan…).")
    amount = storage.number(data.get("importe"), "cuánto aportas cada vez", errors, mayor_que=0)
    day = storage.number(data.get("dia"), "qué día del mes", errors, minimo=1)
    if day is not None and (day != int(day) or not 1 <= day <= 31):
        errors.append("El día del mes tiene que ser un número del 1 al 31.")
    start, end = str(data.get("desde") or ""), str(data.get("hasta") or today.isoformat())
    for name, f in (("desde", start), ("hasta", end)):
        try:
            if not FECHA.match(f):
                raise ValueError
            dt.date.fromisoformat(f)
        except ValueError:
            errors.append(f"La fecha «{name}» no es válida.")
    if not errors:
        if end > today.isoformat():
            errors.append("Solo se pueden añadir aportaciones que ya han pasado.")
        elif start > end:
            errors.append("La fecha de inicio es posterior a la de fin.")
    if errors:
        raise storage.ValidationError(errors)
    return p, round(amount, 2), int(day), start, end


def preview_plan(cfg, data, price_series=None, today=None):
    p, amount, day, start, end = parse_request(cfg, data, today)
    entries = contribution_dates(start, end, day)
    if not entries:
        raise storage.ValidationError(["En esas fechas no cae ninguna aportación."])
    if len(entries) > MAX_APORTACIONES:
        raise storage.ValidationError([f"Son {len(entries)} aportaciones: como mucho {MAX_APORTACIONES} de una vez."])
    is_manual = p.get("fuente") == "manual"
    if not is_manual and not price_series:
        raise storage.ValidationError([f"No encuentro los precios de «{engine.strip_html(p.get('corto') or p['nombre'])}». "
                                       "Pulsa «Actualizar precios» y vuelve a probar."])
    purchases = [(dt.date.fromisoformat(m["fecha"]), float(m.get("importe") or 0)) for m in cfg.get("movimientos", [])
               if m.get("producto") == p["id"] and m.get("tipo") == "compra"]
    lines = []
    for f in entries:
        df = dt.date.fromisoformat(f)
        repetida = any(abs((df - cf).days) <= DIAS_REPETIDA and abs(ci - amount) <= max(1.0, amount * 0.02)
                       for cf, ci in purchases)
        line = {"fecha": f, "importe": amount, "precio": None, "fechaPrecio": None, "unidades": None,
                 "estado": "repetida" if repetida else "nueva"}
        if not is_manual:
            price = engine.value_at(price_series or {}, f, margen=7)
            if price:
                line.update(precio=round(price, 6), fechaPrecio=engine.date_at(price_series, f, margen=7),
                             unidades=round(amount / price, 6))
            elif not repetida:
                line["estado"] = "sinPrecio"
        lines.append(line)
    return {"producto": p["id"], "nombre": engine.strip_html(p.get("nombre") or p["id"]), "aMano": is_manual,
            "importe": amount, "dia": day, "desde": start, "hasta": end, "lineas": lines,
            "nuevas": sum(1 for x in lines if x["estado"] == "nueva")}


def create(cfg, data, price_series=None, today=None):
    """Recalculate the contribution plan on the server before adding its new entries."""
    pl = preview_plan(cfg, data, price_series, today)
    new_rows = [x for x in pl["lineas"] if x["estado"] == "nueva"]
    if not new_rows:
        raise storage.ValidationError(["No hay ninguna aportación nueva que añadir: ya las tienes anotadas."])
    for x in new_rows:
        storage.save_movement(cfg, {
            "producto": pl["producto"], "tipo": "compra", "fecha": x["fecha"], "importe": x["importe"],
            "unidades": x["unidades"] or "",
            "nota": NOTA.format(engine.format_spanish_date(x["fechaPrecio"])) if x["fechaPrecio"] else "Aportación periódica",
        })
    entries = [r for r in cfg.get("periodicas", []) if isinstance(r, dict)
             and not (r.get("producto") == pl["producto"] and r.get("dia") == pl["dia"])]
    entries.append({"producto": pl["producto"], "importe": pl["importe"], "dia": pl["dia"],
                  "ultima": max(x["fecha"] for x in pl["lineas"])})
    cfg["periodicas"] = entries
    return {"anadidas": len(new_rows), "saltadas": len(pl["lineas"]) - len(new_rows)}


def forget(cfg, data):
    """Forget the schedule while keeping the recorded purchases."""
    pid = str(data.get("producto") or "")
    try:
        day = int(data.get("dia"))
    except (TypeError, ValueError):
        day = None
    before = len(cfg.get("periodicas", []))
    cfg["periodicas"] = [r for r in cfg.get("periodicas", []) if isinstance(r, dict)
                         and not (r.get("producto") == pid and r.get("dia") == day)]
    if len(cfg["periodicas"]) == before:
        raise storage.ValidationError(["Esa aportación periódica ya no estaba."])
    return None

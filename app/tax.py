"""Summarize portfolio activity for the Spanish tax year."""

import datetime as dt
import re
from collections import defaultdict

from . import engine

VENTANA_RECOMPRA = {"etf": 2, "accion": 2, "fondo": 12}
ES_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")


def r2(x):
    return round(x + 0.0, 2)


def add_months(date, months):
    d = dt.date.fromisoformat(date)
    m = d.month - 1 + months
    year, month = d.year + m // 12, m % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return dt.date(year, month, day).isoformat()
        except ValueError:
            continue


def product_isin(p):
    for k in ("isin", "identificador"):
        x = str(p.get(k) or "").strip().upper()
        if ES_ISIN.match(x):
            return x
    return ""


def years_with_data(cfg):
    return sorted({m["fecha"][:4] for m in cfg.get("movimientos", [])
                   if m.get("tipo") in ("venta", "dividendo", "comision", "traspaso") and m.get("fecha")},
                  reverse=True)


def default_year(years, today=None):
    """Use the latest completed year with data, falling back to the most recent year."""
    current = str((today or dt.date.today()).year)
    closed = [a for a in years if a < current]
    return closed[0] if closed else (years[0] if years else current)


def report(cfg, year=None, today=None):
    years = years_with_data(cfg)
    year = str(year) if year else default_year(years, today)
    products = {p["id"]: p for p in cfg.get("productos", [])}
    est, _, _ = engine.portfolio_fifo(cfg)
    movs = cfg.get("movimientos", [])
    warnings = []

    def name(pid):
        p = products.get(pid) or {}
        return engine.strip_html(p.get("nombre") or p.get("corto") or pid)

    purchases_of = defaultdict(list)
    for m in movs:
        if m.get("tipo") == "compra":
            purchases_of[m.get("producto")].append(m["fecha"])

    sales, withdrawals = [], []
    for pid, e in est.items():
        p = products.get(pid) or {}
        kind = p.get("tipo") or "otro"
        for v in e.get("ventasDetalle", []):
            if v["fecha"][:4] != year:
                continue
            purchases = [{"fecha": f, "unidades": round(u, 6), "coste": r2(c)} for f, u, c in v["compras"]]
            line = {"producto": pid, "nombre": name(pid), "isin": product_isin(p),
                     "tipo": engine.PRODUCT_TYPES.get(kind, "Otro"), "fecha": v["fecha"],
                     "unidades": round(v["unidades"] + v["faltan"], 6) if v["unidades"] + v["faltan"] else None,
                     "transmision": r2(v["importe"]), "adquisicion": r2(v["coste"]),
                     "ganancia": r2(v["importe"] - v["coste"]), "compras": purchases, "avisos": []}
            if kind == "pension":
                withdrawals.append(line)
                continue
            if not purchases:
                line["adquisicion"] = None
                line["avisos"].append(
                    "Solo está anotada la ganancia, sin participaciones ni coste (así da MyInvestor algunos "
                    "reembolsos): suma tal cual. Compruébala con el informe fiscal de tu banco." if not line["unidades"]
                    else "No hay compras anotadas de las que salga esta venta: su ganancia es lo cobrado tal cual. "
                         "Revísala con el informe de tu banco.")
            elif v["faltan"]:
                line["avisos"].append("Vendes más de lo que tenías anotado: falta alguna compra y la ganancia "
                                       "no es fiable.")
            if purchases and any(c["coste"] <= 0 for c in purchases):
                line["avisos"].append("Parte de lo vendido no tiene coste anotado (viene de cuadrar participaciones "
                                       "o de un traspaso sin coste). Revisa su valor de adquisición.")
            months = VENTANA_RECOMPRA.get(kind)
            if months and line["ganancia"] < 0:
                start, end = add_months(v["fecha"], -months), add_months(v["fecha"], months)
                if any(start <= f <= end and f != v["fecha"] for f in purchases_of[pid]):
                    term = "dos meses" if months == 2 else "un año"
                    line["avisos"].append(f"Compraste el mismo producto en el {term} anterior o posterior a esta "
                                           f"venta con pérdida: puede que esa pérdida no se pueda compensar todavía "
                                           f"(regla de los {term.replace('un año', 'doce meses')}). Revísalo.")
            sales.append(line)
    sales.sort(key=lambda x: (x["fecha"], x["nombre"]))
    withdrawals.sort(key=lambda x: x["fecha"])

    income, fees, property_expenses = {}, defaultdict(float), defaultdict(float)
    for m in movs:
        if m.get("fecha", "")[:4] != year or m.get("producto") not in products:
            continue
        imp = float(m.get("importe") or 0)
        product_type = products[m["producto"]].get("tipo")
        if m.get("tipo") == "dividendo":
            clase = ("Intereses" if product_type in ("efectivo", "p2p") else "Alquileres" if product_type == "inmueble"
                     else "Dividendos y cupones")
            x = income.setdefault(m["producto"], {"producto": m["producto"], "nombre": name(m["producto"]),
                                                  "clase": clase, "cobros": 0, "importe": 0.0})
            x["cobros"] += 1
            x["importe"] += imp
        elif m.get("tipo") == "comision":
            (property_expenses if product_type == "inmueble" else fees)[m["producto"]] += imp
        elif m.get("tipo") == "traspaso":
            o, d_ = products.get(m["producto"]) or {}, products.get(m.get("destino")) or {}
            ok = (o.get("tipo"), d_.get("tipo")) in (("fondo", "fondo"), ("pension", "pension"))
            if not ok:
                warnings.append(f"Traspaso del {engine.format_spanish_date(m['fecha'])} de {name(m['producto'])} a "
                              f"{name(m.get('destino'))}: sin pasar por Hacienda solo se puede traspasar entre fondos "
                              "de inversión o entre planes de pensiones. Si en realidad vendiste y compraste, "
                              "anótalo como una venta y una compra.")
    income = sorted(({**x, "importe": r2(x["importe"])} for x in income.values()), key=lambda x: -x["importe"])
    fees = [{"producto": pid, "nombre": name(pid), "importe": r2(v)}
                  for pid, v in sorted(fees.items(), key=lambda kv: -kv[1]) if v]
    property_expenses = [{"producto": pid, "nombre": name(pid), "importe": r2(v)}
                   for pid, v in sorted(property_expenses.items(), key=lambda kv: -kv[1]) if v]

    con_coste = [v for v in sales if v["adquisicion"] is not None]
    totales = {
        "ganancias": r2(sum(v["ganancia"] for v in sales if v["ganancia"] > 0)),
        "perdidas": r2(sum(v["ganancia"] for v in sales if v["ganancia"] < 0)),
        "saldo": r2(sum(v["ganancia"] for v in sales)),
        "transmision": r2(sum(v["transmision"] for v in sales)),
        "adquisicion": r2(sum(v["adquisicion"] for v in con_coste)),
        "dividendos": r2(sum(x["importe"] for x in income if x["clase"] == "Dividendos y cupones")),
        "intereses": r2(sum(x["importe"] for x in income if x["clase"] == "Intereses")),
        "alquileres": r2(sum(x["importe"] for x in income if x["clase"] == "Alquileres")),
        "gastosAlquiler": r2(sum(x["importe"] for x in property_expenses)),
        "comisiones": r2(sum(x["importe"] for x in fees)),
        "rescates": r2(sum(v["transmision"] for v in withdrawals)),
    }
    if any(x["clase"] == "Alquileres" for x in income) or property_expenses:
        warnings.append("Los alquileres van en su propio apartado de la Renta (rendimientos del capital inmobiliario), con "
                      "sus gastos deducibles, la amortización y las reducciones que te correspondan: aquí solo tienes lo "
                      "cobrado y lo gastado que anotaste.")
    if any(x["clase"] != "Alquileres" for x in income):
        warnings.append("Dividendos, cupones e intereses: van como los anotaste, que normalmente es lo que te ingresaron, ya sin "
                      "retención. En la Renta va el importe bruto y, aparte, la retención: los dos están en el informe "
                      "fiscal de tu banco o bróker.")
    if withdrawals:
        warnings.append("Lo que rescatas de un plan de pensiones no es una ganancia patrimonial: tributa como "
                      "rendimiento del trabajo (todo lo que sacas, no solo lo ganado). Va aparte.")
    return {"ano": year, "anos": years, "ventas": sales, "rescates": withdrawals, "cobros": income,
            "comisiones": fees, "gastosAlquiler": property_expenses, "totales": totales, "avisos": warnings}


def report_csv(inf):
    """Format a semicolon-delimited report with decimal commas for Spanish spreadsheet settings."""
    import csv
    import io
    num = lambda x: "" if x is None else f"{x:.2f}".replace(".", ",")
    date = engine.format_spanish_date
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", lineterminator="\r\n")
    w.writerow([f"Resumen para la Renta {inf['ano']} (orientativo, hecho con FinAppGo: compruébalo con tu banco)"])
    w.writerow([])
    w.writerow(["Ventas", "ISIN", "Tipo", "Fecha de venta", "Fechas de compra", "Unidades",
                "Valor de transmisión", "Valor de adquisición", "Ganancia o pérdida", "Revisar"])
    for v in inf["ventas"]:
        contribution_dates = sorted({c["fecha"] for c in v["compras"]})
        w.writerow([v["nombre"], v["isin"], v["tipo"], date(v["fecha"]), ", ".join(date(f) for f in contribution_dates),
                    "" if v["unidades"] is None else f"{v['unidades']:.6f}".rstrip("0").rstrip(",.").replace(".", ","),
                    num(v["transmision"]), num(v["adquisicion"]), num(v["ganancia"]), " ".join(v["avisos"])])
    t = inf["totales"]
    w.writerow(["Total", "", "", "", "", "", num(t["transmision"]), num(t["adquisicion"]), num(t["saldo"]), ""])
    w.writerow([])
    w.writerow(["Dividendos, cupones e intereses", "Clase", "Cobros", "Importe anotado"])
    for x in inf["cobros"]:
        w.writerow([x["nombre"], x["clase"], x["cobros"], num(x["importe"])])
    if inf["comisiones"]:
        w.writerow([])
        w.writerow(["Comisiones pagadas aparte", "Importe"])
        for x in inf["comisiones"]:
            w.writerow([x["nombre"], num(x["importe"])])
    if inf["gastosAlquiler"]:
        w.writerow([])
        w.writerow(["Gastos de inmuebles anotados", "Importe"])
        for x in inf["gastosAlquiler"]:
            w.writerow([x["nombre"], num(x["importe"])])
    if inf["rescates"]:
        w.writerow([])
        w.writerow(["Rescates de planes de pensiones (rendimiento del trabajo)", "Fecha", "Importe"])
        for v in inf["rescates"]:
            w.writerow([v["nombre"], date(v["fecha"]), num(v["transmision"])])
    if inf["avisos"]:
        w.writerow([])
        for a in inf["avisos"]:
            w.writerow([a])
    return out.getvalue()

"""Parse and preview spreadsheet and broker imports before applying them."""

import copy
import csv
import datetime as dt
import io
import re
import unicodedata

from . import storage, search, engine
from .engine import parse_spanish_number, value_at

COLUMNS = ["fecha", "identificador", "nombre", "tipo_producto", "tipo_movimiento",
            "unidades", "importe", "moneda", "comision", "nota"]

SINONIMOS = {
    "fecha": ["fecha", "date", "fecha operacion", "fecha valor", "fecha ejecucion"],
    "identificador": ["identificador", "isin", "ticker", "simbolo", "codigo", "id"],
    "nombre": ["nombre", "producto", "descripcion", "name"],
    "tipo_producto": ["tipo producto", "tipo_producto", "clase", "tipo de producto"],
    "tipo_movimiento": ["tipo movimiento", "tipo_movimiento", "movimiento", "operacion", "tipo"],
    "unidades": ["unidades", "participaciones", "titulos", "acciones", "cantidad", "units"],
    "importe": ["importe", "importe eur", "total", "amount", "importe total"],
    "moneda": ["moneda", "divisa", "currency"],
    "comision": ["comision", "comisiones", "fee", "gastos"],
    "nota": ["nota", "notas", "comentario", "observaciones"],
}
TIPO_MOV = {
    "compra": "compra", "suscripcion": "compra", "buy": "compra", "aportacion": "compra",
    "venta": "venta", "reembolso": "venta", "sell": "venta",
    "dividendo": "dividendo", "cupon": "dividendo", "dividend": "dividendo", "interes": "dividendo",
    "comision": "comision", "fee": "comision", "custodia": "comision",
    "saldo": "saldo", "valor": "saldo", "valoracion": "saldo",
    "traspaso salida": "traspaso_salida", "traspaso de salida": "traspaso_salida", "traspaso origen": "traspaso_salida",
    "traspaso entrada": "traspaso_entrada", "traspaso de entrada": "traspaso_entrada", "traspaso destino": "traspaso_entrada",
    "ajuste": "ajuste", "ajuste de participaciones": "ajuste",
}
TIPO_PROD = {
    "fondo": "fondo", "fondo de inversion": "fondo", "etf": "etf", "etp": "etf",
    "accion": "accion", "acciones": "accion", "cripto": "cripto", "criptomoneda": "cripto",
    "commodity": "commodity", "materia prima": "commodity", "oro": "commodity",
    "bono": "bono", "renta fija": "bono", "pension": "pension", "plan de pensiones": "pension",
    "efectivo": "efectivo", "cuenta": "efectivo", "cuenta corriente": "efectivo",
    "inmueble": "inmueble", "piso": "inmueble", "vivienda": "inmueble",
    "deuda": "deuda", "prestamo": "deuda", "hipoteca": "deuda", "otro": "otro",
    "p2p": "p2p", "prestamos p2p": "p2p", "crowdfunding": "p2p", "crowdlending": "p2p",
}


def strip_accents(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.replace("_", " ")).strip().lower()


def decode(raw_value):
    if isinstance(raw_value, str):
        return raw_value
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw_value.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_value.decode("utf-8", "replace")


CAB_MYINVESTOR = {"fecha": ["fecha fiscal", "fecha"],
                  "coste": ["inversion", "inversión", "coste"],
                  "valor": ["valor de mercado", "valor mercado", "valor"]}


def read_myinvestor_csv(text):
    text = decode(text)
    delimiter = ";" if text.count(";") >= text.count(",") else ","
    rows = [f for f in csv.reader(io.StringIO(text), delimiter=delimiter)
             if any((c or "").strip() for c in f)]
    if not rows:
        return [], []

    cab = [(c or "").strip().lower() for c in rows[0]]

    def col(key, defecto):
        for i, c in enumerate(cab):
            if any(a in c for a in CAB_MYINVESTOR[key]):
                return i
        return defecto

    ic, ico, iv = col("fecha", 0), col("coste", 1), col("valor", 2)
    lots, redemptions = [], []
    for row in rows[1:]:
        if len(row) <= max(ic, ico, iv):
            continue
        m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", row[ic])
        if not m:
            continue
        date = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        cost_basis, value = parse_spanish_number(row[ico]), parse_spanish_number(row[iv])
        if cost_basis <= 0 and value <= 0:
            if len(row) > 3 and parse_spanish_number(row[3]):
                redemptions.append([date, round(parse_spanish_number(row[3]), 2)])
            continue
        lots.append([date, round(cost_basis, 2), round(value, 2)])
    lots.sort(key=lambda x: x[0])
    return lots, redemptions


TOLERANCIA_TRASPASO = 0.02


def statement_nav(lots, nav_series):
    """Estimate the NAV used by MyInvestor to value the statement, typically from a recent trading day."""
    normales = [(c / nav_series[f], v) for f, c, v in lots if nav_series.get(f) and c > 0 and v > 0]
    if not nav_series:
        return None, 0
    best, note = None, (0, 0.0)
    for f in sorted(nav_series, reverse=True):
        vl = nav_series[f]
        errors = [abs(u * vl / v - 1) for u, v in normales]
        inside = [e for e in errors if e < 0.005]
        candidata = (len(inside), -sum(inside) / len(inside) if inside else 0.0)
        if candidata > note:
            best, note = vl, candidata
    return (best, note[0]) if note[0] else (nav_series[max(nav_series)], 0)


def myinvestor_movements(producto_id, lots, redemptions, nav_series):
    """Convert statement lots into purchases. Infer the units when the statement supplies only cost and NAV."""
    nav_at_statement, cuadran = statement_nav(lots, nav_series)
    movs, missing_nav, transfers = [], 0, 0
    for date, cost_basis, value in lots:
        vc = nav_series.get(date)
        note = "MyInvestor"
        is_transfer = False
        if vc and cost_basis > 0:
            units = cost_basis / vc
            if cuadran and value > 0 and abs(units * nav_at_statement / value - 1) > TOLERANCIA_TRASPASO:
                units, transfers = value / nav_at_statement, transfers + 1
                note = "MyInvestor · traspaso: participaciones estimadas con el valor de mercado"
                is_transfer = True
        elif nav_at_statement and value > 0:
            units = value / nav_at_statement
            home = min(nav_series) if nav_series else None
            if home and date < (dt.date.fromisoformat(home) - dt.timedelta(days=7)).isoformat():
                transfers, is_transfer = transfers + 1, True
                note = "MyInvestor · traspaso: participaciones estimadas con el valor de mercado"
            else:
                missing_nav += 1
        else:
            units, missing_nav = 0.0, missing_nav + 1
        movs.append({"fecha": date, "producto": producto_id, "tipo": "compra",
                     "unidades": round(units, 6), "importe": cost_basis, "nota": note,
                     **({"_traspaso": True} if is_transfer else {})})
    for date, result in redemptions:
        movs.append({"fecha": date, "producto": producto_id, "tipo": "venta",
                     "unidades": 0, "importe": result,
                     "nota": "Plusvalía de un reembolso (MyInvestor no da la fecha de venta)"})
    return movs, missing_nav, transfers


def read_table(name, content):
    if name and name.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        libro = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        sheet = libro["Movimientos"] if "Movimientos" in libro.sheetnames else libro.worksheets[0]
        rows = [list(f) for f in sheet.iter_rows(values_only=True)]
    else:
        text = decode(content)
        text = re.sub(r"^\s*```[a-zA-Z]*\s*$", "", text, flags=re.M).strip()
        lines = text.splitlines()
        if not any(l.strip() for l in lines):
            return [], "El texto está vacío."
        cab = next(l for l in lines if l.strip())
        delimiter = max([";", "\t", ","], key=cab.count)
        rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))
    rows = [(n, f) for n, f in enumerate(rows, start=1)
             if f and any(c not in (None, "") and str(c).strip() for c in f)]
    if not rows:
        return [], "No hay ninguna fila con datos."

    cab = [strip_accents(c) for c in rows[0][1]]
    idx = {}
    for col, alias in SINONIMOS.items():
        for i, c in enumerate(cab):
            if c in alias and i not in idx.values():
                idx[col] = i
                break
    missing = [c for c in ("fecha", "tipo_movimiento", "importe") if c not in idx]
    if missing:
        return [], ("No encuentro las columnas " + ", ".join(missing) + ". La primera fila tiene que ser la "
                    "cabecera de la plantilla: " + ";".join(COLUMNS))
    if len(rows) < 2:
        if name and name.lower().endswith((".xlsx", ".xlsm")):
            return [], ("La hoja «Movimientos» está vacía: solo tiene la cabecera. Las filas de la hoja "
                        "«Ejemplo» son de muestra y no se importan; escribe tus operaciones en «Movimientos», "
                        "debajo de la cabecera, guarda el archivo y vuelve a subirlo.")
        return [], "Solo hay cabecera: escribe tus operaciones debajo, una por fila."
    output = []
    for n, f in rows[1:]:
        output.append((n, {col: (f[i] if i < len(f) else None) for col, i in idx.items()}))
    return output, None


def parse_date(v):
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    t = str(v or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        a, me, di = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", t)
        if not m:
            return None
        a = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
        me, di = int(m.group(2)), int(m.group(1))
    try:
        return dt.date(a, me, di).isoformat()
    except ValueError:
        return None


def parse_number(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)):
        return abs(float(v))
    t = str(v).strip().replace("€", "").replace("$", "").replace(" ", "")
    if not re.fullmatch(r"[-+]?[\d.,]+", t):
        return "error"
    return abs(parse_spanish_number(t))


class Plan:

    def __init__(self):
        self.new_products = []
        self.movements = []
        self.valuations = []
        self.reemplazar = []
        self.errors = []
        self.warnings = []
        self.myinvestor_transfers = []
        self.series_mi = {}

    def error(self, row, mensaje):
        self.errors.append({"fila": row, "mensaje": mensaje})


def _existing_product(cfg, instrument_id, name):
    identifier = (instrument_id or "").strip().upper()
    for p in cfg.get("productos", []):
        if identifier and identifier in ((p.get("identificador") or "").upper(), (p.get("codigo") or "").upper()):
            return p
    nom = strip_accents(name)
    if nom and not identifier:
        for p in cfg.get("productos", []):
            if nom in (strip_accents(p.get("nombre")), strip_accents(p.get("corto"))):
                return p
    return None


class ProductResolver:

    def __init__(self, cfg, preview_plan, directory):
        self.cfg, self.preview_plan, self.directory = cfg, preview_plan, directory
        self.cache, self.series, self.frescas = {}, {}, set()

    def product(self, row, instrument_id, name, tipo_prod):
        key = ((instrument_id or "").strip().upper(), strip_accents(name) if not instrument_id else "")
        if key in self.cache:
            return self.cache[key]
        ref = None
        existing = _existing_product(self.cfg, instrument_id, name)
        if existing:
            ref = existing["id"]
        elif instrument_id:
            n_fallos = len(search.FETCH_FAILURES)
            res = search.search(instrument_id)
            if not res and search.fetch_error_since(n_fallos):
                self.preview_plan.error(row, f"No he podido consultar «{instrument_id}» en internet ahora mismo "
                                      "(la conexión ha fallado o Yahoo/Morningstar no han respondido). "
                                      "Comprueba tu conexión y vuelve a pulsar «Previsualizar»: suele bastar "
                                      "con intentarlo otra vez.")
                ref = None
            elif res:
                r = res[0]
                fi = r.get("ficha") or {}
                data = {"nombre": name or r.get("nombre") or r["codigo"], "tipo": r["tipo"],
                         "identificador": instrument_id.strip(), "fuente": r["fuente"], "codigo": r["codigo"],
                         "moneda": r.get("moneda") or "EUR", "vivo": r.get("vivo") or "",
                         "ter": fi.get("ter"), "riesgo": fi.get("riesgo"), "clase": fi.get("clase") or "",
                         "gestora": fi.get("gestora") or "", "largoPlazo": True}
                ref = self._new_entry(data, r)
            else:
                self.preview_plan.error(row, f"No encuentro «{instrument_id}» con precio en internet. Si no cotiza, "
                                      "créalo en Productos con «Valor anotado a mano» y ese mismo "
                                      "identificador, y vuelve a importar.")
        elif name:
            kind = tipo_prod if tipo_prod in engine.PRODUCT_TYPES else "otro"
            ref = self._new_entry({"nombre": name, "tipo": kind, "fuente": "manual",
                               "largoPlazo": kind not in ("efectivo", "deuda")}, None)
        else:
            self.preview_plan.error(row, "No tiene identificador ni nombre: no sé de qué producto es.")
        self.cache[key] = ref
        return ref

    def _new_entry(self, data, result):
        ref = f"nuevo:{len(self.preview_plan.new_products) + 1}"
        self.preview_plan.new_products.append({
            "ref": ref, "datos": data,
            "precio": result and result.get("precio"), "monedaPrecio": result and result.get("moneda"),
            "fecha": result and result.get("fecha"), "mercado": result and result.get("mercado")})
        return ref

    def data(self, ref):
        if ref and ref.startswith("nuevo:"):
            return next(n["datos"] for n in self.preview_plan.new_products if n["ref"] == ref)
        return storage.product(self.cfg, ref)

    def price_series(self, ref, date=None):
        if ref not in self.series:
            p = self.data(ref)
            self.series[ref] = engine.product_price_series(p, self.directory) if p and p.get("fuente") != "manual" else {}
        s = self.series[ref]
        if date and s and max(s) < date and ref not in self.frescas:
            self.frescas.add(ref)
            self.series[ref] = s = engine.product_price_series(self.data(ref), self.directory, refresh=True)
        return s


def prepare_table(cfg, rows, directory):
    preview_plan = Plan()
    res = ProductResolver(cfg, preview_plan, directory)
    exchange_rates, transfers = {}, []
    for n, f in rows:
        date = parse_date(f.get("fecha"))
        kind = TIPO_MOV.get(strip_accents(f.get("tipo_movimiento")))
        identifier = str(f.get("identificador") or "").strip()
        name = str(f.get("nombre") or "").strip()
        tprod = TIPO_PROD.get(strip_accents(f.get("tipo_producto")), "")
        amount, units, fee = (parse_number(f.get(k)) for k in ("importe", "unidades", "comision"))
        currency = (str(f.get("moneda") or "").strip() or "EUR").upper()
        note = str(f.get("nota") or "").strip()

        if not date:
            preview_plan.error(n, f"La fecha «{f.get('fecha') or ''}» no es válida. Usa el formato 2025-03-10 o 10/03/2025.")
            continue
        if not kind:
            preview_plan.error(n, f"El tipo de movimiento «{f.get('tipo_movimiento') or ''}» no es válido: "
                          "usa compra, venta, dividendo, comision, saldo, traspaso_salida o traspaso_entrada.")
            continue
        if "error" in (amount, units, fee):
            preview_plan.error(n, "Algún número no se entiende (importe, unidades o comisión).")
            continue
        if not amount and kind not in ("saldo", "ajuste"):
            preview_plan.error(n, "No tiene importe.")
            continue
        if kind == "ajuste":
            amount = amount or 0.0
        if not identifier and not name:
            preview_plan.error(n, "No tiene identificador: pon el ISIN o el ticker (o, si es una cuenta, su nombre).")
            continue
        if kind == "saldo" and not identifier:
            tprod = tprod or "efectivo"
        ref = res.product(n, identifier, name, tprod)
        if not ref:
            continue
        markers = []

        if currency != "EUR" and amount is not None:
            if currency not in exchange_rates:
                exchange_rates[currency] = engine.exchange_rate_series(currency, directory)
            fx = value_at(exchange_rates[currency], date, margen=6)
            if not fx and (currency, "fresco") not in exchange_rates:
                exchange_rates[currency] = engine.exchange_rate_series(currency, directory, refresh=True)
                exchange_rates[(currency, "fresco")] = True
                fx = value_at(exchange_rates[currency], date, margen=6)
            if not fx:
                preview_plan.error(n, f"No encuentro el cambio de {currency} a euros del {storage.format_date(date)}.")
                continue
            amount = amount * fx
            fee = fee * fx if fee else fee
            markers.append(f"convertido de {currency}")

        if kind == "saldo":
            preview_plan.valuations.append({"fila": n, "producto": ref, "fecha": date, "valor": round(amount or 0, 2)})
            continue

        p = res.data(ref)
        has_market_price = p and p.get("fuente") != "manual" and p.get("tipo") not in storage.BALANCE_ONLY
        if kind in ("traspaso_salida", "traspaso_entrada"):
            if not units and has_market_price:
                price = value_at(res.price_series(ref, date), date, margen=6)
                if not price:
                    preview_plan.error(n, "No trae participaciones y no encuentro el precio de ese día para calcularlas.")
                    continue
                units = amount / price
                markers.append("unidades calculadas")
            transfers.append({"fila": n, "producto": ref, "fecha": date, "tipo": kind, "unidades": units or 0,
                              "importe": round(amount, 2), "nota": note, "marcas": markers})
            continue
        if kind in ("compra", "venta") and not units and has_market_price:
            price = value_at(res.price_series(ref, date), date, margen=6)
            if not price:
                preview_plan.error(n, "No trae unidades y no encuentro el precio de ese día para calcularlas.")
                continue
            net = amount - (fee or 0) if kind == "compra" else amount + (fee or 0)
            units = net / price
            markers.append("unidades calculadas")
        preview_plan.movements.append({"fila": n, "producto": ref, "fecha": date, "tipo": kind,
                                 "unidades": units, "importe": round(amount, 2),
                                 "comision": round(fee, 2) if fee else None,
                                 "nota": note, "marcas": markers, "origen": "importado"})
    pair_transfers(preview_plan, transfers)
    return preview_plan


def pair_transfers(preview_plan, rows):
    """Match rows for the outgoing and incoming legs of imported transfers."""
    inflows = [f for f in rows if f["tipo"] == "traspaso_entrada"]
    for s in [f for f in rows if f["tipo"] == "traspaso_salida"]:
        pair = next((e for e in inflows if e["fecha"] == s["fecha"] and e["producto"] != s["producto"]
                       and abs(e["importe"] - s["importe"]) <= max(1.0, 0.01 * s["importe"])), None)
        if not pair:
            preview_plan.error(s["fila"], "Traspaso de salida sin su entrada: añade otra fila «traspaso_entrada» con el "
                                  "fondo de destino, la misma fecha y el mismo importe.")
            continue
        inflows.remove(pair)
        preview_plan.movements.append({"fila": s["fila"], "producto": s["producto"], "destino": pair["producto"],
                                 "fecha": s["fecha"], "tipo": "traspaso", "unidades": s["unidades"],
                                 "unidadesDestino": pair["unidades"], "importe": s["importe"],
                                 "comision": None, "nota": s["nota"] or pair["nota"],
                                 "marcas": s["marcas"] + [m for m in pair["marcas"] if m not in s["marcas"]],
                                 "origen": "importado"})
    for e in inflows:
        preview_plan.error(e["fila"], "Traspaso de entrada sin su salida: añade otra fila «traspaso_salida» con el "
                              "fondo de origen, la misma fecha y el mismo importe.")


def prepare_myinvestor(cfg, files, directory):
    """Prepare imports grouped by statement. Re-importing a fund replaces its previously imported lots."""
    preview_plan = Plan()
    res = ProductResolver(cfg, preview_plan, directory)
    for name, content in files:
        m = re.search(r"([A-Z]{2}[A-Z0-9]{9}\d)", (name or "").upper())
        if not m:
            preview_plan.error(name, "No encuentro el ISIN en el nombre del archivo. Descárgalo otra vez de "
                               "MyInvestor sin cambiarle el nombre (lleva el ISIN del fondo).")
            continue
        isin = m.group(1)
        lots, redemptions = read_myinvestor_csv(content)
        if not lots and not redemptions:
            preview_plan.error(name, "No parece un extracto «Plusvalías y minusvalías» de MyInvestor, o está vacío.")
            continue
        ref = res.product(name, isin, "", "fondo")
        if not ref:
            continue
        p = res.data(ref)
        if p.get("fuente") == "manual":
            preview_plan.error(name, f"«{p.get('corto') or p['nombre']}» se valora a mano: el extracto de MyInvestor "
                               "necesita un fondo con precio en internet.")
            continue
        price_series = res.price_series(ref, lots[-1][0] if lots else None)
        preview_plan.series_mi[ref] = price_series
        movs, missing_nav, transfers = myinvestor_movements(ref, lots, redemptions, price_series)
        if missing_nav:
            preview_plan.warnings.append(f"{isin}: {missing_nav} compras sin valor liquidativo de ese día; sus "
                               "participaciones se han estimado con el valor del extracto.")
        if transfers:
            transfer_flag = [m for m in movs if m.get("_traspaso")]
            previous_value = next((m for m in cfg.get("movimientos", []) if m.get("tipo") == "traspaso"
                           and m.get("destino") == ref and m.get("origen") == "myinvestor"), None)
            preview_plan.myinvestor_transfers.append({
                "ref": ref, "isin": isin, "lotes": len(transfer_flag),
                "coste": round(sum(m["importe"] for m in transfer_flag), 2),
                "unidades": round(sum(m["unidades"] for m in transfer_flag), 6), "serie": price_series,
                "detalle": [[m["fecha"], m["importe"], m["unidades"]] for m in transfer_flag],
                "sugerencia": {"origen": previous_value["producto"],
                               "fecha": "estimar" if previous_value.get("fechaEstimada") else previous_value["fecha"]} if previous_value else None})
        preview_plan.reemplazar.append((ref, "myinvestor"))
        for mv in movs:
            preview_plan.movements.append({**mv, "fila": name, "comision": None, "marcas": [],
                                     "origen": "myinvestor"})
    return preview_plan


def valid_answer(item, answer, real):
    if not isinstance(answer, dict) or not answer.get("origen") or answer.get("origen") == "ninguno":
        return None
    n = len(item.get("detalle") or []) or 1
    contribution_dates = answer.get("fechas")
    if not isinstance(contribution_dates, list):
        contribution_dates = [answer.get("fecha")] * n
    contribution_dates = (list(contribution_dates) + [None] * n)[:n]
    out = []
    for f in contribution_dates:
        if f == "estimar":
            out.append("estimar")
            continue
        f = parse_date(f)
        if not f:
            return None
        out.append(f)
    return {"origen": answer["origen"], "fechas": out, "fecha": out[0]}


def estimate_transfer_date(source_series, serie_destino, lot):
    """Estimate the transfer date by minimizing the difference between source proceeds and destination cost."""
    date, cost_basis, unidades_destino = lot[0], lot[1], lot[2] if len(lot) > 2 else None
    vl_compra = value_at(source_series, date, margen=7)
    if not vl_compra or not serie_destino or not unidades_destino:
        return None
    unidades_origen = cost_basis / vl_compra
    best, error = None, None
    for d in sorted(serie_destino):
        if d < date:
            continue
        vo = value_at(source_series, d, margen=7)
        if not vo:
            continue
        e = abs(unidades_destino * serie_destino[d] / (unidades_origen * vo) - 1)
        if error is None or e < error:
            best, error = d, e
    return best


def build_myinvestor_transfers(cfg, item, resp, destination, source_series=None):
    details = item.get("detalle") or []
    contribution_dates = resp.get("fechas") or [resp.get("fecha")] * max(1, len(details))
    if not details:
        mov, notice = _build_transfer(cfg, item, {"origen": resp["origen"], "fecha": contribution_dates[0]}, destination, source_series)
        return [mov], notice
    grupos = {}
    for lot, f in zip(details, contribution_dates):
        estimated = f == "estimar"
        if estimated:
            f = estimate_transfer_date(source_series or {}, item.get("serie") or {}, lot)
            if not f:
                raise storage.ValidationError([
                    f"No puedo estimar la fecha del traspaso del lote del {storage.format_date(lot[0])} "
                    f"({storage.format_number(lot[1])} €): faltan precios. Pon la fecha a mano."])
        grupos.setdefault((f, estimated), []).append(lot)
    movs, warnings = [], []
    for (f, estimated), lots in sorted(grupos.items()):
        sub = {**item, "detalle": lots, "coste": round(sum(l[1] for l in lots), 2),
               "unidades": sum(l[2] for l in lots if len(l) > 2)}
        mov, notice = _build_transfer(cfg, sub, {"origen": resp["origen"], "fecha": f}, destination, source_series)
        if estimated:
            mov["fechaEstimada"] = True
            warnings.append(f"Fecha estimada: {storage.format_date(f)}. Es el día en que más cuadran los precios de los dos "
                          "fondos, pero puede no ser el bueno: compruébala en el historial de órdenes de MyInvestor.")
        if notice:
            warnings.append(notice)
        movs.append(mov)
    return movs, " ".join(dict.fromkeys(warnings)) or None


def _build_transfer(cfg, item, resp, destination, source_series=None):
    source = storage.product(cfg, resp["origen"])
    if not source or source["id"] == destination:
        raise storage.ValidationError(["Elige como origen un fondo distinto del de destino."])
    name = source.get("corto") or source["nombre"]
    from_statement = [m for m in cfg.get("movimientos", []) if m.get("producto") == source["id"]
                    and m.get("tipo") == "compra" and m.get("origen") == "myinvestor"]
    if from_statement and item.get("detalle"):
        return _statement_transfer(cfg, item, resp, destination, source, from_statement, source_series or {})
    lots = engine.open_lots(cfg, source["id"], resp["fecha"])
    total_cost_basis = sum(l[1] for l in lots)
    if not lots or total_cost_basis <= 0:
        raise storage.ValidationError([f"En FinAppGo, «{name}» no tenía nada el {storage.format_date(resp['fecha'])}. "
                                       "Si ya lo has reimportado o borrado, elige «No están en FinAppGo»."])
    missing_amount, units = item["coste"], 0.0
    for lu, lc, _, _ in lots:
        if missing_amount <= 0.005:
            break
        take = min(lc, missing_amount)
        units += lu * take / lc if lc else lu
        missing_amount -= take
    notice = None
    if missing_amount > max(1.0, 0.02 * item["coste"]):
        notice = (f"«{name}» solo tenía {storage.format_number(round(total_cost_basis, 2))} € de coste en FinAppGo y el traspaso es de "
                 f"{storage.format_number(item['coste'])} €: sale todo lo que tenía. Revisa que esté completo.")
    price = value_at(item.get("serie") or {}, resp["fecha"], margen=7)
    amount = round(item["unidades"] * price, 2) if price else item["coste"]
    mov = storage.save_movement(cfg, {
        "tipo": "traspaso", "producto": source["id"], "destino": destination, "fecha": resp["fecha"],
        "unidades": units, "unidadesDestino": item["unidades"], "importe": amount,
        "nota": "Traspaso importado de MyInvestor"})
    mov["origen"] = "myinvestor"
    return mov, notice


def _statement_transfer(cfg, item, resp, destination, source, from_statement, source_series):
    name = source.get("corto") or source["nombre"]
    usados, units, rebuild = set(), 0.0, []
    for date, cost_basis, *_ in item["detalle"]:
        if date > resp["fecha"]:
            raise storage.ValidationError([f"La fecha del traspaso ({storage.format_date(resp['fecha'])}) es anterior a la "
                                           f"compra que se traspasó ({storage.format_date(date)}). Revisa la fecha."])
        par = next((m for m in from_statement if id(m) not in usados and m["fecha"] == date
                    and abs(float(m.get("importe") or 0) - cost_basis) <= max(0.02, cost_basis * 0.001)), None)
        if par:
            usados.add(id(par))
            units += float(par.get("unidades") or 0)
        else:
            rebuild.append((date, cost_basis))
    for date, cost_basis in rebuild:
        vl = value_at(source_series, date, margen=7)
        if not vl:
            raise storage.ValidationError([f"No encuentro el valor liquidativo de «{name}» el {storage.format_date(date)}: "
                                           "no puedo reconstruir lo que salió de él. Elige «No está en FinAppGo»."])
        purchase = storage.save_movement(cfg, {
            "tipo": "compra", "producto": source["id"], "fecha": date, "unidades": cost_basis / vl, "importe": cost_basis,
            "nota": "Reconstruido: se compró aquí y salió después en un traspaso (el extracto de MyInvestor ya no lo trae)"})
        purchase["origen"] = "myinvestor-traspaso"
        purchase["paraTraspaso"] = destination
        units += cost_basis / vl
    price = value_at(item.get("serie") or {}, resp["fecha"], margen=7)
    amount = round(item["unidades"] * price, 2) if price else item["coste"]
    mov = storage.save_movement(cfg, {
        "tipo": "traspaso", "producto": source["id"], "destino": destination, "fecha": resp["fecha"],
        "unidades": units, "unidadesDestino": item["unidades"], "importe": amount,
        "nota": "Traspaso importado de MyInvestor"})
    mov["origen"] = "myinvestor"
    notice = (f"El extracto de «{name}» ya no trae lo que salió en este traspaso: FinAppGo lo ha añadido en su fecha "
             f"({len(rebuild)} {'compra' if len(rebuild) == 1 else 'compras'}) para que se vea cómo entró y salió."
             if rebuild else None)
    return mov, notice


def apply(cfg, preview_plan, answers=None, carpeta_series=None):
    ids, errors = {}, list(preview_plan.errors)
    for n in preview_plan.new_products:
        prod, _ = storage.save_product(cfg, dict(n["datos"]))
        ids[n["ref"]] = prod["id"]
    real = lambda ref: ids.get(ref, ref)

    replaced = 0
    for ref, source in preview_plan.reemplazar:
        before = len(cfg["movimientos"])
        cfg["movimientos"] = [m for m in cfg["movimientos"]
                              if not (m.get("producto") == real(ref) and m.get("origen") == source)
                              and not (m.get("tipo") == "traspaso" and m.get("destino") == real(ref)
                                       and m.get("origen") == source)
                              and not (m.get("origen") == "myinvestor-traspaso" and m.get("paraTraspaso") == real(ref))]
        replaced += before - len(cfg["movimientos"])

    answers = answers or {}
    contestados = {it["ref"]: valid_answer(it, answers.get(it["ref"]), real) for it in preview_plan.myinvestor_transfers}

    def signature(m):
        return (m["producto"], m["fecha"], m["tipo"], round(float(m.get("unidades") or 0), 4),
                round(float(m.get("importe") or 0), 2))
    existing_entries = {signature(m) for m in cfg["movimientos"]}

    added, duplicados, rows = 0, 0, []
    order = {"compra": 0, "comision": 1, "dividendo": 2, "venta": 3, "traspaso": 4, "ajuste": 6}
    apartados = []
    for mv in sorted(preview_plan.movements, key=lambda m: (m["fecha"], order.get(m["tipo"], 9))):
        if mv.get("_traspaso") and contestados.get(mv["producto"]):
            apartados.append(mv)
            continue
        data = {k: mv[k] for k in ("fecha", "tipo", "unidades", "importe", "comision", "nota", "unidadesDestino")
                 if mv.get(k) is not None}
        data["producto"] = real(mv["producto"])
        if mv.get("destino"):
            data["destino"] = real(mv["destino"])
        state = "nuevo"
        if signature({**data, "unidades": data.get("unidades", 0)}) in existing_entries:
            duplicados += 1
            state = "repetido"
        else:
            try:
                saved = storage.save_movement(cfg, data)
                saved["origen"] = mv["origen"]
                if mv["tipo"] == "traspaso":
                    existing_entries.add(signature(saved))
                added += 1
            except storage.ValidationError as e:
                errors.append({"fila": mv["fila"], "mensaje": " ".join(e.errors)})
                state = "error"
        rows.append({"fila": mv["fila"], "fecha": mv["fecha"], "producto": data["producto"], "tipo": mv["tipo"],
                      "unidades": mv.get("unidades"), "importe": mv["importe"], "marcas": mv["marcas"],
                      "estado": state})

    myinvestor_transfers = []
    for it in preview_plan.myinvestor_transfers:
        resp = contestados.get(it["ref"])
        state = {"ref": it["ref"], "isin": it["isin"], "lotes": it["lotes"], "coste": it["coste"],
                  "unidades": it["unidades"], "sugerencia": it["sugerencia"], "detalle": it.get("detalle") or [],
                  "respuesta": answers.get(it["ref"]) if isinstance(answers.get(it["ref"]), dict) else None,
                  "hecho": False, "error": None, "aviso": None}
        if resp:
            try:
                origen_ref = next((r for r in preview_plan.series_mi if real(r) == resp["origen"]), None)
                source_series = preview_plan.series_mi.get(origen_ref) if origen_ref else None
                if source_series is None:
                    o = storage.product(cfg, resp["origen"])
                    source_series = (engine.product_price_series(o, carpeta_series)
                                    if o and o.get("fuente") != "manual" and carpeta_series else {})
                movs, state["aviso"] = build_myinvestor_transfers(cfg, it, resp, real(it["ref"]), source_series)
                state["hecho"] = True
                state["fechas"] = [m["fecha"] for m in movs]
                for mov in movs:
                    existing_entries.add(signature(mov))
                    rows.append({"fila": it["isin"], "fecha": mov["fecha"], "producto": real(it["ref"]),
                                  "tipo": "traspaso", "unidades": mov["unidadesDestino"], "importe": mov["importe"],
                                  "marcas": ["traspaso desde " + (storage.product(cfg, resp["origen"]) or {}).get("nombre", "")]
                                  + (["fecha estimada"] if mov.get("fechaEstimada") else []),
                                  "estado": "nuevo"})
                    added += 1
            except storage.ValidationError as e:
                state["error"] = " ".join(e.errors)
                for mv in [m for m in apartados if m["producto"] == it["ref"]]:
                    data = {k: mv[k] for k in ("fecha", "tipo", "unidades", "importe", "nota") if mv.get(k) is not None}
                    data["producto"] = real(mv["producto"])
                    saved = storage.save_movement(cfg, data)
                    saved["origen"] = mv["origen"]
                    added += 1
                    rows.append({"fila": mv["fila"], "fecha": mv["fecha"], "producto": data["producto"], "tipo": "compra",
                                  "unidades": mv.get("unidades"), "importe": mv["importe"], "marcas": ["traspaso"],
                                  "estado": "nuevo"})
        myinvestor_transfers.append(state)

    saldos = 0
    for v in preview_plan.valuations:
        try:
            storage.save_valuation(cfg, {"producto": real(v["producto"]), "fecha": v["fecha"], "valor": v["valor"]})
            saldos += 1
            rows.append({"fila": v["fila"], "fecha": v["fecha"], "producto": real(v["producto"]), "tipo": "saldo",
                          "unidades": None, "importe": v["valor"], "marcas": [], "estado": "nuevo"})
        except storage.ValidationError as e:
            errors.append({"fila": v["fila"], "mensaje": " ".join(e.errors)})

    def total(t):
        return round(sum(f["importe"] for f in rows if f["tipo"] == t and f["estado"] == "nuevo"), 2)
    names = {p["id"]: p.get("corto") or p["nombre"] for p in cfg["productos"]}
    for f in rows:
        f["productoNombre"] = names.get(f["producto"], f["producto"])
    for t in myinvestor_transfers:
        t["nombre"] = names.get(real(t["ref"]), t["isin"])
        t["origenes"] = [{"id": p["id"], "nombre": p.get("corto") or p["nombre"]} for p in cfg["productos"]
                         if p["id"] != real(t["ref"]) and p.get("tipo") not in storage.BALANCE_ONLY]
    return {
        "añadidos": added, "repetidos": duplicados, "saldos": saldos, "sustituidos": replaced,
        "errores": sorted(errors, key=lambda e: (str(type(e["fila"])), str(e["fila"]).zfill(6))),
        "avisos": preview_plan.warnings,
        "totales": {"compras": total("compra"), "ventas": total("venta"),
                    "dividendos": total("dividendo"), "comisiones": total("comision"),
                    "numCompras": sum(1 for f in rows if f["tipo"] == "compra" and f["estado"] == "nuevo")},
        "productosNuevos": [{**n["datos"], "id": ids.get(n["ref"]), "precio": n["precio"],
                             "monedaPrecio": n["monedaPrecio"], "fechaPrecio": n["fecha"],
                             "mercado": n["mercado"]} for n in preview_plan.new_products],
        "filas": sorted(rows, key=lambda f: f["fecha"], reverse=True),
        "traspasosMyInvestor": myinvestor_transfers,
    }


def preview(cfg, preview_plan, answers=None, carpeta_series=None):
    """Apply the plan to a copy and return the report without modifying the portfolio."""
    return apply(copy.deepcopy(cfg), preview_plan, answers, carpeta_series)

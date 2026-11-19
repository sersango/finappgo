"""Serve the dashboard and portfolio API."""

import base64
import datetime as dt
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

from flask import Flask, Response, g, jsonify, redirect, request, send_from_directory
from werkzeug.serving import make_server

from . import storage, search, export, tax, imports, engine, recurring, spreadsheet, network

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "app", "web")
DATA_DIR = os.environ.get("PATRIMONIO_DATOS") or os.path.join(ROOT, "mis_datos")
DEMO = os.path.join(ROOT, "demo", "portfolio.json")
PORT = int(os.environ.get("PATRIMONIO_PUERTO") or 8765)
HORAS_PRECIOS = 6
VERSION_CACHE = 2

app = Flask(__name__, static_folder=None)
app.json.sort_keys = False
lock = threading.RLock()


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
COOKIE = "finappgo_acceso"
UPLOAD_LIMIT = 25 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = UPLOAD_LIMIT
_ACCESS_KEYS = {}

ACCESS_REQUIRED_PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8"><title>FinAppGo</title>
<style>body{font:16px/1.6 system-ui,sans-serif;margin:14vh auto;max-width:540px;padding:0 22px;color:#1d1d1b;background:#f9f9f7}
h1{font-size:22px}code{background:#ecebe6;padding:1px 6px;border-radius:5px}</style></head><body>
<h1>Abre FinAppGo con el enlace de acceso</h1>
<p>Consulta los registros del contenedor y abre el enlace de acceso en el navegador.</p></body></html>"""


def access_token():
    path = os.path.join(DATA_DIR, ".acceso")
    if path in _ACCESS_KEYS:
        return _ACCESS_KEYS[path]
    access_key = None
    try:
        with open(path, encoding="utf-8") as f:
            access_key = f.read().strip()
    except OSError:
        pass
    if not access_key or not re.fullmatch(r"[A-Za-z0-9_-]{40,}", access_key):
        access_key = secrets.token_urlsafe(32)
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(access_key)
    _ACCESS_KEYS[path] = access_key
    return access_key


def access_url(port):
    return f"http://127.0.0.1:{port}/?acceso={access_token()}"


def allowed_hosts():
    extra = os.environ.get("PATRIMONIO_HOSTS_PERMITIDOS") or ""
    return LOOPBACK_HOSTS | {h.strip().lower() for h in extra.split(",") if h.strip()}


def bind_address():
    return (os.environ.get("PATRIMONIO_HOST") or "127.0.0.1").strip()


def on_network():
    return bind_address() not in ("127.0.0.1", "localhost", "::1")


def in_docker():
    return os.environ.get("PATRIMONIO_DOCKER") == "1"


NOMBRES_DE_CASA = (".local", ".lan", ".home", ".internal", ".home.arpa", ".ts.net")


def valid_host(host):
    """Accept local and explicitly allowed hosts to prevent DNS rebinding."""
    h = _without_port(host)
    if h in allowed_hosts():
        return True
    if not on_network():
        return False
    ip = h.strip("[]")
    try:
        address = ipaddress.ip_address(ip)
        return address.is_private or address.is_loopback or address in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        pass
    return bool(re.fullmatch(r"[a-z0-9-]{1,63}", h)) or h.endswith(NOMBRES_DE_CASA)


def _without_port(host):
    host = (host or "").strip().lower()
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _same_origin(url):
    m = re.match(r"^https?://([^/]+)", url or "")
    return bool(m) and valid_host(m.group(1))


def _reject(text):
    if request.path.startswith("/api/"):
        return jsonify(ok=False, errores=[text]), 403
    if request.path == "/":
        return Response(ACCESS_REQUIRED_PAGE, status=403, mimetype="text/html")
    return Response(text, status=403, mimetype="text/plain")


@app.before_request
def restrict_requests():
    if not valid_host(request.host):
        return Response("FinAppGo no responde en esta dirección. Si entras con un nombre propio, añádelo en "
                        "PATRIMONIO_HOSTS_PERMITIDOS.", status=403, mimetype="text/plain")
    if request.path == "/api/ping":
        return None
    host_name = request.headers.get("Sec-Fetch-Site")
    if host_name and host_name not in ("same-origin", "none"):
        abrir_app = (request.method == "GET" and request.path == "/"
                     and request.headers.get("Sec-Fetch-Mode") == "navigate")
        if not abrir_app:
            return _reject("Petición bloqueada: no viene de FinAppGo.")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        source = request.headers.get("Origin") or request.headers.get("Referer")
        if source and not _same_origin(source):
            return _reject("Petición bloqueada: no viene de FinAppGo.")
    access_key = access_token()
    given = request.args.get("acceso")
    if given is not None:
        if not hmac.compare_digest(given, access_key):
            return _reject("Llave de acceso incorrecta. Abre el enlace que aparece en los registros del contenedor.")
        g.poner_cookie = True
        if request.method == "GET":
            remainder = urllib.parse.urlencode([(k, v) for k, v in request.args.items(multi=True) if k != "acceso"])
            return redirect(request.path + ("?" + remainder if remainder else ""))
        return None
    if not hmac.compare_digest(request.cookies.get(COOKIE, ""), access_key):
        return _reject("Falta la llave de acceso. Abre el enlace que aparece en los registros del contenedor.")
    return None


def _inline_script_hashes():
    """Allow the inline bootstrap scripts in the Content Security Policy by hash."""
    try:
        with open(os.path.join(WEB, "index.html"), encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return []
    hashes = set()
    for code in re.findall(r'<script id="script-loader">(.*?)</script>', html, flags=re.S):
        for variante in (code, code.replace("\r\n", "\n")):
            hashes.add("'sha256-" + base64.b64encode(hashlib.sha256(variante.encode("utf-8")).digest()).decode() + "'")
    return sorted(hashes)


CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' " + " ".join(_inline_script_hashes()),
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "connect-src 'self' https://api.coingecko.com https://api.binance.com",
    "font-src 'self'", "object-src 'none'", "base-uri 'none'", "form-action 'self'",
    "frame-ancestors 'none'",
])


@app.before_request
def verify_active_profile():
    """Reject edits from browser tabs still on a different profile."""
    pid = request.headers.get("X-FinAppGo-Perfil")
    if not pid or request.method in ("GET", "HEAD", "OPTIONS") or request.path.startswith("/api/perfiles"):
        return None
    d = profiles()
    if pid == d["activo"]:
        return None
    name = "Todos juntos" if d["activo"] == ALL_PROFILES else next(
        (x["nombre"] for x in d["lista"] if x["id"] == d["activo"]), d["activo"])
    return jsonify(ok=False, perfilCambiado=True, errores=[
        f"En otra pestaña has cambiado al perfil «{name}». Recarga esta página para seguir: no se ha guardado nada."]), 409


@app.after_request
def security_headers(resp):
    if g.get("poner_cookie"):
        resp.set_cookie(COOKIE, access_token(), max_age=400 * 24 * 3600, httponly=True,
                        samesite="Strict", path="/")
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = resp.headers.get("Cache-Control") or "no-store"
    return resp


def read_json(path, defecto=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


ALL_PROFILES = "todos"
DEFAULT_PROFILE = "principal"


def profiles():
    d = read_json(os.path.join(DATA_DIR, "perfiles.json"), {}) or {}
    entries = [x for x in d.get("lista") or [] if isinstance(x, dict) and isinstance(x.get("nombre"), str)
             and re.fullmatch(r"[a-z0-9_]{1,40}", str(x.get("id") or ""))]
    if not any(x["id"] == DEFAULT_PROFILE for x in entries):
        entries.insert(0, {"id": DEFAULT_PROFILE, "nombre": "Yo"})
    active = d.get("activo") or DEFAULT_PROFILE
    if active != ALL_PROFILES and not any(x["id"] == active for x in entries):
        active = DEFAULT_PROFILE
    if active == ALL_PROFILES and len(with_portfolio(entries)) < 2:
        active = DEFAULT_PROFILE
    return {"activo": active, "lista": entries}


def save_profiles(d):
    write_json(os.path.join(DATA_DIR, "perfiles.json"), {"activo": d["activo"], "lista": d["lista"]})


def directory(pid=None):
    pid = pid or profiles()["activo"]
    return DATA_DIR if pid in (DEFAULT_PROFILE, ALL_PROFILES) else os.path.join(DATA_DIR, "perfiles", pid)


def with_portfolio(entries):
    return [x for x in entries if os.path.exists(os.path.join(directory(x["id"]), "cartera.json"))]


def combined_portfolio():
    cfg = json.loads(json.dumps(storage.CARTERA_VACIA))
    entries = with_portfolio(profiles()["lista"])
    cfg["titular"] = "Todos juntos"
    for per in entries:
        c = read_json(os.path.join(directory(per["id"]), "cartera.json"), {}) or {}
        if per["id"] == DEFAULT_PROFILE:
            cfg["hitos"] = c.get("hitos") or cfg["hitos"]
            cfg["objetivo"] = c.get("objetivo") or cfg["objetivo"]
        pre = per["id"] + "__"
        for x in c.get("productos", []):
            corto = x.get("corto") or x.get("nombre") or x["id"]
            cfg["productos"].append({**x, "id": pre + x["id"], "nombre": f"{x.get('nombre') or corto} ({per['nombre']})",
                                     "corto": f"{corto[:18]} · {per['nombre'][:8]}", "perfil": per["nombre"]})
        for m in c.get("movimientos", []):
            new_entry = {**m, "id": pre + str(m.get("id")), "producto": pre + str(m.get("producto"))}
            if m.get("destino"):
                new_entry["destino"] = pre + str(m["destino"])
            cfg["movimientos"].append(new_entry)
        for v in c.get("valoraciones", []):
            cfg["valoraciones"].append({**v, "id": pre + str(v.get("id")), "producto": pre + str(v.get("producto"))})
    cfg["movimientos"].sort(key=lambda m: m["fecha"])
    return cfg


def mode():
    if profiles()["activo"] == ALL_PROFILES:
        return "todos"
    return "propio" if os.path.exists(os.path.join(directory(), "cartera.json")) else "demo"


def portfolio():
    m = mode()
    if m == "todos":
        return combined_portfolio()
    return read_json(os.path.join(directory(), "cartera.json") if m == "propio" else DEMO, {})


def dashboard_path():
    return os.path.join(directory(), f"calculado_{mode()}.json")


def state():
    return read_json(os.path.join(DATA_DIR, "estado.json"), {})


def recalculate(fetch_prices):
    """Update the dashboard cache, optionally fetching missing or stale prices."""
    with lock:
        data = engine.build_dashboard(portfolio(), directory(), fetch_prices=fetch_prices, cache=os.path.join(DATA_DIR, "cache"),
                                historico=mode() != "todos")
        est = state()
        if fetch_prices is True:
            est["preciosActualizados"] = dt.datetime.now().replace(microsecond=0).isoformat()
            est["versionCache"] = VERSION_CACHE
            write_json(os.path.join(DATA_DIR, "estado.json"), est)
        if data is not None:
            data["modo"] = mode()
            data["preciosActualizados"] = est.get("preciosActualizados")
        write_json(dashboard_path(), data)
        return data


def stale_prices():
    ultima = state().get("preciosActualizados")
    if not ultima or not os.path.exists(dashboard_path()) or state().get("versionCache") != VERSION_CACHE:
        return True
    return dt.datetime.now() - dt.datetime.fromisoformat(ultima) > dt.timedelta(hours=HORAS_PRECIOS)


@app.get("/")
def home():
    return send_from_directory(WEB, "index.html")


@app.get("/datos.js")
def dashboard_js():
    data = read_json(dashboard_path())
    if data is None and not os.path.exists(dashboard_path()):
        data = recalculate(fetch_prices=False)
    elif mode() == "demo" and os.path.getmtime(DEMO) > os.path.getmtime(dashboard_path()):
        data = recalculate(fetch_prices=False)
    cuerpo = ("window.DATOS = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
              + "window.PERFILES = " + json.dumps(profile_info(), ensure_ascii=False) + ";\n")
    return Response(cuerpo, mimetype="application/javascript",
                    headers={"Cache-Control": "no-store"})


@app.post("/api/actualizar")
def api_refresh():
    try:
        data = recalculate(fetch_prices=True)
    except Exception as e:
        logging.exception("Fallo al actualizar")
        return jsonify(ok=False, error=f"No he podido actualizar: {e}"), 500
    return jsonify(ok=True, avisos=(data or {}).get("avisos", []))


@app.get("/api/cartera")
def api_portfolio():
    return jsonify(modo=mode(), cartera=portfolio(), tipos=engine.PRODUCT_TYPES, fuentes=engine.PRICE_SOURCES,
                   tiposMovimiento=storage.TIPOS_MOV)


@app.get("/api/buscar")
def api_search():
    n = len(search.FETCH_FAILURES)
    res = search.search(request.args.get("q", ""))
    return jsonify(resultados=res, sinConexion=(not res and bool(search.fetch_error_since(n))))


SAVE_HANDLERS = {"productos": storage.save_product, "movimientos": storage.save_movement,
           "valoraciones": storage.save_valuation}
DELETE_HANDLERS = {"productos": storage.delete_product, "movimientos": storage.delete_movement,
          "valoraciones": storage.delete_valuation}
AVISO_DEMO = ("Estás viendo la cartera de ejemplo. Pulsa «Empezar con mis datos» "
              "para crear la tuya y poder guardar cambios.")
AVISO_TODOS = ("Estás viendo «Todos juntos», que solo sirve para mirar. Elige un perfil arriba "
               "para cambiar sus datos.")


def write_blocked():
    m = mode()
    if m == "demo":
        return jsonify(ok=False, errores=[AVISO_DEMO]), 403
    if m == "todos":
        return jsonify(ok=False, errores=[AVISO_TODOS]), 403
    return None


def update_portfolio(fn):
    if write_blocked():
        return write_blocked()
    with lock:
        path = os.path.join(directory(), "cartera.json")
        cfg = storage.load(path)
        try:
            item = fn(cfg)
        except storage.ValidationError as e:
            return jsonify(ok=False, errores=e.errors), 400
        storage.save(path, cfg)
        data = recalculate(fetch_prices="faltan")
    fetch_missing_exposures()
    return jsonify(ok=True, item=item, cartera=cfg, avisos=(data or {}).get("avisos", []))


_IN_FLIGHT = threading.Lock()


def fetch_missing_exposures(esperar=False):
    """Fetch missing exposure data in the background without blocking the dashboard."""
    from . import exposure
    base = DATA_DIR
    cache = os.path.join(base, "cache")

    def without_fetching(p):
        k = exposure.key(p)
        return k and not p.get("exposicion") and not os.path.exists(
            os.path.join(cache, "EXPO_" + re.sub(r"[^A-Za-z0-9]", "_", k) + ".json"))
    try:
        missing = [p for p in portfolio().get("productos", []) if without_fetching(p)]
    except Exception:
        return
    if not missing:
        return

    def worker():
        if not _IN_FLIGHT.acquire(blocking=False):
            return
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=4) as ex:
                llegados = [r for r in ex.map(lambda p: exposure.product_exposure(p, cache, network=True), missing) if r]
            if llegados and DATA_DIR == base:
                recalculate(fetch_prices=False)
        except Exception:
            logging.exception("No he podido completar el reparto por países")
        finally:
            _IN_FLIGHT.release()
    if esperar:
        worker()
    else:
        threading.Thread(target=worker, daemon=True).start()


def exchange_rate_on(currency, iso_date):
    fx = engine.value_at(engine.exchange_rate_series(currency, DATA_DIR), iso_date, margen=6)
    if not fx:
        fx = engine.value_at(engine.exchange_rate_series(currency, DATA_DIR, refresh=True), iso_date, margen=6)
    return fx


def movement_in_eur(data):
    """Convert the amount to euros using the transaction date and record the original amount in the note."""
    currency = str(data.get("moneda") or "EUR").strip().upper()
    if currency in ("EUR", ""):
        return data
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise storage.ValidationError([f"La moneda «{currency}» no es válida."])
    errors = []
    f = storage.date(data.get("fecha"), errors)
    amount = storage.number(data.get("importe"), "el importe", errors, mayor_que=0)
    fee = storage.number(data.get("comision"), "la comisión", errors, obligatorio=False, minimo=0)
    if errors:
        raise storage.ValidationError(errors)
    fx = exchange_rate_on(currency, f)
    if not fx:
        raise storage.ValidationError([f"No encuentro el cambio de {currency} a euros del {storage.format_date(f)}. "
                                       "Comprueba tu conexión a internet o escribe el importe en euros."])
    original = f"{storage.format_number(amount)} {currency} (1 {currency} = {storage.format_number(fx)} €)"
    note = storage.text(data.get("nota"))
    return {**data, "importe": round(amount * fx, 2), "comision": round(fee * fx, 2) if fee else None,
            "nota": (note + " · " if note else "") + original}


@app.get("/api/cambio")
def api_exchange_rate():
    currency = (request.args.get("moneda") or "").upper()
    date = request.args.get("fecha") or dt.date.today().isoformat()
    if not re.fullmatch(r"[A-Z]{3}", currency) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return jsonify(ok=False), 400
    with lock:
        fx = 1.0 if currency == "EUR" else exchange_rate_on(currency, date)
    return jsonify(ok=bool(fx), cambio=fx)


@app.post("/api/<collection>")
def api_save(collection):
    if collection not in SAVE_HANDLERS:
        return jsonify(ok=False, errores=["No sé guardar eso."]), 404
    data = request.get_json(silent=True) or {}

    def fn(cfg):
        if collection == "movimientos":
            return SAVE_HANDLERS[collection](cfg, movement_in_eur(data))
        if collection != "productos":
            return SAVE_HANDLERS[collection](cfg, data)
        prod, cambio = storage.save_product(cfg, data)
        if cambio and prod["fuente"] != "manual" and not search.probe_price(prod["fuente"], prod["codigo"]):
            raise storage.ValidationError([
                f"No encuentro precio para «{prod['codigo']}» en {engine.PRICE_SOURCES[prod['fuente']]}. "
                "Revisa el código con el buscador o elige «a mano» y anota tú su valor."])
        return prod
    return update_portfolio(fn)


@app.delete("/api/<collection>/<identifier>")
def api_delete(collection, identifier):
    if collection not in DELETE_HANDLERS:
        return jsonify(ok=False, errores=["No sé borrar eso."]), 404
    return update_portfolio(lambda cfg: DELETE_HANDLERS[collection](cfg, identifier))


@app.post("/api/objetivo")
def api_goal():
    data = request.get_json(silent=True) or {}
    return update_portfolio(lambda cfg: storage.save_goal(cfg, data))


@app.post("/api/colchon")
def api_emergency_fund():
    data = request.get_json(silent=True) or {}
    return update_portfolio(lambda cfg: storage.save_emergency_fund(cfg, data))


@app.post("/api/reparto")
def api_allocation():
    data = request.get_json(silent=True) or {}
    return update_portfolio(lambda cfg: storage.save_allocation(cfg, data))


@app.get("/api/unidades")
def api_units():
    pid, date = request.args.get("producto") or "", request.args.get("fecha") or dt.date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return jsonify(ok=False), 400
    cfg = portfolio()
    if not storage.product(cfg, pid):
        return jsonify(ok=False, errores=["Ese producto ya no existe."]), 404
    return jsonify(ok=True, unidades=round(storage.units_at(cfg, pid, date, exclude=request.args.get("excluir")), 8))


def _contribution_prices(cfg, data):
    p = storage.product(cfg, str(data.get("producto") or ""))
    if not p or p.get("fuente") == "manual":
        return {}
    return engine.product_price_series(p, DATA_DIR)


@app.post("/api/periodicas/ver")
def api_preview_contributions():
    if write_blocked():
        return write_blocked()
    data = request.get_json(silent=True) or {}
    with lock:
        cfg = portfolio()
        try:
            return jsonify(ok=True, plan=recurring.preview_plan(cfg, data, _contribution_prices(cfg, data)))
        except storage.ValidationError as e:
            return jsonify(ok=False, errores=e.errors), 400


@app.post("/api/periodicas/crear")
def api_create_contributions():
    data = request.get_json(silent=True) or {}
    return update_portfolio(lambda cfg: recurring.create(cfg, data, _contribution_prices(cfg, data)))


@app.post("/api/periodicas/olvidar")
def api_forget_contributions():
    data = request.get_json(silent=True) or {}
    return update_portfolio(lambda cfg: recurring.forget(cfg, data))


@app.get("/api/fiscal")
def api_tax():
    if mode() == "todos":
        return jsonify(ok=False, errores=["La declaración es de cada persona: elige un perfil arriba."]), 400
    year = request.args.get("ano") or None
    if year is not None and not re.fullmatch(r"\d{4}", year):
        return jsonify(ok=False, errores=["Año no válido."]), 400
    with lock:
        inf = tax.report(portfolio(), year)
    return jsonify(ok=True, csv=tax.report_csv(inf), **inf)


@app.get("/api/precio")
def api_price():
    pid, date = request.args.get("producto") or "", request.args.get("fecha") or dt.date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return jsonify(ok=False), 400
    p = storage.product(portfolio(), pid)
    if not p or p.get("fuente") == "manual":
        return jsonify(ok=False)
    with lock:
        price_series = engine.product_price_series(p, DATA_DIR)
    price, as_of = engine.value_at(price_series, date, margen=7), engine.date_at(price_series, date, margen=7)
    return jsonify(ok=bool(price), precio=price, fecha=as_of)


@app.post("/api/repartir-colores")
def api_assign_colors():
    calc = read_json(dashboard_path()) or {}
    grandes = [p["id"] for p in sorted(calc.get("productos", []) + calc.get("otrosActivos", []),
                                       key=lambda p: -(p.get("valor") or 0))]
    return update_portfolio(lambda cfg: storage.assign_colors(cfg, grandes))


@app.post("/api/empezar")
def api_initialize():
    if mode() != "demo":
        return jsonify(ok=False, errores=["Ya tienes tu propia cartera."]), 400
    with lock:
        if (request.get_json(silent=True) or {}).get("desde") == "ejemplo":
            cfg = dict(read_json(DEMO, {}), titular="Mi patrimonio (copia del ejemplo)")
        else:
            cfg = json.loads(json.dumps(storage.CARTERA_VACIA))
        storage.save(os.path.join(directory(), "cartera.json"), cfg)
        recalculate(fetch_prices="faltan")
    return jsonify(ok=True)


PLANES = {}


@app.post("/api/importar/previsualizar")
def api_preview_import():
    if write_blocked():
        return write_blocked()
    source = request.form.get("origen")
    files = [(f.filename, f.read()) for f in request.files.getlist("archivos") if f.filename]
    text = (request.form.get("texto") or "").strip()
    with lock:
        cfg = storage.load(os.path.join(directory(), "cartera.json"))
        if source == "myinvestor":
            if not files:
                return jsonify(ok=False, errores=["Elige los archivos CSV que has descargado de MyInvestor."]), 400
            preview_plan = imports.prepare_myinvestor(cfg, files, DATA_DIR)
        else:
            if not files and not text:
                return jsonify(ok=False, errores=["Elige un archivo o pega el texto que te ha dado la IA."]), 400
            rows, error = [], None
            for name, content in files or [("pegado.csv", text)]:
                leidas, error = imports.read_table(name, content)
                if error:
                    return jsonify(ok=False, errores=[f"{name}: {error}" if files else error]), 400
                rows += leidas
            preview_plan = imports.prepare_table(cfg, rows, DATA_DIR)
        report = imports.preview(cfg, preview_plan, None, DATA_DIR)
    token = secrets.token_hex(8)
    PLANES.clear()
    PLANES[token] = preview_plan
    return jsonify(ok=True, token=token, informe=report)


def _transfer_answers(data):
    r = data.get("respuestas")
    if not isinstance(r, dict):
        return {}
    return {str(k)[:80]: {"origen": str(v.get("origen") or "")[:80], "fecha": str(v.get("fecha") or "")[:10],
                          **({"fechas": [str(f or "")[:10] for f in v["fechas"][:60]]}
                             if isinstance(v.get("fechas"), list) else {})}
            for k, v in r.items() if isinstance(v, dict)}


@app.post("/api/importar/revisar")
def api_revise_import():
    if write_blocked():
        return write_blocked()
    data = request.get_json(silent=True) or {}
    preview_plan = PLANES.get(data.get("token"))
    if preview_plan is None:
        return jsonify(ok=False, errores=["Esa vista previa ya no vale: vuelve a revisar el archivo."]), 400
    with lock:
        cfg = storage.load(os.path.join(directory(), "cartera.json"))
        report = imports.preview(cfg, preview_plan, _transfer_answers(data), DATA_DIR)
    return jsonify(ok=True, token=data.get("token"), informe=report)


@app.post("/api/importar/confirmar")
def api_confirm_import():
    request_data = request.get_json(silent=True) or {}
    preview_plan = PLANES.pop(request_data.get("token"), None)
    if preview_plan is None:
        return jsonify(ok=False, errores=["Esa vista previa ya no vale: vuelve a revisar el archivo."]), 400
    report = {}
    answers = _transfer_answers(request_data)

    def fn(cfg):
        report.update(imports.apply(cfg, preview_plan, answers, DATA_DIR))
        return None
    answer = update_portfolio(fn)
    if isinstance(answer, tuple):
        return answer
    data = answer.get_json()
    data["informe"] = {k: report[k] for k in ("añadidos", "repetidos", "saldos", "sustituidos")}
    data["informe"]["traspasos"] = sum(1 for t in report.get("traspasosMyInvestor", []) if t["hecho"])
    return jsonify(data)


@app.get("/api/plantilla.xlsx")
def api_xlsx_template():
    return Response(spreadsheet.workbook(), headers={"Content-Disposition": 'attachment; filename="plantilla_patrimonio.xlsx"'},
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/plantilla.csv")
def api_csv_template():
    return Response(spreadsheet.empty_csv(), mimetype="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="plantilla_patrimonio.csv"'})


@app.get("/api/exportar-excel")
def api_export_workbook():
    name = f"finappgo_mis_datos_{dt.date.today().isoformat()}.xlsx"
    return Response(spreadsheet.portfolio_workbook(portfolio()),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/prompt")
def api_prompt():
    with open(os.path.join(ROOT, "app", "import-prompt.es.txt"), encoding="utf-8") as f:
        return jsonify(texto=f.read())


def backups_path():
    return os.path.join(directory(), "copias")


ID_OK = re.compile(r"[A-Za-z0-9_.\-]{1,80}")
VALID_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def validate_backup(cfg):
    """Validate each part of the portfolio before replacing active data."""
    malo = storage.ValidationError(["Ese archivo no es una copia de seguridad de esta app (o está dañado)."])
    if not isinstance(cfg, dict) or not all(isinstance(cfg.get(k), list)
                                            for k in ("productos", "movimientos", "valoraciones")):
        raise malo
    number = lambda x: x is None or (isinstance(x, (int, float)) and not isinstance(x, bool))
    ids = set()
    for p in cfg["productos"]:
        if not isinstance(p, dict) or not ID_OK.fullmatch(str(p.get("id") or "")) \
                or not isinstance(p.get("nombre", ""), str):
            raise malo
        ids.add(p["id"])
    for m in cfg["movimientos"]:
        if not isinstance(m, dict) or not VALID_DATE.fullmatch(str(m.get("fecha") or "")) \
                or m.get("producto") not in ids or (m.get("destino") is not None and m["destino"] not in ids) \
                or not all(number(m.get(k)) for k in ("importe", "unidades", "unidadesDestino", "comision")):
            raise malo
    for v in cfg["valoraciones"]:
        if not isinstance(v, dict) or not VALID_DATE.fullmatch(str(v.get("fecha") or "")) \
                or v.get("producto") not in ids or not number(v.get("valor")) or not number(v.get("aportado")):
            raise malo
    return cfg


def restore(cfg):
    with lock:
        storage.save(os.path.join(directory(), "cartera.json"), cfg)
        for old in ("calculado_propio.json", "historico.json"):
            if os.path.exists(os.path.join(directory(), old)):
                os.remove(os.path.join(directory(), old))
        recalculate(fetch_prices="faltan")


@app.get("/api/copias")
def api_backups():
    entries = []
    if mode() != "todos" and os.path.isdir(backups_path()):
        for n in os.listdir(backups_path()):
            if not n.endswith(".json"):
                continue
            path = os.path.join(backups_path(), n)
            cfg = read_json(path, {}) or {}
            entries.append({"archivo": n,
                          "fecha": dt.datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="minutes"),
                          "motivo": "Antes de empezar de nuevo" if n.startswith("antes_de_reiniciar")
                          else "Antes de recuperar una copia" if n.startswith("antes_de_recuperar")
                          else "Automática",
                          "productos": len(cfg.get("productos", [])),
                          "movimientos": len(cfg.get("movimientos", []))})
    entries.sort(key=lambda c: c["fecha"], reverse=True)
    return jsonify(copias=entries)


@app.get("/api/copia/descargar")
def api_download_backup():
    if mode() != "propio":
        return jsonify(ok=False, errores=["Todavía no tienes una cartera propia que guardar."]), 400
    with open(os.path.join(directory(), "cartera.json"), "rb") as f:
        content = f.read()
    name = f"copia_patrimonio_{dt.date.today().isoformat()}.json"
    return Response(content, mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/copia/subir")
def api_upload_backup():
    if mode() == "todos":
        return write_blocked()
    f = request.files.get("archivo")
    if not f:
        return jsonify(ok=False, errores=["Elige el archivo de la copia (termina en .json)."]), 400
    try:
        cfg = validate_backup(json.loads(imports.decode(f.read())))
    except ValueError:
        return jsonify(ok=False, errores=["Ese archivo no es una copia de seguridad de esta app."]), 400
    except storage.ValidationError as e:
        return jsonify(ok=False, errores=e.errors), 400
    restore(cfg)
    return jsonify(ok=True)


@app.post("/api/copia/recuperar")
def api_recover_backup():
    if mode() == "todos":
        return write_blocked()
    name = os.path.basename((request.get_json(silent=True) or {}).get("archivo") or "")
    path = os.path.join(backups_path(), name)
    if not name.endswith(".json") or not os.path.exists(path):
        return jsonify(ok=False, errores=["Esa copia ya no existe."]), 400
    try:
        cfg = validate_backup(read_json(path))
    except storage.ValidationError as e:
        return jsonify(ok=False, errores=e.errors), 400
    if mode() == "propio":
        sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        with open(os.path.join(directory(), "cartera.json"), "rb") as a, \
                open(os.path.join(backups_path(), f"antes_de_recuperar_{sello}.json"), "wb") as b:
            b.write(a.read())
    restore(cfg)
    return jsonify(ok=True)


@app.get("/api/exportar-web")
def api_export_html():
    data = read_json(dashboard_path())
    if not data:
        return jsonify(ok=False, errores=["Todavía no hay nada que exportar."]), 400
    redact_amounts = request.args.get("ocultar") == "1"
    html = export.render_page(WEB, data, redact_amounts=redact_amounts, title=data.get("titular") or "Mi patrimonio")
    name = "patrimonio_sin_importes.html" if redact_amounts else "patrimonio.html"
    return Response(html.encode("utf-8"), mimetype="text/html",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


REPO = "https://github.com/sersango/finappgo"
_VERSION = {}


def current_version():
    with open(os.path.join(ROOT, "app", "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


@app.get("/api/version")
def api_version():
    """Check the published version at most once per day."""
    current = current_version()
    if not _VERSION or dt.datetime.now() - _VERSION["cuando"] > dt.timedelta(hours=24):
        try:
            url = REPO.replace("github.com", "raw.githubusercontent.com") + "/main/app/VERSION"
            with network.open_url(url, engine.UA, timeout=5) as r:
                _VERSION.update(ultima=r.read().decode().strip(), cuando=dt.datetime.now())
        except Exception:
            _VERSION.update(ultima=None, cuando=dt.datetime.now())
    ultima = _VERSION.get("ultima")
    return jsonify(actual=current, ultima=ultima, repo=REPO, docker=in_docker(),
                   hayNueva=bool(ultima) and as_tuple(ultima) > as_tuple(current))


def as_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


_RELEASE_NOTES_CACHE = {}
VIDEO_OK = re.compile(r"^https://(www\.)?(youtube\.com|youtu\.be)/[A-Za-z0-9_\-?=&/.%]+$")


def validate_release_notes(n):
    if not isinstance(n, dict) or not re.fullmatch(r"\d+\.\d+\.\d+", str(n.get("version") or "")):
        return None
    puntos = [engine.strip_html(x)[:300] for x in (n.get("novedades") or []) if isinstance(x, str)][:15]
    video = n.get("video") if isinstance(n.get("video"), str) and VIDEO_OK.match(n["video"]) else None
    return {"version": n["version"], "titulo": engine.strip_html(str(n.get("titulo") or ""))[:120],
            "novedades": puntos, "video": video}


@app.get("/api/novedades")
def api_release_notes():
    local = validate_release_notes(read_json(os.path.join(ROOT, "app", "release-notes.es.json")))
    if not _RELEASE_NOTES_CACHE or dt.datetime.now() - _RELEASE_NOTES_CACHE["cuando"] > dt.timedelta(hours=24):
        remote = None
        try:
            url = REPO.replace("github.com", "raw.githubusercontent.com") + "/main/app/release-notes.es.json"
            with network.open_url(url, engine.UA, timeout=5) as r:
                remote = validate_release_notes(json.loads(r.read().decode("utf-8")))
        except Exception:
            pass
        _RELEASE_NOTES_CACHE.update(remota=remote, cuando=dt.datetime.now())
    remote, current = _RELEASE_NOTES_CACHE.get("remota"), current_version()
    installed = local if local and local["version"] == current else None
    if installed and remote and remote["version"] == current and remote.get("video"):
        installed = dict(installed, video=remote["video"])
    nueva = remote if remote and as_tuple(remote["version"]) > as_tuple(current) else None
    return jsonify(actual=current, tuya=installed, nueva=nueva, repo=REPO, docker=in_docker())


@app.post("/api/reiniciar")
def api_reset():
    if mode() != "propio":
        return jsonify(ok=False, errores=["Ahora mismo no tienes ninguna cartera propia."]), 400
    a = (request.get_json(silent=True) or {}).get("a")
    if profiles()["activo"] != DEFAULT_PROFILE:
        a = "vacia"
    with lock:
        path = os.path.join(directory(), "cartera.json")
        backups = os.path.join(directory(), "copias")
        os.makedirs(backups, exist_ok=True)
        sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        os.replace(path, os.path.join(backups, f"antes_de_reiniciar_{sello}.json"))
        for old in ("calculado_propio.json", "historico.json"):
            if os.path.exists(os.path.join(directory(), old)):
                os.remove(os.path.join(directory(), old))
        if a == "vacia":
            storage.save(path, json.loads(json.dumps(storage.CARTERA_VACIA)))
        recalculate(fetch_prices="faltan")
    return jsonify(ok=True)


def profile_info():
    d = profiles()
    exists = {x["id"] for x in with_portfolio(d["lista"])}
    return {"activo": d["activo"], "todos": len(exists) >= 2,
            "lista": [{**x, "conDatos": x["id"] in exists} for x in d["lista"]]}


@app.get("/api/perfiles")
def api_profiles():
    return jsonify(ok=True, **profile_info())


@app.post("/api/perfiles")
def api_create_profile():
    name = storage.text((request.get_json(silent=True) or {}).get("nombre"), 40)
    if not name:
        return jsonify(ok=False, errores=["Ponle un nombre al perfil (por ejemplo, el de tu pareja)."]), 400
    with lock:
        d = profiles()
        if any(x["nombre"].lower() == name.lower() for x in d["lista"]):
            return jsonify(ok=False, errores=[f"Ya tienes un perfil que se llama «{name}»."]), 400
        pid = storage.slug(name, {x["id"] for x in d["lista"]} | {DEFAULT_PROFILE, ALL_PROFILES})
        cfg = json.loads(json.dumps(storage.CARTERA_VACIA))
        cfg["titular"] = name
        os.makedirs(directory(pid), exist_ok=True)
        storage.save(os.path.join(directory(pid), "cartera.json"), cfg)
        d["lista"].append({"id": pid, "nombre": name})
        d["activo"] = pid
        save_profiles(d)
    return jsonify(ok=True, id=pid)


@app.post("/api/perfiles/activar")
def api_activate_profile():
    pid = (request.get_json(silent=True) or {}).get("id")
    with lock:
        d = profiles()
        if pid != ALL_PROFILES and not any(x["id"] == pid for x in d["lista"]):
            return jsonify(ok=False, errores=["Ese perfil ya no existe."]), 404
        if pid == ALL_PROFILES and len(with_portfolio(d["lista"])) < 2:
            return jsonify(ok=False, errores=["«Todos juntos» necesita al menos dos perfiles con datos."]), 400
        d["activo"] = pid
        save_profiles(d)
        recalculate(fetch_prices="faltan")
    return jsonify(ok=True)


@app.post("/api/perfiles/renombrar")
def api_rename_profile():
    data = request.get_json(silent=True) or {}
    name = storage.text(data.get("nombre"), 40)
    with lock:
        d = profiles()
        per = next((x for x in d["lista"] if x["id"] == data.get("id")), None)
        if not per:
            return jsonify(ok=False, errores=["Ese perfil ya no existe."]), 404
        if not name:
            return jsonify(ok=False, errores=["Ponle un nombre al perfil."]), 400
        per["nombre"] = name
        save_profiles(d)
    return jsonify(ok=True)


@app.post("/api/perfiles/borrar")
def api_delete_profile():
    """Archive the profile directory before removing it from the profile list."""
    pid = (request.get_json(silent=True) or {}).get("id")
    with lock:
        d = profiles()
        if pid == DEFAULT_PROFILE or not any(x["id"] == pid for x in d["lista"]):
            return jsonify(ok=False, errores=["Ese perfil no se puede borrar."]), 400
        source = directory(pid)
        if os.path.isdir(source):
            destination = os.path.join(DATA_DIR, "copias", f"perfil_borrado_{pid}_{dt.datetime.now():%Y%m%d_%H%M%S}")
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            os.replace(source, destination)
        d["lista"] = [x for x in d["lista"] if x["id"] != pid]
        if d["activo"] in (pid, ALL_PROFILES):
            d["activo"] = DEFAULT_PROFILE
        save_profiles(d)
        recalculate(fetch_prices="faltan")
    return jsonify(ok=True)


ERRORS = []


class _ErrorLogHandler(logging.Handler):
    def emit(self, registro):
        text = self.format(registro)
        ERRORS.append(f"{dt.datetime.now():%Y-%m-%d %H:%M} {text}"[-1500:])
        del ERRORS[:-5]


_log_handler = _ErrorLogHandler(level=logging.ERROR)
_log_handler.setFormatter(logging.Formatter("%(message)s\n%(exc_text)s"))
logging.getLogger().addHandler(_log_handler)
app.logger.addHandler(_log_handler)


@app.get("/api/diagnostico")
def api_diagnostics():
    """Return diagnostic information without portfolio amounts or instrument names."""
    import platform
    calc = read_json(dashboard_path()) or {}
    cfg = portfolio()
    kinds = {}
    for p in cfg.get("productos", []):
        key = f"{p.get('tipo')}/{p.get('fuente')}"
        kinds[key] = kinds.get(key, 0) + 1
    text = "\n".join([
        f"FinAppGo {current_version()} · {platform.system()} {platform.release()} ({platform.machine()}) · Python {platform.python_version()}",
        f"Modo: {mode()} · perfiles: {len(profiles()['lista'])} · productos: {len(cfg.get('productos', []))} {kinds}"
        f" · movimientos: {len(cfg.get('movimientos', []))} · valores anotados: {len(cfg.get('valoraciones', []))}",
        f"Precios actualizados: {state().get('preciosActualizados') or 'nunca'} · datos a {calc.get('fechaExtracto') or '—'}",
        f"Avisos en el panel: {len(calc.get('avisos') or [])}",
        "Últimos errores:" + ("\n" + "\n".join(ERRORS) if ERRORS else " ninguno"),
    ])
    return jsonify(ok=True, texto=text)


@app.get("/api/ping")
def api_ping():
    return jsonify(app="patrimonio")


@app.get("/<path:file>")
def static_files(file):
    return send_from_directory(WEB, file)


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return json.load(r).get("app") == "patrimonio"
    except Exception:
        return False


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    if already_running(PORT):
        print("FinAppGo is already running.")
        if not os.environ.get("PATRIMONIO_NO_ABRIR"):
            webbrowser.open(access_url(PORT))
        return

    print("\n  FinAppGo")
    print("  " + "-" * 40)
    if mode() == "demo":
        print("  Demo mode.")
    stale = stale_prices()
    if stale:
        print("  Refreshing prices...")
    try:
        recalculate(fetch_prices=stale or "faltan")
        fetch_missing_exposures()
    except Exception as e:
        print(f"\n  [!] Price refresh failed: {e}")
        print("      Using cached data.")

    srv = None
    host = bind_address()
    for port in (range(PORT, PORT + 10) if not on_network() else [PORT]):
        try:
            srv = make_server(host, port, app, threaded=True)
            break
        except OSError:
            continue
    if srv is None:
        print("  [!] No available port.")
        return
    url = f"http://127.0.0.1:{srv.server_port}/"
    if on_network():
        print(f"\n  FinAppGo is listening on your network (port {srv.server_port}).")
        print("  Open the following access link from a browser on your network.")
        print("  Replace NAS-IP with the address of the host.")
        print(f"\n      http://NAS-IP:{srv.server_port}/?acceso={access_token()}\n")
        print("  The access key is stored in .acceso in the data directory.")
    else:
        if not os.environ.get("PATRIMONIO_NO_ABRIR"):
            threading.Timer(0.8, webbrowser.open, [access_url(srv.server_port)]).start()
        print(f"\n  FinAppGo is running at {url}")
        print(f"  Access link: {access_url(srv.server_port)}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

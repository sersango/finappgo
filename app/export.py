"""Export the dashboard as a standalone HTML document."""

import base64
import datetime as dt
import html as html_
import json
import os
import random
import re

CAMPOS_DINERO = {
    "valor", "aportado", "plusvalia", "serie", "serieAportado", "importe", "valorExtracto",
    "realizado", "participaciones", "titulos", "valorConCoste", "patrimonio", "ritmoMensual",
    "anual", "base", "compraventaPagada", "inicio", "fin", "mercado", "nuevo",
    "comision", "min", "max", "mediana", "p33", "p67", "snapshots", "flujos", "tuya", "tuValor",
    "coste", "unidades", "gastoMensual", "cobros", "costeVendido", "gananciaTotal", "alquiler", "intereses",
}


def _scale(x, k):
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, (int, float)):
        return round(x * k, 2)
    if isinstance(x, list):
        return [_scale(v, k) for v in x]
    if isinstance(x, dict):
        return {c: _scale(v, k) for c, v in x.items()}
    return x


def _anonymize(node, k):
    if isinstance(node, list):
        return [_anonymize(v, k) for v in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for c, v in node.items():
        if c in CAMPOS_DINERO:
            out[c] = _scale(v, k)
        elif c in ("hitos", "objetivo", "precioMedio"):
            continue
        else:
            out[c] = _anonymize(v, k)
    return out


def hide_amounts(data):
    """Scale monetary values before exporting a dashboard with amounts hidden."""
    k = random.uniform(0.37, 2.9)
    out = _anonymize(data, k)
    am = out.get("aportacionesMensuales") or {}
    for c in ("total", "porProducto"):
        if c in am:
            am[c] = _scale(am[c], k)
    dv = out.get("dividendos")
    if dv:
        dv["total"], dv["ultimos12"] = _scale(dv["total"], k), _scale(dv["ultimos12"], k)
        dv["porAno"] = [[a, _scale(v, k)] for a, v in dv["porAno"]]
        for line in dv["porProducto"]:
            line["total"], line["ultimos12"] = _scale(line["total"], k), _scale(line["ultimos12"], k)
    out["total"]["hitos"] = []
    out["objetivo"] = None
    if out.get("vivo"):
        out["vivo"]["titulos"] = round(data["vivo"]["titulos"] * k, 6)
    return out


def render_page(web, data, redact_amounts=False, title="Mi patrimonio"):
    def read(name):
        with open(os.path.join(web, name), encoding="utf-8") as f:
            return f.read()

    if redact_amounts:
        data = hide_amounts(data)
    data = dict(data, modo="estatico", avisos=[])
    html = read("index.html")

    html = re.sub(r'\s*<button class="btn" id="btnPrecios".*?</button>', "", html, flags=re.S)
    html = re.sub(r'\s*<button data-tab="datos".*?</button>', "", html, flags=re.S)
    html = re.sub(r'\s*<button data-tab="ayuda".*?</button>', "", html, flags=re.S)
    html = re.sub(r'<div class="banner" id="bannerDemo".*?</div>', "", html, flags=re.S)
    html = re.sub(r'<div class="panel" id="tab-datos".*?</div></div>', "", html, flags=re.S)
    html = re.sub(r'<div class="panel" id="tab-ayuda".*?<!-- /help -->', "", html, flags=re.S)
    html = re.sub(r'<div class="banner" id="bannerVersion".*?</div>', "", html, flags=re.S)

    previous_value = "window.ESTATICO = true;\n"
    if redact_amounts:
        previous_value += "window.OCULTAR_IMPORTES = true;\n"
    portions = [previous_value + "window.DATOS = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";"]
    portions += [read(n) for n in ("channel.js", "charts.js", "calculations.js", "app.js")]
    scripts = "\n".join("<script>\n" + t.replace("</script>", "<\\/script>") + "\n</script>" for t in portions)
    html, n = re.subn(r'<script id="script-loader">.*?</script>', lambda m: scripts, html, flags=re.S)
    if not n:
        raise RuntimeError("Missing script loader in index.html.")

    with open(os.path.join(web, "icon-64.png"), "rb") as f:
        icono = "data:image/png;base64," + base64.b64encode(f.read()).decode()
    html = html.replace('src="icon-64.png"', f'src="{icono}"')
    html = re.sub(r'\s*<link rel="(icon|apple-touch-icon)"[^>]*>', "", html)
    desc = "Panel de patrimonio neto e inversiones hecho con FinAppGo." + (" Importes ocultos." if redact_amounts else "")
    title = html_.escape(str(title), quote=True)
    headers = ('<meta name="robots" content="noindex, nofollow">\n'
                 f'<link rel="icon" type="image/png" href="{icono}">\n'
                 f'<meta property="og:title" content="{title} · FinAppGo">\n'
                 f'<meta property="og:description" content="{desc}">\n'
                 f'<meta name="description" content="{desc}">\n'
                 f'<!-- Exportado el {dt.datetime.now():%d/%m/%Y %H:%M} -->')
    html = html.replace("</head>", headers + "\n</head>", 1)
    return html

"""Resolve exposure by asset, sector, and country through Morningstar."""

import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request

from . import network
from .engine import UA, strip_html

CADUCA_DIAS = 30
BUSCA = "https://lt.morningstar.com/api/rest.svc/klr5zyak8x/security/screener?"
DETALLE = ("https://lt.morningstar.com/api/rest.svc/klr5zyak8x/security_details/{}?viewId=MFsnapshot"
           "&idtype=msid&responseViewFormat=json&languageId=es-ES&currencyId=EUR")
SAL = "https://api-global.morningstar.com/sal-service/v1/fund/{}/{}/data"
SAL_QS = "?languageId=es-ES&locale=es-ES&clientId=MDC&benchmarkId=category&component=sal-mip-{}&version=4.69.0"
SAL_CAB = {"apikey": "lstzFDEOhfFNMLikKa0am9mgEKLBl49T", "Origin": "https://www.morningstar.com",
           "Referer": "https://www.morningstar.com/"}
ES_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")

SECTORS = {"101": "Materiales", "102": "Consumo discrecional", "103": "Financiero", "104": "Inmobiliario",
            "205": "Consumo básico", "206": "Salud", "207": "Utilities", "308": "Comunicaciones",
            "309": "Energía", "310": "Industrial", "311": "Tecnología"}
SECTORES_SAL = {"basicMaterials": "101", "consumerCyclical": "102", "financialServices": "103", "realEstate": "104",
                "consumerDefensive": "205", "healthcare": "206", "utilities": "207",
                "communicationServices": "308", "energy": "309", "industrials": "310", "technology": "311"}
SECTORES_ES = {"materiales básicos": "101", "productos de consumo cíclicos": "102", "consumo cíclico": "102",
               "servicios financieros": "103", "inmobiliario": "104", "productos de consumo defensivos": "205",
               "consumo defensivo": "205", "salud": "206", "servicios públicos": "207",
               "servicios de comunicación": "308", "comunicaciones": "308", "energía": "309",
               "industria": "310", "industriales": "310", "tecnología": "311"}
PAISES = {
    "USA": "Estados Unidos", "JPN": "Japón", "GBR": "Reino Unido", "CAN": "Canadá", "FRA": "Francia",
    "CHE": "Suiza", "DEU": "Alemania", "AUS": "Australia", "NLD": "Países Bajos", "ESP": "España",
    "ITA": "Italia", "SWE": "Suecia", "DNK": "Dinamarca", "HKG": "Hong Kong", "SGP": "Singapur",
    "BEL": "Bélgica", "FIN": "Finlandia", "NOR": "Noruega", "IRL": "Irlanda", "ISR": "Israel",
    "AUT": "Austria", "PRT": "Portugal", "NZL": "Nueva Zelanda", "LUX": "Luxemburgo", "TWN": "Taiwán",
    "KOR": "Corea del Sur", "CHN": "China", "IND": "India", "BRA": "Brasil", "ZAF": "Sudáfrica",
    "MEX": "México", "SAU": "Arabia Saudí", "IDN": "Indonesia", "THA": "Tailandia", "MYS": "Malasia",
    "ARE": "Emiratos Árabes", "QAT": "Catar", "POL": "Polonia", "CHL": "Chile", "TUR": "Turquía",
    "PHL": "Filipinas", "GRC": "Grecia", "PER": "Perú", "HUN": "Hungría", "KWT": "Kuwait",
    "COL": "Colombia", "CZE": "Chequia", "EGY": "Egipto", "ARG": "Argentina", "RUS": "Rusia",
    "VNM": "Vietnam", "NGA": "Nigeria", "PAK": "Pakistán", "BMU": "Bermudas", "CYM": "Islas Caimán",
    "JEY": "Jersey", "GGY": "Guernsey", "IMN": "Isla de Man", "CUW": "Curazao", "PAN": "Panamá",
    "URY": "Uruguay", "ROU": "Rumanía", "SVN": "Eslovenia", "SVK": "Eslovaquia", "HRV": "Croacia",
    "EST": "Estonia", "LVA": "Letonia", "LTU": "Lituania", "ISL": "Islandia", "MAC": "Macao",
    "KAZ": "Kazajistán", "MAR": "Marruecos", "KEN": "Kenia", "BGR": "Bulgaria", "CYP": "Chipre",
    "MLT": "Malta", "BHR": "Baréin", "OMN": "Omán", "JOR": "Jordania", "LKA": "Sri Lanka",
}
PAISES_SAL = {"unitedStates": "USA", "japan": "JPN", "unitedKingdom": "GBR", "canada": "CAN", "france": "FRA",
              "switzerland": "CHE", "germany": "DEU", "australia": "AUS", "netherlands": "NLD", "spain": "ESP",
              "italy": "ITA", "sweden": "SWE", "denmark": "DNK", "hongKong": "HKG", "singapore": "SGP",
              "belgium": "BEL", "finland": "FIN", "norway": "NOR", "ireland": "IRL", "israel": "ISR",
              "austria": "AUT", "portugal": "PRT", "newZealand": "NZL", "luxembourg": "LUX", "taiwan": "TWN",
              "southKorea": "KOR", "china": "CHN", "india": "IND", "brazil": "BRA", "southAfrica": "ZAF",
              "mexico": "MEX", "saudiArabia": "SAU", "indonesia": "IDN", "thailand": "THA", "malaysia": "MYS",
              "unitedArabEmirates": "ARE", "qatar": "QAT", "poland": "POL", "chile": "CHL", "turkey": "TUR",
              "philippines": "PHL", "greece": "GRC", "peru": "PER", "hungary": "HUN", "kuwait": "KWT",
              "colombia": "COL", "czechRepublic": "CZE", "egypt": "EGY", "argentina": "ARG", "russia": "RUS"}


def _get(url, headers=None, timeout=20):
    with network.open_url(url, {**UA, **(headers or {})}, timeout=timeout) as r:
        text = r.read().decode("utf-8", "replace")
    return json.loads(text) if text.strip() else None


def _country(iso):
    return PAISES.get(iso, iso)


def _normalize_weights(pares):
    acc = {}
    for n, v in pares:
        if v and v > 0:
            acc[n] = acc.get(n, 0.0) + float(v)
    total = sum(acc.values())
    if total <= 0:
        return []
    return [[n, round(v * 100 / total, 2)] for n, v in sorted(acc.items(), key=lambda x: -x[1])]


def _breakdown(portafolio, key, kind=None):
    for b in portafolio.get(key) or []:
        if b.get("SalePosition") == "N" and (kind is None or b.get("Type") in (kind, None)):
            return b.get("BreakdownValues") or []
    return []


def secids(isin):
    q = {"page": 1, "pageSize": 10, "outputType": "json", "version": 1, "languageId": "es-ES", "currencyId": "EUR",
         "universeIds": "FOESP$$ALL|ETEUR$$ALL|FOALL$$ALL", "securityDataPoints": "SecId|isin|Universe", "term": isin}
    rows = (_get(BUSCA + urllib.parse.urlencode(q)) or {}).get("rows") or []
    rows = [f for f in rows if (f.get("isin") or "").upper() == isin]
    rows.sort(key=lambda f: not str(f.get("Universe", "")).startswith("FO"))
    seen = []
    for f in rows:
        if f.get("SecId") and f["SecId"] not in seen:
            seen.append(f["SecId"])
    return seen


def details(secid):
    d = _get(DETALLE.format(urllib.parse.quote(secid)))
    d = (d[0] if d else {}) if isinstance(d, list) else (d or {})
    p = (d.get("Portfolios") or [{}])[0]
    countries = _normalize_weights((_country(x["Type"]), x.get("Value")) for x in _breakdown(p, "CountryExposure", "Equity"))
    sectors = _normalize_weights((SECTORS.get(x["Type"], "Otros"), x.get("Value")) for x in _breakdown(p, "GlobalStockSectorBreakdown"))
    allocation = _breakdown(p, "AssetAllocations")
    rv = next((x.get("Value") for x in allocation if x.get("Type") == "1"), None)
    if not countries and not sectors:
        if rv is not None and rv < 1 and any((x.get("Value") or 0) > 1 for x in allocation):
            return {"paises": [], "sectores": [], "rv": 0.0, "top10": None,
                    "actualizado": (p.get("Date") or "")[:10] or None}
        return None
    top = sorted((h for h in p.get("PortfolioHoldings") or [] if h.get("Weighting")), key=lambda h: -h["Weighting"])[:10]
    return {"paises": countries, "sectores": sectors,
            "rv": round(max(0.0, min(1.0, rv / 100)), 4) if rv is not None else None,
            "top10": [[strip_html(h.get("SecurityName") or h.get("ExternalName") or "?"), round(h["Weighting"], 2)]
                      for h in top] or None,
            "actualizado": (p.get("Date") or "")[:10] or None}


def sal_details(secid):
    def fetch(path, componente):
        return _get(SAL.format(path, urllib.parse.quote(secid)) + SAL_QS.format(componente), SAL_CAB) or {}
    c = fetch("portfolio/regionalSectorIncludeCountries", "sector-exposure")
    fp = c.get("fundPortfolio") or {}
    countries = _normalize_weights((_country(PAISES_SAL.get(x.get("name"), x.get("name"))), x.get("percent")) for x in fp.get("countries") or [])
    s = (fetch("portfolio/v2/sector", "sector-exposure").get("EQUITY") or {}).get("fundPortfolio") or {}
    sectors = _normalize_weights((SECTORS.get(SECTORES_SAL.get(k, ""), "Otros"), v) for k, v in s.items()
                      if k in SECTORES_SAL and isinstance(v, (int, float)))
    if not countries and not sectors:
        return None
    a = fetch("process/asset/v2", "asset-allocation").get("allocationMap") or {}
    rv = None
    try:
        rv = sum(float(v.get("netAllocation") or 0) for k, v in a.items() if "Equity" in k) / 100 if a else None
    except (TypeError, ValueError):
        rv = None
    return {"paises": countries, "sectores": sectors,
            "rv": round(max(0.0, min(1.0, rv)), 4) if rv is not None else None, "top10": None,
            "actualizado": (fp.get("portfolioDate") or s.get("portfolioDate") or "")[:10] or None}


def stock(p):
    identifier = (p.get("identificador") or "").strip().upper()
    termino = identifier if ES_ISIN.match(identifier) else (p.get("codigo") or identifier).split(".")[0]
    if not termino:
        return None
    q = {"page": 1, "pageSize": 5, "outputType": "json", "version": 1, "languageId": "es-ES", "currencyId": "EUR",
         "universeIds": "E0WWE$$ALL", "securityDataPoints": "SecId|Name|isin|Ticker|SectorName|Domicile", "term": termino}
    rows = (_get(BUSCA + urllib.parse.urlencode(q)) or {}).get("rows") or []
    f = next((f for f in rows if f.get("SectorName") and f.get("Domicile")), None)
    if not f:
        return None
    sector = SECTORS.get(SECTORES_ES.get(f["SectorName"].strip().lower(), ""), strip_html(f["SectorName"]))
    return {"paises": [[_country(f["Domicile"]), 100.0]], "sectores": [[sector, 100.0]], "rv": 1.0, "top10": None,
            "actualizado": dt.date.today().isoformat(), "empresa": True}


def key(p):
    como = (p.get("expoComo") or "").strip().upper()
    if como:
        return "ISIN:" + como
    kind = p.get("tipoClave") or p.get("tipo")
    identifier = (p.get("identificador") or "").strip().upper()
    if kind == "accion":
        return "ACCION:" + (identifier or (p.get("codigo") or "").upper()) if (identifier or p.get("codigo")) else None
    if kind not in ("fondo", "etf", "pension", "otro", "bono"):
        return None
    if ES_ISIN.match(identifier):
        return "ISIN:" + identifier
    code = (p.get("codigo") or "").strip()
    if p.get("fuente") == "morningstar" and re.match(r"^(F0|0P)[A-Z0-9]{6,10}$", code):
        return "MS:" + code
    return None


def fetch_exposure(k, p):
    kind, value = k.split(":", 1)
    if kind == "ACCION":
        return stock(p)
    ids = secids(value) if kind == "ISIN" else [value]
    for sid in ids:
        r = details(sid) or sal_details(sid)
        if r:
            r["fuente"] = "Morningstar · cartera " + ("del fondo de referencia" if p.get("expoComo") else "del producto")
            return r
    return None


def product_exposure(p, cache, network=True, solo_si_falta=False):
    k = key(p)
    if not k:
        return None
    path = os.path.join(cache, "EXPO_" + re.sub(r"[^A-Za-z0-9]", "_", k) + ".json")
    saved = None
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        pass
    fresco = saved and (dt.date.today() - dt.date.fromisoformat(saved["consulta"])).days < CADUCA_DIAS
    if fresco or not network or (solo_si_falta and saved):
        return (saved or {}).get("datos")
    try:
        data = fetch_exposure(k, p)
    except Exception:
        return (saved or {}).get("datos")
    os.makedirs(cache, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"consulta": dt.date.today().isoformat(), "datos": data}, f, ensure_ascii=False)
    return data

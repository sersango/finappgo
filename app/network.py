"""Restrict server-side HTTP requests to known data providers."""

import urllib.parse
import urllib.request

PERMITIDOS = {
    "query1.finance.yahoo.com": "precios de Yahoo Finance",
    "query2.finance.yahoo.com": "buscador de Yahoo Finance",
    "lt.morningstar.com": "precios, buscador y cartera de los fondos (Morningstar)",
    "api-global.morningstar.com": "cartera de los planes de pensiones (Morningstar)",
    "api.coingecko.com": "precios de criptomonedas (CoinGecko)",
    "raw.githubusercontent.com": "comprobar si hay una versión nueva de FinAppGo",
}


class DisallowedHost(Exception):
    pass


def open_url(url, headers=None, timeout=15):
    """Open an HTTPS GET request to an allowlisted host."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in PERMITIDOS:
        raise DisallowedHost(f"FinAppGo no sale a {parts.scheme}://{parts.hostname}")
    req = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
    return urllib.request.urlopen(req, timeout=timeout)

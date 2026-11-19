# Security and privacy

FinAppGo stores portfolios, profiles, price caches, backups and the access key in the Docker volume mounted at `/data`. Backups, spreadsheets and exported dashboards can contain financial data. Keep those files and the container logs private.

## Access

Deploy on a trusted LAN and use a VPN for remote access. The container listens on port 8765 by default. Do not forward that port from the internet.

Open the access URL printed in the container logs. FinAppGo exchanges the key for an `HttpOnly`, `SameSite=Strict` cookie. The persistent key is stored in `/data/.acceso`.

The server validates the request host, rejects cross-origin access and applies a Content Security Policy. Docker mode allows private network addresses and local hostnames. For a custom hostname, set `PATRIMONIO_HOSTS_PERMITIDOS`. Browser extensions with access to the dashboard, or users with access to the container or volume, can read its data.

## Outbound requests

The server's network module permits HTTPS GET requests to an allowlist. Requests to price and exposure providers can contain instrument identifiers, currency pairs and search terms. GitHub requests check the project version and release notes. The browser can contact CoinGecko or Binance for live Bitcoin quotes.

The application does not send holdings, amounts, transaction dates or portfolio totals to those providers. Network providers can see the originating IP and the identifiers requested. External AI services receive any statement content you manually share with them.

Report a security issue without including access links or financial data.

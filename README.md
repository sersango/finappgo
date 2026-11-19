# FinAppGo

FinAppGo is a self-hosted personal finance dashboard. It tracks investments, cash, property, and liabilities, and supports portfolio analysis and transaction imports.

## Run with Docker Compose

Run `docker compose up -d` and inspect `docker compose logs finappgo` for the access link. Open the link in a browser on your trusted network. The service listens on port 8765. Do not expose it to the internet; use a VPN for remote access.

The named Docker volume contains portfolios, backups, profiles and the access key. Back up this volume before updating or removing the application. When upgrading an existing deployment, set `FINAPPGO_DATA_VOLUME` to the exact existing Docker volume name before starting Compose; otherwise a new, empty volume is created. Find the name with `docker volume ls` and back it up first.

To update, pull the desired image and recreate the container with `docker compose pull` and `docker compose up -d`. Pin an image tag for controlled upgrades. Keep a backup before upgrading, and retain a previous image tag for rollback.

## Development and tests

The server is Python and Flask. The frontend uses HTML, CSS and JavaScript. Install `requirements.txt` in an isolated development environment and run `python -m unittest discover -s tests -b`. Tests use temporary data and do not require real portfolio data.

## License

MIT. See [LICENSE](LICENSE). This project is based on [Rumbo](https://github.com/danidm98/rumbo).

# FinAppGo

FinAppGo is a self-hosted personal finance dashboard. It tracks investments, cash, property, and liabilities, and supports portfolio analysis and transaction imports.

## Run with Docker Compose

Run `docker compose up -d` and inspect `docker compose logs finappgo` for the access link. Open the link in a browser on your trusted network. The service listens on port 8765. Use a VPN for remote access. See [Security and privacy](docs/SECURITY.md).

The named Docker volume contains portfolios, backups, profiles and the access key. Back up this volume before updating or removing the application. To reuse a volume under the previous service name, find its exact name with `docker volume ls`, stop the old container, and back up the volume. Set `FINAPPGO_DATA_VOLUME` to that name and `FINAPPGO_EXTERNAL_VOLUME=true` before starting the new service. In Container Station, you can instead set the volume's `name` and `external: true` directly in the YAML. Use the access link from the new container logs to renew the browser session.

To update, pull the desired image and recreate the container with `docker compose pull` and `docker compose up -d`. Pin an image tag for controlled upgrades. Keep a backup before upgrading, and retain a previous image tag for rollback.

## Development and tests

The server is Python and Flask. The frontend uses HTML, CSS and JavaScript. Install `requirements.txt` in an isolated development environment and run `python -m unittest discover -s tests -b`. Tests use temporary data and do not require real portfolio data.

## License

MIT. See [LICENSE](LICENSE). This project is based on [Rumbo](https://github.com/danidm98/rumbo).

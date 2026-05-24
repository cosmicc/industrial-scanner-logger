# Industrial Scanner Logger

<!-- badges:start -->
[![CI](https://github.com/cosmicc/industrial-scanner-logger/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/cosmicc/industrial-scanner-logger/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/github/actions/workflow/status/cosmicc/industrial-scanner-logger/ci.yml?branch=main&label=tests&logo=githubactions&logoColor=white)](https://github.com/cosmicc/industrial-scanner-logger/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12-3776ab?logo=python&logoColor=white)](pyproject.toml)
[![Release](https://img.shields.io/github/v/release/cosmicc/industrial-scanner-logger?label=release&sort=semver)](https://github.com/cosmicc/industrial-scanner-logger/releases/latest)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-required-336791?logo=postgresql&logoColor=white)](README.md#requirements)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](README.md#current-behavior)
<!-- badges:end -->

Industrial Scanner Logger is a Python 3, Ubuntu-hosted shipment scan logging platform for Honeywell HF811 fixed-mount industrial scanners that receives scanner barcode output over TCP, validates and classifies FedEx tracking scan events, suppresses same-day same-scanner duplicate successes, writes durable CSV and raw diagnostic scan logs, records scan data in PostgreSQL for query and reporting, exposes FastAPI REST endpoints behind nginx, serves a lightweight web interface, and includes installer, schema, configuration, systemd service, firewall, logging, and troubleshooting tooling for running the complete scanner logging system on a production server.

## Current Behavior

- Listens on TCP port `55256` by default.
- Writes one dated scan CSV per day.
- Writes failed scans to `failed_scans.csv`.
- Writes completed daily totals per scanner and per day to `scan_totals.csv`.
- Writes accepted scan events to PostgreSQL for duplicate decisions, query/API
  use, and dashboard data while retaining all CSV logging.
- Writes troubleshooting events to `/var/log/industrial-scanner-logger.log` when installed as a service.
- Writes raw per-scan event lines to daily logs under `/var/log/industrial-scanner-logger/`.
- Runs an optional REST API service for querying PostgreSQL scan data.
- Serves health, search, completed CSV log download, and TV dashboard pages
  through nginx when installed.
- Treats a scan as `SUCCESS` only when the barcode is exactly 34 numeric digits.
- Treats blank scans, the configured no-read message, wrong lengths, and non-numeric values as `FAILED`.
- Identifies each scanner by the last octet of its IPv4 address.
- Logs repeated successful tracking numbers from the same or different scanners.
- Marks a successful scan as a duplicate only after the 3 different successful tracking number repeat threshold is met.

## Requirements

- Python 3.9 or newer
- Runtime Python packages listed in `requirements.txt`
- Ubuntu systemd host for the installer
- PostgreSQL, installed and initialized automatically by `scripts/install.sh`
- Nginx is installed automatically by `scripts/install.sh` when the API proxy is enabled
- UFW is installed and configured automatically by `scripts/install.sh`

## Quick Start

From the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
cp config/industrial-scanner-logger.conf ./industrial-scanner-logger.conf
nano ./industrial-scanner-logger.conf
scanner-tcp-receiver --config ./industrial-scanner-logger.conf
```

You can also run the compatibility script directly:

```bash
python3 scanner_tcp_receiver.py --config ./industrial-scanner-logger.conf
```

## Config File

The service runs the receiver with no runtime options. Receiver settings live in:

```text
/etc/industrial-scanner-logger.conf
```

The same INI format is used for manual runs with `--config`:

```ini
[receiver]
host = 0.0.0.0
port = 55256
output_dir = /scanner-logs
prefix = Site_Shipped_Tracking
no_read_message = __NO_READ__
success_length = 34
max_barcode_chars = 256
max_clients = 10
frame_idle_timeout = 0.25
client_idle_timeout = 0
shutdown_timeout = 5
tracking_repair_enabled = false

[logging]
log_file = /var/log/industrial-scanner-logger.log
scan_data_log_dir = /var/log/industrial-scanner-logger
scan_data_log_prefix = scanner-log-data

[tcp_keepalive]
enabled = true
idle = 60
interval = 15
probes = 4

[postgresql]
dsn = postgresql:///scannerlogger?host=/var/run/postgresql&user=scannerlogger
table = scanner_logger.scan_events
connect_timeout = 3
retry_interval = 30

[scanners]
last_scanner_id =
mandatory_scanner_ids =

[scanner_names]
# 20 = Lane 1 Scanner
# 21 = Last Scanner

[api]
enabled = true
host = 127.0.0.1
port = 8000
root_path = /api
log_level = info

[nginx]
site_name = industrial-scanner-logger
listen = 80 default_server
server_name = _
web_root = /var/www/scanner-site
disable_default_site = true
```

Check the installed receiver version:

```bash
scanner-tcp-receiver --version
```

## Ubuntu Install

Install the receiver services and nginx API proxy:

```bash
sudo scripts/install.sh
```

The installer copies the project to `/opt/industrial-scanner-logger`, creates a
Python virtual environment, installs the Python package dependencies, creates a
dedicated `scannerlogger` system user, installs the receiver and API systemd
units, installs PostgreSQL and applies the database schema, installs nginx if
needed, enables an nginx site for `/api`, and starts the services. It also
installs UFW, denies incoming traffic by default, and allows only `22/tcp`,
`55256/tcp`, `80/tcp`, and `443/tcp` incoming.

The nginx site template is:

```text
nginx/industrial-scanner-logger.conf
```

By default, the installer writes it to:

```text
/etc/nginx/sites-available/industrial-scanner-logger.conf
/etc/nginx/sites-enabled/industrial-scanner-logger.conf
```

It uses `/api` for the REST API and leaves `/` for the web interface document
root:

```text
/var/www/scanner-site
```

Static files placed under the repo's `html/` directory are copied into the web
root during install. For example:

```text
html/index.html -> /var/www/scanner-site/index.html
html/health/index.html -> /var/www/scanner-site/health/index.html
html/logs/index.html -> /var/www/scanner-site/logs/index.html
html/tv-dashboard/index.html -> /var/www/scanner-site/tv-dashboard/index.html
html/assets/site.css -> /var/www/scanner-site/assets/site.css
```

The default nginx listen value is `80 default_server`, so the installer disables
Ubuntu's packaged default site symlink if it exists. If you are merging this
into an existing nginx site, install with options such as:

```bash
sudo scripts/install.sh --nginx-listen 80 --keep-nginx-default-site
```

Receiver options are in:

```text
/etc/industrial-scanner-logger.conf
```

Edit that file to change the bind address, TCP port, output directory, CSV
prefix, no-read text, success length, receiver safety limits, troubleshooting
log path, PostgreSQL options, REST API bind settings, or nginx site settings:

```bash
sudo nano /etc/industrial-scanner-logger.conf
sudo systemctl restart industrial-scanner-logger
sudo systemctl restart industrial-scanner-logger-api
sudo refresh-app-config
sudo refresh-nginx-config
```

`refresh-app-config` updates `/etc/industrial-scanner-logger.conf` from the
installed default `config/industrial-scanner-logger.conf` schema. It keeps
existing values for options that still exist, adds new default options, removes
options deleted from the defaults file, and restarts the receiver service around
the config rewrite.

`refresh-nginx-config` renders `nginx/industrial-scanner-logger.conf` with the
`[api]` and `[nginx]` values from `/etc/industrial-scanner-logger.conf`, writes
the result to `/etc/nginx/sites-available`, validates it with `nginx -t`, and
restarts nginx.

Useful service commands:

```bash
sudo systemctl status industrial-scanner-logger
sudo systemctl status industrial-scanner-logger-api
sudo systemctl status nginx
sudo journalctl -u industrial-scanner-logger -f
sudo journalctl -u industrial-scanner-logger-api -f
sudo tail -f /var/log/industrial-scanner-logger.log
sudo tail -f /var/log/industrial-scanner-logger/scanner-log-data-$(date +%F).log
sudo refresh-app-config
sudo refresh-nginx-config
sudo nginx -t
sudo systemctl restart industrial-scanner-logger
sudo systemctl restart industrial-scanner-logger-api
sudo systemctl reload nginx
sudo systemctl stop industrial-scanner-logger
```

The troubleshooting log records service startup, version, configuration, scanner
connections and disconnections, warnings, and errors. The service journal and
troubleshooting log do not receive one line per scan.

Raw per-scan event lines are written to daily files like:

```text
/var/log/industrial-scanner-logger/scanner-log-data-2026-05-17.log
```

These daily scan data logs contain the `Event:... Barcode:...` lines that used
to go to the service console. The CSV outputs remain the primary structured
record.

For service installs, idle scanner disconnects are disabled by default with
`client_idle_timeout = 0`. A scanner can sit connected with no boxes moving
without being disconnected by the receiver. TCP keepalive stays enabled so dead
network connections can still be detected without treating normal scanner idle
time as a failure. Existing installs keep their current config file, so set
`client_idle_timeout = 0` in `/etc/industrial-scanner-logger.conf` or rerun the
installer with `--overwrite-config` to pick up this default.

## PostgreSQL Logging

PostgreSQL is mandatory. The receiver uses `scanner_logger.scan_events` as the
source of truth for duplicate decisions over the previous 30 days, then writes
the accepted row before the next scanner event can be evaluated.

The receiver inserts final scan events into:

```text
scanner_logger.scan_events
```

Every non-empty scanner output is also inserted into:

```text
scanner_logger.raw_scan_events
```

The table schema is in:

```text
db/schema.sql
```

Python inserts scan timing, scanner metadata, duplicate and repair flags, the
received barcode, and the tracking number. The date and time come from the
receiver script at the same point where the CSV row is written; PostgreSQL does
not assign the scan event timestamp. PostgreSQL generated columns and views
provide success/failure classification, failed scan queries, daily totals,
package progression, duplicate queries, and successful packages
missing the configured last scanner.

Use `[scanners] last_scanner_id` for the final outbound scanner before boxes
are loaded. Use `[scanners] mandatory_scanner_ids` for scanner IDs that must
stay connected for the health page and TV dashboard to report OK. Use
`[scanner_names]` to map IP last-octet scanner IDs to readable names:

```ini
[scanners]
last_scanner_id = 21
mandatory_scanner_ids = 20, 21

[scanner_names]
20 = Lane 1 Scanner
21 = Last Scanner

[dashboard]
health_page_refresh_seconds = 3
tv_dashboard_refresh_seconds = 1
```

Repeated successful scans are logged from the same scanner and across scanners.
A same-scanner repeat is marked `is_duplicate = true` only when that scanner
accepted 3 different successful tracking numbers between the previous accepted
scan of that tracking number in the previous 30 days and the current scan.
Cross-scanner repeats also set `is_cross_scanner_duplicate = true` when that
threshold is met across the previous 30 days of successful scans and the
tracking number was previously accepted from a different scanner.

Set `[receiver] tracking_repair_enabled = true` to allow conservative repair of
short numeric failed scans. A short scan is repaired only when successful scans
from the same day provide one unambiguous matching prefix; repaired rows are
logged to `/var/log/industrial-scanner-logger.log` and marked with
`is_repaired = true` in CSV and PostgreSQL output. For repaired PostgreSQL rows,
`barcode` keeps the short value received from the scanner, while
`tracking_number` stores the repaired full tracking number.

`scanner_logger.raw_scan_events` stores the scanner value before repair. The
normal `scanner_logger.scan_events` table skips failed nonnumeric scans such as
no-read markers; those rows remain available in `raw_scan_events`.

The installer enables PostgreSQL logging by default with local Unix socket peer
authentication:

```text
postgresql:///scannerlogger?host=/var/run/postgresql&user=scannerlogger
```

That default expects the Linux service user and PostgreSQL role to both be named
`scannerlogger`, and the database to be named `scannerlogger`. The installer
creates that local role/database and applies `db/schema.sql` when the default
DSN is used. With a custom DSN, the installer applies `db/schema.sql` through
that DSN.

Existing service installs keep their current config file. After this change,
run `sudo refresh-app-config` to add new config options from
`config/industrial-scanner-logger.conf` and remove obsolete options such as the
old `[postgresql]` `enabled` and `required` keys without overwriting modified
settings.

After pulling schema changes, reapply `db/schema.sql` to the PostgreSQL database
before restarting PostgreSQL-backed logging or API queries.

PostgreSQL connection, duplicate lookup, or write failures are logged to the
troubleshooting log and stop the receiver so duplicate decisions cannot be made
from stale local state.

## REST API

The installer creates a separate API service:

```text
industrial-scanner-logger-api.service
```

The API reads PostgreSQL connection settings, bind settings, and its proxy root
path from `/etc/industrial-scanner-logger.conf`. By default it binds locally
and treats `/api` as its public root path:

```text
http://127.0.0.1:8000 with root_path = /api
```

Core public endpoints behind nginx:

```text
GET /api/v1/health
GET /api/v1/dashboard/health
GET /api/v1/logs/daily-csv
GET /api/v1/logs/daily-csv/{scan_date}
GET /api/v1/scans
GET /api/v1/scans/{scan_id}
GET /api/v1/views
GET /api/v1/views/daily-scan-totals
GET /api/v1/views/daily-scan-totals-all-scanners
GET /api/v1/views/failed-scans
GET /api/v1/views/successful-scans
GET /api/v1/views/duplicate-successful-scans
GET /api/v1/views/successful-scan-progression
GET /api/v1/views/successful-scans-missing-last-scanner
```

The list endpoints support common filters such as `start_date`, `end_date`,
`scanner_id`, `barcode`, `limit`, and `offset` where those fields exist.
The `barcode` filter matches either the received barcode or repaired tracking
number when both fields are available. Numeric 10-digit barcode filters also
match the end of those tracking fields so users can search by the last 10
digits. Full 34-digit tracking numbers are matched exactly. `/api/v1/scans`
also supports `is_success`.

`/api/v1/logs/daily-csv` lists completed daily CSV files for download and
excludes the current day because that file may still be open for writing.
Header-only daily CSV files are shown as days with no scans instead of being
made available for download. `/logs` is the browser page for those downloads
and shows the newest entries first in groups of 10. `/health` refreshes every 3
seconds by default, and `/tv-dashboard` refreshes every second by default. The
TV dashboard is formatted for a 1920x1080 display and currently shows scan
rate, today's total, successful, duplicate, and failed counts, last received
scan age, connected scanner count, and mandatory scanner warnings from the
health dashboard data.

Interactive API docs are available through nginx:

```text
/api/docs
```

The uvicorn app routes are `/v1/...` internally. The installed nginx site strips
the `/api` prefix before proxying to uvicorn, while `/` serves the web root for
the separate web interface:

```nginx
location = /api {
    return 308 /api/;
}

location /api/ {
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix /api;
    proxy_redirect off;
    proxy_pass http://127.0.0.1:8000/;
}
```

Uninstall the runtime services, service files, config file, nginx site, and UFW
package while preserving the installed app directory, CSV logs, script logs,
raw scan data logs, the nginx package, and the service user/group:

```bash
sudo scripts/uninstall.sh
```

## CSV Outputs

Daily scan files are named with the configured prefix and current date:

```text
Site_Shipped_Tracking_2026-05-16.csv
```

Daily scan CSV columns:

```text
date,time,scanner_id,scanner_name,scanner_role,status,is_duplicate,is_cross_scanner_duplicate,is_repaired,tracking
```

Failed scan CSV columns:

```text
date,time,scanner_id,failed_barcode
```

Daily totals CSV columns:

```text
date,scanner_id,total_events,successful_scans,failed_scans
```

The `scanner_id` is the last octet of the scanner IP address. For example,
scanner `10.10.10.20` is recorded as scanner `20`. `scan_totals.csv` includes
one row per scanner plus an `ALL` row for the full day.

`scanner_role` is `last` only for the configured final outbound scanner.
`is_duplicate` is `true` only for successful scans that repeat after the 3
different successful tracking number threshold is met. `is_cross_scanner_duplicate`
is `true` only for duplicate successful scans whose tracking number was already
accepted from another scanner within the duplicate lookback window.
`is_repaired` is `true` only when tracking-number repair reconstructed a short
numeric failed scan into a valid tracking number.

## Development

Run the unit tests:

```bash
python -m unittest discover -s tests
```

Install development tools and run Ruff:

```bash
python -m pip install -e ".[dev]"
ruff check .
```

## Repository

GitHub repository:

```text
https://github.com/cosmicc/industrial-scanner-logger
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

# Industrial Scanner Logger

Python 3 TCP receiver, CSV logger, and optional PostgreSQL scan event logger for
a Honeywell HF811 industrial scanner.

Current release: `v1.1.2`

The current receiver listens for scanner TCP connections, classifies scan events, and writes daily CSV logs. It is packaged so the project can be installed, tested, versioned, and uploaded to GitHub as it grows.

## Current Behavior

- Listens on TCP port `55256` by default.
- Writes one dated scan CSV per day.
- Writes failed scans to `failed_scans.csv`.
- Writes completed daily totals per scanner and per day to `scan_totals.csv`.
- Can also write accepted scan events to PostgreSQL for query/API use while
  retaining all CSV logging.
- Writes troubleshooting events to `/var/log/industrial-scanner-logger.log` when installed as a service.
- Writes raw per-scan event lines to daily logs under `/var/log/industrial-scanner-logger/`.
- Runs an optional REST API service for querying PostgreSQL scan data.
- Treats a scan as `SUCCESS` only when the barcode is exactly 34 numeric digits.
- Treats blank scans, the configured no-read message, wrong lengths, and non-numeric values as `FAILED`.
- Identifies each scanner by the last octet of its IPv4 address.
- Ignores duplicate successful tracking numbers on the same scanner during the same day by default.
- Allows the same package tracking number to be logged by different scanners.

## Requirements

- Python 3.9 or newer
- Runtime Python packages listed in `requirements.txt`
- The service installer installs `requirements.txt` automatically

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
max_clients = 8
frame_idle_timeout = 0.25
client_idle_timeout = 0
shutdown_timeout = 5

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
enabled = true
required = false
dsn = postgresql:///scannerlogger?host=/var/run/postgresql&user=scannerlogger
table = scanner_logger.scan_events
connect_timeout = 3
retry_interval = 30

[api]
enabled = true
host = 127.0.0.1
port = 8000
log_level = info
```

Check the installed receiver version:

```bash
scanner-tcp-receiver --version
```

## Ubuntu Systemd Service

Install the receiver as a systemd service:

```bash
sudo scripts/install_service.sh
```

The installer copies the project to `/opt/industrial-scanner-logger`, creates a
Python virtual environment, installs the Python package dependencies, creates a
dedicated `scannerlogger` system user, installs a systemd unit, and starts the
service.

Receiver options are in:

```text
/etc/industrial-scanner-logger.conf
```

Edit that file to change the bind address, TCP port, output directory, CSV
prefix, no-read text, success length, receiver safety limits, troubleshooting
log path, PostgreSQL options, or REST API bind settings:

```bash
sudo nano /etc/industrial-scanner-logger.conf
sudo systemctl restart industrial-scanner-logger
sudo systemctl restart industrial-scanner-logger-api
```

Useful service commands:

```bash
sudo systemctl status industrial-scanner-logger
sudo systemctl status industrial-scanner-logger-api
sudo journalctl -u industrial-scanner-logger -f
sudo journalctl -u industrial-scanner-logger-api -f
scripts/live-scanner-log
sudo tail -f /var/log/industrial-scanner-logger.log
sudo tail -f /var/log/industrial-scanner-logger/scanner-log-data-$(date +%F).log
sudo systemctl restart industrial-scanner-logger
sudo systemctl restart industrial-scanner-logger-api
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

The receiver can insert each accepted scan event into:

```text
scanner_logger.scan_events
```

The table schema is in:

```text
db/schema.sql
```

Python inserts `scan_date`, `scan_time`, `scanner_id`, and `tracking_number`.
The date and time come from the receiver script at the same point where the CSV
row is written; PostgreSQL does not assign the scan event timestamp. PostgreSQL
generated columns and views provide success/failure classification, failed scan
queries, daily totals, and duplicate scan queries.

The service installer enables PostgreSQL logging by default with local Unix
socket peer authentication:

```text
postgresql:///scannerlogger?host=/var/run/postgresql&user=scannerlogger
```

That default expects the Linux service user and PostgreSQL role to both be named
`scannerlogger`, and the database to be named `scannerlogger`. Disable
PostgreSQL logging during service install if the database is not ready yet:

```bash
sudo scripts/install_service.sh --disable-postgresql
```

Existing service installs keep their current config file. To add PostgreSQL
logging to an existing service, edit `/etc/industrial-scanner-logger.conf` and
set `enabled = true` under `[postgresql]`, or rerun the installer with
`--overwrite-config`.

PostgreSQL write failures are logged to the troubleshooting log. CSV and raw
daily scan logs continue to be written unless `--postgresql-required` is set.

## REST API

The installer creates a separate API service:

```text
industrial-scanner-logger-api.service
```

The API reads PostgreSQL connection settings and bind settings from
`/etc/industrial-scanner-logger.conf`. By default it binds locally:

```text
http://127.0.0.1:8000
```

Core endpoints:

```text
GET /api/v1/health
GET /api/v1/scans
GET /api/v1/scans/{scan_id}
GET /api/v1/views
GET /api/v1/views/daily-scan-totals
GET /api/v1/views/daily-scan-totals-all-scanners
GET /api/v1/views/failed-scans
GET /api/v1/views/successful-scans
GET /api/v1/views/duplicate-successful-scans
```

The list endpoints support common filters such as `start_date`, `end_date`,
`scanner_id`, `barcode`, `limit`, and `offset` where those fields exist.
`/api/v1/scans` also supports `is_success`.

Interactive API docs are available from FastAPI:

```text
http://127.0.0.1:8000/docs
```

Uninstall the service and config file while preserving the app directory,
CSV logs, script logs, raw scan data logs, and service user/group:

```bash
sudo scripts/uninstall_service.sh
```

Only remove the installed application directory when you explicitly want to:

```bash
sudo scripts/uninstall_service.sh --remove-app
```

## CSV Outputs

Daily scan files are named with the configured prefix and current date:

```text
Site_Shipped_Tracking_2026-05-16.csv
```

Daily scan CSV columns:

```text
date,time,scanner_id,status,tracking
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

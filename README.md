# Industrial Scanner Logger

Python 3 TCP receiver and CSV logger for a Honeywell HF811 industrial scanner.

Current release: `v1.1.1`

The current receiver listens for scanner TCP connections, classifies scan events, and writes daily CSV logs. It is packaged so the project can be installed, tested, versioned, and uploaded to GitHub as it grows.

## Current Behavior

- Listens on TCP port `55256` by default.
- Writes one dated scan CSV per day.
- Writes failed scans to `failed_scans.csv`.
- Writes completed daily totals per scanner and per day to `scan_totals.csv`.
- Writes troubleshooting events to `/var/log/industrial-scanner-logger.log` when installed as a service.
- Treats a scan as `SUCCESS` only when the barcode is exactly 34 numeric digits.
- Treats blank scans, the configured no-read message, wrong lengths, and non-numeric values as `FAILED`.
- Identifies each scanner by the last octet of its IPv4 address.
- Ignores duplicate successful tracking numbers on the same scanner during the same day by default.
- Allows the same package tracking number to be logged by different scanners.

## Requirements

- Python 3.9 or newer
- No runtime third-party Python packages

## Quick Start

From the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
scanner-tcp-receiver \
  --output-dir ./scanner-logs \
  --log-file ./scanner-logs/industrial-scanner-logger.log
```

You can also run the compatibility script directly:

```bash
python3 scanner_tcp_receiver.py \
  --output-dir ./scanner-logs \
  --log-file ./scanner-logs/industrial-scanner-logger.log
```

## Common Options

```bash
scanner-tcp-receiver \
  --host 0.0.0.0 \
  --port 55256 \
  --output-dir /scanner-logs \
  --prefix Site_Shipped_Tracking \
  --no-read-message __NO_READ__ \
  --success-length 34 \
  --max-barcode-chars 256 \
  --max-clients 8 \
  --frame-idle-timeout 0.25 \
  --client-idle-timeout 300 \
  --shutdown-timeout 5 \
  --log-file /var/log/industrial-scanner-logger.log
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

The installer copies the project to `/opt/industrial-scanner-logger`, creates a Python virtual environment, creates a dedicated `scannerlogger` system user, installs a systemd unit, and starts the service.

Receiver options are service-level configuration in:

```text
/etc/default/industrial-scanner-logger
```

Edit that file to change the bind address, TCP port, output directory, CSV prefix, no-read text, success length, receiver safety limits, or troubleshooting log path:

```bash
sudo nano /etc/default/industrial-scanner-logger
sudo systemctl restart industrial-scanner-logger
```

Useful service commands:

```bash
sudo systemctl status industrial-scanner-logger
sudo journalctl -u industrial-scanner-logger -f
scripts/live-scanner-log
sudo tail -f /var/log/industrial-scanner-logger.log
sudo systemctl restart industrial-scanner-logger
sudo systemctl stop industrial-scanner-logger
```

The troubleshooting log records service startup, version, configuration, scanner
connections and disconnections, warnings, and errors. It does not write the raw
barcode or tracking data received from scanners; that scanner data remains in
the CSV outputs.

Uninstall the service while preserving CSV logs and service defaults:

```bash
sudo scripts/uninstall_service.sh
```

Remove the service, installed app, defaults file, logs, and service user/group:

```bash
sudo scripts/uninstall_service.sh --purge
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

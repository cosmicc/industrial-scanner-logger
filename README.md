# Industrial Scanner Logger

Python 3 TCP receiver and CSV logger for a Honeywell HF811 industrial scanner.

The current receiver listens for scanner TCP connections, classifies scan events, and writes daily CSV logs. It is packaged so the project can be installed, tested, versioned, and uploaded to GitHub as it grows.

## Current Behavior

- Listens on TCP port `55256` by default.
- Writes one dated scan CSV per day.
- Writes failed scans to `failed_scans.csv`.
- Writes completed daily totals to `scan_totals.csv`.
- Treats a scan as `SUCCESS` only when the barcode is exactly 34 numeric digits.
- Treats blank scans, the configured no-read message, wrong lengths, and non-numeric values as `FAILED`.
- Ignores duplicate successful tracking numbers during the same day by default.

## Requirements

- Python 3.9 or newer
- No runtime third-party Python packages

## Quick Start

From the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
scanner-tcp-receiver --output-dir ./scanner-logs
```

You can also run the compatibility script directly:

```bash
python3 scanner_tcp_receiver.py --output-dir ./scanner-logs
```

## Common Options

```bash
scanner-tcp-receiver \
  --host 0.0.0.0 \
  --port 55256 \
  --output-dir /scanner-logs \
  --prefix Ferndale_Shipped_Tracking \
  --no-read-message __NO_READ__ \
  --success-length 34
```

## CSV Outputs

Daily scan files are named with the configured prefix and current date:

```text
Ferndale_Shipped_Tracking_2026-05-16.csv
```

Daily scan CSV columns:

```text
date,time,status,tracking
```

Failed scan CSV columns:

```text
date,time,failed_barcode
```

Daily totals CSV columns:

```text
date,total_events,successful_scans,failed_scans
```

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

## GitHub Setup

Initialize and publish the repository after choosing the GitHub repository name and visibility:

```bash
git init
git add .
git commit -m "Initial project scaffold"
gh repo create industrial-scanner-logger --source=. --private --push
```

No open-source license has been selected yet. Add a `LICENSE` file before making the repository public if other people should be allowed to use, modify, or redistribute the code.

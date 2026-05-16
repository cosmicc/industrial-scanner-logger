#!/usr/bin/env python3
"""
HF811 Daily FedEx Tracking TCP Listener

Creates a new dated CSV file each day.

Daily scan CSV format:
    date,time,status,tracking

Failed scans CSV:
    /scanner-logs/failed_scans.csv

Failed scans CSV format:
    date,time,failed_barcode

Daily totals CSV:
    /scanner-logs/scan_totals.csv

Daily totals CSV format:
    date,total_events,successful_scans,failed_scans

Console output format:
    Event:<number> Success:<number> Failed:<number> Status:<SUCCESS|FAILED> Time:<time> Barcode:<barcode>

Success rule:
    Barcode must be exactly 34 numeric digits.

Example daily CSV files:
    Site_Shipped_Tracking_2026-05-13.csv
    Site_Shipped_Tracking_2026-05-14.csv
"""

import argparse
import csv
import re
import shutil
import socket
import threading
from datetime import datetime
from pathlib import Path

from industrial_scanner_logger._version import __version__


# False = successful FedEx tracking numbers are logged only once per day.
# Failed scans are always logged.
LOG_DUPLICATE_SUCCESS_SCANS = False


def clean_barcode(raw: str) -> str:
    """
    Remove common TCP/scanner line endings and surrounding whitespace.
    Keeps the actual barcode content intact.
    """
    return raw.strip("\r\n\t \x00")


class DailyCsvLogger:
    def __init__(
        self,
        output_dir: Path,
        file_prefix: str,
        no_read_message: str,
        success_length: int,
    ):
        self.output_dir = output_dir
        self.file_prefix = file_prefix
        self.no_read_message = no_read_message
        self.success_length = success_length
        self.lock = threading.Lock()

        self.current_date = None
        self.current_csv_path = None

        self.seen_success_barcodes = set()

        self.event_count = 0
        self.success_count = 0
        self.failed_count = 0

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.totals_path = self.output_dir / "scan_totals.csv"
        self.failed_scans_path = self.output_dir / "failed_scans.csv"

        self._ensure_totals_file()
        self._ensure_failed_scans_file()
        self._write_missing_prior_totals()
        self._rotate_if_needed()

    def _today_string(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _time_string(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _timestamp_string(self) -> str:
        return datetime.now().strftime("%Y%m%d-%H%M%S")

    def _csv_path_for_date(self, date_str: str) -> Path:
        filename = f"{self.file_prefix}_{date_str}.csv"
        return self.output_dir / filename

    def _backup_file(self, path: Path):
        if path.exists():
            backup_path = path.with_name(f"{path.name}.backup-{self._timestamp_string()}")
            shutil.copy2(path, backup_path)
            print(f"Backup created: {backup_path}")

    def _classify_scan(self, barcode: str) -> str:
        """
        SUCCESS only if the decoded value is exactly 34 numeric digits.

        FAILED if:
          - blank
          - scanner no-read message
          - not exactly 34 characters
          - contains anything other than digits
        """
        barcode_clean = clean_barcode(barcode)

        if not barcode_clean:
            return "FAILED"

        if barcode_clean == self.no_read_message:
            return "FAILED"

        if len(barcode_clean) != self.success_length:
            return "FAILED"

        if not barcode_clean.isdigit():
            return "FAILED"

        return "SUCCESS"

    def _ensure_daily_csv_header(self, csv_path: Path):
        """
        Ensure the daily CSV has the latest header.

        If an older daily file exists with:
            date,time,tracking

        it is migrated to:
            date,time,status,tracking
        """
        expected_header = ["date", "time", "status", "tracking"]

        if not csv_path.exists() or csv_path.stat().st_size == 0:
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(expected_header)
            return

        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            current_header = next(reader, [])

        if current_header == expected_header:
            return

        self._backup_file(csv_path)

        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(expected_header)

            for row in rows:
                date_str = clean_barcode(row.get("date", ""))
                time_str = clean_barcode(row.get("time", ""))
                tracking = clean_barcode(row.get("tracking", "") or row.get("barcode", ""))
                status = clean_barcode(row.get("status", ""))

                if status not in {"SUCCESS", "FAILED"}:
                    status = self._classify_scan(tracking)

                csv_tracking = "" if tracking == self.no_read_message else tracking
                writer.writerow([date_str, time_str, status, csv_tracking])

        print(f"Migrated daily CSV header: {csv_path}")

    def _ensure_totals_file(self):
        """
        Ensure scan_totals.csv exists with the latest header.

        If an older totals file exists with:
            date,total_unique_scans

        it is migrated to:
            date,total_events,successful_scans,failed_scans

        Old total_unique_scans values are treated as successful_scans with failed_scans=0.
        """
        expected_header = ["date", "total_events", "successful_scans", "failed_scans"]

        if not self.totals_path.exists() or self.totals_path.stat().st_size == 0:
            with self.totals_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(expected_header)
            return

        with self.totals_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            current_header = next(reader, [])

        if current_header == expected_header:
            return

        self._backup_file(self.totals_path)

        with self.totals_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        with self.totals_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(expected_header)

            for row in rows:
                date_str = clean_barcode(row.get("date", ""))

                if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                    continue

                if "total_unique_scans" in row:
                    successful = int(row.get("total_unique_scans") or 0)
                    total_events = successful
                    failed = 0
                else:
                    total_events = int(row.get("total_events") or 0)
                    successful = int(row.get("successful_scans") or 0)
                    failed = int(row.get("failed_scans") or 0)

                writer.writerow([date_str, total_events, successful, failed])

        print(f"Migrated totals CSV header: {self.totals_path}")

    def _ensure_failed_scans_file(self):
        expected_header = ["date", "time", "failed_barcode"]

        if not self.failed_scans_path.exists() or self.failed_scans_path.stat().st_size == 0:
            with self.failed_scans_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(expected_header)
            return

        with self.failed_scans_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            current_header = next(reader, [])

        if current_header == expected_header:
            return

        self._backup_file(self.failed_scans_path)

        with self.failed_scans_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        with self.failed_scans_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(expected_header)

            for row in rows:
                date_str = clean_barcode(row.get("date", ""))
                time_str = clean_barcode(row.get("time", ""))
                failed_barcode = clean_barcode(
                    row.get("failed_barcode", "")
                    or row.get("tracking", "")
                    or row.get("barcode", "")
                )
                writer.writerow([date_str, time_str, failed_barcode])

        print(f"Migrated failed scans CSV header: {self.failed_scans_path}")

    def _load_existing_day_state(self, csv_path: Path):
        """
        Load today's CSV state after restart so console counters resume correctly.
        """
        seen_success = set()
        event_count = 0
        success_count = 0
        failed_count = 0

        if not csv_path.exists():
            return seen_success, event_count, success_count, failed_count

        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                tracking = clean_barcode(
                    row.get("tracking", "") or row.get("barcode", "")
                )

                status = clean_barcode(row.get("status", ""))

                if status not in {"SUCCESS", "FAILED"}:
                    status = self._classify_scan(tracking)

                event_count += 1

                if status == "SUCCESS":
                    success_count += 1
                    if tracking:
                        seen_success.add(tracking)
                else:
                    failed_count += 1

        return seen_success, event_count, success_count, failed_count

    def _count_csv_day(self, csv_path: Path):
        """
        Count total, success, and failed rows in a dated CSV.
        """
        if not csv_path.exists():
            return 0, 0, 0

        event_count = 0
        success_count = 0
        failed_count = 0

        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                tracking = clean_barcode(
                    row.get("tracking", "") or row.get("barcode", "")
                )

                status = clean_barcode(row.get("status", ""))

                if status not in {"SUCCESS", "FAILED"}:
                    status = self._classify_scan(tracking)

                event_count += 1

                if status == "SUCCESS":
                    success_count += 1
                else:
                    failed_count += 1

        return event_count, success_count, failed_count

    def _existing_total_dates(self):
        dates = set()

        if not self.totals_path.exists():
            return dates

        with self.totals_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                date_part = clean_barcode(row.get("date", ""))

                if re.match(r"^\d{4}-\d{2}-\d{2}$", date_part):
                    dates.add(date_part)

        return dates

    def _append_scan_total(
        self,
        date_str: str,
        total_events: int,
        successful_scans: int,
        failed_scans: int,
    ):
        """
        Append one completed day's totals to scan_totals.csv.
        Avoids duplicate date entries.
        """
        existing_dates = self._existing_total_dates()

        if date_str in existing_dates:
            return

        with self.totals_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([date_str, total_events, successful_scans, failed_scans])

        print(
            f"Daily total written: {date_str},"
            f"{total_events},{successful_scans},{failed_scans}"
        )

    def _write_missing_prior_totals(self):
        """
        On startup, write totals for any old dated CSVs that do not already
        have an entry in scan_totals.csv.
        """
        today = self._today_string()
        existing_dates = self._existing_total_dates()

        pattern = f"{self.file_prefix}_*.csv"

        for csv_path in sorted(self.output_dir.glob(pattern)):
            filename = csv_path.name

            match = re.match(
                rf"^{re.escape(self.file_prefix)}_(\d{{4}}-\d{{2}}-\d{{2}})\.csv$",
                filename,
            )

            if not match:
                continue

            file_date = match.group(1)

            # Only finalize prior days, never today's active file.
            if file_date >= today:
                continue

            if file_date in existing_dates:
                continue

            self._ensure_daily_csv_header(csv_path)

            total_events, successful_scans, failed_scans = self._count_csv_day(csv_path)

            self._append_scan_total(
                file_date,
                total_events,
                successful_scans,
                failed_scans,
            )

    def _rotate_if_needed(self):
        """
        Switch to a new daily CSV when the date changes.

        The previous day's total is written on the first scanner event after midnight.
        """
        today = self._today_string()

        if self.current_date == today:
            return

        # If crossing from an existing day to a new day, finalize the prior day.
        if self.current_date is not None:
            self._append_scan_total(
                self.current_date,
                self.event_count,
                self.success_count,
                self.failed_count,
            )

        self.current_date = today
        self.current_csv_path = self._csv_path_for_date(today)

        self._ensure_daily_csv_header(self.current_csv_path)

        (
            self.seen_success_barcodes,
            self.event_count,
            self.success_count,
            self.failed_count,
        ) = self._load_existing_day_state(self.current_csv_path)

        print("=" * 80)
        print(f"Now logging to: {self.current_csv_path.resolve()}")
        print(f"Starting event count: {self.event_count}")
        print(f"Starting successful scan count: {self.success_count}")
        print(f"Starting failed scan count: {self.failed_count}")
        print(f"Daily totals file: {self.totals_path.resolve()}")
        print(f"Failed scans file: {self.failed_scans_path.resolve()}")
        print(f"Success rule: exactly {self.success_length} numeric digits")
        print("=" * 80)

    def _append_failed_scan(self, date_str: str, time_str: str, failed_barcode: str):
        """
        Append failed scan to failed_scans.csv forever.
        This file does not roll over.
        """
        with self.failed_scans_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([date_str, time_str, failed_barcode])

    def write_scan_event(self, raw_barcode: str):
        barcode = clean_barcode(raw_barcode)

        if not barcode:
            return

        with self.lock:
            self._rotate_if_needed()

            status = self._classify_scan(barcode)

            if status == "SUCCESS":
                if barcode in self.seen_success_barcodes and not LOG_DUPLICATE_SUCCESS_SCANS:
                    print(f"Duplicate ignored - {barcode}")
                    return

                self.seen_success_barcodes.add(barcode)
                self.success_count += 1

            else:
                self.failed_count += 1

            self.event_count += 1

            date_str = self.current_date
            time_str = self._time_string()

            # Daily CSV:
            # For scanner no-read, keep tracking blank.
            # For partial/invalid/short/long decodes, keep the decoded value for review.
            csv_tracking = "" if barcode == self.no_read_message else barcode

            with self.current_csv_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([date_str, time_str, status, csv_tracking])

            # Forever-appended failed scan CSV:
            # Keep the no-read message visible here so the failure is explicit.
            if status == "FAILED":
                self._append_failed_scan(date_str, time_str, barcode)

            print(
                f"Event:{self.event_count} "
                f"Success:{self.success_count} "
                f"Failed:{self.failed_count} "
                f"Status:{status} "
                f"Time:{time_str} "
                f"Barcode:{barcode}"
            )


def handle_client(conn: socket.socket, addr, logger: DailyCsvLogger):
    print(f"Scanner connected from {addr[0]}:{addr[1]}")

    buffer = ""

    # Timeout fallback:
    # If the scanner sends data without CR/LF, flush the idle buffer as one event.
    conn.settimeout(0.25)

    with conn:
        while True:
            try:
                data = conn.recv(4096)

                if not data:
                    print(f"Scanner disconnected from {addr[0]}:{addr[1]}")
                    break

                text = data.decode("utf-8", errors="replace")
                buffer += text

                # Preferred mode:
                # Scanner sends CR, LF, or CR/LF after each barcode/event.
                while "\n" in buffer or "\r" in buffer:
                    delimiter_positions = [
                        pos for pos in [buffer.find("\n"), buffer.find("\r")] if pos != -1
                    ]

                    split_pos = min(delimiter_positions)

                    barcode = buffer[:split_pos]
                    buffer = buffer[split_pos + 1:]

                    logger.write_scan_event(barcode)

            except socket.timeout:
                # Fallback:
                # If data arrived but no CR/LF arrived after it, treat the idle
                # buffer as one complete barcode/event.
                if buffer:
                    logger.write_scan_event(buffer)
                    buffer = ""

            except ConnectionResetError:
                print(f"Scanner connection reset from {addr[0]}:{addr[1]}")
                break


def main():
    parser = argparse.ArgumentParser(description="HF811 daily FedEx tracking CSV logger")

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show the receiver version and exit",
    )

    parser.add_argument("--host", default="0.0.0.0", help="IP address to listen on")
    parser.add_argument("--port", type=int, default=55256, help="TCP port to listen on")

    parser.add_argument(
        "--output-dir",
        default="/scanner-logs",
        help="Folder where dated CSV files, scan_totals.csv, and failed_scans.csv will be created",
    )

    parser.add_argument(
        "--prefix",
        default="Site_Shipped_Tracking",
        help="Daily CSV filename prefix",
    )

    parser.add_argument(
        "--no-read-message",
        default="__NO_READ__",
        help="Exact scanner No Read Message text to treat as FAILED",
    )

    parser.add_argument(
        "--success-length",
        type=int,
        default=34,
        help="Required numeric tracking length for SUCCESS",
    )

    args = parser.parse_args()

    print(f"Industrial Scanner Logger v{__version__}")

    logger = DailyCsvLogger(
        output_dir=Path(args.output_dir),
        file_prefix=args.prefix,
        no_read_message=args.no_read_message,
        success_length=args.success_length,
    )

    print(f"Listening on {args.host}:{args.port}")
    print(f"No-read message treated as FAILED: {args.no_read_message}")
    print(f"Success rule: exactly {args.success_length} numeric digits")
    print("Press Ctrl+C to stop.")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(5)

    try:
        while True:
            conn, addr = server.accept()

            thread = threading.Thread(
                target=handle_client,
                args=(conn, addr, logger),
                daemon=True,
            )
            thread.start()

    except KeyboardInterrupt:
        print("\nStopping listener.")

    finally:
        server.close()


if __name__ == "__main__":
    main()

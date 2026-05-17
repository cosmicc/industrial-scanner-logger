#!/usr/bin/env python3
"""
HF811 Daily FedEx Tracking TCP Listener

Creates a new dated CSV file each day.

Daily scan CSV format:
    date,time,scanner_id,status,tracking

Failed scans CSV:
    /scanner-logs/failed_scans.csv

Failed scans CSV format:
    date,time,scanner_id,failed_barcode

Daily totals CSV:
    /scanner-logs/scan_totals.csv

Daily totals CSV format:
    date,scanner_id,total_events,successful_scans,failed_scans

Console output format:
    Event:<number> Success:<number> Failed:<number> Scanner:<id>
    ScannerEvent:<number> ScannerSuccess:<number> ScannerFailed:<number>
    Status:<SUCCESS|FAILED> Time:<time> Barcode:<barcode>

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
import time
from datetime import datetime
from pathlib import Path

from industrial_scanner_logger._version import __version__


# False = successful FedEx tracking numbers are logged only once per day.
# Failed scans are always logged.
LOG_DUPLICATE_SUCCESS_SCANS = False

DEFAULT_MAX_BARCODE_CHARS = 256
DEFAULT_MAX_CLIENTS = 8
DEFAULT_FRAME_IDLE_TIMEOUT_SECONDS = 0.25
DEFAULT_CLIENT_IDLE_TIMEOUT_SECONDS = 300.0
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 5.0
LOG_BARCODE_PREVIEW_CHARS = 120
MIN_MAX_BARCODE_CHARS = 64
UNKNOWN_SCANNER_ID = "UNKNOWN"
ALL_SCANNERS_ID = "ALL"

SAFE_FILE_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SCANNER_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def clean_barcode(raw: str) -> str:
    """
    Remove common TCP/scanner line endings and surrounding whitespace.
    Keeps the actual barcode content intact.
    """
    return raw.strip("\r\n\t \x00")


def validate_file_prefix(file_prefix: str) -> str:
    """
    Keep daily CSV names inside the output directory and shell-friendly.
    """
    if not SAFE_FILE_PREFIX_RE.match(file_prefix):
        raise ValueError(
            "CSV filename prefix must start with a letter or number and contain only "
            "letters, numbers, underscore, dash, or dot"
        )

    if file_prefix in {".", ".."}:
        raise ValueError("CSV filename prefix cannot be '.' or '..'")

    return file_prefix


def validate_positive_int(value: int, name: str) -> int:
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")

    return value


def validate_positive_float(value: float, name: str) -> float:
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")

    return value


def oversized_scan_marker(raw_length: int) -> str:
    return f"__OVERSIZED_SCAN_LENGTH_{raw_length}__"


def truncate_for_log(value: str, max_chars: int = LOG_BARCODE_PREVIEW_CHARS) -> str:
    """
    Keep console and journal lines bounded even for malformed scanner input.
    """
    display_value = value.replace("\r", "\\r").replace("\n", "\\n")

    if len(display_value) <= max_chars:
        return display_value

    omitted = len(display_value) - max_chars
    return f"{display_value[:max_chars]}...[truncated {omitted} chars]"


def normalize_scanner_id(scanner_id: str) -> str:
    scanner_id = clean_barcode(str(scanner_id))

    if not scanner_id:
        return UNKNOWN_SCANNER_ID

    if SCANNER_ID_RE.match(scanner_id):
        return scanner_id

    return UNKNOWN_SCANNER_ID


def scanner_id_from_addr(addr) -> str:
    """
    Identify scanners by the last octet of their IPv4 address.
    Example: 10.10.10.20 -> 20.
    """
    try:
        host = str(addr[0])
    except (IndexError, TypeError):
        return UNKNOWN_SCANNER_ID

    octets = host.split(".")

    if len(octets) == 4 and all(octet.isdigit() for octet in octets):
        last_octet = int(octets[-1])

        if 0 <= last_octet <= 255 and all(
            0 <= int(octet) <= 255 for octet in octets
        ):
            return str(last_octet)

    return UNKNOWN_SCANNER_ID


class DailyCsvLogger:
    def __init__(
        self,
        output_dir: Path,
        file_prefix: str,
        no_read_message: str,
        success_length: int,
        max_barcode_chars: int = DEFAULT_MAX_BARCODE_CHARS,
    ):
        self.output_dir = output_dir
        self.file_prefix = validate_file_prefix(file_prefix)
        self.no_read_message = no_read_message
        self.success_length = validate_positive_int(success_length, "success_length")
        self.max_barcode_chars = validate_positive_int(
            max_barcode_chars,
            "max_barcode_chars",
        )

        if self.max_barcode_chars < MIN_MAX_BARCODE_CHARS:
            raise ValueError(
                f"max_barcode_chars must be at least {MIN_MAX_BARCODE_CHARS}"
            )

        if self.success_length > self.max_barcode_chars:
            raise ValueError("success_length cannot be greater than max_barcode_chars")

        if len(self.no_read_message) > self.max_barcode_chars:
            raise ValueError("no_read_message cannot be longer than max_barcode_chars")

        self.lock = threading.Lock()

        self.current_date = None
        self.current_csv_path = None

        self.seen_success_barcodes_by_scanner = {}
        self.scanner_counts = {}

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

    def _migration_temp_path(self, path: Path) -> Path:
        return path.with_name(f".{path.name}.migrating-{self._timestamp_string()}")

    def _normalize_barcode_for_storage(self, barcode: str) -> str:
        if len(barcode) <= self.max_barcode_chars:
            return barcode

        return oversized_scan_marker(len(barcode))

    def _new_counts(self):
        return {
            "total_events": 0,
            "successful_scans": 0,
            "failed_scans": 0,
        }

    def _get_counts(self, scanner_id: str):
        scanner_id = normalize_scanner_id(scanner_id)
        return self.scanner_counts.setdefault(scanner_id, self._new_counts())

    def _get_seen_successes(self, scanner_id: str):
        scanner_id = normalize_scanner_id(scanner_id)
        return self.seen_success_barcodes_by_scanner.setdefault(scanner_id, set())

    def _recalculate_total_counts(self):
        self.event_count = sum(
            counts["total_events"] for counts in self.scanner_counts.values()
        )
        self.success_count = sum(
            counts["successful_scans"] for counts in self.scanner_counts.values()
        )
        self.failed_count = sum(
            counts["failed_scans"] for counts in self.scanner_counts.values()
        )

    def _build_all_scanners_counts(self):
        return self._aggregate_counts(self.scanner_counts)

    def _aggregate_counts(self, counts_by_scanner):
        return {
            "total_events": sum(
                counts["total_events"] for counts in counts_by_scanner.values()
            ),
            "successful_scans": sum(
                counts["successful_scans"] for counts in counts_by_scanner.values()
            ),
            "failed_scans": sum(
                counts["failed_scans"] for counts in counts_by_scanner.values()
            ),
        }

    def _parse_nonnegative_count(self, row, field_name: str, date_str: str):
        raw_value = row.get(field_name) or 0

        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            print(
                f"Skipping totals row for {date_str}: "
                f"invalid {field_name}={raw_value!r}"
            )
            return None

        if value < 0:
            print(
                f"Skipping totals row for {date_str}: "
                f"invalid negative {field_name}={value}"
            )
            return None

        return value

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
            date,time,scanner_id,status,tracking
        """
        expected_header = ["date", "time", "scanner_id", "status", "tracking"]

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
        temp_path = self._migration_temp_path(csv_path)

        try:
            with (
                csv_path.open("r", newline="", encoding="utf-8") as source,
                temp_path.open("w", newline="", encoding="utf-8") as target,
            ):
                reader = csv.DictReader(source)
                writer = csv.writer(target)
                writer.writerow(expected_header)

                for row in reader:
                    date_str = clean_barcode(row.get("date", ""))
                    time_str = clean_barcode(row.get("time", ""))
                    scanner_id = normalize_scanner_id(
                        row.get("scanner_id", "") or UNKNOWN_SCANNER_ID
                    )
                    tracking = clean_barcode(
                        row.get("tracking", "") or row.get("barcode", "")
                    )
                    was_oversized = len(tracking) > self.max_barcode_chars
                    tracking = self._normalize_barcode_for_storage(tracking)
                    status = clean_barcode(row.get("status", ""))

                    if was_oversized:
                        status = "FAILED"

                    elif status not in {"SUCCESS", "FAILED"}:
                        status = self._classify_scan(tracking)

                    csv_tracking = "" if tracking == self.no_read_message else tracking
                    writer.writerow([
                        date_str,
                        time_str,
                        scanner_id,
                        status,
                        csv_tracking,
                    ])

            temp_path.replace(csv_path)

        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        print(f"Migrated daily CSV header: {csv_path}")

    def _ensure_totals_file(self):
        """
        Ensure scan_totals.csv exists with the latest header.

        If an older totals file exists with:
            date,total_unique_scans

        it is migrated to:
            date,scanner_id,total_events,successful_scans,failed_scans

        Old total_unique_scans values are treated as ALL scanner totals with failed_scans=0.
        """
        expected_header = [
            "date",
            "scanner_id",
            "total_events",
            "successful_scans",
            "failed_scans",
        ]

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
        temp_path = self._migration_temp_path(self.totals_path)

        try:
            with (
                self.totals_path.open("r", newline="", encoding="utf-8") as source,
                temp_path.open("w", newline="", encoding="utf-8") as target,
            ):
                reader = csv.DictReader(source)
                writer = csv.writer(target)
                writer.writerow(expected_header)

                for row in reader:
                    date_str = clean_barcode(row.get("date", ""))
                    scanner_id = normalize_scanner_id(
                        row.get("scanner_id", "") or ALL_SCANNERS_ID
                    )

                    if not DATE_RE.match(date_str):
                        continue

                    if "total_unique_scans" in row:
                        successful = self._parse_nonnegative_count(
                            row, "total_unique_scans", date_str
                        )
                        if successful is None:
                            continue

                        total_events = successful
                        failed = 0

                    else:
                        total_events = self._parse_nonnegative_count(
                            row, "total_events", date_str
                        )
                        successful = self._parse_nonnegative_count(
                            row, "successful_scans", date_str
                        )
                        failed = self._parse_nonnegative_count(
                            row, "failed_scans", date_str
                        )

                        if None in {total_events, successful, failed}:
                            continue

                    writer.writerow([
                        date_str,
                        scanner_id,
                        total_events,
                        successful,
                        failed,
                    ])

            temp_path.replace(self.totals_path)

        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        print(f"Migrated totals CSV header: {self.totals_path}")

    def _ensure_failed_scans_file(self):
        expected_header = ["date", "time", "scanner_id", "failed_barcode"]

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
        temp_path = self._migration_temp_path(self.failed_scans_path)

        try:
            with (
                self.failed_scans_path.open("r", newline="", encoding="utf-8") as source,
                temp_path.open("w", newline="", encoding="utf-8") as target,
            ):
                reader = csv.DictReader(source)
                writer = csv.writer(target)
                writer.writerow(expected_header)

                for row in reader:
                    date_str = clean_barcode(row.get("date", ""))
                    time_str = clean_barcode(row.get("time", ""))
                    scanner_id = normalize_scanner_id(
                        row.get("scanner_id", "") or UNKNOWN_SCANNER_ID
                    )
                    failed_barcode = clean_barcode(
                        row.get("failed_barcode", "")
                        or row.get("tracking", "")
                        or row.get("barcode", "")
                    )
                    failed_barcode = self._normalize_barcode_for_storage(
                        failed_barcode
                    )
                    writer.writerow([date_str, time_str, scanner_id, failed_barcode])

            temp_path.replace(self.failed_scans_path)

        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        print(f"Migrated failed scans CSV header: {self.failed_scans_path}")

    def _load_existing_day_state(self, csv_path: Path):
        """
        Load today's CSV state after restart so console counters resume correctly.
        """
        seen_success_by_scanner = {}
        counts_by_scanner = {}

        if not csv_path.exists():
            return seen_success_by_scanner, counts_by_scanner

        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                scanner_id = normalize_scanner_id(
                    row.get("scanner_id", "") or UNKNOWN_SCANNER_ID
                )
                counts = counts_by_scanner.setdefault(scanner_id, self._new_counts())
                tracking = clean_barcode(
                    row.get("tracking", "") or row.get("barcode", "")
                )
                was_oversized = len(tracking) > self.max_barcode_chars
                tracking = self._normalize_barcode_for_storage(tracking)

                status = clean_barcode(row.get("status", ""))

                if was_oversized:
                    status = "FAILED"

                elif status not in {"SUCCESS", "FAILED"}:
                    status = self._classify_scan(tracking)

                counts["total_events"] += 1

                if status == "SUCCESS":
                    counts["successful_scans"] += 1
                    if tracking:
                        seen_success_by_scanner.setdefault(scanner_id, set()).add(
                            tracking
                        )
                else:
                    counts["failed_scans"] += 1

        return seen_success_by_scanner, counts_by_scanner

    def _count_csv_day(self, csv_path: Path):
        """
        Count total, success, and failed rows in a dated CSV.
        """
        if not csv_path.exists():
            return {}

        counts_by_scanner = {}

        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                scanner_id = normalize_scanner_id(
                    row.get("scanner_id", "") or UNKNOWN_SCANNER_ID
                )
                counts = counts_by_scanner.setdefault(scanner_id, self._new_counts())
                tracking = clean_barcode(
                    row.get("tracking", "") or row.get("barcode", "")
                )
                was_oversized = len(tracking) > self.max_barcode_chars
                tracking = self._normalize_barcode_for_storage(tracking)

                status = clean_barcode(row.get("status", ""))

                if was_oversized:
                    status = "FAILED"

                elif status not in {"SUCCESS", "FAILED"}:
                    status = self._classify_scan(tracking)

                counts["total_events"] += 1

                if status == "SUCCESS":
                    counts["successful_scans"] += 1
                else:
                    counts["failed_scans"] += 1

        return counts_by_scanner

    def _existing_total_keys(self):
        keys = set()

        if not self.totals_path.exists():
            return keys

        with self.totals_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                date_part = clean_barcode(row.get("date", ""))
                scanner_id = normalize_scanner_id(
                    row.get("scanner_id", "") or ALL_SCANNERS_ID
                )

                if DATE_RE.match(date_part):
                    keys.add((date_part, scanner_id))

        return keys

    def _append_scan_total(
        self,
        date_str: str,
        scanner_id: str,
        total_events: int,
        successful_scans: int,
        failed_scans: int,
    ):
        """
        Append one completed scanner/day total to scan_totals.csv.
        Avoids duplicate date/scanner entries.
        """
        scanner_id = normalize_scanner_id(scanner_id)
        existing_keys = self._existing_total_keys()

        if (date_str, scanner_id) in existing_keys:
            return

        with self.totals_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                date_str,
                scanner_id,
                total_events,
                successful_scans,
                failed_scans,
            ])

        print(
            f"Daily total written: {date_str},{scanner_id},"
            f"{total_events},{successful_scans},{failed_scans}"
        )

    def _append_scan_totals_for_day(self, date_str: str, counts_by_scanner):
        for scanner_id in sorted(counts_by_scanner):
            counts = counts_by_scanner[scanner_id]
            self._append_scan_total(
                date_str,
                scanner_id,
                counts["total_events"],
                counts["successful_scans"],
                counts["failed_scans"],
            )

        aggregate_counts = self._aggregate_counts(counts_by_scanner)
        self._append_scan_total(
            date_str,
            ALL_SCANNERS_ID,
            aggregate_counts["total_events"],
            aggregate_counts["successful_scans"],
            aggregate_counts["failed_scans"],
        )

    def _write_missing_prior_totals(self):
        """
        On startup, write totals for any old dated CSVs that do not already
        have an entry in scan_totals.csv.
        """
        today = self._today_string()

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

            self._ensure_daily_csv_header(csv_path)

            counts_by_scanner = self._count_csv_day(csv_path)
            self._append_scan_totals_for_day(file_date, counts_by_scanner)

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
            self._append_scan_totals_for_day(self.current_date, self.scanner_counts)

        self.current_date = today
        self.current_csv_path = self._csv_path_for_date(today)

        self._ensure_daily_csv_header(self.current_csv_path)

        (
            self.seen_success_barcodes_by_scanner,
            self.scanner_counts,
        ) = self._load_existing_day_state(self.current_csv_path)
        self._recalculate_total_counts()

        print("=" * 80)
        print(f"Now logging to: {self.current_csv_path.resolve()}")
        print(f"Starting event count: {self.event_count}")
        print(f"Starting successful scan count: {self.success_count}")
        print(f"Starting failed scan count: {self.failed_count}")
        print(f"Starting scanner count: {len(self.scanner_counts)}")
        print(f"Daily totals file: {self.totals_path.resolve()}")
        print(f"Failed scans file: {self.failed_scans_path.resolve()}")
        print(f"Success rule: exactly {self.success_length} numeric digits")
        print("=" * 80)

    def _append_failed_scan(
        self,
        date_str: str,
        time_str: str,
        scanner_id: str,
        failed_barcode: str,
    ):
        """
        Append failed scan to failed_scans.csv forever.
        This file does not roll over.
        """
        with self.failed_scans_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([date_str, time_str, scanner_id, failed_barcode])

    def write_scan_event(self, raw_barcode: str, scanner_id: str = UNKNOWN_SCANNER_ID):
        scanner_id = normalize_scanner_id(scanner_id)
        barcode = self._normalize_barcode_for_storage(clean_barcode(raw_barcode))

        if not barcode:
            return

        with self.lock:
            self._rotate_if_needed()

            status = self._classify_scan(barcode)
            scanner_counts = self._get_counts(scanner_id)
            seen_success_barcodes = self._get_seen_successes(scanner_id)

            if status == "SUCCESS":
                if barcode in seen_success_barcodes and not LOG_DUPLICATE_SUCCESS_SCANS:
                    print(
                        f"Duplicate ignored - Scanner:{scanner_id} "
                        f"Barcode:{truncate_for_log(barcode)}"
                    )
                    return

                seen_success_barcodes.add(barcode)
                scanner_counts["successful_scans"] += 1
                self.success_count += 1

            else:
                scanner_counts["failed_scans"] += 1
                self.failed_count += 1

            scanner_counts["total_events"] += 1
            self.event_count += 1

            date_str = self.current_date
            time_str = self._time_string()

            # Daily CSV:
            # For scanner no-read, keep tracking blank.
            # For partial/invalid/short/long decodes, keep the decoded value for review.
            csv_tracking = "" if barcode == self.no_read_message else barcode

            with self.current_csv_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([date_str, time_str, scanner_id, status, csv_tracking])

            # Forever-appended failed scan CSV:
            # Keep the no-read message visible here so the failure is explicit.
            if status == "FAILED":
                self._append_failed_scan(date_str, time_str, scanner_id, barcode)

            print(
                f"Event:{self.event_count} "
                f"Success:{self.success_count} "
                f"Failed:{self.failed_count} "
                f"Scanner:{scanner_id} "
                f"ScannerEvent:{scanner_counts['total_events']} "
                f"ScannerSuccess:{scanner_counts['successful_scans']} "
                f"ScannerFailed:{scanner_counts['failed_scans']} "
                f"Status:{status} "
                f"Time:{time_str} "
                f"Barcode:{truncate_for_log(barcode)}"
            )


def address_label(addr) -> str:
    try:
        return f"{addr[0]}:{addr[1]}"
    except (IndexError, TypeError):
        return str(addr)


def write_client_scan(
    logger: DailyCsvLogger,
    barcode: str,
    addr,
    scanner_id: str,
    fatal_event: threading.Event,
) -> bool:
    try:
        logger.write_scan_event(barcode, scanner_id)
        return True

    except Exception as exc:
        print(
            f"Fatal logging error for {address_label(addr)} "
            f"ScannerID:{scanner_id}: {exc}"
        )
        fatal_event.set()
        return False


def handle_client(
    conn: socket.socket,
    addr,
    logger: DailyCsvLogger,
    stop_event: threading.Event,
    fatal_event: threading.Event,
    max_barcode_chars: int,
    frame_idle_timeout: float,
    client_idle_timeout: float,
):
    scanner_id = scanner_id_from_addr(addr)
    print(f"Scanner connected from {address_label(addr)} ScannerID:{scanner_id}")

    buffer = ""
    last_data_time = time.monotonic()

    # Timeout fallback:
    # If the scanner sends data without CR/LF, flush the idle buffer as one event.
    conn.settimeout(frame_idle_timeout)

    with conn:
        while not stop_event.is_set() and not fatal_event.is_set():
            try:
                data = conn.recv(4096)

                if not data:
                    print(
                        f"Scanner disconnected from {address_label(addr)} "
                        f"ScannerID:{scanner_id}"
                    )
                    break

                last_data_time = time.monotonic()
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

                    if len(barcode) > max_barcode_chars:
                        marker = oversized_scan_marker(len(barcode))
                        print(
                            f"Oversized barcode frame from {address_label(addr)} "
                            f"ScannerID:{scanner_id} rejected at {len(barcode)} "
                            "characters"
                        )
                        write_client_scan(logger, marker, addr, scanner_id, fatal_event)
                        return

                    if not write_client_scan(
                        logger,
                        barcode,
                        addr,
                        scanner_id,
                        fatal_event,
                    ):
                        return

                if len(buffer) > max_barcode_chars:
                    marker = oversized_scan_marker(len(buffer))
                    print(
                        f"Oversized barcode frame from {address_label(addr)} "
                        f"ScannerID:{scanner_id} rejected at {len(buffer)} "
                        "characters"
                    )
                    write_client_scan(logger, marker, addr, scanner_id, fatal_event)
                    return

            except socket.timeout:
                # Fallback:
                # If data arrived but no CR/LF arrived after it, treat the idle
                # buffer as one complete barcode/event.
                if buffer:
                    if not write_client_scan(
                        logger,
                        buffer,
                        addr,
                        scanner_id,
                        fatal_event,
                    ):
                        return
                    buffer = ""

                elif time.monotonic() - last_data_time >= client_idle_timeout:
                    print(
                        f"Scanner idle timeout from {address_label(addr)} "
                        f"ScannerID:{scanner_id}"
                    )
                    break

            except ConnectionResetError:
                print(
                    f"Scanner connection reset from {address_label(addr)} "
                    f"ScannerID:{scanner_id}"
                )
                break

            except OSError as exc:
                print(
                    f"Scanner socket error from {address_label(addr)} "
                    f"ScannerID:{scanner_id}: {exc}"
                )
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

    parser.add_argument(
        "--max-barcode-chars",
        type=int,
        default=DEFAULT_MAX_BARCODE_CHARS,
        help=(
            "Maximum accepted characters in one scanner frame before the frame "
            "is logged as oversized and the client is disconnected"
        ),
    )

    parser.add_argument(
        "--max-clients",
        type=int,
        default=DEFAULT_MAX_CLIENTS,
        help="Maximum simultaneous scanner TCP clients",
    )

    parser.add_argument(
        "--frame-idle-timeout",
        type=float,
        default=DEFAULT_FRAME_IDLE_TIMEOUT_SECONDS,
        help="Seconds of read idleness before a partial barcode frame is flushed",
    )

    parser.add_argument(
        "--client-idle-timeout",
        type=float,
        default=DEFAULT_CLIENT_IDLE_TIMEOUT_SECONDS,
        help="Seconds before disconnecting an idle client with no buffered barcode",
    )

    parser.add_argument(
        "--shutdown-timeout",
        type=float,
        default=DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
        help="Seconds to wait for connected scanner threads during shutdown",
    )

    args = parser.parse_args()

    try:
        validate_file_prefix(args.prefix)
        validate_positive_int(args.port, "port")
        validate_positive_int(args.success_length, "success_length")
        validate_positive_int(args.max_barcode_chars, "max_barcode_chars")
        validate_positive_int(args.max_clients, "max_clients")
        validate_positive_float(args.frame_idle_timeout, "frame_idle_timeout")
        validate_positive_float(args.client_idle_timeout, "client_idle_timeout")
        validate_positive_float(args.shutdown_timeout, "shutdown_timeout")

        if args.port > 65535:
            raise ValueError("port must be between 1 and 65535")

        if args.max_barcode_chars < MIN_MAX_BARCODE_CHARS:
            raise ValueError(
                f"max_barcode_chars must be at least {MIN_MAX_BARCODE_CHARS}"
            )

        if args.success_length > args.max_barcode_chars:
            raise ValueError("success_length cannot be greater than max_barcode_chars")

        if len(args.no_read_message) > args.max_barcode_chars:
            raise ValueError("no_read_message cannot be longer than max_barcode_chars")

    except ValueError as exc:
        parser.error(str(exc))

    print(f"Industrial Scanner Logger v{__version__}")

    logger = DailyCsvLogger(
        output_dir=Path(args.output_dir),
        file_prefix=args.prefix,
        no_read_message=args.no_read_message,
        success_length=args.success_length,
        max_barcode_chars=args.max_barcode_chars,
    )

    print(f"Listening on {args.host}:{args.port}")
    print(f"No-read message treated as FAILED: {args.no_read_message}")
    print(f"Success rule: exactly {args.success_length} numeric digits")
    print(f"Maximum barcode frame length: {args.max_barcode_chars} characters")
    print(f"Maximum simultaneous clients: {args.max_clients}")
    print("Press Ctrl+C to stop.")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(args.max_clients)
    server.settimeout(0.5)

    stop_event = threading.Event()
    fatal_event = threading.Event()
    active_threads = set()
    active_threads_lock = threading.Lock()

    def cleanup_threads():
        with active_threads_lock:
            finished_threads = {
                thread for thread in active_threads if not thread.is_alive()
            }
            active_threads.difference_update(finished_threads)

    def client_runner(client_conn, client_addr):
        try:
            handle_client(
                client_conn,
                client_addr,
                logger,
                stop_event,
                fatal_event,
                args.max_barcode_chars,
                args.frame_idle_timeout,
                args.client_idle_timeout,
            )
        finally:
            with active_threads_lock:
                active_threads.discard(threading.current_thread())

    try:
        while not stop_event.is_set() and not fatal_event.is_set():
            cleanup_threads()

            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue

            with active_threads_lock:
                active_count = len(active_threads)

            if active_count >= args.max_clients:
                scanner_id = scanner_id_from_addr(addr)
                print(
                    f"Rejecting scanner connection from {address_label(addr)}: "
                    f"ScannerID:{scanner_id} maximum clients reached "
                    f"({args.max_clients})"
                )
                conn.close()
                continue

            thread = threading.Thread(
                target=client_runner,
                args=(conn, addr),
            )

            with active_threads_lock:
                active_threads.add(thread)

            thread.start()

    except KeyboardInterrupt:
        print("\nStopping listener.")

    finally:
        stop_event.set()
        server.close()

        with active_threads_lock:
            threads_to_join = list(active_threads)

        for thread in threads_to_join:
            thread.join(timeout=args.shutdown_timeout)

    if fatal_event.is_set():
        print("Stopping listener after fatal logging error.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

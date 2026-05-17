import csv
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from industrial_scanner_logger import __version__  # noqa: E402
from industrial_scanner_logger.receiver import (  # noqa: E402
    DailyCsvLogger,
    clean_barcode,
    handle_client,
    oversized_scan_marker,
    scanner_id_from_addr,
)


class FakeSocket:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def recv(self, _size):
        if self.chunks:
            return self.chunks.pop(0)

        return b""

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self.close()


class ReceiverTests(unittest.TestCase):
    def test_project_version_is_1_1_0(self):
        self.assertEqual(__version__, "1.1.0")

    def test_clean_barcode_removes_scanner_line_noise(self):
        self.assertEqual(clean_barcode("\x0012345\r\n"), "12345")
        self.assertEqual(clean_barcode("\tABC123 "), "ABC123")

    def test_scanner_id_from_addr_uses_last_ipv4_octet(self):
        self.assertEqual(scanner_id_from_addr(("10.10.10.20", 55256)), "20")
        self.assertEqual(scanner_id_from_addr(("192.168.1.7", 55256)), "7")
        self.assertEqual(scanner_id_from_addr(("localhost", 55256)), "UNKNOWN")

    def test_classify_scan_accepts_only_expected_numeric_length(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
            )

            self.assertEqual(logger._classify_scan("1" * 34), "SUCCESS")
            self.assertEqual(logger._classify_scan("1" * 33), "FAILED")
            self.assertEqual(logger._classify_scan("A" * 34), "FAILED")
            self.assertEqual(logger._classify_scan("__NO_READ__"), "FAILED")

    def test_rejects_unsafe_file_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                DailyCsvLogger(
                    output_dir=Path(temp_dir),
                    file_prefix="../bad",
                    no_read_message="__NO_READ__",
                    success_length=34,
                )

    def test_oversized_scan_is_logged_as_marker_not_raw_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
                max_barcode_chars=64,
            )

            payload = "X" * 200
            expected_marker = oversized_scan_marker(len(payload))

            logger.write_scan_event(payload)

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(rows[0]["status"], "FAILED")
            self.assertEqual(rows[0]["scanner_id"], "UNKNOWN")
            self.assertEqual(rows[0]["tracking"], expected_marker)
            self.assertNotEqual(rows[0]["tracking"], payload)

            with logger.failed_scans_path.open(newline="", encoding="utf-8") as f:
                failed_rows = list(csv.DictReader(f))

            self.assertEqual(failed_rows[0]["scanner_id"], "UNKNOWN")
            self.assertEqual(failed_rows[0]["failed_barcode"], expected_marker)

    def test_totals_migration_skips_corrupt_counts(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            output_dir = Path(temp_dir)
            totals_path = output_dir / "scan_totals.csv"
            output_dir.mkdir(parents=True, exist_ok=True)

            with totals_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "total_unique_scans"])
                writer.writerow(["2026-05-15", "not-a-number"])
                writer.writerow(["2026-05-16", "3"])

            DailyCsvLogger(
                output_dir=output_dir,
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
            )

            with totals_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(
                rows,
                [
                    {
                        "date": "2026-05-16",
                        "scanner_id": "ALL",
                        "total_events": "3",
                        "successful_scans": "3",
                        "failed_scans": "0",
                    }
                ],
            )

    def test_client_handler_closes_oversized_undelimited_frame(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
                max_barcode_chars=64,
            )
            payload = b"X" * 80
            fake_sock = FakeSocket([payload])
            stop_event = threading.Event()
            fatal_event = threading.Event()

            handle_client(
                fake_sock,
                ("10.10.10.20", 0),
                logger,
                stop_event,
                fatal_event,
                64,
                0.05,
                1.0,
            )

            self.assertTrue(fake_sock.closed)
            self.assertFalse(fatal_event.is_set())

            with logger.failed_scans_path.open(newline="", encoding="utf-8") as f:
                failed_rows = list(csv.DictReader(f))

            self.assertEqual(
                failed_rows[0]["failed_barcode"],
                oversized_scan_marker(len(payload)),
            )
            self.assertEqual(failed_rows[0]["scanner_id"], "20")

    def test_duplicate_success_rule_is_per_scanner(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
            )

            valid_tracking = "1" * 34

            logger.write_scan_event(valid_tracking, "20")
            logger.write_scan_event(valid_tracking, "20")
            logger.write_scan_event(valid_tracking, "21")

            self.assertEqual(logger.event_count, 2)
            self.assertEqual(logger.success_count, 2)
            self.assertEqual(logger.failed_count, 0)

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual([row["scanner_id"] for row in rows], ["20", "21"])
            self.assertEqual([row["tracking"] for row in rows], [valid_tracking] * 2)

            logger._append_scan_totals_for_day("2026-05-16", logger.scanner_counts)

            with logger.totals_path.open(newline="", encoding="utf-8") as f:
                totals_rows = list(csv.DictReader(f))

            self.assertEqual(
                totals_rows,
                [
                    {
                        "date": "2026-05-16",
                        "scanner_id": "20",
                        "total_events": "1",
                        "successful_scans": "1",
                        "failed_scans": "0",
                    },
                    {
                        "date": "2026-05-16",
                        "scanner_id": "21",
                        "total_events": "1",
                        "successful_scans": "1",
                        "failed_scans": "0",
                    },
                    {
                        "date": "2026-05-16",
                        "scanner_id": "ALL",
                        "total_events": "2",
                        "successful_scans": "2",
                        "failed_scans": "0",
                    },
                ],
            )

    def test_write_scan_event_logs_success_failure_and_ignores_duplicate_success(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
            )

            valid_tracking = "1" * 34

            logger.write_scan_event(valid_tracking)
            logger.write_scan_event(valid_tracking)
            logger.write_scan_event("__NO_READ__")

            self.assertEqual(logger.event_count, 2)
            self.assertEqual(logger.success_count, 1)
            self.assertEqual(logger.failed_count, 1)

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["scanner_id"], "UNKNOWN")
            self.assertEqual(rows[0]["status"], "SUCCESS")
            self.assertEqual(rows[0]["tracking"], valid_tracking)
            self.assertEqual(rows[1]["scanner_id"], "UNKNOWN")
            self.assertEqual(rows[1]["status"], "FAILED")
            self.assertEqual(rows[1]["tracking"], "")

            with logger.failed_scans_path.open(newline="", encoding="utf-8") as f:
                failed_rows = list(csv.DictReader(f))

            self.assertEqual(len(failed_rows), 1)
            self.assertEqual(failed_rows[0]["scanner_id"], "UNKNOWN")
            self.assertEqual(failed_rows[0]["failed_barcode"], "__NO_READ__")


if __name__ == "__main__":
    unittest.main()

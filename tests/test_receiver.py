import csv
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from industrial_scanner_logger import __version__  # noqa: E402
from industrial_scanner_logger.receiver import DailyCsvLogger, clean_barcode  # noqa: E402


class ReceiverTests(unittest.TestCase):
    def test_project_version_is_1_0_1(self):
        self.assertEqual(__version__, "1.0.1")

    def test_clean_barcode_removes_scanner_line_noise(self):
        self.assertEqual(clean_barcode("\x0012345\r\n"), "12345")
        self.assertEqual(clean_barcode("\tABC123 "), "ABC123")

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
            self.assertEqual(rows[0]["status"], "SUCCESS")
            self.assertEqual(rows[0]["tracking"], valid_tracking)
            self.assertEqual(rows[1]["status"], "FAILED")
            self.assertEqual(rows[1]["tracking"], "")

            with logger.failed_scans_path.open(newline="", encoding="utf-8") as f:
                failed_rows = list(csv.DictReader(f))

            self.assertEqual(len(failed_rows), 1)
            self.assertEqual(failed_rows[0]["failed_barcode"], "__NO_READ__")


if __name__ == "__main__":
    unittest.main()

import csv
import socket
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
    configure_script_logging,
    handle_client,
    load_receiver_config,
    oversized_scan_marker,
    parse_postgresql_table,
    reset_script_logging,
    scanner_id_for_postgresql,
    scanner_id_from_addr,
)


class FakePostgreSQLLogger:
    def __init__(self):
        self.rows = []
        self.closed = False

    def write_scan_event(self, tracking_number, scanner_id, scan_date, scan_time):
        self.rows.append((scan_date, scan_time, scanner_id, tracking_number))
        return True

    def close(self):
        self.closed = True


class FakeSocket:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False
        self.timeout = None
        self.socket_options = []

    def settimeout(self, timeout):
        self.timeout = timeout

    def setsockopt(self, level, option, value):
        self.socket_options.append((level, option, value))

    def recv(self, _size):
        if self.chunks:
            chunk = self.chunks.pop(0)

            if isinstance(chunk, BaseException):
                raise chunk

            return chunk

        return b""

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self.close()


class ReceiverTests(unittest.TestCase):
    def test_project_version_is_1_2_0(self):
        self.assertEqual(__version__, "1.2.0")

    def test_clean_barcode_removes_scanner_line_noise(self):
        self.assertEqual(clean_barcode("\x0012345\r\n"), "12345")
        self.assertEqual(clean_barcode("\tABC123 "), "ABC123")

    def test_scanner_id_from_addr_uses_last_ipv4_octet(self):
        self.assertEqual(scanner_id_from_addr(("10.10.10.20", 55256)), "20")
        self.assertEqual(scanner_id_from_addr(("192.168.1.7", 55256)), "7")
        self.assertEqual(scanner_id_from_addr(("localhost", 55256)), "UNKNOWN")

    def test_scanner_id_for_postgresql_uses_smallint_range(self):
        self.assertEqual(scanner_id_for_postgresql("20"), 20)
        self.assertEqual(scanner_id_for_postgresql("255"), 255)
        self.assertEqual(scanner_id_for_postgresql("UNKNOWN"), 0)
        self.assertEqual(scanner_id_for_postgresql("scanner-A"), 0)

    def test_parse_postgresql_table_requires_safe_schema_table_name(self):
        self.assertEqual(
            parse_postgresql_table("scanner_logger.scan_events"),
            ("scanner_logger", "scan_events"),
        )

        with self.assertRaises(ValueError):
            parse_postgresql_table("scan_events")

        with self.assertRaises(ValueError):
            parse_postgresql_table("scanner_logger.scan-events")

    def test_load_receiver_config_reads_ini_options(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "industrial-scanner-logger.conf"
            config_path.write_text(
                """
[receiver]
host = 127.0.0.1
port = 60000
output_dir = /tmp/scanner-logs
prefix = Test
no_read_message = NOREAD
success_length = 20
max_barcode_chars = 128
max_clients = 3
frame_idle_timeout = 0.5
client_idle_timeout = 0
shutdown_timeout = 2

[logging]
log_file = /tmp/industrial-scanner-logger.log
scan_data_log_dir = /tmp/raw-scans
scan_data_log_prefix = scanner-data

[tcp_keepalive]
enabled = false
idle = 30
interval = 10
probes = 2

[postgresql]
enabled = true
required = true
dsn = postgresql:///scannerlogger?host=/var/run/postgresql&user=scannerlogger
table = scanner_logger.scan_events
connect_timeout = 4
retry_interval = 12

[api]
enabled = true
host = 0.0.0.0
port = 8080
root_path = /api
log_level = warning
""".strip(),
                encoding="utf-8",
            )

            config = load_receiver_config(str(config_path))

            self.assertTrue(config.config_loaded)
            self.assertEqual(config.host, "127.0.0.1")
            self.assertEqual(config.port, 60000)
            self.assertEqual(config.output_dir, "/tmp/scanner-logs")
            self.assertEqual(config.prefix, "Test")
            self.assertEqual(config.no_read_message, "NOREAD")
            self.assertEqual(config.success_length, 20)
            self.assertEqual(config.max_barcode_chars, 128)
            self.assertEqual(config.max_clients, 3)
            self.assertEqual(config.frame_idle_timeout, 0.5)
            self.assertEqual(config.client_idle_timeout, 0)
            self.assertEqual(config.shutdown_timeout, 2)
            self.assertEqual(config.log_file, "/tmp/industrial-scanner-logger.log")
            self.assertEqual(config.scan_data_log_dir, "/tmp/raw-scans")
            self.assertEqual(config.scan_data_log_prefix, "scanner-data")
            self.assertTrue(config.disable_tcp_keepalive)
            self.assertEqual(config.tcp_keepalive_idle, 30)
            self.assertEqual(config.tcp_keepalive_interval, 10)
            self.assertEqual(config.tcp_keepalive_probes, 2)
            self.assertTrue(config.postgresql_enabled)
            self.assertTrue(config.postgresql_required)
            self.assertEqual(config.postgresql_table, "scanner_logger.scan_events")
            self.assertEqual(config.postgresql_connect_timeout, 4)
            self.assertEqual(config.postgresql_retry_interval, 12)
            self.assertTrue(config.api_enabled)
            self.assertEqual(config.api_host, "0.0.0.0")
            self.assertEqual(config.api_port, 8080)
            self.assertEqual(config.api_root_path, "/api")
            self.assertEqual(config.api_log_level, "warning")

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

    def test_client_handler_flushes_undelimited_scan_on_disconnect(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
            )
            valid_tracking = b"2" * 34
            fake_sock = FakeSocket([valid_tracking, b""])

            handle_client(
                fake_sock,
                ("10.10.10.20", 0),
                logger,
                threading.Event(),
                threading.Event(),
                256,
                10.0,
                0,
            )

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["scanner_id"], "20")
            self.assertEqual(rows[0]["status"], "SUCCESS")
            self.assertEqual(rows[0]["tracking"], valid_tracking.decode("ascii"))

    def test_disabled_client_idle_timeout_keeps_scanner_until_data_arrives(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
            )
            valid_tracking = (b"3" * 34) + b"\n"
            fake_sock = FakeSocket([socket.timeout(), socket.timeout(), valid_tracking, b""])

            handle_client(
                fake_sock,
                ("10.10.10.21", 0),
                logger,
                threading.Event(),
                threading.Event(),
                256,
                0.01,
                0,
            )

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["scanner_id"], "21")
            self.assertEqual(rows[0]["status"], "SUCCESS")

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

    def test_postgresql_logger_receives_accepted_scan_events_after_dedup(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            postgresql_logger = FakePostgreSQLLogger()
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
                postgresql_logger=postgresql_logger,
            )

            valid_tracking = "4" * 34

            logger.write_scan_event(valid_tracking, "20")
            logger.write_scan_event(valid_tracking, "20")
            logger.write_scan_event("__NO_READ__", "20")

            self.assertEqual(len(postgresql_logger.rows), 2)
            self.assertEqual(postgresql_logger.rows[0][0], logger.current_date)
            self.assertRegex(postgresql_logger.rows[0][1], r"^\d{2}:\d{2}:\d{2}$")
            self.assertEqual(postgresql_logger.rows[0][2:], ("20", valid_tracking))
            self.assertEqual(postgresql_logger.rows[1][0], logger.current_date)
            self.assertRegex(postgresql_logger.rows[1][1], r"^\d{2}:\d{2}:\d{2}$")
            self.assertEqual(postgresql_logger.rows[1][2:], ("20", "__NO_READ__"))

            logger.close()
            self.assertTrue(postgresql_logger.closed)

    def test_script_log_omits_scanner_barcode_data_and_daily_data_log_keeps_it(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            output_dir = Path(temp_dir)
            log_path = output_dir / "industrial-scanner-logger.log"
            valid_tracking = "9" * 34

            configure_script_logging(str(log_path), console=False)

            try:
                logger = DailyCsvLogger(
                    output_dir=output_dir,
                    file_prefix="Test",
                    no_read_message="__NO_READ__",
                    success_length=34,
                )
                logger.write_scan_event(valid_tracking, "20")

                fake_sock = FakeSocket([b""])
                handle_client(
                    fake_sock,
                    ("10.10.10.20", 0),
                    logger,
                    threading.Event(),
                    threading.Event(),
                    256,
                    0.05,
                    1.0,
                )
            finally:
                reset_script_logging()

            script_log = log_path.read_text(encoding="utf-8")
            data_logs = list(output_dir.glob("scanner-log-data-*.log"))

            self.assertIn("Now logging to:", script_log)
            self.assertIn("Scanner connected address=10.10.10.20:0", script_log)
            self.assertIn("Scanner disconnected address=10.10.10.20:0", script_log)
            self.assertNotIn("Scan event recorded", script_log)
            self.assertNotIn(valid_tracking, script_log)
            self.assertEqual(len(data_logs), 1)
            self.assertIn(valid_tracking, data_logs[0].read_text(encoding="utf-8"))

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

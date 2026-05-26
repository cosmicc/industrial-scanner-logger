import csv
import socket
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from industrial_scanner_logger import __version__  # noqa: E402
from industrial_scanner_logger.receiver import (  # noqa: E402
    DAILY_CSV_HEADER,
    DailyCsvLogger,
    clean_barcode,
    configure_script_logging,
    handle_client,
    load_receiver_config,
    oversized_scan_marker,
    parse_configured_scanner_ids,
    parse_postgresql_table,
    reset_script_logging,
    scanner_id_for_postgresql,
    scanner_id_from_addr,
)


class FakePostgreSQLLogger:
    def __init__(self):
        self.rows = []
        self.raw_rows = []
        self.closed = False

    def write_scan_event(
        self,
        tracking_number,
        barcode,
        scanner_id,
        scanner_name,
        scanner_role,
        last_scanner_id,
        is_duplicate,
        is_cross_scanner_duplicate,
        is_repaired,
        scan_date,
        scan_time,
        raw_tracking_number=None,
        raw_barcode=None,
        raw_is_duplicate=False,
        raw_is_cross_scanner_duplicate=False,
        write_scan_event=True,
    ):
        self.raw_rows.append({
            "scan_date": scan_date,
            "scan_time": scan_time,
            "scanner_id": scanner_id,
            "scanner_name": scanner_name,
            "scanner_role": scanner_role,
            "last_scanner_id": last_scanner_id,
            "is_duplicate": raw_is_duplicate,
            "is_cross_scanner_duplicate": raw_is_cross_scanner_duplicate,
            "is_repaired": False,
            "tracking_number": raw_tracking_number or barcode,
            "barcode": raw_barcode or barcode,
        })

        if not write_scan_event:
            return True

        self.rows.append({
            "scan_date": scan_date,
            "scan_time": scan_time,
            "scanner_id": scanner_id,
            "scanner_name": scanner_name,
            "scanner_role": scanner_role,
            "last_scanner_id": last_scanner_id,
            "is_duplicate": is_duplicate,
            "is_cross_scanner_duplicate": is_cross_scanner_duplicate,
            "is_repaired": is_repaired,
            "tracking_number": tracking_number,
            "barcode": barcode,
        })
        return True

    def close(self):
        self.closed = True


class FakeDuplicatePostgreSQLLogger(FakePostgreSQLLogger):
    def __init__(self, duplicate_flags):
        super().__init__()
        self.duplicate_flags = duplicate_flags
        self.duplicate_calls = []

    def duplicate_flags_for_success(
        self,
        scanner_id,
        tracking_number,
        scan_date,
        scan_time,
        last_scanner_id="",
    ):
        self.duplicate_calls.append({
            "scanner_id": scanner_id,
            "tracking_number": tracking_number,
            "scan_date": scan_date,
            "scan_time": scan_time,
            "last_scanner_id": last_scanner_id,
        })
        return self.duplicate_flags


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
    def test_project_version_is_1_2_1(self):
        self.assertEqual(__version__, "1.2.1")

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

    def test_parse_configured_scanner_ids_accepts_comma_and_space_lists(self):
        self.assertEqual(
            parse_configured_scanner_ids(
                "20, 21 22,20",
                "scanners.mandatory_scanner_ids",
            ),
            ["20", "21", "22"],
        )

        with self.assertRaises(ValueError):
            parse_configured_scanner_ids(
                "20,scanner-a",
                "scanners.mandatory_scanner_ids",
            )

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
tracking_repair_enabled = true

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
dsn = postgresql:///scannerlogger?host=/var/run/postgresql&user=scannerlogger
table = scanner_logger.scan_events
connect_timeout = 4
retry_interval = 12

[scanners]
last_scanner_id = 21
mandatory_scanner_ids = 20, 21

[scanner_names]
20 = Lane 1 Scanner
21 = Last Scanner

[dashboard]
current_scan_rate_stale_seconds = 120
health_page_refresh_seconds = 4
tv_dashboard_refresh_seconds = 2
tv_duplicate_alert_enabled = false
tv_duplicate_alert_seconds = 75

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
            self.assertTrue(config.tracking_repair_enabled)
            self.assertEqual(config.log_file, "/tmp/industrial-scanner-logger.log")
            self.assertEqual(config.scan_data_log_dir, "/tmp/raw-scans")
            self.assertEqual(config.scan_data_log_prefix, "scanner-data")
            self.assertTrue(config.disable_tcp_keepalive)
            self.assertEqual(config.tcp_keepalive_idle, 30)
            self.assertEqual(config.tcp_keepalive_interval, 10)
            self.assertEqual(config.tcp_keepalive_probes, 2)
            self.assertEqual(config.postgresql_table, "scanner_logger.scan_events")
            self.assertEqual(config.postgresql_connect_timeout, 4)
            self.assertEqual(config.postgresql_retry_interval, 12)
            self.assertEqual(config.last_scanner_id, "21")
            self.assertEqual(
                config.scanner_names,
                {
                    "20": "Lane 1 Scanner",
                    "21": "Last Scanner",
                },
            )
            self.assertTrue(config.api_enabled)
            self.assertEqual(config.mandatory_scanner_ids, ["20", "21"])
            self.assertEqual(config.current_scan_rate_stale_seconds, 120)
            self.assertEqual(config.health_page_refresh_seconds, 4)
            self.assertEqual(config.tv_dashboard_refresh_seconds, 2)
            self.assertFalse(config.tv_duplicate_alert_enabled)
            self.assertEqual(config.tv_duplicate_alert_seconds, 75)
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

    def test_five_column_daily_csv_migrates_to_rich_header(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            output_dir = Path(temp_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            csv_path = output_dir / f"Test_{today}.csv"
            valid_tracking = "6" * 34

            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "time", "scanner_id", "status", "tracking"])
                writer.writerow([today, "08:00:00", "21", "SUCCESS", valid_tracking])

            DailyCsvLogger(
                output_dir=output_dir,
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
                last_scanner_id="21",
                scanner_names={"21": "Last Scanner"},
            )

            with csv_path.open(newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)

            self.assertEqual(header, DAILY_CSV_HEADER)

            with csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(rows[0]["scanner_id"], "21")
            self.assertEqual(rows[0]["scanner_name"], "Last Scanner")
            self.assertEqual(rows[0]["scanner_role"], "last")
            self.assertEqual(rows[0]["status"], "SUCCESS")
            self.assertEqual(rows[0]["is_duplicate"], "false")
            self.assertEqual(rows[0]["is_cross_scanner_duplicate"], "false")
            self.assertEqual(rows[0]["is_repaired"], "false")
            self.assertEqual(rows[0]["tracking"], valid_tracking)

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

    def test_immediate_repeated_successes_are_logged_without_duplicate_flag(self):
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

            self.assertEqual(logger.event_count, 3)
            self.assertEqual(logger.success_count, 3)
            self.assertEqual(logger.failed_count, 0)

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual([row["scanner_id"] for row in rows], ["20", "20", "21"])
            self.assertEqual([row["tracking"] for row in rows], [valid_tracking] * 3)
            self.assertEqual([row["is_duplicate"] for row in rows], ["false"] * 3)
            self.assertEqual(
                [row["is_cross_scanner_duplicate"] for row in rows],
                ["false"] * 3,
            )

            logger._append_scan_totals_for_day("2026-05-16", logger.scanner_counts)

            with logger.totals_path.open(newline="", encoding="utf-8") as f:
                totals_rows = list(csv.DictReader(f))

            self.assertEqual(
                totals_rows,
                [
                    {
                        "date": "2026-05-16",
                        "scanner_id": "20",
                        "total_events": "2",
                        "successful_scans": "2",
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
                        "total_events": "3",
                        "successful_scans": "3",
                        "failed_scans": "0",
                    },
                ],
            )

    def test_same_scanner_duplicate_requires_three_different_successes_between_scans(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
            )

            tracking_a = "1" * 34
            tracking_b = "2" * 34
            tracking_c = "3" * 34
            tracking_d = "4" * 34

            logger.write_scan_event(tracking_a, "20")
            logger.write_scan_event(tracking_b, "20")
            logger.write_scan_event(tracking_c, "20")
            logger.write_scan_event(tracking_d, "20")
            logger.write_scan_event(tracking_a, "20")

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(rows[-1]["tracking"], tracking_a)
            self.assertEqual(rows[-1]["is_duplicate"], "true")
            self.assertEqual(rows[-1]["is_cross_scanner_duplicate"], "false")

    def test_same_scanner_repeat_before_three_different_successes_is_not_duplicate(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
            )

            tracking_a = "1" * 34
            tracking_b = "2" * 34
            tracking_c = "3" * 34

            logger.write_scan_event(tracking_a, "20")
            logger.write_scan_event(tracking_b, "20")
            logger.write_scan_event(tracking_c, "20")
            logger.write_scan_event(tracking_a, "20")

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(rows[-1]["tracking"], tracking_a)
            self.assertEqual(rows[-1]["is_duplicate"], "false")
            self.assertEqual(rows[-1]["is_cross_scanner_duplicate"], "false")

    def test_duplicate_flags_can_come_from_postgresql_month_lookup(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            postgresql_logger = FakeDuplicatePostgreSQLLogger((True, True))
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
                postgresql_logger=postgresql_logger,
                last_scanner_id="21",
            )

            valid_tracking = "1" * 34

            logger.write_scan_event(valid_tracking, "21")

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(rows[0]["is_duplicate"], "true")
            self.assertEqual(rows[0]["is_cross_scanner_duplicate"], "true")
            self.assertEqual(postgresql_logger.rows[0]["is_duplicate"], True)
            self.assertEqual(
                postgresql_logger.rows[0]["is_cross_scanner_duplicate"],
                True,
            )
            self.assertEqual(
                postgresql_logger.duplicate_calls[0]["scanner_id"],
                "21",
            )
            self.assertEqual(
                postgresql_logger.duplicate_calls[0]["tracking_number"],
                valid_tracking,
            )
            self.assertEqual(
                postgresql_logger.duplicate_calls[0]["last_scanner_id"],
                "21",
            )

    def test_cross_scanner_database_duplicate_becomes_regular_on_non_last_scanner(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            postgresql_logger = FakeDuplicatePostgreSQLLogger((True, True))
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
                postgresql_logger=postgresql_logger,
                last_scanner_id="21",
            )

            valid_tracking = "1" * 34

            logger.write_scan_event(valid_tracking, "20")

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(rows[0]["is_duplicate"], "true")
            self.assertEqual(rows[0]["is_cross_scanner_duplicate"], "false")
            self.assertTrue(postgresql_logger.rows[0]["is_duplicate"])
            self.assertFalse(
                postgresql_logger.rows[0]["is_cross_scanner_duplicate"],
            )

    def test_postgresql_logger_receives_final_and_raw_scan_events(self):
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
            numeric_short = "12345"

            logger.write_scan_event(valid_tracking, "20")
            logger.write_scan_event(valid_tracking, "20")
            logger.write_scan_event("__NO_READ__", "20")
            logger.write_scan_event(numeric_short, "20")

            self.assertEqual(len(postgresql_logger.rows), 3)
            self.assertEqual(len(postgresql_logger.raw_rows), 4)
            self.assertEqual(postgresql_logger.rows[0]["scan_date"], logger.current_date)
            self.assertRegex(
                postgresql_logger.rows[0]["scan_time"],
                r"^\d{2}:\d{2}:\d{2}$",
            )
            self.assertEqual(postgresql_logger.rows[0]["scanner_id"], "20")
            self.assertEqual(postgresql_logger.rows[0]["tracking_number"], valid_tracking)
            self.assertEqual(postgresql_logger.rows[0]["barcode"], valid_tracking)
            self.assertFalse(postgresql_logger.rows[0]["is_duplicate"])
            self.assertFalse(postgresql_logger.rows[0]["is_repaired"])
            self.assertEqual(postgresql_logger.rows[1]["tracking_number"], valid_tracking)
            self.assertEqual(postgresql_logger.rows[1]["barcode"], valid_tracking)
            self.assertFalse(postgresql_logger.rows[1]["is_duplicate"])
            self.assertFalse(postgresql_logger.rows[1]["is_repaired"])
            self.assertEqual(postgresql_logger.rows[2]["tracking_number"], numeric_short)
            self.assertEqual(postgresql_logger.rows[2]["barcode"], numeric_short)
            self.assertFalse(postgresql_logger.rows[2]["is_duplicate"])
            self.assertFalse(postgresql_logger.rows[2]["is_repaired"])
            self.assertEqual(
                [row["tracking_number"] for row in postgresql_logger.raw_rows],
                [valid_tracking, valid_tracking, "__NO_READ__", numeric_short],
            )
            self.assertEqual(
                [row["barcode"] for row in postgresql_logger.raw_rows],
                [valid_tracking, valid_tracking, "__NO_READ__", numeric_short],
            )

            logger.close()
            self.assertTrue(postgresql_logger.closed)

    def test_tracking_repair_reconstructs_short_numeric_scan(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            output_dir = Path(temp_dir)
            log_path = output_dir / "industrial-scanner-logger.log"
            postgresql_logger = FakePostgreSQLLogger()
            normal_tracking = "9622080430009854574100871915237873"
            short_tracking = "871913626933"
            repaired_tracking = "9622080430009854574100871913626933"

            configure_script_logging(str(log_path), console=False)

            try:
                logger = DailyCsvLogger(
                    output_dir=output_dir,
                    file_prefix="Test",
                    no_read_message="__NO_READ__",
                    success_length=34,
                    postgresql_logger=postgresql_logger,
                    tracking_repair_enabled=True,
                )

                logger.write_scan_event(normal_tracking, "20")
                logger.write_scan_event(short_tracking, "21")
            finally:
                reset_script_logging()

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(rows[1]["status"], "SUCCESS")
            self.assertEqual(rows[1]["is_repaired"], "true")
            self.assertEqual(rows[1]["tracking"], repaired_tracking)
            self.assertEqual(postgresql_logger.rows[1]["tracking_number"], repaired_tracking)
            self.assertEqual(postgresql_logger.rows[1]["barcode"], short_tracking)
            self.assertTrue(postgresql_logger.rows[1]["is_repaired"])
            self.assertEqual(postgresql_logger.raw_rows[1]["tracking_number"], short_tracking)
            self.assertEqual(postgresql_logger.raw_rows[1]["barcode"], short_tracking)
            self.assertFalse(postgresql_logger.raw_rows[1]["is_repaired"])

            script_log = log_path.read_text(encoding="utf-8")
            self.assertIn("Tracking number repaired", script_log)
            self.assertIn(f"captured={short_tracking}", script_log)
            self.assertIn(f"repaired_to={repaired_tracking}", script_log)

    def test_tracking_repair_leaves_nonmatching_short_scan_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
                tracking_repair_enabled=True,
            )

            logger.write_scan_event("9622080430009854574100871915237873", "20")
            logger.write_scan_event("991913626933", "21")

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(rows[1]["status"], "FAILED")
            self.assertEqual(rows[1]["is_repaired"], "false")
            self.assertEqual(rows[1]["tracking"], "991913626933")

    def test_tracking_repair_leaves_ambiguous_short_scan_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
                tracking_repair_enabled=True,
            )

            logger.write_scan_event("9622080430009854574100871915237873", "20")
            logger.write_scan_event("1111111111111111111111871955555555", "21")
            logger.write_scan_event("871913626933", "22")

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(rows[2]["status"], "FAILED")
            self.assertEqual(rows[2]["is_repaired"], "false")
            self.assertEqual(rows[2]["tracking"], "871913626933")

    def test_cross_scanner_duplicate_and_last_scanner_metadata_are_recorded(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            postgresql_logger = FakePostgreSQLLogger()
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
                postgresql_logger=postgresql_logger,
                last_scanner_id="21",
                scanner_names={
                    "20": "Lane 1 Scanner",
                    "21": "Last Scanner",
                },
            )

            valid_tracking = "6" * 34
            other_tracking_numbers = ["7" * 34, "8" * 34, "9" * 34]

            logger.write_scan_event(valid_tracking, "20")
            for tracking_number in other_tracking_numbers:
                logger.write_scan_event(tracking_number, "20")
            logger.write_scan_event(valid_tracking, "21")

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(rows[0]["scanner_name"], "Lane 1 Scanner")
            self.assertEqual(rows[0]["scanner_role"], "standard")
            self.assertEqual(rows[0]["is_duplicate"], "false")
            self.assertEqual(rows[0]["is_cross_scanner_duplicate"], "false")
            self.assertEqual(rows[-1]["scanner_name"], "Last Scanner")
            self.assertEqual(rows[-1]["scanner_role"], "last")
            self.assertEqual(rows[-1]["is_duplicate"], "true")
            self.assertEqual(rows[-1]["is_cross_scanner_duplicate"], "true")

            self.assertEqual(postgresql_logger.rows[0]["scanner_name"], "Lane 1 Scanner")
            self.assertEqual(postgresql_logger.rows[0]["scanner_role"], "standard")
            self.assertEqual(postgresql_logger.rows[0]["last_scanner_id"], "21")
            self.assertFalse(postgresql_logger.rows[0]["is_duplicate"])
            self.assertFalse(
                postgresql_logger.rows[0]["is_cross_scanner_duplicate"],
            )
            self.assertEqual(postgresql_logger.rows[-1]["scanner_name"], "Last Scanner")
            self.assertEqual(postgresql_logger.rows[-1]["scanner_role"], "last")
            self.assertEqual(postgresql_logger.rows[-1]["last_scanner_id"], "21")
            self.assertTrue(postgresql_logger.rows[-1]["is_duplicate"])
            self.assertTrue(
                postgresql_logger.rows[-1]["is_cross_scanner_duplicate"],
            )

    def test_cross_scanner_duplicate_is_regular_duplicate_before_last_scanner(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()):
            logger = DailyCsvLogger(
                output_dir=Path(temp_dir),
                file_prefix="Test",
                no_read_message="__NO_READ__",
                success_length=34,
                last_scanner_id="21",
            )

            valid_tracking = "6" * 34
            other_tracking_numbers = ["7" * 34, "8" * 34, "9" * 34]

            logger.write_scan_event(valid_tracking, "20")
            for tracking_number in other_tracking_numbers:
                logger.write_scan_event(tracking_number, "20")
            logger.write_scan_event(valid_tracking, "22")

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(rows[-1]["scanner_id"], "22")
            self.assertEqual(rows[-1]["is_duplicate"], "true")
            self.assertEqual(rows[-1]["is_cross_scanner_duplicate"], "false")

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
                    last_scanner_id="20",
                    scanner_names={"20": "Lane 1 Scanner"},
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
            self.assertIn("scanner_name=Lane 1 Scanner scanner_role=last", script_log)
            self.assertIn("Scanner disconnected address=10.10.10.20:0", script_log)
            self.assertNotIn("Scan event recorded", script_log)
            self.assertNotIn(valid_tracking, script_log)
            self.assertEqual(len(data_logs), 1)
            self.assertIn(valid_tracking, data_logs[0].read_text(encoding="utf-8"))

    def test_write_scan_event_logs_success_repeat_and_failure(self):
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

            self.assertEqual(logger.event_count, 3)
            self.assertEqual(logger.success_count, 2)
            self.assertEqual(logger.failed_count, 1)

            with logger.current_csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["scanner_id"], "UNKNOWN")
            self.assertEqual(rows[0]["status"], "SUCCESS")
            self.assertEqual(rows[0]["tracking"], valid_tracking)
            self.assertEqual(rows[1]["scanner_id"], "UNKNOWN")
            self.assertEqual(rows[1]["status"], "SUCCESS")
            self.assertEqual(rows[1]["is_duplicate"], "false")
            self.assertEqual(rows[1]["tracking"], valid_tracking)
            self.assertEqual(rows[2]["scanner_id"], "UNKNOWN")
            self.assertEqual(rows[2]["status"], "FAILED")
            self.assertEqual(rows[2]["tracking"], "")

            with logger.failed_scans_path.open(newline="", encoding="utf-8") as f:
                failed_rows = list(csv.DictReader(f))

            self.assertEqual(len(failed_rows), 1)
            self.assertEqual(failed_rows[0]["scanner_id"], "UNKNOWN")
            self.assertEqual(failed_rows[0]["failed_barcode"], "__NO_READ__")

            data_logs = list(Path(temp_dir).glob("scanner-log-data-*.log"))
            self.assertEqual(len(data_logs), 1)
            data_log_text = data_logs[0].read_text(encoding="utf-8")
            self.assertNotIn("Duplicate ignored", data_log_text)
            self.assertEqual(len(data_log_text.splitlines()), 3)

    def test_repeat_before_duplicate_threshold_is_not_reported_as_duplicate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            log_path = output_dir / "industrial-scanner-logger.log"
            stdout = StringIO()

            with redirect_stdout(stdout):
                configure_script_logging(str(log_path), console=True)

                try:
                    logger = DailyCsvLogger(
                        output_dir=output_dir,
                        file_prefix="Test",
                        no_read_message="__NO_READ__",
                        success_length=34,
                    )

                    valid_tracking = "5" * 34

                    logger.write_scan_event(valid_tracking, "21")
                    logger.write_scan_event(valid_tracking, "21")
                finally:
                    reset_script_logging()

            script_log = log_path.read_text(encoding="utf-8")
            data_logs = list(output_dir.glob("scanner-log-data-*.log"))
            self.assertEqual(len(data_logs), 1)
            data_log_text = data_logs[0].read_text(encoding="utf-8")

            self.assertNotIn("Duplicate successful scan ignored", stdout.getvalue())
            self.assertNotIn("Duplicate successful scan ignored", script_log)
            self.assertNotIn("Duplicate ignored", data_log_text)
            self.assertIn("Duplicate:false", data_log_text)
            self.assertEqual(len(data_log_text.splitlines()), 2)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

HAS_API_DEPS = all(
    importlib.util.find_spec(module_name)
    for module_name in ("fastapi", "uvicorn", "psycopg")
)


@unittest.skipUnless(HAS_API_DEPS, "FastAPI API dependencies are not installed")
class ApiQueryTests(unittest.TestCase):
    def test_app_uses_api_root_path_as_proxy_prefix(self):
        from industrial_scanner_logger.api import create_app

        app = create_app(root_path="/api")
        route_paths = {route.path for route in app.routes}

        self.assertEqual(app.root_path, "/api")
        self.assertIn("/v1/health", route_paths)
        self.assertIn("/v1/dashboard/health", route_paths)
        self.assertIn("/v1/logs/daily-csv", route_paths)
        self.assertIn("/v1/logs/daily-csv/{scan_date}", route_paths)
        self.assertIn("/v1/scans", route_paths)
        self.assertNotIn("/api/v1/health", route_paths)

    def test_normalize_root_path_rejects_relative_paths(self):
        from industrial_scanner_logger.api import normalize_root_path

        with self.assertRaises(ValueError):
            normalize_root_path("api")

    def test_build_scan_events_query_collects_filters_and_pagination(self):
        from industrial_scanner_logger.api import build_scan_events_query

        _query, params = build_scan_events_query(
            start_date=date(2026, 5, 17),
            end_date=date(2026, 5, 18),
            scanner_id=20,
            barcode="1" * 34,
            is_success=True,
            limit=25,
            offset=50,
        )

        self.assertEqual(
            params,
            [
                date(2026, 5, 17),
                date(2026, 5, 18),
                20,
                "1" * 34,
                "1" * 34,
                True,
                25,
                50,
            ],
        )

    def test_build_scan_events_query_matches_last_10_tracking_digits(self):
        from industrial_scanner_logger.api import build_scan_events_query

        _query, params = build_scan_events_query(
            barcode="1234567890",
            limit=25,
            offset=50,
        )

        self.assertEqual(
            params,
            [
                "1234567890",
                10,
                "1234567890",
                "1234567890",
                10,
                "1234567890",
                25,
                50,
            ],
        )

    def test_tracking_suffix_search_accepts_only_last_10_digits(self):
        from industrial_scanner_logger.api import is_tracking_suffix_search

        self.assertTrue(is_tracking_suffix_search("1234567890"))
        self.assertFalse(is_tracking_suffix_search("1" * 25))
        self.assertFalse(is_tracking_suffix_search("1" * 9))
        self.assertFalse(is_tracking_suffix_search("1" * 34))
        self.assertFalse(is_tracking_suffix_search("ABC4567890"))

    def test_view_query_rejects_unsupported_filters(self):
        from fastapi import HTTPException

        from industrial_scanner_logger.api import build_view_query

        with self.assertRaises(HTTPException) as context:
            build_view_query(
                "daily-scan-totals-all-scanners",
                scanner_id=20,
            )

        self.assertEqual(context.exception.status_code, 400)

    def test_unknown_view_returns_404(self):
        from fastapi import HTTPException

        from industrial_scanner_logger.api import build_view_query

        with self.assertRaises(HTTPException) as context:
            build_view_query("not-a-view")

        self.assertEqual(context.exception.status_code, 404)

    def test_dashboard_daily_totals_returns_today_and_yesterday_counts(self):
        from industrial_scanner_logger.api import fetch_dashboard_daily_totals

        class FakeCursor:
            def __init__(self):
                self.params = None

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return None

            def execute(self, _query, params):
                self.params = params

            def fetchall(self):
                return [
                    {
                        "scan_date": date(2026, 5, 18),
                        "total_scan_events": 16,
                        "successful_scans": 14,
                        "failed_scans": 2,
                        "duplicate_scans": 2,
                        "cross_scanner_duplicate_scans": 1,
                    }
                ]

        class FakeDb:
            def __init__(self):
                self.cursor_instance = FakeCursor()

            def cursor(self):
                return self.cursor_instance

        db = FakeDb()
        totals = fetch_dashboard_daily_totals(
            db,
            date(2026, 5, 18),
            date(2026, 5, 17),
        )

        self.assertEqual(
            db.cursor_instance.params,
            [date(2026, 5, 18), date(2026, 5, 17)],
        )
        self.assertEqual(
            totals,
            {
                "today": {
                    "scan_date": "2026-05-18",
                    "total_scan_events": 16,
                    "successful_scans": 14,
                    "failed_scans": 2,
                    "duplicate_scans": 2,
                    "cross_scanner_duplicate_scans": 1,
                },
                "yesterday": {
                    "scan_date": "2026-05-17",
                    "total_scan_events": 0,
                    "successful_scans": 0,
                    "failed_scans": 0,
                    "duplicate_scans": 0,
                    "cross_scanner_duplicate_scans": 0,
                },
                "today_by_scanner": [],
            },
        )

    def test_dashboard_today_scanner_totals_uses_scanner_names(self):
        from types import SimpleNamespace

        from industrial_scanner_logger.api import fetch_dashboard_today_scanner_totals

        class FakeCursor:
            def __init__(self):
                self.params = None

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return None

            def execute(self, _query, params):
                self.params = params

            def fetchall(self):
                return [
                    {
                        "scanner_id": 20,
                        "scanner_name": None,
                        "total_scan_events": 8,
                        "successful_scans": 7,
                        "failed_scans": 1,
                        "duplicate_scans": 2,
                        "cross_scanner_duplicate_scans": 1,
                    },
                    {
                        "scanner_id": 21,
                        "scanner_name": "Last Scanner",
                        "total_scan_events": 4,
                        "successful_scans": 4,
                        "failed_scans": 0,
                        "duplicate_scans": 0,
                        "cross_scanner_duplicate_scans": 1,
                    },
                ]

        class FakeDb:
            def __init__(self):
                self.cursor_instance = FakeCursor()

            def cursor(self):
                return self.cursor_instance

        db = FakeDb()
        totals = fetch_dashboard_today_scanner_totals(
            db,
            SimpleNamespace(
                scanner_names={
                    "20": "Lane 1 Scanner",
                    "21": "Configured Last Scanner",
                }
            ),
            date(2026, 5, 18),
        )

        self.assertEqual(db.cursor_instance.params, [date(2026, 5, 18)])
        self.assertEqual(
            totals,
            [
                {
                    "scanner_id": 20,
                    "scanner_name": "Lane 1 Scanner",
                    "display_name": "Lane 1 Scanner",
                    "total_scan_events": 8,
                    "successful_scans": 7,
                    "failed_scans": 1,
                    "duplicate_scans": 2,
                    "cross_scanner_duplicate_scans": 1,
                },
                {
                    "scanner_id": 21,
                    "scanner_name": "Configured Last Scanner",
                    "display_name": "Configured Last Scanner",
                    "total_scan_events": 4,
                    "successful_scans": 4,
                    "failed_scans": 0,
                    "duplicate_scans": 0,
                    "cross_scanner_duplicate_scans": 1,
                },
            ],
        )

    def test_completed_daily_csv_logs_mark_empty_days_without_download(self):
        from types import SimpleNamespace

        from industrial_scanner_logger.api import (
            daily_csv_log_path,
            list_completed_daily_csv_logs,
        )
        from fastapi import HTTPException

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            previous_csv = output_dir / "Test_2026-05-17.csv"
            empty_csv = output_dir / "Test_2026-05-16.csv"
            current_csv = output_dir / "Test_2026-05-18.csv"
            invalid_csv = output_dir / "Test_2026-99-99.csv"
            previous_csv.write_text(
                "\n".join([
                    "date,time,scanner_id,scanner_name,scanner_role,status,"
                    "is_duplicate,is_cross_scanner_duplicate,is_repaired,tracking",
                    "2026-05-17,08:00:00,20,,standard,SUCCESS,false,false,false,123",
                    "2026-05-17,08:01:00,20,,standard,SUCCESS,true,false,false,456",
                    "2026-05-17,08:02:00,21,,standard,SUCCESS,true,true,false,789",
                    "",
                ]),
                encoding="utf-8",
            )
            empty_csv.write_text("date,time,tracking\n", encoding="utf-8")
            current_csv.write_text("still,open,today\n", encoding="utf-8")
            invalid_csv.write_text("invalid,date\n", encoding="utf-8")
            config = SimpleNamespace(output_dir=temp_dir, prefix="Test")

            rows = list_completed_daily_csv_logs(
                config,
                current_day=date(2026, 5, 18),
            )

            with self.assertRaises(HTTPException) as context:
                daily_csv_log_path(config, date(2026, 5, 16))

        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(context.exception.detail, "daily CSV has no scan rows")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["scan_date"], "2026-05-17")
        self.assertEqual(rows[0]["filename"], "Test_2026-05-17.csv")
        self.assertTrue(rows[0]["has_scans"])
        self.assertEqual(rows[0]["scan_count"], 3)
        self.assertEqual(rows[0]["duplicate_count"], 1)
        self.assertEqual(rows[0]["download_url"], "/v1/logs/daily-csv/2026-05-17")
        self.assertEqual(rows[1]["scan_date"], "2026-05-16")
        self.assertFalse(rows[1]["has_scans"])
        self.assertEqual(rows[1]["scan_count"], 0)
        self.assertEqual(rows[1]["duplicate_count"], 0)
        self.assertIsNone(rows[1]["download_url"])

    def test_current_scan_rate_uses_rolling_one_minute_window(self):
        from industrial_scanner_logger.api import (
            CURRENT_SCAN_HOUR_WINDOW_SECONDS,
            CURRENT_SCAN_RATE_WINDOW_SECONDS,
            fetch_current_scan_rate,
        )

        class FakeCursor:
            def __init__(self):
                self.params = None

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return None

            def execute(self, _query, params):
                self.params = params

            def fetchone(self):
                return {
                    "scan_count": 7,
                    "hour_scan_count": 450,
                }

        class FakeDb:
            def __init__(self):
                self.cursor_instance = FakeCursor()

            def cursor(self):
                return self.cursor_instance

        db = FakeDb()
        scan_rate = fetch_current_scan_rate(db)

        self.assertEqual(
            db.cursor_instance.params,
            [
                timedelta(seconds=CURRENT_SCAN_RATE_WINDOW_SECONDS),
                timedelta(seconds=CURRENT_SCAN_HOUR_WINDOW_SECONDS),
            ],
        )
        self.assertEqual(
            scan_rate,
            {
                "window_seconds": 60,
                "hour_window_seconds": 3600,
                "scan_count": 7,
                "hour_scan_count": 450,
                "scans_per_minute": 7.0,
                "scans_per_hour": 450,
            },
        )

    def test_active_duplicate_alert_returns_latest_non_cross_scanner_duplicate(self):
        from types import SimpleNamespace

        from industrial_scanner_logger.api import fetch_active_duplicate_alert

        class FakeCursor:
            def __init__(self):
                self.params = None

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return None

            def execute(self, _query, params):
                self.params = params

            def fetchone(self):
                return {
                    "id": 42,
                    "scan_date": date(2026, 5, 18),
                    "scan_time": "08:15:30",
                    "scanner_id": 20,
                    "scanner_name": "",
                    "scanner_role": "standard",
                    "last_scanner_id": 21,
                    "is_duplicate": True,
                    "is_cross_scanner_duplicate": False,
                    "is_repaired": False,
                    "tracking_number": "9612345678901234567890123456789012",
                    "barcode": "9612345678901234567890123456789012",
                    "barcode_length": 34,
                    "is_success": True,
                    "failure_reason": None,
                    "alert_age_seconds": 12.25,
                }

        class FakeDb:
            def __init__(self):
                self.cursor_instance = FakeCursor()

            def cursor(self):
                return self.cursor_instance

        db = FakeDb()
        alert = fetch_active_duplicate_alert(
            db,
            SimpleNamespace(scanner_names={"20": "Lane 1 Scanner"}),
            60,
        )

        self.assertEqual(db.cursor_instance.params, [timedelta(seconds=60)])
        self.assertEqual(alert["id"], 42)
        self.assertEqual(alert["display_name"], "Lane 1 Scanner")
        self.assertEqual(alert["barcode_last_10"], "1234567890123456789012"[-10:])
        self.assertEqual(alert["alert_seconds"], 60)
        self.assertEqual(alert["alert_age_seconds"], 12.25)
        self.assertEqual(alert["alert_remaining_seconds"], 47.75)

    def test_dashboard_health_skips_duplicate_alert_when_disabled(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from industrial_scanner_logger import api

        class FakeDb:
            def close(self):
                return None

        config = SimpleNamespace(
            port=55256,
            mandatory_scanner_ids=[],
            scanner_names={},
            last_scanner_id="",
            current_scan_rate_stale_seconds=60,
            health_page_refresh_seconds=3,
            tv_dashboard_refresh_seconds=1,
            tv_duplicate_alert_enabled=False,
            tv_duplicate_alert_seconds=60,
        )

        with (
            patch.object(
                api,
                "systemd_service_status",
                return_value={"active": True, "state": "active"},
            ),
            patch.object(api, "connected_scanner_ids_from_ss", return_value=[]),
            patch.object(api, "read_last_log_lines", return_value={"lines": []}),
            patch.object(api, "connect_db", return_value=FakeDb()),
            patch.object(api, "fetch_one", return_value=None),
            patch.object(api, "fetch_all", return_value=[]),
            patch.object(
                api,
                "fetch_dashboard_daily_totals",
                return_value={
                    "today": {},
                    "yesterday": {},
                    "today_by_scanner": [],
                },
            ),
            patch.object(api, "fetch_dashboard_today_scanner_totals", return_value=[]),
            patch.object(api, "fetch_current_scan_rate", return_value={}),
            patch.object(api, "fetch_active_duplicate_alert") as duplicate_alert,
        ):
            payload = api.build_dashboard_health(config)

        duplicate_alert.assert_not_called()
        self.assertFalse(payload["tv_duplicate_alert_enabled"])
        self.assertIsNone(payload["duplicate_alert"])

    def test_dashboard_mandatory_scanners_reports_missing_required_ids(self):
        from types import SimpleNamespace

        from industrial_scanner_logger.api import dashboard_mandatory_scanners

        status = dashboard_mandatory_scanners(
            SimpleNamespace(
                mandatory_scanner_ids=["20", "21"],
                scanner_names={"20": "Lane 1 Scanner", "21": "Last Scanner"},
            ),
            [20],
        )

        self.assertFalse(status["ok"])
        self.assertTrue(status["configured"])
        self.assertEqual(
            status["required_scanners"],
            [
                {
                    "scanner_id": 20,
                    "scanner_name": "Lane 1 Scanner",
                    "display_name": "Lane 1 Scanner",
                    "connected": True,
                },
                {
                    "scanner_id": 21,
                    "scanner_name": "Last Scanner",
                    "display_name": "Last Scanner",
                    "connected": False,
                },
            ],
        )
        self.assertEqual(status["required_scanner_ids"], [20, 21])
        self.assertEqual(status["connected_required_scanner_ids"], [20])
        self.assertEqual(status["missing_scanner_ids"], [21])
        self.assertEqual(
            status["warning"],
            "Mandatory scanner not connected: Last Scanner",
        )

    def test_scan_row_display_name_prefers_current_config_name(self):
        from types import SimpleNamespace

        from industrial_scanner_logger.api import scan_row_with_display_name

        row = scan_row_with_display_name(
            SimpleNamespace(scanner_names={"20": "Lane 1 Scanner"}),
            {
                "scanner_id": 20,
                "scanner_name": "Old Scanner Name",
                "barcode": "123",
            },
        )

        self.assertEqual(row["display_name"], "Lane 1 Scanner")
        self.assertEqual(row["scanner_name"], "Old Scanner Name")

    def test_scan_row_display_name_falls_back_to_scanner_id(self):
        from types import SimpleNamespace

        from industrial_scanner_logger.api import scan_row_with_display_name

        row = scan_row_with_display_name(
            SimpleNamespace(scanner_names={}),
            {
                "scanner_id": 21,
                "scanner_name": "",
                "barcode": "123",
            },
        )

        self.assertEqual(row["display_name"], "Scanner 21")


if __name__ == "__main__":
    unittest.main()

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
            SimpleNamespace(scanner_names={"20": "Lane 1 Scanner"}),
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
                    "scanner_name": "Last Scanner",
                    "display_name": "Last Scanner",
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


if __name__ == "__main__":
    unittest.main()

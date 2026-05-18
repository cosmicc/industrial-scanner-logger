import importlib.util
import unittest
from datetime import date, timedelta


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
                True,
                25,
                50,
            ],
        )

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
                        "successful_scans": 14,
                        "failed_scans": 2,
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
                    "successful_scans": 14,
                    "failed_scans": 2,
                },
                "yesterday": {
                    "scan_date": "2026-05-17",
                    "successful_scans": 0,
                    "failed_scans": 0,
                },
            },
        )

    def test_current_scan_rate_uses_rolling_one_minute_window(self):
        from industrial_scanner_logger.api import (
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
                return {"scan_count": 7}

        class FakeDb:
            def __init__(self):
                self.cursor_instance = FakeCursor()

            def cursor(self):
                return self.cursor_instance

        db = FakeDb()
        scan_rate = fetch_current_scan_rate(db)

        self.assertEqual(
            db.cursor_instance.params,
            [timedelta(seconds=CURRENT_SCAN_RATE_WINDOW_SECONDS)],
        )
        self.assertEqual(
            scan_rate,
            {
                "window_seconds": 60,
                "scan_count": 7,
                "scans_per_minute": 7.0,
                "scans_per_hour": 420.0,
            },
        )


if __name__ == "__main__":
    unittest.main()

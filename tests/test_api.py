import importlib.util
import unittest
from datetime import date


HAS_API_DEPS = all(
    importlib.util.find_spec(module_name)
    for module_name in ("fastapi", "uvicorn", "psycopg")
)


@unittest.skipUnless(HAS_API_DEPS, "FastAPI API dependencies are not installed")
class ApiQueryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

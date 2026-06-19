import importlib.util
import os
import sys
import unittest
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

HAS_API_DEPS = all(
    importlib.util.find_spec(module_name)
    for module_name in ("fastapi", "uvicorn", "psycopg")
)


@unittest.skipUnless(HAS_API_DEPS, "FastAPI API dependencies are not installed")
class HealthCliTests(unittest.TestCase):
    def setUp(self):
        from industrial_scanner_logger import health_cli

        self.health_cli = health_cli

    def test_health_report_redacts_secrets_and_omits_raw_barcode(self):
        config = self.config(api_enabled=True)
        dashboard_health = self.dashboard_health()
        dashboard_health["outgoing_api"].update({
            "enabled": True,
            "active": False,
            "state": "unavailable",
            "queue_count": 2,
            "failed_queue_count": 1,
            "last_error": (
                "postgresql://scanner:super-secret@example.test/scanner "
                "password=hunter2 token=abc123 X-Scanner-Api-Key: scanner-key"
            ),
        })
        dashboard_health["database"].update({
            "active": False,
            "state": "unavailable",
            "error": "password=db-secret",
        })
        dashboard_health["last_received"] = {
            "scan_timestamp": "2026-06-18T14:00:00",
            "scanner_id": 20,
            "display_name": "Lane 1 Scanner",
            "is_success": True,
            "barcode": "9" * 34,
            "tracking_number": "123456789012",
        }
        cli_health = self.health_cli.build_cli_payload(
            config,
            dashboard_health,
            self.service_statuses(),
        )

        report = self.health_cli.format_health_report(cli_health)

        self.assertIn("Outgoing API", report)
        self.assertIn("[redacted]", report)
        self.assertNotIn("super-secret", report)
        self.assertNotIn("hunter2", report)
        self.assertNotIn("abc123", report)
        self.assertNotIn("scanner-key", report)
        self.assertNotIn("db-secret", report)
        self.assertNotIn("9" * 34, report)
        self.assertNotIn("123456789012", report)

    def test_payload_marks_required_nginx_service_problem_degraded(self):
        config = self.config(api_enabled=True)
        services = self.service_statuses()
        services["nginx"] = {
            "unit": "nginx.service",
            "active": False,
            "state": "inactive",
            "error": None,
        }

        cli_health = self.health_cli.build_cli_payload(
            config,
            self.dashboard_health(),
            services,
        )

        self.assertEqual(cli_health["status"], "degraded")
        self.assertIn("nginx", cli_health["service_problems"])

    def test_payload_does_not_require_api_or_nginx_when_api_is_disabled(self):
        config = self.config(api_enabled=False)
        services = self.service_statuses()
        services["api"] = {
            "unit": "industrial-scanner-logger-api.service",
            "active": False,
            "state": "inactive",
            "error": None,
        }
        services["nginx"] = {
            "unit": "nginx.service",
            "active": False,
            "state": "inactive",
            "error": None,
        }

        cli_health = self.health_cli.build_cli_payload(
            config,
            self.dashboard_health(),
            services,
        )

        self.assertEqual(cli_health["status"], "ok")
        self.assertEqual(cli_health["required_service_keys"], ["scanner"])

    def test_outgoing_api_queue_is_unavailable_when_database_is_unavailable(self):
        config = self.config(api_enabled=True)
        dashboard_health = self.dashboard_health()
        dashboard_health["database"] = {
            "active": False,
            "state": "unavailable",
            "error": "peer authentication failed",
        }
        dashboard_health["outgoing_api"] = {
            "enabled": True,
            "active": False,
            "state": "unknown",
            "queue_count": 0,
            "failed_queue_count": 0,
            "oldest_queued_at": None,
            "last_attempt_at": None,
            "last_error": None,
            "last_http_status": None,
            "url_configured": True,
            "api_key_configured": True,
            "error": None,
        }

        cli_health = self.health_cli.build_cli_payload(
            config,
            dashboard_health,
            self.service_statuses(),
        )
        report = self.health_cli.format_health_report(cli_health)

        self.assertEqual(cli_health["status"], "degraded")
        self.assertIn("[WARN] state: not checked (database unavailable)", report)
        self.assertIn("queue: unavailable until database health can be checked", report)
        self.assertNotIn("queue: 0 pending, 0 failed", report)

    def test_health_report_colorizes_statuses_when_enabled(self):
        config = self.config(api_enabled=True)
        dashboard_health = self.dashboard_health()
        dashboard_health["outgoing_api"] = {
            "enabled": True,
            "active": False,
            "state": "pending",
            "queue_count": 3,
            "failed_queue_count": 0,
            "oldest_queued_at": None,
            "last_attempt_at": None,
            "last_error": None,
            "last_http_status": None,
            "url_configured": True,
            "api_key_configured": True,
            "error": None,
        }
        services = self.service_statuses()
        services["nginx"] = {
            "unit": "nginx.service",
            "active": False,
            "state": "inactive",
            "error": None,
        }
        cli_health = self.health_cli.build_cli_payload(
            config,
            dashboard_health,
            services,
        )

        report = self.health_cli.format_health_report(cli_health, color_enabled=True)

        self.assertIn("\033[32m[OK]\033[0m", report)
        self.assertIn("\033[33m[WARN]\033[0m", report)
        self.assertIn("\033[31m[FAIL]\033[0m", report)
        self.assertIn("\033[1m\033[36mServices\033[0m", report)
        self.assertIn("\033[33m3\033[0m pending", report)

    def test_should_use_color_obeys_modes_and_no_color(self):
        class FakeStream:
            def __init__(self, tty):
                self.tty = tty

            def isatty(self):
                return self.tty

        self.assertTrue(
            self.health_cli.should_use_color(
                self.health_cli.COLOR_ALWAYS,
                FakeStream(False),
            )
        )
        self.assertFalse(
            self.health_cli.should_use_color(
                self.health_cli.COLOR_NEVER,
                FakeStream(True),
            )
        )
        with patch.dict(os.environ, {"NO_COLOR": ""}):
            self.assertTrue(
                self.health_cli.should_use_color(
                    self.health_cli.COLOR_AUTO,
                    FakeStream(True),
                )
            )
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertFalse(
                self.health_cli.should_use_color(
                    self.health_cli.COLOR_AUTO,
                    FakeStream(True),
                )
            )

    def test_service_unit_name_adds_missing_suffix(self):
        self.assertEqual(
            self.health_cli.service_unit_name("industrial-scanner-logger"),
            "industrial-scanner-logger.service",
        )
        self.assertEqual(
            self.health_cli.service_unit_name("nginx.service"),
            "nginx.service",
        )

    def config(self, api_enabled=True):
        return SimpleNamespace(
            config_file="/etc/industrial-scanner-logger.conf",
            config_loaded=True,
            postgresql_table="scanner_logger.scan_events",
            api_enabled=api_enabled,
        )

    def service_statuses(self):
        return OrderedDict([
            (
                "scanner",
                {
                    "unit": "industrial-scanner-logger.service",
                    "active": True,
                    "state": "active",
                    "error": None,
                },
            ),
            (
                "api",
                {
                    "unit": "industrial-scanner-logger-api.service",
                    "active": True,
                    "state": "active",
                    "error": None,
                },
            ),
            (
                "nginx",
                {
                    "unit": "nginx.service",
                    "active": True,
                    "state": "active",
                    "error": None,
                },
            ),
            (
                "postgresql",
                {
                    "unit": "postgresql.service",
                    "active": False,
                    "state": "inactive",
                    "error": None,
                },
            ),
        ])

    def dashboard_health(self):
        return {
            "status": "ok",
            "version": "1.3",
            "generated_at": "2026-06-18T14:00:00-04:00",
            "services": {},
            "database": {
                "active": True,
                "state": "ok",
                "error": None,
            },
            "outgoing_api": {
                "enabled": False,
                "active": True,
                "state": "disabled",
                "queue_count": 0,
                "failed_queue_count": 0,
                "oldest_queued_at": None,
                "last_attempt_at": None,
                "last_error": None,
                "last_http_status": None,
                "url_configured": False,
                "api_key_configured": False,
                "error": None,
            },
            "storage": {
                "ok": True,
                "state": "ok",
                "warning_percent": 10,
                "warning_bytes": 5 * 1024 * 1024 * 1024,
                "volumes": [
                    {
                        "label": "CSV output",
                        "path": "/scanner-logs",
                        "checked_path": "/scanner-logs",
                        "ok": True,
                        "free_percent": 80,
                        "free_bytes": 80 * 1024 * 1024 * 1024,
                        "warning_reasons": [],
                        "error": None,
                    }
                ],
            },
            "connected_scanner_count": 2,
            "connected_scanners": [
                {
                    "scanner_id": 20,
                    "display_name": "Lane 1 Scanner",
                },
                {
                    "scanner_id": 21,
                    "display_name": "Last Scanner",
                },
            ],
            "mandatory_scanners": {
                "configured": True,
                "ok": True,
                "required_scanner_ids": [20, 21],
                "connected_required_scanner_ids": [20, 21],
                "required_scanners": [
                    {
                        "scanner_id": 20,
                        "display_name": "Lane 1 Scanner",
                        "connected": True,
                    },
                    {
                        "scanner_id": 21,
                        "display_name": "Last Scanner",
                        "connected": True,
                    },
                ],
                "warning": None,
            },
            "daily_totals": {
                "today": {
                    "total_scan_events": 10,
                    "successful_scans": 8,
                    "duplicate_scans": 1,
                    "failed_scans": 1,
                },
                "today_by_scanner": [
                    {
                        "scanner_id": 20,
                        "display_name": "Lane 1 Scanner",
                        "total_scan_events": 6,
                        "successful_scans": 5,
                        "duplicate_scans": 1,
                        "failed_scans": 0,
                    },
                    {
                        "scanner_id": 21,
                        "display_name": "Last Scanner",
                        "total_scan_events": 4,
                        "successful_scans": 3,
                        "duplicate_scans": 0,
                        "failed_scans": 1,
                    },
                ],
            },
            "current_scan_rate": {
                "scans_per_minute": 2,
                "scans_per_hour": 120,
            },
            "last_received": None,
            "duplicate_alert": None,
            "package_alerts": [],
            "script_log": {
                "path": "/var/log/industrial-scanner-logger.log",
                "available": True,
                "error": None,
            },
        }


if __name__ == "__main__":
    unittest.main()

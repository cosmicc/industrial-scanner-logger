import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InstallScriptTests(unittest.TestCase):
    def test_installer_preserves_existing_ufw_rules_on_refresh(self):
        install_script = (PROJECT_ROOT / "scripts" / "install.sh").read_text(
            encoding="utf-8",
        )

        self.assertNotIn("ufw --force reset", install_script)
        self.assertIn("Do not reset UFW here", install_script)
        self.assertIn('ufw allow "${PORT}/tcp"', install_script)
        self.assertIn("Existing installation detected", install_script)
        self.assertIn("unrelated firewall rules will not be deleted", install_script)

    def test_health_cli_wrapper_runs_as_service_user_when_root(self):
        health_script = (
            PROJECT_ROOT / "scripts" / "industrial-scanner-health"
        ).read_text(encoding="utf-8")

        self.assertIn('SERVICE_USER="${SERVICE_USER:-scannerlogger}"', health_script)
        self.assertIn('if [[ "${HEALTH_RUN_AS_SERVICE_USER}" == "1" && "${EUID}" -eq 0 ]]', health_script)
        self.assertIn('runuser -u "${SERVICE_USER}"', health_script)
        self.assertIn("same database rows as the web health", health_script)

    def test_installer_uses_current_scanner_config_contract(self):
        install_script = (PROJECT_ROOT / "scripts" / "install.sh").read_text(
            encoding="utf-8",
        )
        default_config = (
            PROJECT_ROOT / "config" / "industrial-scanner-logger.conf"
        ).read_text(encoding="utf-8")

        self.assertNotIn("LAST_SCANNER_ID", install_script)
        self.assertNotIn("last_scanner_id =", default_config)
        self.assertIn("SCANNER_PAIRS", install_script)
        self.assertIn(
            "same_scanner_suppression_distinct_successes",
            install_script,
        )
        self.assertIn(
            "scanner_pair_suppression_distinct_successes",
            install_script,
        )
        self.assertIn(
            "same_scanner_suppression_distinct_successes = 5",
            default_config,
        )
        self.assertIn(
            "scanner_pair_suppression_distinct_successes = 10",
            default_config,
        )
        self.assertIn(
            "tv_outgoing_api_queue_alert_threshold = 25",
            default_config,
        )


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

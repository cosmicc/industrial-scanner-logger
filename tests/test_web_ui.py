import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WebUiContractTests(unittest.TestCase):
    def read_project_file(self, relative_path: str) -> str:
        """Read one committed UI or configuration file for contract checks."""
        return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")

    def test_root_version_matches_python_package_version(self):
        from industrial_scanner_logger import __version__

        version = self.read_project_file("VERSION").strip()
        self.assertEqual(version, __version__)

    def test_home_page_only_shows_version_in_footer(self):
        home_html = self.read_project_file("html/index.html")

        self.assertEqual(home_html.count("data-app-version"), 2)
        self.assertNotIn("home-status-detail", home_html)
        self.assertIn('<footer class="home-meta">', home_html)

    def test_tv_last_received_age_uses_server_generated_time(self):
        tv_html = self.read_project_file("html/tv-dashboard/index.html")

        self.assertIn(
            "renderLastReceived(data.last_received, data.generated_at)",
            tv_html,
        )
        self.assertIn("dashboardReferenceTime(generatedAt)", tv_html)

    def test_search_exposes_scanner_mode_totals_and_timeout(self):
        search_html = self.read_project_file("html/search/index.html")

        self.assertIn('<option value="scanner">Scanner ID / Name</option>', search_html)
        self.assertIn('/api/v1/scans/summary', search_html)
        self.assertIn('id="search-totals"', search_html)
        self.assertIn("API_REQUEST_TIMEOUT_MS = 15000", search_html)

    def test_logs_page_has_bounded_api_request(self):
        logs_html = self.read_project_file("html/logs/index.html")

        self.assertIn("API_REQUEST_TIMEOUT_MS = 15000", logs_html)
        self.assertIn("fetchWithTimeout(LOGS_API_URL", logs_html)

    def test_nginx_serves_search_without_directory_redirect(self):
        nginx_config = self.read_project_file("nginx/industrial-scanner-logger.conf")

        self.assertIn("location = /search {", nginx_config)
        self.assertIn("try_files /search/index.html =404;", nginx_config)


if __name__ == "__main__":
    unittest.main()

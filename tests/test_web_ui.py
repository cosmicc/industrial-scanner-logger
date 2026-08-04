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

    def test_tv_dashboard_uses_one_severity_aware_health_overlay(self):
        tv_html = self.read_project_file("html/tv-dashboard/index.html")
        site_css = self.read_project_file("html/assets/site.css")

        self.assertEqual(tv_html.count('id="tv-status"'), 1)
        self.assertNotIn('id="tv-warning"', tv_html)
        self.assertIn("dashboardHealthIssues(data)", tv_html)
        self.assertIn('severity: "critical"', tv_html)
        self.assertIn('severity: "warning"', tv_html)
        self.assertIn("healthIssues.map((issue) => issue.message)", tv_html)
        self.assertIn(".tv-status.health-overlay", site_css)
        self.assertIn("status.hidden = !degraded", tv_html)
        self.assertIn('status.textContent = "";', tv_html)
        self.assertNotIn('status.textContent = "SYSTEM OK";', tv_html)
        self.assertIn(".tv-status[hidden]", site_css)
        self.assertIn("background: #f59e0b;", site_css)

    def test_tv_outgoing_api_warning_requires_queue_above_configured_threshold(self):
        tv_html = self.read_project_file("html/tv-dashboard/index.html")

        self.assertIn(
            "DEFAULT_TV_OUTGOING_API_QUEUE_ALERT_THRESHOLD = 25",
            tv_html,
        )
        self.assertIn(
            "data.tv_outgoing_api_queue_alert_threshold",
            tv_html,
        )
        self.assertIn(
            "outgoingApiQueueExceedsAlertThreshold(",
            tv_html,
        )
        self.assertIn("return safeQueueCount > safeThreshold;", tv_html)

    def test_tv_dashboard_uses_one_fixed_scaled_1080p_canvas(self):
        tv_html = self.read_project_file("html/tv-dashboard/index.html")
        site_css = self.read_project_file("html/assets/site.css")

        self.assertIn('id="tv-stage"', tv_html)
        self.assertIn("TV_CANVAS_WIDTH = 1920", tv_html)
        self.assertIn("TV_CANVAS_HEIGHT = 1080", tv_html)
        self.assertIn("fitTvStageToViewport", tv_html)
        self.assertIn('stage.style.transform = `scale(', tv_html)
        self.assertIn("width: 1920px;", site_css)
        self.assertIn("height: 1080px;", site_css)
        self.assertIn("transform-origin: top left;", site_css)
        self.assertIn("window.innerWidth - scaledWidth", tv_html)
        self.assertIn("window.innerHeight - scaledHeight", tv_html)
        self.assertNotIn("@media (max-width: 1200px), (max-height: 780px)", site_css)

    def test_tv_dashboard_data_is_auto_fitted_to_one_line(self):
        tv_html = self.read_project_file("html/tv-dashboard/index.html")
        site_css = self.read_project_file("html/assets/site.css")

        self.assertIn('class="tv-value tv-elapsed-time"', tv_html)
        self.assertIn('label: "Min"', tv_html)
        self.assertIn('label: "Sec"', tv_html)
        self.assertNotIn('return `${parts.join(", ")} ago`;', tv_html)
        self.assertIn("TV_SINGLE_LINE_SELECTOR", tv_html)
        self.assertIn("fitTvTextToSingleLine", tv_html)
        self.assertIn('window.addEventListener("resize", handleTvViewportResize)', tv_html)
        self.assertIn("overflow-wrap: normal;", site_css)
        self.assertIn("white-space: nowrap;", site_css)

    def test_tv_dashboard_shows_mandatory_scanner_fraction(self):
        tv_html = self.read_project_file("html/tv-dashboard/index.html")

        self.assertIn("mandatoryScanners.required_count", tv_html)
        self.assertIn("mandatoryScanners.connected_count", tv_html)
        self.assertIn(
            "`${formatNumber(connectedMandatoryCount)} of "
            "${formatNumber(requiredMandatoryCount)}`",
            tv_html,
        )
        self.assertIn('`Offline: ${offlineLabels.join(", ")}`', tv_html)
        self.assertIn("All mandatory scanners online", tv_html)
        self.assertIn(".filter((scanner) => !scanner.connected)", tv_html)

    def test_tv_dashboard_reloads_after_deployed_document_changes(self):
        tv_html = self.read_project_file("html/tv-dashboard/index.html")
        nginx_config = self.read_project_file("nginx/industrial-scanner-logger.conf")

        self.assertIn("TV_DASHBOARD_UPDATE_CHECK_MS = 60 * 1000", tv_html)
        self.assertIn("checkForDashboardUpdate", tv_html)
        self.assertIn("fingerprintText(documentText)", tv_html)
        self.assertIn("window.location.reload()", tv_html)
        self.assertIn("location = /tv-dashboard {", nginx_config)
        self.assertIn("location /tv-dashboard/ {", nginx_config)
        self.assertGreaterEqual(
            nginx_config.count(
                'add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;'
            ),
            3,
        )

    def test_stylesheet_is_versioned_and_not_cached_by_nginx(self):
        nginx_config = self.read_project_file("nginx/industrial-scanner-logger.conf")

        for relative_path in (
            "html/index.html",
            "html/health/index.html",
            "html/logs/index.html",
            "html/search/index.html",
            "html/tv-dashboard/index.html",
        ):
            page_html = self.read_project_file(relative_path)
            self.assertIn('href="/assets/site.css?v=1.8"', page_html)

        self.assertIn("location = /assets/site.css {", nginx_config)
        self.assertIn(
            'add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;',
            nginx_config,
        )

    def test_search_exposes_scanner_mode_totals_and_timeout(self):
        search_html = self.read_project_file("html/search/index.html")

        self.assertIn('<option value="scanner">Scanner ID / Name</option>', search_html)
        self.assertIn('/api/v1/scans/summary', search_html)
        self.assertIn('id="search-totals"', search_html)
        self.assertIn("API_REQUEST_TIMEOUT_MS = 15000", search_html)
        self.assertIn("All Duplicate Occurrences", search_html)
        self.assertIn('include_duplicate_occurrences: "true"', search_html)
        self.assertIn("occurrenceTypePill(row.occurrence_type)", search_html)

    def test_logs_page_has_bounded_api_request(self):
        logs_html = self.read_project_file("html/logs/index.html")

        self.assertIn("API_REQUEST_TIMEOUT_MS = 15000", logs_html)
        self.assertIn("fetchWithTimeout(LOGS_API_URL", logs_html)

    def test_search_and_logs_show_delayed_data_loading_overlay(self):
        site_css = self.read_project_file("html/assets/site.css")

        for relative_path in (
            "html/search/index.html",
            "html/logs/index.html",
        ):
            page_html = self.read_project_file(relative_path)
            self.assertIn('id="data-loading-overlay"', page_html)
            self.assertIn("Loading Data", page_html)
            self.assertIn("DATA_LOADING_DELAY_MS = 1000", page_html)
            self.assertIn("const dataRequestId = beginDataRequest();", page_html)
            self.assertIn("endDataRequest(dataRequestId);", page_html)
            self.assertIn("overdueDataRequestIds", page_html)

        self.assertIn(".data-loading-overlay", site_css)
        self.assertIn(".data-loading-spinner", site_css)
        self.assertIn("@keyframes data-loading-spin", site_css)

        logs_html = self.read_project_file("html/logs/index.html")
        self.assertIn('href="${API_ROOT}${row.download_url}"', logs_html)
        self.assertNotIn("downloadCsvWithOverlay", logs_html)

    def test_nginx_serves_search_without_directory_redirect(self):
        nginx_config = self.read_project_file("nginx/industrial-scanner-logger.conf")

        self.assertIn("location = /search {", nginx_config)
        self.assertIn("try_files /search/index.html =404;", nginx_config)
        self.assertGreaterEqual(
            nginx_config.count(
                'add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;'
            ),
            5,
        )

    def test_nginx_serves_logs_without_stale_page_caching(self):
        nginx_config = self.read_project_file("nginx/industrial-scanner-logger.conf")

        self.assertIn("location = /logs {", nginx_config)
        self.assertIn("location /logs/ {", nginx_config)
        self.assertIn("try_files /logs/index.html =404;", nginx_config)
        self.assertGreaterEqual(
            nginx_config.count(
                'add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;'
            ),
            7,
        )


if __name__ == "__main__":
    unittest.main()

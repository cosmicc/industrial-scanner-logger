# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

- Store PostgreSQL scan event timing in one UTC `scan_timestamp` field and
  migrate existing split date/time rows.
- Force PostgreSQL app sessions to UTC and convert legacy local scan times with
  an explicit `America/Detroit` timezone.

## 1.3 - 2026-06-05

- Remove the extra duplicate category and keep one regular duplicate flag.
- Silently drop same-scanner repeats until 3 different successful scans have been accepted on that scanner.
- Page search results from PostgreSQL with selectable 10, 25, 50, 100, or 200 row pages.
- Show total search result counts from PostgreSQL alongside the search page controls.
- Add search date preset buttons for Today, Yesterday, Last 7 Days, Last 30 Days, Last Year, and All Time.
- Default search results to 10 rows per page and tighten the Results card header controls.
- Add Last-page and compact numbered page controls to search result pagination.
- Mirror search pagination below the results table and clarify tracking search length options.
- Make the TV dashboard system status banner consistently full-width and label it System Ok or System Problem.
- Change tracking suffix search from the last 10 digits to the last 12 digits.
- Remove the abandoned order-hold workflow, including its table, API endpoints, search page, navigation links, and TV alert path.
- Remove scanner role storage/display and add scanner-pair duplicate protection for overlapping scanner coverage.
- Store scan tracking numbers as the 12-digit operator value while keeping the full 34-digit value in the barcode field.
- Invert repair storage so repaired rows keep the 12-digit tracking value and write the reconstructed full value to barcode, while raw scan rows keep the original short read.

## 1.2.1 - 2026-05-24 (Pre-release)

- Add configurable health page and TV dashboard refresh intervals.
- Refresh the TV dashboard every second by default and the health page every 3 seconds by default.
- Expand the TV dashboard today panel to show total, successful, duplicate, and failed counts.
- Simplify health page daily total labels.
- Move the TV dashboard updated indicator to the bottom of the page and show elapsed time.

## 1.2.0 - 2026-05-24

- Log same-scanner repeated successful scans instead of silently ignoring them.
- Add `is_duplicate` scan metadata and mark repeats only after the 3 different successful tracking number threshold is met.
- Make PostgreSQL mandatory for receiver startup, duplicate lookups, and scan-event writes.
- Remove obsolete PostgreSQL `enabled` and `required` config options.
- Use PostgreSQL scan history for duplicate decisions over the previous 30 days.
- Add `/logs` for downloading completed daily CSV scan files while excluding the current day.
- Add `/tv-dashboard` for 1920x1080 display of scan-rate, successful-scan, and duplicate totals.
- Update tracking search to use an explicit one-year date range, support suffix searches, and open FedEx links from result rows.
- Add `refresh-nginx-config` for re-rendering the installed nginx site from `/etc/industrial-scanner-logger.conf`.
- Add mandatory scanner connection warnings to the health page and TV dashboard.
- Show last received data and connected scanner count on the TV dashboard.
- Increase the default maximum scanner connection count to 10.
- Mark completed daily CSV files with no scan rows as unavailable for download.
- Paginate the CSV log downloader page in newest-first groups of 10 days.
- Simplify the health, search, and CSV log pages by removing redundant scanner columns and improving empty-day display.
- Display webpage times with 12-hour am/pm formatting.
- Rewrite the home page as an app hub with live status, version metadata, bug-report link, and GitHub source link.
- Show daily CSV total scan and duplicate counts, and add today's per-scanner totals to the health page.
- Add a configurable health dashboard scan-rate stale threshold and color recent scan rows by age.
- Show failed scan counts alongside totals, successful scans, and duplicates on health daily total cards.
- Add `refresh-app-config` for syncing `/etc/industrial-scanner-logger.conf` with the default config schema while preserving existing values.
- Prefer configured scanner names over scanner IDs in dashboard and search displays.

## 1.1.2 - 2026-05-17

- Disable scanner idle disconnects by default so connected scanners can remain idle between boxes.
- Enable configurable TCP keepalive settings for detecting dead scanner sockets.
- Flush buffered undelimited scan data on disconnect, reset, and socket error paths when possible.
- Move high-volume per-scan event lines out of the service console and into daily raw scan data logs.
- Add installer-managed `/var/log/industrial-scanner-logger/scanner-log-data-YYYY-MM-DD.log` files.

## 1.1.1 - 2026-05-17

- Add troubleshooting script logging to console and `/var/log/industrial-scanner-logger.log`.
- Log service startup, version, scanner connections, scanner disconnections, warnings, and errors without writing raw scanner data to the script log.
- Create and preserve the troubleshooting log from the Ubuntu service installer.

## 1.1.0 - 2026-05-17

- Add scanner ID column to daily scan and failed scan CSVs.
- Identify scanners by the last octet of their IPv4 address.
- Track duplicate successful scans independently per scanner.
- Record daily totals per scanner plus an `ALL` aggregate row.

## 1.0.2 - 2026-05-17

- Bound scanner frame size, concurrent clients, idle clients, and shutdown waits.
- Truncate oversized scanner data before writing CSV or console output.
- Stream CSV migrations through temporary files instead of loading whole files.
- Skip corrupt migrated totals rows with a warning instead of crashing startup.
- Validate service-level receiver options more strictly.
- Add MIT license metadata and `LICENSE`.

## 1.0.1 - 2026-05-16

- Fix Ubuntu service installer copy step to avoid `tar: .: file changed as we read it`.

## 1.0.0 - 2026-05-16

- Add baseline Python project structure.
- Package the HF811 TCP receiver as `industrial_scanner_logger`.
- Add `scanner-tcp-receiver` console script entry point.
- Keep `scanner_tcp_receiver.py` as a direct-run compatibility wrapper.
- Add unit tests and GitHub Actions CI.
- Add Ubuntu systemd install and uninstall scripts with service-level receiver options.
- Add package versioning and startup version output.

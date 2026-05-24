# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

- Log same-scanner repeated successful scans instead of silently ignoring them.
- Add `is_duplicate` scan metadata and mark repeats only after the 3 different successful tracking number threshold is met.
- Keep `is_cross_scanner_duplicate` as a narrower flag for duplicate scans previously accepted from another scanner.
- Make PostgreSQL mandatory for receiver startup, duplicate lookups, and scan-event writes.
- Remove obsolete PostgreSQL `enabled` and `required` config options.
- Use PostgreSQL scan history for duplicate decisions over the previous 30 days.
- Add `/logs` for downloading completed daily CSV scan files while excluding the current day.
- Add `/tv-dashboard` for 1920x1080 display of scan-rate, successful-scan, and duplicate totals.
- Update tracking search to use an explicit one-year date range, support last-10-digit searches, and open FedEx links from result rows.
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
- Restrict `is_cross_scanner_duplicate` to the configured last scanner; other scanner repeats remain regular duplicates.
- Add a configurable health dashboard scan-rate stale threshold and color recent scan rows by age.
- Show failed scan counts alongside totals, successful scans, and duplicates on health daily total cards.
- Add `refresh-app-config` for syncing `/etc/industrial-scanner-logger.conf` with the default config schema while preserving existing values.

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

# Changelog

All notable changes to this project will be documented in this file.

## 1.7 - 07.29.2026

### Added

- Add `[scanners] scanner_pair_suppression_distinct_successes`, defaulting to
  10 different accepted successful packages, for tuning overlapping scanner
  pair suppression.
- Add fixed-canvas TV dashboard scaling that preserves one 1920x1080 layout
  across full-screen viewport sizes.

### Changed

- Suppress a repeat from another scanner in the same configured pair until the
  configured number of different successful packages has progressed through
  the pair, without a separate short time timeout.
- Hide the TV dashboard health overlay completely while the system is healthy.
- Remove the obsolete `last_scanner_id` config, installer option, receiver and
  API metadata, PostgreSQL columns and index, missing-last-scanner view, and
  related API route.
- Move the unreleased development version to 1.7.

### Fixed

- Prevent paired scanners from recording expected overlap reads as duplicates
  after only three intervening packages.
- Keep paired-scanner suppression active through long conveyor stops, including
  lunch breaks, because failed, repeated, and suppressed reads do not advance
  its package-progression window.
- Prevent TV dashboard media queries from rearranging panels or changing
  coordinates outside the exact 1920x1080 viewport.

## 1.6 - 07.24.2026

### Added

- Add one severity-aware TV dashboard health overlay that combines all active
  scanner, PostgreSQL, drive-space, outgoing API, and mandatory-scanner issues.

### Changed

- Show one yellow warning or red critical overlay at the top of the TV
  dashboard without moving page content.
- Remove "ago" from the Last Received Data age and abbreviate minutes and
  seconds as `Min` and `Sec`.
- Keep the TV status bar in a fixed overlay layer for healthy, warning, and
  critical states so health refreshes never change dashboard coordinates.

### Fixed

- Keep the TV dashboard's Last Received Data age on one line.
- Prevent a degraded TV dashboard from showing separate system and mandatory
  scanner warning bars.
- Render warning overlays with a clearly yellow background and automatically
  shrink all TV dashboard text to keep every data value on one line.
- Version stylesheet requests and disable nginx caching for the shared
  stylesheet so updated dashboard colors and positioning cannot be hidden by a
  stale browser cache.

## 1.5 - 07.15.2026

### Added

- Add a dedicated scanner ID/name search mode with explicit scanner IDs and
  configured names in the selector and result rows.
- Add matching search totals for all, successful, failed, duplicate, and
  repaired scans.
- Add a root `VERSION` file for release and deployment scripts.
- Add bounded browser API requests and remote-path troubleshooting guidance for
  the Search and CSV Logs pages.

### Changed

- Move the development version to 1.5.
- Remove the duplicate version display below the home-page health indicator
  while retaining the version in the home-page footer.
- Reformat every changelog release with `MM.DD.YYYY` dates and Added, Changed,
  and Fixed sections.

### Fixed

- Calculate the TV dashboard's last-received age from the scanner server's
  generated timestamp so a wrong viewing-device clock cannot keep it at Now.
- Serve `/search` through an explicit nginx route so remote requests do not
  depend on an externally unsafe directory redirect.
- Show a clear timeout error when a remote proxy or application firewall drops
  the Search or CSV Logs API request instead of leaving the page loading
  indefinitely.

## 1.4 - 06.24.2026

### Added

- Add an optional outgoing API sender with a PostgreSQL-backed scan delivery
  queue, retry metadata, secure config placeholders, and health page queue
  status.
- Add `[outgoing_api] api_key` to the app config and restrict refreshed
  installed config files to root plus the scanner service group.
- Add the `industrial-scanner-health` CLI helper for read-only service,
  database, outgoing API, storage, mandatory scanner, and same-day scan
  monitoring from a shell.
- Expand `AGENTS.md` into a comprehensive agent onboarding guide covering app
  architecture, scan flow, storage invariants, timezone handling, outgoing API
  behavior, install/uninstall boundaries, security rules, and validation.

### Changed

- Store PostgreSQL scan event timing in one timezone-free UTC `scan_timestamp`
  field and migrate existing split date/time rows.
- Force PostgreSQL app sessions to UTC and convert legacy local scan times with
  an explicit `America/Detroit` timezone.
- Send outgoing scan webhooks with the configured `X-Scanner-Api-Key`, the
  required scan JSON fields, and UTC `Z` timestamps.
- Include configured `scanner_name`, `is_success`, and `failure_reason` in
  outgoing scan webhook payloads, and queue raw-only failed scans for delivery.
- Harden production uptime by making installed services always restart,
  keeping scanner intake running when outgoing API sender config is not ready,
  and adding health page disk-space monitoring with a prominent low-space
  warning.
- Refresh rendered systemd unit files from `update-services` so deployed
  services pick up restart-policy changes.
- Make uninstall remove only service/startup integration by default while
  preserving `/etc/industrial-scanner-logger.conf`, the installed app directory,
  logs, CSV files, helper scripts, service identity, UFW state, and PostgreSQL
  data; make reinstall use the preserved config before database setup.
- Make `scripts/install.sh` safe to re-run as an install refresh, preserving
  existing config, app data, PostgreSQL state, logs, and unrelated UFW rules
  while refreshing managed files, schema, helpers, units, nginx, and services.
- Run the `industrial-scanner-health` wrapper as the scanner service user when
  invoked through sudo/root so local PostgreSQL peer-auth installs report the
  same database-backed health and today totals as the web health page.
- Colorize `industrial-scanner-health` terminal output with green healthy
  statuses, yellow warnings, red failures, readable section headings, and
  `--color auto|always|never` control.
- Render all human-facing scan dates, scan times, CSV log dates, health totals,
  search rows, TV dashboard rows, and CLI health data in `America/Detroit`
  while keeping stored PostgreSQL timestamps and outgoing API payloads in UTC.
- Remove the API service card from the health page and move PostgreSQL and
  storage status cards into the first status row.

### Fixed

- Prevent suppressed duplicate repeats from being queued for outgoing API
  delivery.
- Use raw scan data rows, not scanner connection or disconnection log messages,
  for the health dashboard's latest received data.

## 1.3 - 06.05.2026

### Added

- Page search results from PostgreSQL with selectable 10, 25, 50, 100, or 200
  row pages.
- Show total search result counts from PostgreSQL alongside the search page
  controls.
- Add search date preset buttons for Today, Yesterday, Last 7 Days, Last 30
  Days, Last Year, and All Time.
- Add Last-page and compact numbered page controls to search result pagination.
- Add scanner-pair duplicate protection for scanners covering overlapping
  conveyor areas.

### Changed

- Remove the extra duplicate category and keep one regular duplicate flag.
- Silently drop same-scanner repeats until three different successful scans
  have been accepted on that scanner.
- Default search results to 10 rows per page and tighten the Results card header
  controls.
- Mirror search pagination below the results table and clarify tracking search
  length options.
- Make the TV dashboard system status banner consistently full-width and label
  it System OK or System Problem.
- Change tracking suffix search from the last 10 digits to the last 12 digits.
- Remove the abandoned order-hold workflow, including its table, API endpoints,
  search page, navigation links, and TV alert path.
- Remove scanner role storage and display.
- Store scan tracking numbers as the 12-digit operator value while keeping the
  full 34-digit value in the barcode field.

### Fixed

- Store repaired rows with the 12-digit tracking value and reconstructed full
  barcode while retaining the original short read in raw scan rows.

## 1.2.1 - 05.24.2026 - Pre-release

### Added

- Add configurable health page and TV dashboard refresh intervals.
- Expand the TV dashboard today panel to show total, successful, duplicate, and
  failed counts.

### Changed

- Refresh the TV dashboard every second by default and the health page every
  three seconds by default.
- Simplify health page daily total labels.
- Move the TV dashboard updated indicator to the bottom of the page and show
  elapsed time.

### Fixed

- No entries.

## 1.2.0 - 05.24.2026

### Added

- Add `is_duplicate` scan metadata and mark repeats only after the three
  different successful tracking number threshold is met.
- Add PostgreSQL scan-history duplicate decisions over the previous 30 days.
- Add `/logs` for downloading completed daily CSV scan files while excluding
  the current day.
- Add `/tv-dashboard` for a 1920x1080 display of scan-rate, successful-scan, and
  duplicate totals.
- Add `refresh-nginx-config` for re-rendering the installed nginx site from
  `/etc/industrial-scanner-logger.conf`.
- Add mandatory scanner connection warnings to the health page and TV
  dashboard.
- Add completed daily CSV total scan and duplicate counts and today's
  per-scanner totals to the health page.
- Add a configurable health dashboard scan-rate stale threshold and color
  recent scan rows by age.
- Add `refresh-app-config` for synchronizing the installed config with the
  default schema while preserving existing values.

### Changed

- Log same-scanner repeated successful scans instead of silently ignoring them.
- Make PostgreSQL mandatory for receiver startup, duplicate lookups, and scan
  event writes.
- Remove obsolete PostgreSQL `enabled` and `required` config options.
- Update tracking search to use an explicit one-year date range, support suffix
  searches, and open FedEx links from result rows.
- Show last received data and connected scanner count on the TV dashboard.
- Increase the default maximum scanner connection count to 10.
- Paginate the CSV log downloader page in newest-first groups of 10 days.
- Simplify the health, search, and CSV log pages by removing redundant scanner
  columns and improving empty-day display.
- Display webpage times with 12-hour am/pm formatting.
- Rewrite the home page as an app hub with live status, version metadata,
  bug-report link, and GitHub source link.
- Show failed scan counts alongside totals, successful scans, and duplicates on
  health daily total cards.
- Prefer configured scanner names over scanner IDs in dashboard and search
  displays.

### Fixed

- Mark completed daily CSV files with no scan rows as unavailable for download.

## 1.1.2 - 05.17.2026

### Added

- Add configurable TCP keepalive settings for detecting dead scanner sockets.
- Add installer-managed
  `/var/log/industrial-scanner-logger/scanner-log-data-YYYY-MM-DD.log` files.

### Changed

- Disable scanner idle disconnects by default so connected scanners can remain
  idle between boxes.
- Move high-volume per-scan event lines out of the service console and into
  daily raw scan data logs.

### Fixed

- Flush buffered undelimited scan data on disconnect, reset, and socket error
  paths when possible.

## 1.1.1 - 05.17.2026

### Added

- Add troubleshooting script logging to console and
  `/var/log/industrial-scanner-logger.log`.
- Log service startup, version, scanner connections, scanner disconnections,
  warnings, and errors without writing raw scanner data to the script log.
- Create and preserve the troubleshooting log from the Ubuntu service
  installer.

### Changed

- No entries.

### Fixed

- No entries.

## 1.1.0 - 05.17.2026

### Added

- Add scanner ID columns to daily scan and failed scan CSVs.
- Identify scanners by the last octet of their IPv4 address.
- Add daily totals per scanner plus an `ALL` aggregate row.

### Changed

- Track duplicate successful scans independently per scanner.

### Fixed

- No entries.

## 1.0.2 - 05.17.2026

### Added

- Add MIT license metadata and `LICENSE`.

### Changed

- Bound scanner frame size, concurrent clients, idle clients, and shutdown
  waits.
- Truncate oversized scanner data before writing CSV or console output.
- Stream CSV migrations through temporary files instead of loading whole files.
- Validate service-level receiver options more strictly.

### Fixed

- Skip corrupt migrated totals rows with a warning instead of crashing startup.

## 1.0.1 - 05.16.2026

### Added

- No entries.

### Changed

- No entries.

### Fixed

- Fix the Ubuntu service installer copy step to avoid
  `tar: .: file changed as we read it`.

## 1.0.0 - 05.16.2026

### Added

- Add the baseline Python project structure.
- Package the HF811 TCP receiver as `industrial_scanner_logger`.
- Add the `scanner-tcp-receiver` console script entry point.
- Add unit tests and GitHub Actions CI.
- Add Ubuntu systemd install and uninstall scripts with service-level receiver
  options.
- Add package versioning and startup version output.

### Changed

- Keep `scanner_tcp_receiver.py` as a direct-run compatibility wrapper.

### Fixed

- No entries.

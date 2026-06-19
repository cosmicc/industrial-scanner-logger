# AGENTS.md

Read this file before changing the Industrial Scanner Logger app. It is the
agent onboarding guide for the codebase: what the app does, how scan data moves
through it, which files own which behavior, and which invariants must not be
broken.

## Project Mission

Industrial Scanner Logger is a Debian/Ubuntu, systemd-managed Python app for
fixed-mount industrial barcode scanners. It accepts scanner output over TCP,
classifies FedEx scan events, writes CSV and raw scan logs, stores scan data in
PostgreSQL, optionally delivers processed scans to an outgoing API, exposes a
read-only FastAPI service behind nginx, serves static browser dashboards, and
provides a shell health report.

The highest-value runtime path is local scanner capture. External API delivery,
dashboards, and reporting must not weaken local scan intake or corrupt stored
scan history.

## Security Priorities

- Security is the highest-priority requirement for every change.
- Treat scanner data, API credentials, database access, systemd services,
  nginx config, firewall rules, and health output as security-sensitive.
- Do not log secrets, bearer tokens, outgoing API keys, database passwords, or
  unnecessary raw scanner payloads.
- Keep full raw barcode output out of routine service logs. Raw per-scan
  diagnostic lines belong in the configured raw scan data log files, and even
  there oversized values are replaced with a marker.
- Prefer explicit validation, least privilege, safe failure behavior, and
  durable local logging over convenience.
- The service config can contain `outgoing_api.api_key`. Installed config files
  must remain restricted to root plus the scanner service group.
- External outgoing API URLs must be HTTPS. Plain HTTP is allowed only for
  localhost-style testing.

## Implementation Expectations

- Ask clarifying questions before coding when the request, data flow, security
  impact, or expected behavior is unclear.
- Provide technical feedback when a requested approach creates a security,
  reliability, data-integrity, or maintainability risk.
- Do not take shortcuts. Implement complete behavior, validation, tests, and
  documentation that match the scope of the change.
- Keep code clear to read. Use descriptive names for variables, functions,
  classes, config keys, database columns, and tests.
- Add useful comments for non-obvious code, security-sensitive decisions,
  important variables, database fields, migrations, and operational behavior.
  Avoid comments that only restate syntax.
- Python should follow PEP rules except the line length rule used by this repo.
- Keep `CHANGELOG.md` updated for every meaningful code, schema, config,
  installer, API, documentation, or web UI change.
- Preserve existing scanner processing semantics unless the user explicitly
  changes them.

## Repository Map

- `src/industrial_scanner_logger/receiver.py` is the TCP receiver, CSV writer,
  PostgreSQL writer, duplicate detector, repair logic, outgoing API sender, and
  receiver config loader.
- `src/industrial_scanner_logger/api.py` is the FastAPI app used by browser
  pages and the CLI health report. It is read-only against scan data.
- `src/industrial_scanner_logger/health_cli.py` formats the same health payload
  as a terminal report.
- `src/industrial_scanner_logger/timezones.py` owns the timezone contract for
  display time and UTC database comparisons.
- `db/schema.sql` owns tables, migrations, generated columns, indexes, grants,
  and read-only views.
- `config/industrial-scanner-logger.conf` is the default INI schema.
- `scripts/install.sh` installs and refreshes the production app.
- `scripts/uninstall.sh` removes service/startup integration while preserving
  app data.
- `scripts/update-services` refreshes schema, web files, health helper, systemd
  units, and running services in an installed app.
- `scripts/refresh-app-config` and `scripts/refresh-nginx-config` synchronize
  installed config and nginx files.
- `scripts/industrial-scanner-health` is the installed wrapper that runs the
  Python CLI health module, switching to the service user under sudo/root.
- `systemd/*.service` are templates rendered by install/update scripts.
- `nginx/industrial-scanner-logger.conf` is the nginx site template.
- `html/` contains static browser UI: home, health, logs, search, TV dashboard,
  and shared CSS.
- `scanner_tcp_receiver.py` is the compatibility wrapper for the receiver.
- `tests/` contains unit tests for receiver behavior, API/query behavior, CLI
  health formatting, and installer script expectations.

## Runtime Entry Points

- `scanner-tcp-receiver` maps to `industrial_scanner_logger.receiver:main`.
- `scanner-rest-api` maps to `industrial_scanner_logger.api:main`.
- `industrial-scanner-health` maps to `industrial_scanner_logger.health_cli:main`.
- The receiver systemd service runs `@PYTHON_BIN@ @INSTALL_DIR@/scanner_tcp_receiver.py`.
- The API systemd service runs `@PYTHON_BIN@ -m industrial_scanner_logger.api`.
- Nginx serves `/` from the static web root and proxies `/api/` to uvicorn.

## Core Data Flow

1. A scanner connects to the TCP receiver. Scanner ID is derived from the last
   octet of the scanner IPv4 address; unknown or invalid addresses become
   `UNKNOWN` in CSV and scanner ID `0` in PostgreSQL.
2. `handle_client()` reads TCP frames. Line endings flush frames. If scanners
   send data without line endings, `frame_idle_timeout` flushes the buffered
   frame. Oversized frames are recorded as an oversized marker instead of the
   raw payload.
3. `write_client_scan()` passes the cleaned frame to
   `DailyCsvLogger.write_scan_event()`.
4. `DailyCsvLogger` rotates the daily CSV and raw scan data log on the
   `America/Detroit` calendar day, loads existing same-day state after restart,
   and migrates old CSV headers when needed.
5. A scan is `SUCCESS` only when the cleaned barcode is exactly
   `success_length` numeric digits. The default and FedEx rule is 34 digits.
   Blank values, configured no-read text, wrong lengths, and non-numeric values
   are `FAILED`.
6. Successful scans use the last 12 digits as `tracking_number`; the full
   34-digit value remains in `barcode`. Failed and raw rows keep diagnostic
   values where useful.
7. Duplicate decisions are checked before accepting a successful scan. The
   receiver prefers PostgreSQL-backed lookup over in-memory state when
   PostgreSQL is available.
8. Accepted events are written to the daily CSV, failed scans CSV when
   applicable, raw scan data log, `scanner_logger.raw_scan_events`, and usually
   `scanner_logger.scan_events`.
9. If outgoing API is enabled, accepted processed `scan_events` rows are queued
   in `scanner_logger.outgoing_scan_queue`.
10. The API, browser pages, and CLI health report read from PostgreSQL and
    local service/log state; they do not mutate scan history.

## Scan Semantics

- Default success length is 34 numeric digits.
- Default operator-facing tracking number length is 12 digits, taken from the
  end of a successful barcode.
- `scanner_logger.scan_events` is the processed scan source of truth.
- `scanner_logger.raw_scan_events` stores pre-repair/raw scanner values and is
  the source for raw scan rows shown on the health page.
- Nonnumeric failed scans, including the no-read marker, are raw-only in
  PostgreSQL. They still appear in CSV/failed-scan logging.
- Repaired scans store the repaired full 34-digit barcode in `barcode` and the
  12-digit suffix in `tracking_number`; the original short read remains in
  `raw_scan_events`.
- Do not change scanner intake, duplicate, repair, or raw/final table behavior
  unless the user explicitly asks for that semantic change.

## Duplicate Logic

- Duplicate handling is intentionally conservative. It suppresses immediate
  repeats but still records meaningful later repeats.
- Duplicate protection is scoped to the scanner's duplicate group. By default
  each scanner is its own group. `[scanners] scanner_pairs` can join scanners
  that cover overlapping conveyor areas.
- A successful tracking number that was already seen in its duplicate group is
  silently dropped until there have been at least 3 different successful
  tracking numbers accepted in that group since the previous accepted scan of
  the same tracking number.
- Once the threshold is met, the repeat is accepted with `is_duplicate = true`.
- PostgreSQL duplicate lookup considers the previous 30 days with UTC stored
  timestamps. The in-memory state is only a fallback/restart helper.

## Tracking Repair

- Tracking repair is disabled by default and controlled by
  `[receiver] tracking_repair_enabled`.
- Repair only applies to short numeric failed scans. It never repairs blank
  values, no-read markers, nonnumeric values, values already at or above the
  success length, or values with too little overlap.
- A short value is repaired only if successful scans from the same visible
  `America/Detroit` day produce exactly one matching full-length candidate.
- Ambiguous repair candidates must leave the scan failed.
- Repair logs should use truncated values and must not expose excessive raw
  scanner data.

## PostgreSQL Contract

- PostgreSQL is mandatory for production receiver startup, duplicate decisions,
  scan writes, API queries, health totals, and outgoing API queueing.
- The default local DSN is
  `postgresql:///scannerlogger?host=/var/run/postgresql&user=scannerlogger`.
  It relies on the Linux service user and PostgreSQL role both being
  `scannerlogger`.
- Keep database scan timestamps as UTC values in
  `TIMESTAMP(0) WITHOUT TIME ZONE` columns unless the user explicitly changes
  that requirement.
- Receiver and API PostgreSQL connections must keep
  `options="-c timezone=UTC"` so current-time comparisons and migrations behave
  predictably.
- `db/schema.sql` must remain idempotent. It handles fresh installs, legacy
  split `scan_date`/`scan_time` rows, and previous `TIMESTAMPTZ` columns.
- Do not hand-roll SQL identifiers with string interpolation. Use
  `psycopg.sql.Identifier`/`SQL` for dynamic schema/table names.
- Generated columns in both scan tables calculate `barcode_length`,
  `is_success`, and `failure_reason`; keep Python and SQL success semantics in
  sync.
- Read-only views are human-facing and derive visible dates/times in
  `America/Detroit`. Base table storage remains UTC.
- Grants must keep the service role able to insert/select scan tables and
  insert/select/update/delete queue rows without broader privileges.

## Timezone Contract

- Store PostgreSQL scan timestamps in UTC only. The canonical database column is
  `scan_timestamp TIMESTAMP(0) WITHOUT TIME ZONE`; values are naive UTC by
  convention, not local time and not embedded-timezone values.
- Use `src/industrial_scanner_logger/timezones.py` for display-time handling.
  `DISPLAY_TIMEZONE_NAME` is `America/Detroit`.
- Treat all human-facing dates and times as `America/Detroit` time. This
  includes the health page, TV dashboard, scan search, CSV log browser,
  command-line health report, daily CSV filenames and rows, failed scan CSV
  rows, raw scan data log lines, raw scan rows shown on the health page, and
  "today" or "yesterday" totals.
- When filtering database rows for a visible calendar day, convert the
  `America/Detroit` day start and next-day start to UTC-naive bounds first,
  then compare those bounds against `scan_timestamp`. Do not use
  `date.today()`, server-local time, `scan_timestamp::date`, or
  `scan_timestamp::time(0)` for human-facing day boundaries.
- When presenting a stored scan timestamp, treat the database value as UTC and
  convert it to `America/Detroit` before returning `scan_date`, `scan_time`, or
  visible `scan_timestamp` to browser pages, the CLI, or other troubleshooting
  output.
- The outgoing API payload is the only intentional exception: outbound scan
  JSON must keep `scan_timestamp` in UTC seconds with a trailing `Z`. Do not
  convert the sender payload timestamp to `America/Detroit`.
- Queue and health metadata that is displayed to people should be converted to
  `America/Detroit`; internal retry timing and stored queue timestamps should
  remain UTC.
- Browser code should not rely on the viewer's local timezone for scanner
  timestamps. Prefer offset-bearing timestamps from the API plus explicit
  `America/Detroit` formatting.

## Outgoing API Contract

- Outgoing delivery is optional. Scanner intake should continue when outgoing
  API config is absent or the sender cannot start.
- Only processed rows inserted into `scanner_logger.scan_events` are queued.
  Raw-only rows are not sent.
- The sender posts one JSON row per request with `Content-Type:
  application/json`, `Accept: application/json`, and `X-Scanner-Api-Key`.
- The outgoing JSON body is intentionally small:
  `scanner_id`, `tracking_number`, `barcode`, `is_repaired`, `is_duplicate`,
  and UTC `scan_timestamp`.
- Successful delivery deletes only the queue row. It never deletes scan
  history.
- HTTP `429` and `5xx` responses are retryable. Other non-2xx responses are
  recorded as delivery failures but do not remove scan history.
- Error text is bounded and must redact the outgoing API key if an upstream
  response echoes it.
- Health output may show queue state, counts, last HTTP status, and sanitized
  error text, but never secrets.

## CSV And Local File Contract

- Daily scan CSVs live under `[receiver] output_dir` and are named
  `<prefix>_YYYY-MM-DD.csv` using the `America/Detroit` day.
- Daily CSV header is:
  `date,time,scanner_id,scanner_name,status,is_duplicate,is_repaired,tracking`.
- `failed_scans.csv` is append-only and does not rotate.
- `scan_totals.csv` records completed day totals by scanner plus `ALL`.
- Raw per-scan data logs live under `[logging] scan_data_log_dir` and rotate by
  `America/Detroit` day.
- CSV migrations must stream through temp files; do not load large files into
  memory.
- Oversized scanner input must be replaced with an oversized marker before
  storage/logging.
- Existing CSV/log data is valuable production history. Do not delete or
  regenerate it unless the user explicitly requests destructive cleanup.

## REST API And Web UI

- `api.py` is a read-only FastAPI service. It should not mutate scan history.
- Public nginx paths are `/api/v1/...`, `/health`, `/logs`, `/search`, and
  `/tv-dashboard`.
- Uvicorn routes are `/v1/...`; nginx strips the `/api` prefix when proxying.
- `/api/v1/dashboard/health` is the shared payload for the web health page, TV
  dashboard, and CLI health report.
- `/api/v1/scans` and `/api/v1/scans/count` support date range, scanner,
  barcode/tracking, status, duplicate, repair, limit, and offset filters.
- Numeric 12-digit barcode filters match `tracking_number` and the rightmost
  12 digits of full barcode fields.
- `/api/v1/logs/daily-csv` excludes the current `America/Detroit` day because
  that CSV may still be open.
- Browser pages are static files under `html/`; after install they are copied
  to the nginx web root. If you change static assets, install/update workflows
  must copy them.
- UI health output must be useful for troubleshooting without exposing secrets.

## CLI Health Contract

- The installed shell wrapper is `scripts/industrial-scanner-health`; the
  Python formatter is `health_cli.py`.
- When run via sudo/root, the wrapper should execute as the service user so
  local PostgreSQL peer auth reads the same rows as the receiver/API services.
- CLI health should use `api.build_dashboard_health()` for the same database,
  today totals, storage, scanner, and outgoing API checks as the web health
  page.
- Default terminal output is colorized: green for healthy, yellow for warning,
  red for failure. Keep `--color auto|always|never` and `NO_COLOR` behavior.
- The command exits nonzero when required health checks are degraded, unless
  `--no-fail` is used.

## Install, Refresh, And Uninstall Boundaries

- `scripts/install.sh` is both installer and refresh path. Re-running it on an
  installed host should refresh managed files, schema, venv dependencies,
  helpers, systemd units, nginx files, web files, firewall rules owned by this
  app, and services without duplicating resources.
- If `/etc/industrial-scanner-logger.conf` exists, install should treat it as
  authoritative unless `--overwrite-config` is used. This preserves DSN, paths,
  scanner IDs, API settings, and nginx settings across reinstall.
- Do not reset UFW. The app may add required rules, but unrelated host firewall
  rules must survive refreshes.
- `scripts/uninstall.sh` is intentionally non-destructive. It removes service
  startup integration and the app nginx site, but preserves `/etc` config,
  install directory, logs, CSVs, raw logs, web root, helper scripts, service
  identity, PostgreSQL package/service/roles/databases/schemas/data, nginx
  package, and UFW state.
- `scripts/update-services` is the post-deploy refresh helper for installed
  apps. It reapplies schema, copies HTML, renders systemd units, refreshes the
  CLI helper, restarts receiver/API services, and should be kept in sync with
  install-managed paths.
- Raw systemd templates contain placeholders such as `@INSTALL_DIR@`; verify
  rendered units, not raw templates, when checking systemd syntax.

## Configuration Contract

- Default config schema lives in `config/industrial-scanner-logger.conf`.
- Runtime config for installed services is `/etc/industrial-scanner-logger.conf`.
- `load_receiver_config()` reads the INI file and returns a namespace used by
  receiver, API, and CLI health paths.
- Add new config options to the default config file, config loader, install
  script, refresh helper behavior if needed, README/CHANGELOG, and tests.
- Keep validation strict: numeric ranges, safe filename prefixes, scanner IDs
  in 0-255 range, schema.table names only for PostgreSQL table config, API root
  path beginning with `/`, and API root path not `/` when nginx is enabled.
- Never silently accept malformed scanner pair config; overlapping group
  definitions can corrupt duplicate behavior.

## Tests And Validation

Use targeted validation for the files you change. Typical commands:

```bash
python3 -m compileall src tests
python3 -m unittest discover -s tests
git diff --check
```

When API dependencies are available, run the full dependency-backed suite:

```bash
/tmp/industrial-scanner-health-check/bin/python -m unittest discover -s tests
```

For shell script changes:

```bash
bash -n scripts/install.sh scripts/uninstall.sh scripts/update-services \
  scripts/refresh-app-config scripts/refresh-nginx-config \
  scripts/industrial-scanner-health
```

Run `shellcheck` on touched shell scripts when available. If a validation
command cannot be run, say so clearly in the final response.

When changing browser JavaScript, at minimum parse inline scripts with Node or
otherwise validate syntax. When changing UI behavior, inspect the page or add a
focused test if practical.

When changing schema or migrations, validate against a disposable PostgreSQL
database or temp cluster when practical. At minimum, inspect idempotence and
legacy migration paths carefully.

## Common Pitfalls

- Do not derive visible day boundaries from UTC midnight.
- Do not convert outgoing API payload timestamps to `America/Detroit`.
- Do not treat raw scan rows and processed scan rows as interchangeable.
- Do not delete CSV/log/PostgreSQL history as part of fixes or reinstall work.
- Do not bypass PostgreSQL duplicate lookup with only in-memory state in
  production paths.
- Do not expose API keys, database passwords, full raw scanner payloads, or
  bearer tokens in health output, logs, or test fixtures.
- Do not use broad string interpolation for SQL identifiers.
- Do not run destructive git commands or revert unrelated user changes.
- Do not skip `CHANGELOG.md` for behavior, schema, config, installer, or
  documentation changes.

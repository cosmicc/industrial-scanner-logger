# AGENTS.md

Read this file before changing the Industrial Scanner Logger app.

## Project Priorities

- Security is the highest-priority requirement for every change.
- Treat scanner data, API credentials, database access, systemd services, and
  web health output as security-sensitive surfaces.
- Do not log secrets, bearer tokens, OAuth2 client secrets, database passwords,
  or unnecessary raw scanner payloads in troubleshooting logs.
- Prefer secure defaults, explicit validation, least privilege, and clear
  failure behavior over convenience.

## Implementation Expectations

- Ask clarifying questions before coding when the request, data flow, security
  impact, or expected behavior is unclear.
- Provide technical feedback when a requested approach creates a security,
  reliability, data integrity, or maintainability risk.
- Do not take shortcuts. Implement complete behavior, validation, tests, and
  documentation that match the scope of the change.
- Keep code clear to read. Use descriptive names for variables, functions,
  classes, config keys, database columns, and tests.
- Add useful remarks/comments for non-obvious code, security-sensitive choices,
  variables with important meaning, database fields, and operational behavior.
- Avoid comments that merely repeat obvious syntax.
- Python should follow PEP rules except the line length rule used by this repo.

## Project Conventions

- Keep `CHANGELOG.md` updated for every meaningful code, schema, config,
  installer, API, or web UI change.
- Keep database scan timestamps as UTC values in
  `TIMESTAMP(0) WITHOUT TIME ZONE` columns unless the user explicitly changes
  that requirement.
- Keep local CSV timestamp behavior separate from database UTC storage.
- Preserve existing scanner processing semantics unless the user explicitly
  changes them.
- Keep scanner intake independent from external API health or configuration
  whenever possible; local scanner capture is the highest-priority runtime path.
- Use `scanner_logger.scan_events` as the processed scan source of truth.
- Use `scanner_logger.raw_scan_events` for pre-repair/raw scanner values.
- Health pages should be useful for troubleshooting without exposing secrets.

## Timezone Contract

- Store PostgreSQL scan timestamps in UTC only. The canonical database column is
  `scan_timestamp TIMESTAMP(0) WITHOUT TIME ZONE`; values are naive UTC by
  convention, not local time and not embedded-timezone values.
- Keep PostgreSQL app sessions pinned to UTC with `options="-c timezone=UTC"`
  so current-time database comparisons and migrations behave predictably.
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
  `scan_timestamp` to browser pages, the CLI, or other troubleshooting output.
- The outgoing API payload is the only intentional exception: outbound scan
  JSON must keep `scan_timestamp` in UTC seconds with a trailing `Z`. Do not
  convert the sender payload timestamp to `America/Detroit`.
- Queue and health metadata that is displayed to people should be converted to
  `America/Detroit`; internal retry timing and stored queue timestamps should
  remain UTC.
- Browser code should not rely on the viewer's local timezone for scanner
  timestamps. Prefer offset-bearing timestamps from the API plus explicit
  `America/Detroit` formatting.

## Validation Expectations

- Run targeted tests for changed Python behavior when practical.
- Run syntax/compile checks for changed Python files when practical.
- Check shell scripts touched by the change with syntax validation when
  practical.
- If a validation command cannot be run, document that clearly in the final
  response.

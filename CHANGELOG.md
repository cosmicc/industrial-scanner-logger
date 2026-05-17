# Changelog

All notable changes to this project will be documented in this file.

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

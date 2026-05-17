# Changelog

All notable changes to this project will be documented in this file.

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

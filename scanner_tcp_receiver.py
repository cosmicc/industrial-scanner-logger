#!/usr/bin/env python3
"""
Backward-compatible entry point for running the scanner receiver from the repo.

After installing the package, the same command is also available as:
    scanner-tcp-receiver
"""

from pathlib import Path
import sys


src_dir = Path(__file__).resolve().parent / "src"
if src_dir.exists():
    sys.path.insert(0, str(src_dir))

from industrial_scanner_logger.receiver import main


if __name__ == "__main__":
    raise SystemExit(main())

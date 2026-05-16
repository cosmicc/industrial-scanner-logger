# Contributing

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Checks

```bash
python -m unittest discover -s tests
ruff check .
```

Keep runtime dependencies minimal unless the added dependency removes meaningful operational complexity.

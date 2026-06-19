"""
Timezone helpers for scanner timestamps.

PostgreSQL stores scanner timestamps as timezone-free UTC values. Human-facing
CSV files, dashboards, and search results use America/Detroit time, while the
outgoing API sender keeps its explicit UTC payload contract.
"""

from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

DISPLAY_TIMEZONE_NAME = "America/Detroit"
DISPLAY_TIMEZONE = ZoneInfo(DISPLAY_TIMEZONE_NAME)


def display_now() -> datetime:
    """Return the current America/Detroit timestamp for visible status payloads."""
    return datetime.now(DISPLAY_TIMEZONE).replace(microsecond=0)


def display_today() -> date:
    """Return today's date in the scanner site's display timezone."""
    return display_now().date()


def display_datetime_from_utc(value) -> Optional[datetime]:
    """
    Convert a UTC database timestamp into America/Detroit time.

    The database stores UTC instants in TIMESTAMP WITHOUT TIME ZONE columns, so
    naive datetime values from psycopg must be treated as UTC before display.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        timestamp = parse_timestamp_string(value)
    else:
        return None

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(DISPLAY_TIMEZONE)


def display_timestamp_from_utc(value) -> Optional[str]:
    """Format a UTC database timestamp as America/Detroit ISO seconds."""
    display_timestamp = display_datetime_from_utc(value)

    if display_timestamp is None:
        return None

    return display_timestamp.isoformat(timespec="seconds")


def display_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """
    Return UTC-naive bounds for one America/Detroit calendar day.

    These bounds are safe for comparing against the UTC-by-convention database
    `scan_timestamp` column without changing how the timestamp is stored.
    """
    start_local = datetime.combine(day, datetime_time.min, tzinfo=DISPLAY_TIMEZONE)
    next_start_local = start_local + timedelta(days=1)

    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0),
        next_start_local.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0),
    )


def display_day_start_utc(day: date) -> datetime:
    """Return the UTC-naive start bound for one America/Detroit date."""
    return display_day_bounds_utc(day)[0]


def next_display_day_start_utc(day: date) -> datetime:
    """Return the UTC-naive exclusive end bound for one America/Detroit date."""
    return display_day_bounds_utc(day)[1]


def parse_timestamp_string(value: str) -> datetime:
    """
    Parse a timestamp string while accepting the outgoing-API-style trailing Z.
    """
    normalized_value = value.strip()

    if normalized_value.endswith("Z"):
        normalized_value = f"{normalized_value[:-1]}+00:00"

    return datetime.fromisoformat(normalized_value)

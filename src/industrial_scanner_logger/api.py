import re
import shutil
import subprocess
import sys
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from psycopg import sql
from psycopg.rows import dict_row

from industrial_scanner_logger._version import __version__
from industrial_scanner_logger.receiver import (
    DEFAULT_CONFIG_FILE,
    load_receiver_config,
    validate_positive_int,
)

API_TITLE = "Industrial Scanner Logger API"
DEFAULT_API_ROOT_PATH = "/api"
API_VERSION_PREFIX = "/v1"
MAX_LIMIT = 1000
DEFAULT_LIMIT = 100
SCANNER_SERVICE_UNIT = "industrial-scanner-logger.service"
API_SERVICE_UNIT = "industrial-scanner-logger-api.service"
SCANNER_SCRIPT_LOG_PATH = Path("/var/log/industrial-scanner-logger.log")
CURRENT_SCAN_RATE_WINDOW_SECONDS = 60
CURRENT_SCAN_HOUR_WINDOW_SECONDS = 3600
DAILY_CSV_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SCAN_EVENT_COLUMNS = [
    "id",
    "scan_date",
    "scan_time",
    "scanner_id",
    "scanner_name",
    "scanner_role",
    "last_scanner_id",
    "is_duplicate",
    "is_cross_scanner_duplicate",
    "is_repaired",
    "tracking_number",
    "barcode",
    "barcode_length",
    "is_success",
    "failure_reason",
]

VIEW_DEFINITIONS = {
    "daily-scan-totals": {
        "relation": "daily_scan_totals",
        "columns": [
            "scan_date",
            "scanner_id",
            "scanner_name",
            "scanner_role",
            "total_scan_events",
            "successful_scans",
            "failed_scans",
            "unique_successful_barcodes",
        ],
        "date_column": "scan_date",
        "scanner_column": "scanner_id",
        "order": ["scan_date DESC", "scanner_id ASC"],
    },
    "daily-scan-totals-all-scanners": {
        "relation": "daily_scan_totals_all_scanners",
        "columns": [
            "scan_date",
            "total_scan_events",
            "successful_scans",
            "failed_scans",
            "unique_successful_barcodes",
        ],
        "date_column": "scan_date",
        "order": ["scan_date DESC"],
    },
    "failed-scans": {
        "relation": "failed_scans",
        "columns": [
            "id",
            "scan_date",
            "scan_time",
            "scanner_id",
            "scanner_name",
            "scanner_role",
            "last_scanner_id",
            "is_duplicate",
            "is_cross_scanner_duplicate",
            "is_repaired",
            "tracking_number",
            "barcode",
            "barcode_length",
            "failure_reason",
        ],
        "date_column": "scan_date",
        "scanner_column": "scanner_id",
        "barcode_column": "barcode",
        "tracking_number_column": "tracking_number",
        "order": ["scan_date DESC", "scan_time DESC", "id DESC"],
    },
    "successful-scans": {
        "relation": "successful_scans",
        "columns": [
            "id",
            "scan_date",
            "scan_time",
            "scanner_id",
            "scanner_name",
            "scanner_role",
            "last_scanner_id",
            "is_duplicate",
            "is_cross_scanner_duplicate",
            "is_repaired",
            "tracking_number",
            "barcode",
            "barcode_length",
        ],
        "date_column": "scan_date",
        "scanner_column": "scanner_id",
        "barcode_column": "barcode",
        "tracking_number_column": "tracking_number",
        "order": ["scan_date DESC", "scan_time DESC", "id DESC"],
    },
    "duplicate-successful-scans": {
        "relation": "duplicate_successful_scans",
        "columns": [
            "tracking_number",
            "barcode",
            "scan_count",
            "scanner_count",
            "scanner_ids",
            "scanner_names",
            "first_seen_at",
            "last_seen_at",
        ],
        "barcode_column": "barcode",
        "tracking_number_column": "tracking_number",
        "order": ["last_seen_at DESC", "barcode ASC"],
    },
    "successful-scan-progression": {
        "relation": "successful_scan_progression",
        "columns": [
            "id",
            "scan_date",
            "scan_time",
            "scanner_id",
            "scanner_name",
            "scanner_role",
            "last_scanner_id",
            "tracking_number",
            "barcode",
            "scan_sequence",
            "scanner_count",
            "is_duplicate",
            "has_cross_scanner_duplicate",
            "is_cross_scanner_duplicate",
            "is_repaired",
        ],
        "date_column": "scan_date",
        "scanner_column": "scanner_id",
        "barcode_column": "barcode",
        "tracking_number_column": "tracking_number",
        "order": ["scan_date DESC", "scan_time DESC", "id DESC"],
    },
    "successful-scans-missing-last-scanner": {
        "relation": "successful_scans_missing_last_scanner",
        "columns": [
            "scan_date",
            "tracking_number",
            "barcode",
            "last_scanner_id",
            "first_seen_at",
            "last_seen_at",
            "scan_count",
            "scanner_count",
            "scanner_ids",
            "scanner_names",
        ],
        "date_column": "scan_date",
        "barcode_column": "barcode",
        "tracking_number_column": "tracking_number",
        "order": ["scan_date DESC", "last_seen_at DESC", "barcode ASC"],
    },
}


def build_dashboard_health(config):
    current_day = date.today()
    previous_day = current_day - timedelta(days=1)

    services = {
        "scanner": systemd_service_status(SCANNER_SERVICE_UNIT),
        "api": systemd_service_status(API_SERVICE_UNIT),
    }

    connected_scanner_ids = connected_scanner_ids_from_ss(config.port)
    connected_scanners = dashboard_connected_scanners(config, connected_scanner_ids)
    script_log = read_last_log_lines(SCANNER_SCRIPT_LOG_PATH, line_count=10)

    database = {
        "active": False,
        "state": "unavailable",
        "error": None,
    }
    last_received = None
    recent_scans = []
    daily_totals = empty_daily_totals(current_day, previous_day)
    current_scan_rate = empty_current_scan_rate()

    try:
        db = connect_db(config)
        try:
            last_received = fetch_one(
                db,
                """
                SELECT
                    id,
                    scan_date,
                    scan_time,
                    scanner_id,
                    scanner_name,
                    scanner_role,
                    last_scanner_id,
                    is_duplicate,
                    is_cross_scanner_duplicate,
                    is_repaired,
                    tracking_number,
                    barcode,
                    barcode_length,
                    is_success,
                    failure_reason
                FROM scanner_logger.scan_events
                ORDER BY scan_date DESC, scan_time DESC, id DESC
                LIMIT 1
                """,
                [],
            )

            recent_scans = fetch_all(
                db,
                """
                SELECT
                    id,
                    scan_date,
                    scan_time,
                    scanner_id,
                    scanner_name,
                    scanner_role,
                    last_scanner_id,
                    is_duplicate,
                    is_cross_scanner_duplicate,
                    is_repaired,
                    tracking_number,
                    barcode,
                    barcode_length,
                    is_success,
                    failure_reason
                FROM scanner_logger.raw_scan_events
                ORDER BY scan_date DESC, scan_time DESC, id DESC
                LIMIT 10
                """,
                [],
            )

            daily_totals = fetch_dashboard_daily_totals(
                db,
                current_day,
                previous_day,
            )
            current_scan_rate = fetch_current_scan_rate(db)

            database = {
                "active": True,
                "state": "ok",
                "error": None,
            }
        finally:
            db.close()

    except Exception as exc:
        database = {
            "active": False,
            "state": "unavailable",
            "error": str(exc),
        }

    overall_ok = (
        services["scanner"]["active"]
        and services["api"]["active"]
        and database["active"]
    )

    return {
        "status": "ok" if overall_ok else "degraded",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "services": services,
        "database": database,
        "connected_scanner_ids": connected_scanner_ids,
        "connected_scanners": connected_scanners,
        "last_received": last_received,
        "recent_scans": recent_scans,
        "daily_totals": daily_totals,
        "current_scan_rate": current_scan_rate,
        "script_log": script_log,
    }


def empty_daily_totals(current_day: date, previous_day: date) -> dict:
    return {
        "today": dashboard_total_row(current_day),
        "yesterday": dashboard_total_row(previous_day),
    }


def dashboard_connected_scanners(config, connected_scanner_ids: list[int]) -> list[dict]:
    scanners = []

    for scanner_id in connected_scanner_ids:
        scanner_id_text = str(scanner_id)
        scanner_name = config.scanner_names.get(scanner_id_text, "")
        scanner_role = (
            "last"
            if config.last_scanner_id and scanner_id_text == config.last_scanner_id
            else "standard"
        )

        scanners.append({
            "scanner_id": scanner_id,
            "scanner_name": scanner_name,
            "scanner_role": scanner_role,
        })

    return scanners


def dashboard_total_row(scan_date: date, row: Optional[dict] = None) -> dict:
    row = row or {}
    return {
        "scan_date": scan_date.isoformat(),
        "successful_scans": int(row.get("successful_scans") or 0),
        "failed_scans": int(row.get("failed_scans") or 0),
        "duplicate_scans": int(row.get("duplicate_scans") or 0),
    }


def fetch_dashboard_daily_totals(
    db,
    current_day: date,
    previous_day: date,
) -> dict:
    rows = fetch_all(
        db,
        """
        SELECT
            scan_date,
            count(*) FILTER (WHERE is_success) AS successful_scans,
            count(*) FILTER (WHERE is_success = false) AS failed_scans,
            count(*) FILTER (WHERE is_duplicate) AS duplicate_scans
        FROM scanner_logger.scan_events
        WHERE scan_date IN (%s, %s)
        GROUP BY scan_date
        """,
        [current_day, previous_day],
    )
    rows_by_date = {row["scan_date"]: row for row in rows}

    return {
        "today": dashboard_total_row(current_day, rows_by_date.get(current_day)),
        "yesterday": dashboard_total_row(previous_day, rows_by_date.get(previous_day)),
    }


def empty_current_scan_rate() -> dict:
    return scan_rate_row(0, 0)


def scan_rate_row(minute_scan_count: int, hour_scan_count: int) -> dict:
    scans_per_minute = (minute_scan_count / CURRENT_SCAN_RATE_WINDOW_SECONDS) * 60

    return {
        "window_seconds": CURRENT_SCAN_RATE_WINDOW_SECONDS,
        "hour_window_seconds": CURRENT_SCAN_HOUR_WINDOW_SECONDS,
        "scan_count": minute_scan_count,
        "hour_scan_count": hour_scan_count,
        "scans_per_minute": round(scans_per_minute, 2),
        "scans_per_hour": hour_scan_count,
    }


def fetch_current_scan_rate(db) -> dict:
    row = fetch_one(
        db,
        """
        SELECT
            count(*) FILTER (
                WHERE (scan_date + scan_time) >= (localtimestamp - %s)
                  AND (scan_date + scan_time) <= localtimestamp
            ) AS scan_count,
            count(*) FILTER (
                WHERE (scan_date + scan_time) >= (localtimestamp - %s)
                  AND (scan_date + scan_time) <= localtimestamp
            ) AS hour_scan_count
        FROM scanner_logger.scan_events
        """,
        [
            timedelta(seconds=CURRENT_SCAN_RATE_WINDOW_SECONDS),
            timedelta(seconds=CURRENT_SCAN_HOUR_WINDOW_SECONDS),
        ],
    )

    return scan_rate_row(
        int(row.get("scan_count") or 0),
        int(row.get("hour_scan_count") or 0),
    )


def daily_csv_log_path(config, scan_date: date) -> Path:
    if scan_date >= date.today():
        raise HTTPException(status_code=404, detail="daily CSV is not finalized")

    filename = f"{config.prefix}_{scan_date.isoformat()}.csv"
    csv_path = Path(config.output_dir) / filename

    if not csv_path.exists() or not csv_path.is_file():
        raise HTTPException(status_code=404, detail="daily CSV not found")

    return csv_path


def daily_csv_log_row(config, csv_path: Path, scan_date: date) -> dict:
    stat = csv_path.stat()
    return {
        "scan_date": scan_date.isoformat(),
        "filename": csv_path.name,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(
            timespec="seconds"
        ),
        "download_url": f"{API_VERSION_PREFIX}/logs/daily-csv/{scan_date.isoformat()}",
    }


def list_completed_daily_csv_logs(config, current_day: Optional[date] = None) -> list:
    current_day = current_day or date.today()
    output_dir = Path(config.output_dir)

    if not output_dir.exists() or not output_dir.is_dir():
        return []

    csv_pattern = re.compile(
        rf"^{re.escape(config.prefix)}_(\d{{4}}-\d{{2}}-\d{{2}})\.csv$"
    )
    rows = []

    for csv_path in output_dir.iterdir():
        match = csv_pattern.match(csv_path.name)
        if match is None or not csv_path.is_file():
            continue

        date_text = match.group(1)
        if not DAILY_CSV_DATE_RE.match(date_text):
            continue

        try:
            scan_date = date.fromisoformat(date_text)
        except ValueError:
            continue

        if scan_date >= current_day:
            continue

        rows.append(daily_csv_log_row(config, csv_path, scan_date))

    return sorted(rows, key=lambda row: row["scan_date"], reverse=True)


def fetch_one(db, query, params):
    with db.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchone()


def systemd_service_status(unit_name: str) -> dict:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit_name],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception as exc:
        return {
            "unit": unit_name,
            "active": False,
            "state": "unknown",
            "error": str(exc),
        }

    state = result.stdout.strip() or result.stderr.strip() or "unknown"

    return {
        "unit": unit_name,
        "active": state == "active",
        "state": state,
        "error": None if result.returncode in (0, 3) else result.stderr.strip(),
    }


def connected_scanner_ids_from_ss(listen_port: int) -> list[int]:
    ss_path = shutil.which("ss")
    if ss_path is None:
        return []

    output = run_ss_for_port(ss_path, listen_port)
    if output is None:
        output = run_ss_all_established(ss_path)

    scanner_ids = set()

    for line in (output or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue

        # With ss -Htn, local and peer endpoints are normally the final two columns.
        local_endpoint = parts[-2]
        peer_endpoint = parts[-1]

        _local_host, local_port = split_host_port(local_endpoint)
        peer_host, _peer_port = split_host_port(peer_endpoint)

        if local_port != str(listen_port):
            continue

        scanner_id = scanner_id_from_ipv4_host(peer_host)
        if scanner_id is not None:
            scanner_ids.add(scanner_id)

    return sorted(scanner_ids)


def run_ss_for_port(ss_path: str, listen_port: int) -> str | None:
    try:
        result = subprocess.run(
            [
                ss_path,
                "-Htn",
                "state",
                "established",
                f"( sport = :{listen_port} )",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    return result.stdout


def run_ss_all_established(ss_path: str) -> str:
    try:
        result = subprocess.run(
            [ss_path, "-Htn", "state", "established"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return ""

    if result.returncode != 0:
        return ""

    return result.stdout


def split_host_port(endpoint: str) -> tuple[str, str]:
    endpoint = endpoint.strip()

    if endpoint.startswith("[") and "]:" in endpoint:
        host, _, port = endpoint[1:].rpartition("]:")
        return host, port

    host, separator, port = endpoint.rpartition(":")
    if not separator:
        return endpoint, ""

    return host, port


def scanner_id_from_ipv4_host(host: str) -> int | None:
    host = host.strip("[]")

    if host.startswith("::ffff:"):
        host = host.removeprefix("::ffff:")

    octets = host.split(".")
    if len(octets) != 4:
        return None

    if not all(octet.isdigit() for octet in octets):
        return None

    values = [int(octet) for octet in octets]
    if not all(0 <= value <= 255 for value in values):
        return None

    return values[-1]


def read_last_log_lines(log_path: Path, line_count: int = 10) -> dict:
    try:
        if not log_path.exists():
            return {
                "path": str(log_path),
                "available": False,
                "error": "log file does not exist",
                "lines": [],
            }

        with log_path.open("r", encoding="utf-8", errors="replace") as log_file:
            lines = list(deque(log_file, maxlen=line_count))

        return {
            "path": str(log_path),
            "available": True,
            "error": None,
            "lines": [line.rstrip("\n") for line in lines],
        }

    except Exception as exc:
        return {
            "path": str(log_path),
            "available": False,
            "error": str(exc),
            "lines": [],
        }


def create_app(root_path: str = DEFAULT_API_ROOT_PATH) -> FastAPI:
    normalized_root_path = normalize_root_path(root_path)
    app = FastAPI(
        title=API_TITLE,
        version=__version__,
        description="Read-only REST API for industrial scanner PostgreSQL data.",
        root_path=normalized_root_path,
    )

    @app.get("/")
    def root(request: Request):
        request_root_path = request.scope.get("root_path") or normalized_root_path
        return {
            "service": "industrial-scanner-logger-api",
            "version": __version__,
            "root_path": request_root_path,
            "endpoints": [
                external_path(request_root_path, f"{API_VERSION_PREFIX}/health"),
                external_path(request_root_path, f"{API_VERSION_PREFIX}/scans"),
                external_path(request_root_path, f"{API_VERSION_PREFIX}/scans/{{scan_id}}"),
                external_path(request_root_path, f"{API_VERSION_PREFIX}/views"),
                external_path(request_root_path, f"{API_VERSION_PREFIX}/views/{{view_name}}"),
                external_path(request_root_path, f"{API_VERSION_PREFIX}/logs/daily-csv"),
                external_path(
                    request_root_path,
                    f"{API_VERSION_PREFIX}/logs/daily-csv/{{scan_date}}",
                ),
            ],
        }

    @app.get(f"{API_VERSION_PREFIX}/health")
    def health(db=Depends(get_db)):
        try:
            with db.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                cursor.fetchone()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"PostgreSQL unavailable: {exc}",
            ) from exc

        return {"status": "ok", "version": __version__}

    @app.get(f"{API_VERSION_PREFIX}/scans")
    def list_scans(
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        scanner_id: Optional[int] = Query(default=None, ge=0, le=255),
        barcode: Optional[str] = None,
        is_success: Optional[bool] = None,
        limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        offset: int = Query(default=0, ge=0),
        db=Depends(get_db),
    ):
        query, params = build_scan_events_query(
            start_date=start_date,
            end_date=end_date,
            scanner_id=scanner_id,
            barcode=barcode,
            is_success=is_success,
            limit=limit,
            offset=offset,
        )
        return fetch_all(db, query, params)

    @app.get(f"{API_VERSION_PREFIX}/scans/{{scan_id}}")
    def get_scan(scan_id: int, db=Depends(get_db)):
        query = sql.SQL("SELECT {} FROM scanner_logger.scan_events WHERE id = %s").format(
            column_list(SCAN_EVENT_COLUMNS)
        )

        rows = fetch_all(db, query, [scan_id])

        if not rows:
            raise HTTPException(status_code=404, detail="scan event not found")

        return rows[0]

    @app.get(f"{API_VERSION_PREFIX}/views")
    def list_views():
        return {"views": sorted(VIEW_DEFINITIONS)}

    @app.get(f"{API_VERSION_PREFIX}/views/{{view_name}}")
    def get_view_rows(
        view_name: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        scanner_id: Optional[int] = Query(default=None, ge=0, le=255),
        barcode: Optional[str] = None,
        limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        offset: int = Query(default=0, ge=0),
        db=Depends(get_db),
    ):
        query, params = build_view_query(
            view_name=view_name,
            start_date=start_date,
            end_date=end_date,
            scanner_id=scanner_id,
            barcode=barcode,
            limit=limit,
            offset=offset,
        )
        return fetch_all(db, query, params)

    @app.get(f"{API_VERSION_PREFIX}/dashboard/health")
    def dashboard_health(config=Depends(get_config)):
        return build_dashboard_health(config)

    @app.get(f"{API_VERSION_PREFIX}/logs/daily-csv")
    def list_daily_csv_logs(config=Depends(get_config)):
        return {
            "current_day_excluded": date.today().isoformat(),
            "logs": list_completed_daily_csv_logs(config),
        }

    @app.get(f"{API_VERSION_PREFIX}/logs/daily-csv/{{scan_date}}")
    def download_daily_csv_log(scan_date: date, config=Depends(get_config)):
        csv_path = daily_csv_log_path(config, scan_date)
        return FileResponse(
            csv_path,
            media_type="text/csv",
            filename=csv_path.name,
        )

    return app


def normalize_root_path(root_path: str) -> str:
    normalized = (root_path or "").strip()

    if normalized in ("", "/"):
        return ""

    if not normalized.startswith("/"):
        raise ValueError("api.root_path must be empty or start with /")

    return normalized.rstrip("/")


def external_path(root_path: str, path: str) -> str:
    normalized_root_path = normalize_root_path(root_path)

    if not path.startswith("/"):
        path = f"/{path}"

    return f"{normalized_root_path}{path}"


def get_config():
    return load_receiver_config(DEFAULT_CONFIG_FILE)


def get_db(config=Depends(get_config)):
    try:
        connection = connect_db(config)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"PostgreSQL unavailable: {exc}",
        ) from exc

    try:
        yield connection
    finally:
        connection.close()


def connect_db(config):
    import psycopg

    return psycopg.connect(
        config.postgresql_dsn,
        autocommit=True,
        row_factory=dict_row,
    )


def fetch_all(db, query, params):
    with db.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def column_list(columns):
    return sql.SQL(", ").join(sql.Identifier(column) for column in columns)


def build_scan_events_query(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    scanner_id: Optional[int] = None,
    barcode: Optional[str] = None,
    is_success: Optional[bool] = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
):
    conditions = []
    params = []

    add_common_filters(
        conditions,
        params,
        start_date=start_date,
        end_date=end_date,
        scanner_id=scanner_id,
        barcode=barcode,
        tracking_number_column="tracking_number",
    )

    if is_success is not None:
        conditions.append(sql.SQL("is_success = %s"))
        params.append(is_success)

    query = sql.SQL("SELECT {} FROM scanner_logger.scan_events{} {} LIMIT %s OFFSET %s").format(
        column_list(SCAN_EVENT_COLUMNS),
        where_clause(conditions),
        sql.SQL("ORDER BY scan_date DESC, scan_time DESC, id DESC"),
    )
    params.extend([limit, offset])
    return query, params


def build_view_query(
    view_name: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    scanner_id: Optional[int] = None,
    barcode: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
):
    view = VIEW_DEFINITIONS.get(view_name)

    if view is None:
        raise HTTPException(status_code=404, detail="unknown view")

    conditions = []
    params = []
    add_common_filters(
        conditions,
        params,
        start_date=start_date,
        end_date=end_date,
        scanner_id=scanner_id,
        barcode=barcode,
        date_column=view.get("date_column"),
        scanner_column=view.get("scanner_column"),
        barcode_column=view.get("barcode_column"),
        tracking_number_column=view.get("tracking_number_column"),
    )

    query = sql.SQL("SELECT {} FROM scanner_logger.{}{} {} LIMIT %s OFFSET %s").format(
        column_list(view["columns"]),
        sql.Identifier(view["relation"]),
        where_clause(conditions),
        order_clause(view["order"]),
    )
    params.extend([limit, offset])
    return query, params


def add_common_filters(
    conditions: list,
    params: list,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    scanner_id: Optional[int] = None,
    barcode: Optional[str] = None,
    date_column: Optional[str] = "scan_date",
    scanner_column: Optional[str] = "scanner_id",
    barcode_column: Optional[str] = "barcode",
    tracking_number_column: Optional[str] = None,
):
    if start_date is not None:
        if date_column is None:
            raise HTTPException(status_code=400, detail="start_date is not supported")
        conditions.append(sql.SQL("{} >= %s").format(sql.Identifier(date_column)))
        params.append(start_date)

    if end_date is not None:
        if date_column is None:
            raise HTTPException(status_code=400, detail="end_date is not supported")
        conditions.append(sql.SQL("{} <= %s").format(sql.Identifier(date_column)))
        params.append(end_date)

    if scanner_id is not None:
        if scanner_column is None:
            raise HTTPException(status_code=400, detail="scanner_id is not supported")
        conditions.append(sql.SQL("{} = %s").format(sql.Identifier(scanner_column)))
        params.append(scanner_id)

    if barcode is not None:
        if barcode_column is None and tracking_number_column is None:
            raise HTTPException(status_code=400, detail="barcode is not supported")

        barcode_filters = []

        if barcode_column is not None:
            barcode_filters.append(sql.Identifier(barcode_column))

        if (
            tracking_number_column is not None
            and tracking_number_column != barcode_column
        ):
            barcode_filters.append(sql.Identifier(tracking_number_column))

        filter_sql = sql.SQL(" OR ").join(
            sql.SQL("{} = %s").format(column)
            for column in barcode_filters
        )
        conditions.append(sql.SQL("(") + filter_sql + sql.SQL(")"))
        params.extend([barcode] * len(barcode_filters))


def where_clause(conditions):
    if not conditions:
        return sql.SQL("")

    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)


def order_clause(order_parts):
    return sql.SQL("ORDER BY ") + sql.SQL(", ").join(sql.SQL(part) for part in order_parts)


def main():
    config = load_receiver_config(DEFAULT_CONFIG_FILE)

    if not config.api_enabled:
        print("Industrial Scanner Logger API is disabled in config.")
        return 0

    try:
        validate_positive_int(config.api_port, "api.port")
        api_root_path = normalize_root_path(config.api_root_path)

        if config.api_port > 65535:
            raise ValueError("api.port must be between 1 and 65535")
    except ValueError as exc:
        print(f"Invalid API config: {exc}", file=sys.stderr)
        return 1

    uvicorn.run(
        create_app(root_path=api_root_path),
        host=config.api_host,
        port=config.api_port,
        log_level=config.api_log_level,
        root_path=api_root_path,
    )
    return 0


app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())

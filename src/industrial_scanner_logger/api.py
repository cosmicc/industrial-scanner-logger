import sys
from datetime import date
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from psycopg import sql
from psycopg.rows import dict_row

from industrial_scanner_logger._version import __version__
from industrial_scanner_logger.receiver import (
    DEFAULT_CONFIG_FILE,
    load_receiver_config,
    validate_positive_int,
)


API_TITLE = "Industrial Scanner Logger API"
MAX_LIMIT = 1000
DEFAULT_LIMIT = 100

SCAN_EVENT_COLUMNS = [
    "id",
    "scan_date",
    "scan_time",
    "scanner_id",
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
            "tracking_number",
            "barcode",
            "barcode_length",
            "failure_reason",
        ],
        "date_column": "scan_date",
        "scanner_column": "scanner_id",
        "barcode_column": "barcode",
        "order": ["scan_date DESC", "scan_time DESC", "id DESC"],
    },
    "successful-scans": {
        "relation": "successful_scans",
        "columns": [
            "id",
            "scan_date",
            "scan_time",
            "scanner_id",
            "tracking_number",
            "barcode",
            "barcode_length",
        ],
        "date_column": "scan_date",
        "scanner_column": "scanner_id",
        "barcode_column": "barcode",
        "order": ["scan_date DESC", "scan_time DESC", "id DESC"],
    },
    "duplicate-successful-scans": {
        "relation": "duplicate_successful_scans",
        "columns": [
            "barcode",
            "scan_count",
            "scanner_count",
            "first_seen_at",
            "last_seen_at",
        ],
        "barcode_column": "barcode",
        "order": ["last_seen_at DESC", "barcode ASC"],
    },
}


def create_app() -> FastAPI:
    app = FastAPI(
        title=API_TITLE,
        version=__version__,
        description="Read-only REST API for industrial scanner PostgreSQL data.",
    )

    @app.get("/")
    def root():
        return {
            "service": "industrial-scanner-logger-api",
            "version": __version__,
            "endpoints": [
                "/api/v1/health",
                "/api/v1/scans",
                "/api/v1/scans/{scan_id}",
                "/api/v1/views",
                "/api/v1/views/{view_name}",
            ],
        }

    @app.get("/api/v1/health")
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

    @app.get("/api/v1/scans")
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

    @app.get("/api/v1/scans/{scan_id}")
    def get_scan(scan_id: int, db=Depends(get_db)):
        query = sql.SQL("SELECT {} FROM scanner_logger.scan_events WHERE id = %s").format(
            column_list(SCAN_EVENT_COLUMNS)
        )

        rows = fetch_all(db, query, [scan_id])

        if not rows:
            raise HTTPException(status_code=404, detail="scan event not found")

        return rows[0]

    @app.get("/api/v1/views")
    def list_views():
        return {"views": sorted(VIEW_DEFINITIONS)}

    @app.get("/api/v1/views/{view_name}")
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

    return app


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
        if barcode_column is None:
            raise HTTPException(status_code=400, detail="barcode is not supported")
        conditions.append(sql.SQL("{} = %s").format(sql.Identifier(barcode_column)))
        params.append(barcode)


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

        if config.api_port > 65535:
            raise ValueError("api.port must be between 1 and 65535")
    except ValueError as exc:
        print(f"Invalid API config: {exc}", file=sys.stderr)
        return 1

    uvicorn.run(
        "industrial_scanner_logger.api:app",
        host=config.api_host,
        port=config.api_port,
        log_level=config.api_log_level,
    )
    return 0


app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())

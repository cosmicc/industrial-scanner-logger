BEGIN;

CREATE SCHEMA IF NOT EXISTS scanner_logger;

CREATE TABLE IF NOT EXISTS scanner_logger.scan_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    scan_date DATE NOT NULL,

    scan_time TIME(0) NOT NULL,

    scanner_id SMALLINT NOT NULL CHECK (scanner_id BETWEEN 0 AND 255),

    tracking_number TEXT NOT NULL CHECK (btrim(tracking_number, E' \t\r\n') <> ''),

    barcode TEXT GENERATED ALWAYS AS (
        NULLIF(btrim(tracking_number, E' \t\r\n'), '')
    ) STORED,

    barcode_length INTEGER GENERATED ALWAYS AS (
        char_length(NULLIF(btrim(tracking_number, E' \t\r\n'), ''))
    ) STORED,

    is_success BOOLEAN GENERATED ALWAYS AS (
        COALESCE(NULLIF(btrim(tracking_number, E' \t\r\n'), '') ~ '^[0-9]{34}$', false)
    ) STORED,

    failure_reason TEXT GENERATED ALWAYS AS (
        CASE
            WHEN COALESCE(NULLIF(btrim(tracking_number, E' \t\r\n'), '') ~ '^[0-9]{34}$', false)
                THEN NULL
            WHEN NULLIF(btrim(tracking_number, E' \t\r\n'), '') IS NULL
                THEN 'empty'
            WHEN btrim(tracking_number, E' \t\r\n') !~ '^[0-9]+$'
                THEN 'non_numeric'
            WHEN char_length(btrim(tracking_number, E' \t\r\n')) < 34
                THEN 'too_short'
            WHEN char_length(btrim(tracking_number, E' \t\r\n')) > 34
                THEN 'too_long'
            ELSE 'invalid'
        END
    ) STORED
);

CREATE INDEX IF NOT EXISTS idx_scan_events_scan_date_time
    ON scanner_logger.scan_events (scan_date DESC, scan_time DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_scan_events_scanner_scan_date_time
    ON scanner_logger.scan_events (scanner_id, scan_date DESC, scan_time DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_scan_events_barcode
    ON scanner_logger.scan_events (barcode);

CREATE INDEX IF NOT EXISTS idx_scan_events_success_scan_date_time
    ON scanner_logger.scan_events (is_success, scan_date DESC, scan_time DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_scan_events_failed_scan_date_time
    ON scanner_logger.scan_events (scan_date DESC, scan_time DESC, id DESC)
    WHERE is_success = false;

CREATE INDEX IF NOT EXISTS idx_scan_events_success_barcode_scan_date_time
    ON scanner_logger.scan_events (barcode, scan_date DESC, scan_time DESC, id DESC)
    WHERE is_success = true;

CREATE INDEX IF NOT EXISTS idx_scan_events_scanner_barcode_scan_date_time
    ON scanner_logger.scan_events (scanner_id, barcode, scan_date DESC, scan_time DESC, id DESC)
    WHERE is_success = true;

CREATE OR REPLACE VIEW scanner_logger.daily_scan_totals AS
SELECT
    scan_date,
    scanner_id,
    count(*) AS total_scan_events,
    count(*) FILTER (WHERE is_success) AS successful_scans,
    count(*) FILTER (WHERE is_success = false) AS failed_scans,
    count(DISTINCT barcode) FILTER (WHERE is_success) AS unique_successful_barcodes
FROM scanner_logger.scan_events
GROUP BY
    scan_date,
    scanner_id;

CREATE OR REPLACE VIEW scanner_logger.daily_scan_totals_all_scanners AS
SELECT
    scan_date,
    count(*) AS total_scan_events,
    count(*) FILTER (WHERE is_success) AS successful_scans,
    count(*) FILTER (WHERE is_success = false) AS failed_scans,
    count(DISTINCT barcode) FILTER (WHERE is_success) AS unique_successful_barcodes
FROM scanner_logger.scan_events
GROUP BY
    scan_date;

CREATE OR REPLACE VIEW scanner_logger.failed_scans AS
SELECT
    id,
    scan_date,
    scan_time,
    scanner_id,
    tracking_number,
    barcode,
    barcode_length,
    failure_reason
FROM scanner_logger.scan_events
WHERE is_success = false;

CREATE OR REPLACE VIEW scanner_logger.successful_scans AS
SELECT
    id,
    scan_date,
    scan_time,
    scanner_id,
    tracking_number,
    barcode,
    barcode_length
FROM scanner_logger.scan_events
WHERE is_success = true;

CREATE OR REPLACE VIEW scanner_logger.duplicate_successful_scans AS
SELECT
    barcode,
    count(*) AS scan_count,
    count(DISTINCT scanner_id) AS scanner_count,
    min(scan_date + scan_time) AS first_seen_at,
    max(scan_date + scan_time) AS last_seen_at
FROM scanner_logger.scan_events
WHERE is_success = true
GROUP BY barcode
HAVING count(*) > 1;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'scannerlogger') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA scanner_logger TO scannerlogger';
        EXECUTE 'GRANT INSERT, SELECT ON scanner_logger.scan_events TO scannerlogger';
        EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA scanner_logger TO scannerlogger';
    END IF;
END $$;

COMMIT;

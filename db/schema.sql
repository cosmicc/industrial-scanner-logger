BEGIN;

CREATE SCHEMA IF NOT EXISTS scanner_logger;

CREATE TABLE IF NOT EXISTS scanner_logger.scan_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    scan_timestamp TIMESTAMPTZ NOT NULL,

    scanner_id SMALLINT NOT NULL CHECK (scanner_id BETWEEN 0 AND 255),

    scanner_name TEXT,

    last_scanner_id SMALLINT CHECK (last_scanner_id BETWEEN 0 AND 255),

    is_duplicate BOOLEAN NOT NULL DEFAULT false,

    is_repaired BOOLEAN NOT NULL DEFAULT false,

    tracking_number TEXT NOT NULL CHECK (btrim(tracking_number, E' \t\r\n') <> ''),

    barcode TEXT NOT NULL CHECK (btrim(barcode, E' \t\r\n') <> ''),

    barcode_length INTEGER GENERATED ALWAYS AS (
        char_length(NULLIF(btrim(barcode, E' \t\r\n'), ''))
    ) STORED,

    is_success BOOLEAN GENERATED ALWAYS AS (
        COALESCE(NULLIF(btrim(barcode, E' \t\r\n'), '') ~ '^[0-9]{34}$', false)
    ) STORED,

    failure_reason TEXT GENERATED ALWAYS AS (
        CASE
            WHEN COALESCE(NULLIF(btrim(barcode, E' \t\r\n'), '') ~ '^[0-9]{34}$', false)
                THEN NULL
            WHEN NULLIF(btrim(barcode, E' \t\r\n'), '') IS NULL
                THEN 'empty'
            WHEN btrim(barcode, E' \t\r\n') !~ '^[0-9]+$'
                THEN 'non_numeric'
            WHEN char_length(btrim(barcode, E' \t\r\n')) < 34
                THEN 'too_short'
            WHEN char_length(btrim(barcode, E' \t\r\n')) > 34
                THEN 'too_long'
            ELSE 'invalid'
        END
    ) STORED
);

CREATE TABLE IF NOT EXISTS scanner_logger.raw_scan_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    scan_timestamp TIMESTAMPTZ NOT NULL,

    scanner_id SMALLINT NOT NULL CHECK (scanner_id BETWEEN 0 AND 255),

    scanner_name TEXT,

    last_scanner_id SMALLINT CHECK (last_scanner_id BETWEEN 0 AND 255),

    is_duplicate BOOLEAN NOT NULL DEFAULT false,

    is_repaired BOOLEAN NOT NULL DEFAULT false,

    tracking_number TEXT NOT NULL CHECK (btrim(tracking_number, E' \t\r\n') <> ''),

    barcode TEXT NOT NULL CHECK (btrim(barcode, E' \t\r\n') <> ''),

    barcode_length INTEGER GENERATED ALWAYS AS (
        char_length(NULLIF(btrim(barcode, E' \t\r\n'), ''))
    ) STORED,

    is_success BOOLEAN GENERATED ALWAYS AS (
        COALESCE(NULLIF(btrim(barcode, E' \t\r\n'), '') ~ '^[0-9]{34}$', false)
    ) STORED,

    failure_reason TEXT GENERATED ALWAYS AS (
        CASE
            WHEN COALESCE(NULLIF(btrim(barcode, E' \t\r\n'), '') ~ '^[0-9]{34}$', false)
                THEN NULL
            WHEN NULLIF(btrim(barcode, E' \t\r\n'), '') IS NULL
                THEN 'empty'
            WHEN btrim(barcode, E' \t\r\n') !~ '^[0-9]+$'
                THEN 'non_numeric'
            WHEN char_length(btrim(barcode, E' \t\r\n')) < 34
                THEN 'too_short'
            WHEN char_length(btrim(barcode, E' \t\r\n')) > 34
                THEN 'too_long'
            ELSE 'invalid'
        END
    ) STORED
);

DROP TABLE IF EXISTS scanner_logger.pending_orders;

DROP VIEW IF EXISTS scanner_logger.successful_scans_missing_last_scanner;
DROP VIEW IF EXISTS scanner_logger.successful_scan_progression;
DROP VIEW IF EXISTS scanner_logger.duplicate_successful_scans;
DROP VIEW IF EXISTS scanner_logger.successful_scans;
DROP VIEW IF EXISTS scanner_logger.failed_scans;
DROP VIEW IF EXISTS scanner_logger.daily_scan_totals_all_scanners;
DROP VIEW IF EXISTS scanner_logger.daily_scan_totals;

ALTER TABLE scanner_logger.scan_events
    DROP COLUMN IF EXISTS scanner_role;

ALTER TABLE scanner_logger.raw_scan_events
    DROP COLUMN IF EXISTS scanner_role;

-- Legacy rows used receiver-local America/Detroit date and time values.
DO $$
DECLARE
    target_table REGCLASS;
BEGIN
    FOREACH target_table IN ARRAY ARRAY[
        'scanner_logger.scan_events'::REGCLASS,
        'scanner_logger.raw_scan_events'::REGCLASS
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_attribute
            WHERE attrelid = target_table
              AND attname = 'scan_timestamp'
              AND NOT attisdropped
        ) THEN
            EXECUTE format(
                'ALTER TABLE %s ADD COLUMN scan_timestamp TIMESTAMPTZ',
                target_table
            );
        END IF;

        IF EXISTS (
            SELECT 1
            FROM pg_attribute
            WHERE attrelid = target_table
              AND attname = 'scan_date'
              AND NOT attisdropped
        )
        AND EXISTS (
            SELECT 1
            FROM pg_attribute
            WHERE attrelid = target_table
              AND attname = 'scan_time'
              AND NOT attisdropped
        ) THEN
            EXECUTE format(
                'UPDATE %s
                    SET scan_timestamp = (scan_date + scan_time) AT TIME ZONE ''America/Detroit''
                  WHERE scan_timestamp IS NULL',
                target_table
            );
        END IF;

        EXECUTE format(
            'ALTER TABLE %s ALTER COLUMN scan_timestamp SET NOT NULL',
            target_table
        );
        EXECUTE format('ALTER TABLE %s DROP COLUMN IF EXISTS scan_date', target_table);
        EXECUTE format('ALTER TABLE %s DROP COLUMN IF EXISTS scan_time', target_table);
    END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS idx_scan_events_scan_timestamp
    ON scanner_logger.scan_events (scan_timestamp DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_scan_events_scanner_scan_timestamp
    ON scanner_logger.scan_events (scanner_id, scan_timestamp DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_scan_events_barcode
    ON scanner_logger.scan_events (barcode);

CREATE INDEX IF NOT EXISTS idx_scan_events_tracking_number
    ON scanner_logger.scan_events (tracking_number);

CREATE INDEX IF NOT EXISTS idx_scan_events_success_scan_timestamp
    ON scanner_logger.scan_events (is_success, scan_timestamp DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_scan_events_failed_scan_timestamp
    ON scanner_logger.scan_events (scan_timestamp DESC, id DESC)
    WHERE is_success = false;

CREATE INDEX IF NOT EXISTS idx_scan_events_duplicate
    ON scanner_logger.scan_events (scan_timestamp DESC, id DESC)
    WHERE is_duplicate = true;

CREATE INDEX IF NOT EXISTS idx_scan_events_success_tracking_scan_timestamp
    ON scanner_logger.scan_events (tracking_number, scan_timestamp DESC, id DESC)
    WHERE is_success = true;

CREATE INDEX IF NOT EXISTS idx_scan_events_scanner_tracking_scan_timestamp
    ON scanner_logger.scan_events (scanner_id, tracking_number, scan_timestamp DESC, id DESC)
    WHERE is_success = true;

CREATE INDEX IF NOT EXISTS idx_scan_events_last_scanner_tracking
    ON scanner_logger.scan_events (
        tracking_number,
        last_scanner_id,
        scanner_id,
        scan_timestamp
    )
    WHERE is_success = true AND last_scanner_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_raw_scan_events_scan_timestamp
    ON scanner_logger.raw_scan_events (scan_timestamp DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_raw_scan_events_scanner_scan_timestamp
    ON scanner_logger.raw_scan_events (scanner_id, scan_timestamp DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_raw_scan_events_barcode
    ON scanner_logger.raw_scan_events (barcode);

CREATE INDEX IF NOT EXISTS idx_raw_scan_events_tracking_number
    ON scanner_logger.raw_scan_events (tracking_number);

CREATE OR REPLACE VIEW scanner_logger.daily_scan_totals AS
SELECT
    (scan_timestamp AT TIME ZONE 'UTC')::date AS scan_date,
    scanner_id,
    scanner_name,
    count(*) AS total_scan_events,
    count(*) FILTER (WHERE is_success) AS successful_scans,
    count(*) FILTER (WHERE is_success = false) AS failed_scans,
    count(DISTINCT tracking_number) FILTER (WHERE is_success) AS unique_successful_barcodes
FROM scanner_logger.scan_events
GROUP BY
    (scan_timestamp AT TIME ZONE 'UTC')::date,
    scanner_id,
    scanner_name;

CREATE OR REPLACE VIEW scanner_logger.daily_scan_totals_all_scanners AS
SELECT
    (scan_timestamp AT TIME ZONE 'UTC')::date AS scan_date,
    count(*) AS total_scan_events,
    count(*) FILTER (WHERE is_success) AS successful_scans,
    count(*) FILTER (WHERE is_success = false) AS failed_scans,
    count(DISTINCT tracking_number) FILTER (WHERE is_success) AS unique_successful_barcodes
FROM scanner_logger.scan_events
GROUP BY
    (scan_timestamp AT TIME ZONE 'UTC')::date;

CREATE OR REPLACE VIEW scanner_logger.failed_scans AS
SELECT
    id,
    scan_timestamp,
    (scan_timestamp AT TIME ZONE 'UTC')::date AS scan_date,
    (scan_timestamp AT TIME ZONE 'UTC')::time(0) AS scan_time,
    scanner_id,
    scanner_name,
    last_scanner_id,
    is_duplicate,
    is_repaired,
    tracking_number,
    barcode,
    barcode_length,
    failure_reason
FROM scanner_logger.scan_events
WHERE is_success = false;

CREATE OR REPLACE VIEW scanner_logger.successful_scans AS
SELECT
    id,
    scan_timestamp,
    (scan_timestamp AT TIME ZONE 'UTC')::date AS scan_date,
    (scan_timestamp AT TIME ZONE 'UTC')::time(0) AS scan_time,
    scanner_id,
    scanner_name,
    last_scanner_id,
    is_duplicate,
    is_repaired,
    tracking_number,
    barcode,
    barcode_length
FROM scanner_logger.scan_events
WHERE is_success = true;

CREATE OR REPLACE VIEW scanner_logger.duplicate_successful_scans AS
SELECT
    tracking_number,
    max(barcode) AS barcode,
    count(*) AS scan_count,
    count(DISTINCT scanner_id) AS scanner_count,
    array_agg(DISTINCT scanner_id ORDER BY scanner_id) AS scanner_ids,
    array_agg(DISTINCT scanner_name ORDER BY scanner_name)
        FILTER (WHERE scanner_name IS NOT NULL) AS scanner_names,
    min(scan_timestamp) AS first_seen_at,
    max(scan_timestamp) AS last_seen_at
FROM scanner_logger.scan_events
WHERE is_success = true
GROUP BY tracking_number
HAVING bool_or(is_duplicate);

CREATE OR REPLACE VIEW scanner_logger.successful_scan_progression AS
WITH events_with_time AS (
    SELECT
        events.*,
        (events.scan_timestamp AT TIME ZONE 'UTC')::date AS scan_date,
        (events.scan_timestamp AT TIME ZONE 'UTC')::time(0) AS scan_time
    FROM scanner_logger.scan_events AS events
    WHERE events.is_success = true
),
scanner_counts AS (
    SELECT
        scan_date,
        tracking_number,
        count(DISTINCT scanner_id) AS scanner_count
    FROM events_with_time
    GROUP BY
        scan_date,
        tracking_number
)
SELECT
    events.id,
    events.scan_timestamp,
    events.scan_date,
    events.scan_time,
    events.scanner_id,
    events.scanner_name,
    events.last_scanner_id,
    events.tracking_number,
    events.barcode,
    row_number() OVER (
        PARTITION BY events.scan_date, events.tracking_number
        ORDER BY events.scan_timestamp, events.id
    ) AS scan_sequence,
    scanner_counts.scanner_count,
    events.is_duplicate,
    events.is_repaired
FROM events_with_time AS events
JOIN scanner_counts
  ON scanner_counts.scan_date = events.scan_date
 AND scanner_counts.tracking_number = events.tracking_number;

CREATE OR REPLACE VIEW scanner_logger.successful_scans_missing_last_scanner AS
WITH source AS (
    SELECT
        events.*,
        (events.scan_timestamp AT TIME ZONE 'UTC')::date AS scan_date
    FROM scanner_logger.scan_events AS events
    WHERE events.is_success = true
)
SELECT
    source.scan_date,
    source.tracking_number,
    max(source.barcode) AS barcode,
    source.last_scanner_id,
    min(source.scan_timestamp) AS first_seen_at,
    max(source.scan_timestamp) AS last_seen_at,
    count(*) AS scan_count,
    count(DISTINCT source.scanner_id) AS scanner_count,
    array_agg(DISTINCT source.scanner_id ORDER BY source.scanner_id) AS scanner_ids,
    array_agg(DISTINCT source.scanner_name ORDER BY source.scanner_name)
        FILTER (WHERE source.scanner_name IS NOT NULL) AS scanner_names
FROM source
WHERE source.last_scanner_id IS NOT NULL
  AND source.scanner_id <> source.last_scanner_id
  AND NOT EXISTS (
      SELECT 1
      FROM scanner_logger.scan_events AS last_scan
      WHERE last_scan.is_success = true
        AND (last_scan.scan_timestamp AT TIME ZONE 'UTC')::date = source.scan_date
        AND last_scan.tracking_number = source.tracking_number
        AND last_scan.scanner_id = source.last_scanner_id
  )
GROUP BY
    source.scan_date,
    source.tracking_number,
    source.last_scanner_id;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'scannerlogger') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA scanner_logger TO scannerlogger';
        EXECUTE 'GRANT INSERT, SELECT ON scanner_logger.scan_events TO scannerlogger';
        EXECUTE 'GRANT INSERT, SELECT ON scanner_logger.raw_scan_events TO scannerlogger';
        EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA scanner_logger TO scannerlogger';
    END IF;
END $$;

COMMIT;

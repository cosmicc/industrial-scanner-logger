BEGIN;

CREATE SCHEMA IF NOT EXISTS scanner_logger;

CREATE TABLE IF NOT EXISTS scanner_logger.scan_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    scan_date DATE NOT NULL,

    scan_time TIME(0) NOT NULL,

    scanner_id SMALLINT NOT NULL CHECK (scanner_id BETWEEN 0 AND 255),

    scanner_name TEXT,

    scanner_role TEXT NOT NULL DEFAULT 'standard',

    last_scanner_id SMALLINT CHECK (last_scanner_id BETWEEN 0 AND 255),

    is_cross_scanner_duplicate BOOLEAN NOT NULL DEFAULT false,

    is_repaired BOOLEAN NOT NULL DEFAULT false,

    tracking_number TEXT NOT NULL CHECK (btrim(tracking_number, E' \t\r\n') <> ''),

    barcode TEXT NOT NULL CHECK (btrim(barcode, E' \t\r\n') <> ''),

    barcode_length INTEGER GENERATED ALWAYS AS (
        char_length(NULLIF(btrim(barcode, E' \t\r\n'), ''))
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

DROP VIEW IF EXISTS scanner_logger.successful_scans_missing_last_scanner;
DROP VIEW IF EXISTS scanner_logger.successful_scan_progression;
DROP VIEW IF EXISTS scanner_logger.duplicate_successful_scans;
DROP VIEW IF EXISTS scanner_logger.successful_scans;
DROP VIEW IF EXISTS scanner_logger.failed_scans;
DROP VIEW IF EXISTS scanner_logger.daily_scan_totals_all_scanners;
DROP VIEW IF EXISTS scanner_logger.daily_scan_totals;

ALTER TABLE scanner_logger.scan_events
    ADD COLUMN IF NOT EXISTS scanner_name TEXT;

ALTER TABLE scanner_logger.scan_events
    ADD COLUMN IF NOT EXISTS scanner_role TEXT NOT NULL DEFAULT 'standard';

ALTER TABLE scanner_logger.scan_events
    ADD COLUMN IF NOT EXISTS last_scanner_id SMALLINT;

ALTER TABLE scanner_logger.scan_events
    ADD COLUMN IF NOT EXISTS is_cross_scanner_duplicate BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE scanner_logger.scan_events
    ADD COLUMN IF NOT EXISTS is_repaired BOOLEAN NOT NULL DEFAULT false;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_attribute
        WHERE attrelid = 'scanner_logger.scan_events'::regclass
          AND attname = 'barcode'
          AND attgenerated <> ''
    ) THEN
        ALTER TABLE scanner_logger.scan_events
            ALTER COLUMN barcode DROP EXPRESSION;
    END IF;
END $$;

ALTER TABLE scanner_logger.scan_events
    ADD COLUMN IF NOT EXISTS barcode TEXT;

UPDATE scanner_logger.scan_events
SET barcode = NULLIF(btrim(tracking_number, E' \t\r\n'), '')
WHERE barcode IS NULL;

ALTER TABLE scanner_logger.scan_events
    ALTER COLUMN barcode SET NOT NULL;

ALTER TABLE scanner_logger.scan_events
    DROP COLUMN IF EXISTS barcode_length;

ALTER TABLE scanner_logger.scan_events
    ADD COLUMN barcode_length INTEGER GENERATED ALWAYS AS (
        char_length(NULLIF(btrim(barcode, E' \t\r\n'), ''))
    ) STORED;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_scan_events_scanner_role'
          AND conrelid = 'scanner_logger.scan_events'::regclass
    ) THEN
        ALTER TABLE scanner_logger.scan_events
            ADD CONSTRAINT ck_scan_events_scanner_role
            CHECK (scanner_role IN ('standard', 'last'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_scan_events_last_scanner_id'
          AND conrelid = 'scanner_logger.scan_events'::regclass
    ) THEN
        ALTER TABLE scanner_logger.scan_events
            ADD CONSTRAINT ck_scan_events_last_scanner_id
            CHECK (last_scanner_id BETWEEN 0 AND 255);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_scan_events_barcode_present'
          AND conrelid = 'scanner_logger.scan_events'::regclass
    ) THEN
        ALTER TABLE scanner_logger.scan_events
            ADD CONSTRAINT ck_scan_events_barcode_present
            CHECK (btrim(barcode, E' \t\r\n') <> '');
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_scan_events_scan_date_time
    ON scanner_logger.scan_events (scan_date DESC, scan_time DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_scan_events_scanner_scan_date_time
    ON scanner_logger.scan_events (scanner_id, scan_date DESC, scan_time DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_scan_events_barcode
    ON scanner_logger.scan_events (barcode);

CREATE INDEX IF NOT EXISTS idx_scan_events_tracking_number
    ON scanner_logger.scan_events (tracking_number);

CREATE INDEX IF NOT EXISTS idx_scan_events_success_scan_date_time
    ON scanner_logger.scan_events (is_success, scan_date DESC, scan_time DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_scan_events_failed_scan_date_time
    ON scanner_logger.scan_events (scan_date DESC, scan_time DESC, id DESC)
    WHERE is_success = false;

DROP INDEX IF EXISTS scanner_logger.idx_scan_events_success_barcode_scan_date_time;

CREATE INDEX IF NOT EXISTS idx_scan_events_success_tracking_scan_date_time
    ON scanner_logger.scan_events (tracking_number, scan_date DESC, scan_time DESC, id DESC)
    WHERE is_success = true;

DROP INDEX IF EXISTS scanner_logger.idx_scan_events_scanner_barcode_scan_date_time;

CREATE INDEX IF NOT EXISTS idx_scan_events_scanner_tracking_scan_date_time
    ON scanner_logger.scan_events (scanner_id, tracking_number, scan_date DESC, scan_time DESC, id DESC)
    WHERE is_success = true;

CREATE INDEX IF NOT EXISTS idx_scan_events_cross_scanner_duplicate
    ON scanner_logger.scan_events (scan_date DESC, scan_time DESC, id DESC)
    WHERE is_cross_scanner_duplicate = true;

DROP INDEX IF EXISTS scanner_logger.idx_scan_events_last_scanner_tracking;

CREATE INDEX IF NOT EXISTS idx_scan_events_last_scanner_tracking
    ON scanner_logger.scan_events (scan_date, tracking_number, last_scanner_id, scanner_id)
    WHERE is_success = true AND last_scanner_id IS NOT NULL;

CREATE OR REPLACE VIEW scanner_logger.daily_scan_totals AS
SELECT
    scan_date,
    scanner_id,
    scanner_name,
    scanner_role,
    count(*) AS total_scan_events,
    count(*) FILTER (WHERE is_success) AS successful_scans,
    count(*) FILTER (WHERE is_success = false) AS failed_scans,
    count(DISTINCT tracking_number) FILTER (WHERE is_success) AS unique_successful_barcodes
FROM scanner_logger.scan_events
GROUP BY
    scan_date,
    scanner_id,
    scanner_name,
    scanner_role;

CREATE OR REPLACE VIEW scanner_logger.daily_scan_totals_all_scanners AS
SELECT
    scan_date,
    count(*) AS total_scan_events,
    count(*) FILTER (WHERE is_success) AS successful_scans,
    count(*) FILTER (WHERE is_success = false) AS failed_scans,
    count(DISTINCT tracking_number) FILTER (WHERE is_success) AS unique_successful_barcodes
FROM scanner_logger.scan_events
GROUP BY
    scan_date;

CREATE OR REPLACE VIEW scanner_logger.failed_scans AS
SELECT
    id,
    scan_date,
    scan_time,
    scanner_id,
    scanner_name,
    scanner_role,
    last_scanner_id,
    is_cross_scanner_duplicate,
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
    scan_date,
    scan_time,
    scanner_id,
    scanner_name,
    scanner_role,
    last_scanner_id,
    is_cross_scanner_duplicate,
    is_repaired,
    tracking_number,
    barcode,
    barcode_length
FROM scanner_logger.scan_events
WHERE is_success = true;

CREATE OR REPLACE VIEW scanner_logger.duplicate_successful_scans AS
SELECT
    tracking_number,
    tracking_number AS barcode,
    count(*) AS scan_count,
    count(DISTINCT scanner_id) AS scanner_count,
    array_agg(DISTINCT scanner_id ORDER BY scanner_id) AS scanner_ids,
    array_agg(DISTINCT scanner_name ORDER BY scanner_name)
        FILTER (WHERE scanner_name IS NOT NULL) AS scanner_names,
    min(scan_date + scan_time) AS first_seen_at,
    max(scan_date + scan_time) AS last_seen_at
FROM scanner_logger.scan_events
WHERE is_success = true
GROUP BY tracking_number
HAVING count(DISTINCT scanner_id) > 1;

CREATE OR REPLACE VIEW scanner_logger.successful_scan_progression AS
WITH scanner_counts AS (
    SELECT
        scan_date,
        tracking_number,
        count(DISTINCT scanner_id) AS scanner_count
    FROM scanner_logger.scan_events
    WHERE is_success = true
    GROUP BY
        scan_date,
        tracking_number
)
SELECT
    events.id,
    events.scan_date,
    events.scan_time,
    events.scanner_id,
    events.scanner_name,
    events.scanner_role,
    events.last_scanner_id,
    events.tracking_number,
    events.barcode,
    row_number() OVER (
        PARTITION BY events.scan_date, events.tracking_number
        ORDER BY events.scan_date, events.scan_time, events.id
    ) AS scan_sequence,
    scanner_counts.scanner_count,
    scanner_counts.scanner_count > 1 AS has_cross_scanner_duplicate,
    events.is_cross_scanner_duplicate,
    events.is_repaired
FROM scanner_logger.scan_events AS events
JOIN scanner_counts
  ON scanner_counts.scan_date = events.scan_date
 AND scanner_counts.tracking_number = events.tracking_number
WHERE events.is_success = true;

CREATE OR REPLACE VIEW scanner_logger.successful_scans_missing_last_scanner AS
SELECT
    source.scan_date,
    source.tracking_number,
    source.tracking_number AS barcode,
    source.last_scanner_id,
    min(source.scan_date + source.scan_time) AS first_seen_at,
    max(source.scan_date + source.scan_time) AS last_seen_at,
    count(*) AS scan_count,
    count(DISTINCT source.scanner_id) AS scanner_count,
    array_agg(DISTINCT source.scanner_id ORDER BY source.scanner_id) AS scanner_ids,
    array_agg(DISTINCT source.scanner_name ORDER BY source.scanner_name)
        FILTER (WHERE source.scanner_name IS NOT NULL) AS scanner_names
FROM scanner_logger.scan_events AS source
WHERE source.is_success = true
  AND source.last_scanner_id IS NOT NULL
  AND source.scanner_id <> source.last_scanner_id
  AND NOT EXISTS (
      SELECT 1
      FROM scanner_logger.scan_events AS last_scan
      WHERE last_scan.is_success = true
        AND last_scan.scan_date = source.scan_date
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
        EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA scanner_logger TO scannerlogger';
    END IF;
END $$;

COMMIT;

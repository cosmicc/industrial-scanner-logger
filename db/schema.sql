BEGIN;

CREATE SCHEMA IF NOT EXISTS scanner_logger;

CREATE TABLE IF NOT EXISTS scanner_logger.scan_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    scan_timestamp TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,

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

    scan_timestamp TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,

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

CREATE TABLE IF NOT EXISTS scanner_logger.outgoing_scan_queue (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Processed scan_events row that will be sent to the external API.
    scan_event_id BIGINT UNIQUE
        REFERENCES scanner_logger.scan_events (id) ON DELETE CASCADE,

    -- Raw-only failed scan row, such as a no-read marker, sent to the external API.
    raw_scan_event_id BIGINT UNIQUE
        REFERENCES scanner_logger.raw_scan_events (id) ON DELETE CASCADE,

    -- UTC queue insertion time stored without timezone metadata.
    created_at TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL
        DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::timestamp(0)),

    -- UTC time when this row is eligible for another delivery attempt.
    next_attempt_at TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL
        DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::timestamp(0)),

    -- Number of failed delivery attempts recorded for this queued scan.
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),

    -- UTC time of the most recent failed delivery attempt.
    last_attempt_at TIMESTAMP(0) WITHOUT TIME ZONE,

    -- Sanitized delivery error used by the health page and troubleshooting logs.
    last_error TEXT,

    -- HTTP response code from the most recent failed API response, when known.
    last_http_status INTEGER CHECK (
        last_http_status IS NULL
        OR last_http_status BETWEEN 100 AND 599
    ),

    CONSTRAINT outgoing_scan_queue_one_event_source CHECK (
        (
            scan_event_id IS NOT NULL
            AND raw_scan_event_id IS NULL
        )
        OR (
            scan_event_id IS NULL
            AND raw_scan_event_id IS NOT NULL
        )
    )
);

ALTER TABLE scanner_logger.outgoing_scan_queue
    ALTER COLUMN scan_event_id DROP NOT NULL;

ALTER TABLE scanner_logger.outgoing_scan_queue
    ADD COLUMN IF NOT EXISTS raw_scan_event_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'scanner_logger.outgoing_scan_queue'::REGCLASS
          AND conname = 'outgoing_scan_queue_raw_scan_event_id_key'
    ) THEN
        ALTER TABLE scanner_logger.outgoing_scan_queue
            ADD CONSTRAINT outgoing_scan_queue_raw_scan_event_id_key
            UNIQUE (raw_scan_event_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'scanner_logger.outgoing_scan_queue'::REGCLASS
          AND conname = 'outgoing_scan_queue_raw_scan_event_id_fkey'
    ) THEN
        ALTER TABLE scanner_logger.outgoing_scan_queue
            ADD CONSTRAINT outgoing_scan_queue_raw_scan_event_id_fkey
            FOREIGN KEY (raw_scan_event_id)
            REFERENCES scanner_logger.raw_scan_events (id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'scanner_logger.outgoing_scan_queue'::REGCLASS
          AND conname = 'outgoing_scan_queue_one_event_source'
    ) THEN
        ALTER TABLE scanner_logger.outgoing_scan_queue
            ADD CONSTRAINT outgoing_scan_queue_one_event_source
            CHECK (
                (
                    scan_event_id IS NOT NULL
                    AND raw_scan_event_id IS NULL
                )
                OR (
                    scan_event_id IS NULL
                    AND raw_scan_event_id IS NOT NULL
                )
            );
    END IF;
END $$;

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
                'ALTER TABLE %s ADD COLUMN scan_timestamp TIMESTAMP(0) WITHOUT TIME ZONE',
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
                    SET scan_timestamp = ((scan_date + scan_time) AT TIME ZONE ''America/Detroit'') AT TIME ZONE ''UTC''
                  WHERE scan_timestamp IS NULL',
                target_table
            );
        END IF;

        IF EXISTS (
            SELECT 1
            FROM pg_attribute
            WHERE attrelid = target_table
              AND attname = 'scan_timestamp'
              AND atttypid = 'timestamp with time zone'::REGTYPE
              AND NOT attisdropped
        ) THEN
            EXECUTE format(
                'ALTER TABLE %s
                    ALTER COLUMN scan_timestamp TYPE TIMESTAMP(0) WITHOUT TIME ZONE
                    USING scan_timestamp AT TIME ZONE ''UTC''',
                target_table
            );
        ELSE
            EXECUTE format(
                'ALTER TABLE %s
                    ALTER COLUMN scan_timestamp TYPE TIMESTAMP(0) WITHOUT TIME ZONE
                    USING scan_timestamp::timestamp(0)',
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

CREATE INDEX IF NOT EXISTS idx_outgoing_scan_queue_next_attempt
    ON scanner_logger.outgoing_scan_queue (next_attempt_at, created_at, id);

CREATE INDEX IF NOT EXISTS idx_outgoing_scan_queue_last_attempt
    ON scanner_logger.outgoing_scan_queue (last_attempt_at DESC, id DESC);

-- Human-facing views convert UTC-by-convention scan timestamps to the scanner
-- site's America/Detroit display timezone. Base table storage remains UTC.
CREATE OR REPLACE VIEW scanner_logger.daily_scan_totals AS
SELECT
    ((scan_timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'America/Detroit')::date AS scan_date,
    scanner_id,
    scanner_name,
    count(*) AS total_scan_events,
    count(*) FILTER (WHERE is_success) AS successful_scans,
    count(*) FILTER (WHERE is_success = false) AS failed_scans,
    count(DISTINCT tracking_number) FILTER (WHERE is_success) AS unique_successful_barcodes
FROM scanner_logger.scan_events
GROUP BY
    ((scan_timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'America/Detroit')::date,
    scanner_id,
    scanner_name;

CREATE OR REPLACE VIEW scanner_logger.daily_scan_totals_all_scanners AS
SELECT
    ((scan_timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'America/Detroit')::date AS scan_date,
    count(*) AS total_scan_events,
    count(*) FILTER (WHERE is_success) AS successful_scans,
    count(*) FILTER (WHERE is_success = false) AS failed_scans,
    count(DISTINCT tracking_number) FILTER (WHERE is_success) AS unique_successful_barcodes
FROM scanner_logger.scan_events
GROUP BY
    ((scan_timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'America/Detroit')::date;

CREATE OR REPLACE VIEW scanner_logger.failed_scans AS
SELECT
    id,
    scan_timestamp,
    ((scan_timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'America/Detroit')::date AS scan_date,
    ((scan_timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'America/Detroit')::time(0) AS scan_time,
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
    ((scan_timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'America/Detroit')::date AS scan_date,
    ((scan_timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'America/Detroit')::time(0) AS scan_time,
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
        ((events.scan_timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'America/Detroit')::date AS scan_date,
        ((events.scan_timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'America/Detroit')::time(0) AS scan_time
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
        ((events.scan_timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'America/Detroit')::date AS scan_date
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
        AND ((last_scan.scan_timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'America/Detroit')::date = source.scan_date
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
        EXECUTE 'GRANT INSERT, SELECT, UPDATE, DELETE ON scanner_logger.outgoing_scan_queue TO scannerlogger';
        EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA scanner_logger TO scannerlogger';
    END IF;
END $$;

COMMIT;

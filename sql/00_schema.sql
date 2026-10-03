-- =====================================================================
-- 00_schema.sql : staging, audit and reference tables (spec 8.2, 9)
-- Re-runnable: drops and recreates everything (NFR: idempotent scripts)
-- =====================================================================

DROP TABLE IF EXISTS
    customer_opportunity, customer_segment, segment_definition,
    customer_360, fact_transaction, dim_customer, dim_location, dim_date,
    clean_transactions, int_transactions, rejected_rows, row_waterfall,
    dq_log, load_log, location_map, project_params, stg_bank_transactions
CASCADE;

-- Single source of truth for window and rule parameters [A].
-- Profiling found complete daily coverage only from 1 Aug to 15 Sep 2016
-- (~20K txns/day); after that the extract is sparse (a few scattered days to
-- 21 Oct). Recency-based rules need complete coverage, so the analysis window
-- is 1 Aug - 15 Sep (46 days) and the spec's 30/60-day rules are scaled to it.
CREATE TABLE project_params (
    window_start        DATE    NOT NULL,
    window_end          DATE    NOT NULL,   -- last day with complete coverage
    extract_end         DATE    NOT NULL,   -- last date present in the file
    as_of_date          DATE    NOT NULL,   -- window_end + 1 (spec 11, AS-05)
    window_days         INT     NOT NULL,
    active_days         INT     NOT NULL,   -- BR-01: Recency <= active_days
    dormant_days        INT     NOT NULL,   -- BR-05: Recency >  dormant_days
    newly_observed_days INT     NOT NULL,   -- BR-04: first txn within last N days
    trend_split_date    DATE    NOT NULL    -- Activity_Trend: [start, split) vs [split, end]
);
INSERT INTO project_params VALUES
    (DATE '2016-08-01', DATE '2016-09-15', DATE '2016-10-21', DATE '2016-09-16',
     46, 15, 30, 15, DATE '2016-08-24');

-- Raw copy, all text, nothing lost silently (spec 32: ingestion layer)
CREATE TABLE stg_bank_transactions (
    src_row                 BIGINT GENERATED ALWAYS AS IDENTITY,  -- file order, for "keep first"
    transaction_id          TEXT,
    customer_id             TEXT,
    customer_dob            TEXT,
    cust_gender             TEXT,
    cust_location           TEXT,
    cust_account_balance    TEXT,
    transaction_date        TEXT,
    transaction_time        TEXT,
    transaction_amount_inr  TEXT,
    load_ts                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE load_log (
    run_id              TEXT PRIMARY KEY,
    file_name           TEXT NOT NULL,
    archive_sha256      TEXT NOT NULL,
    uncompressed_bytes  BIGINT NOT NULL,
    rows_loaded         BIGINT NOT NULL,
    loaded_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Data quality audit (spec 24, FR-039)
CREATE TABLE dq_log (
    check_id      TEXT NOT NULL,
    run_date      TIMESTAMPTZ NOT NULL DEFAULT now(),
    dimension     TEXT NOT NULL,
    rule          TEXT NOT NULL,
    checked_rows  BIGINT,
    failed_rows   BIGINT,
    pass_pct      NUMERIC(7,3),
    threshold_pct NUMERIC(7,3),
    status        TEXT,
    note          TEXT,
    PRIMARY KEY (check_id, run_date)
);

-- Rows removed during cleaning, with the first rule they failed (spec 9, 10)
CREATE TABLE rejected_rows (
    transaction_id          TEXT,
    customer_id             TEXT,
    customer_dob            TEXT,
    cust_gender             TEXT,
    cust_location           TEXT,
    cust_account_balance    TEXT,
    transaction_date        TEXT,
    transaction_time        TEXT,
    transaction_amount_inr  TEXT,
    reject_reason           TEXT NOT NULL,
    rejected_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Row waterfall: raw -> rejected by reason -> clean (FR-012)
CREATE TABLE row_waterfall (
    step_no   INT PRIMARY KEY,
    step      TEXT NOT NULL,
    rows      BIGINT NOT NULL
);

-- Manual mapping of location spelling variants to a canonical city (C13, FR-006)
CREATE TABLE location_map (
    variant     TEXT PRIMARY KEY,   -- already trimmed / upper-cased / punctuation-free
    clean_city  TEXT NOT NULL
);

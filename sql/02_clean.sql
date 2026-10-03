-- =====================================================================
-- 02_clean.sql : parse, validate and clean staging rows (spec 10, FR-003..012)
--   stg_bank_transactions -> int_transactions (typed + reject reason)
--                         -> rejected_rows / clean_transactions
-- =====================================================================

-- ---------------------------------------------------------------------
-- Helper: parse 'd/m/yy' or 'd/m/yyyy' text to DATE, NULL when invalid.
-- Two-digit years use a century pivot: yy <= pivot -> 20yy, else 19yy.
--   * Transaction dates: pivot 99 (all 2016 -> 2000s).
--   * Birth dates: pivot 16 (the data year), so '94' -> 1994 and '05' -> 2005;
--     a 2005 birth is then rejected by the 18-90 age rule (C8/C15, AS-13).
-- Nested CASEs guarantee make_date() is only reached with a valid day/month.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION f_parse_dmy(txt TEXT, pivot_yy INT)
RETURNS DATE LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE
             WHEN p.m BETWEEN 1 AND 12 AND p.d BETWEEN 1 AND 31 AND p.y IS NOT NULL THEN
               CASE WHEN p.d <= EXTRACT(DAY FROM make_date(p.y, p.m, 1) + INTERVAL '1 month - 1 day')
                    THEN make_date(p.y, p.m, p.d) END
           END
    FROM (
        SELECT split_part(t, '/', 1)::INT AS d,
               split_part(t, '/', 2)::INT AS m,
               CASE length(split_part(t, '/', 3))
                    WHEN 4 THEN split_part(t, '/', 3)::INT
                    WHEN 2 THEN split_part(t, '/', 3)::INT
                                + CASE WHEN split_part(t, '/', 3)::INT <= pivot_yy THEN 2000 ELSE 1900 END
               END AS y
        FROM (SELECT btrim(txt) AS t) s
        WHERE s.t ~ '^\d{1,2}/\d{1,2}/(\d{2}|\d{4})$'
    ) p
$$;

-- Helper: integer HHMMSS (leading zeros dropped in the source) -> TIME, NULL if invalid (C16)
CREATE OR REPLACE FUNCTION f_parse_hhmmss(txt TEXT)
RETURNS TIME LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE
             WHEN substr(p, 1, 2)::INT < 24 AND substr(p, 3, 2)::INT < 60 AND substr(p, 5, 2)::INT < 60
             THEN make_time(substr(p, 1, 2)::INT, substr(p, 3, 2)::INT, substr(p, 5, 2)::INT)
           END
    FROM (SELECT lpad(btrim(txt), 6, '0') AS p) s
    WHERE btrim(txt) ~ '^\d{1,6}$'
$$;

-- Helper: numeric text -> NUMERIC, NULL when blank or not a number
CREATE OR REPLACE FUNCTION f_to_numeric(txt TEXT)
RETURNS NUMERIC LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN btrim(txt) ~ '^-?\d+(\.\d+)?([eE][-+]?\d+)?$' THEN btrim(txt)::NUMERIC END
$$;

-- Helper: location text -> upper case, punctuation removed, spaces collapsed; blank -> NULL
CREATE OR REPLACE FUNCTION f_norm_location(txt TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT NULLIF(btrim(regexp_replace(regexp_replace(upper(coalesce(txt, '')),
                  '[^A-Z0-9 ]', ' ', 'g'), '\s+', ' ', 'g')), '')
$$;

-- ---------------------------------------------------------------------
-- Step 1: typed copy of every staging row with its first failing rule
-- ---------------------------------------------------------------------
CREATE TABLE int_transactions AS
WITH typed AS (
    SELECT s.*,
           btrim(s.transaction_id)                          AS txn_id,
           btrim(s.customer_id)                             AS cust_id,
           f_parse_dmy(s.transaction_date, 99)              AS txn_date,
           f_parse_dmy(s.customer_dob, 16)                  AS dob_parsed,
           f_parse_hhmmss(s.transaction_time)               AS txn_time,
           f_to_numeric(s.transaction_amount_inr)           AS amount,
           f_to_numeric(s.cust_account_balance)             AS balance_parsed,
           f_norm_location(s.cust_location)                 AS location_norm,
           ROW_NUMBER() OVER (PARTITION BY btrim(s.transaction_id) ORDER BY s.src_row) AS id_occurrence
    FROM stg_bank_transactions s
)
SELECT t.*,
       CASE
           WHEN t.txn_id IS NULL OR t.txn_id = ''                  THEN 'MISSING_TRANSACTION_ID'
           WHEN t.id_occurrence > 1                                THEN 'DUPLICATE_TRANSACTION_ID'   -- C5
           WHEN t.cust_id IS NULL OR t.cust_id !~ '^C[0-9]+$'      THEN 'INVALID_CUSTOMER_ID'        -- C9
           WHEN t.txn_date IS NULL                                 THEN 'INVALID_TRANSACTION_DATE'   -- C7
           WHEN t.txn_date > pp.window_end AND t.txn_date <= pp.extract_end
                                                                   THEN 'PARTIAL_COVERAGE_PERIOD'    -- [A] sparse tail
           WHEN t.txn_date NOT BETWEEN pp.window_start AND pp.window_end
                                                                   THEN 'DATE_OUTSIDE_WINDOW'        -- C7
           WHEN t.amount IS NULL                                   THEN 'MISSING_OR_INVALID_AMOUNT'
           WHEN t.amount < 0                                       THEN 'NEGATIVE_AMOUNT'            -- C10
           WHEN t.amount = 0                                       THEN 'ZERO_AMOUNT'                -- C10 [A]
       END AS reject_reason
FROM typed t
CROSS JOIN project_params pp;

-- ---------------------------------------------------------------------
-- Step 2: rejected rows keep their raw text plus the reason
-- ---------------------------------------------------------------------
INSERT INTO rejected_rows (transaction_id, customer_id, customer_dob, cust_gender, cust_location,
                           cust_account_balance, transaction_date, transaction_time,
                           transaction_amount_inr, reject_reason)
SELECT transaction_id, customer_id, customer_dob, cust_gender, cust_location,
       cust_account_balance, transaction_date, transaction_time,
       transaction_amount_inr, reject_reason
FROM int_transactions
WHERE reject_reason IS NOT NULL;

-- ---------------------------------------------------------------------
-- Step 3: clean transactions with row-level fixes and flags
-- ---------------------------------------------------------------------
CREATE TABLE clean_transactions AS
SELECT
    i.txn_id                                                    AS transaction_id,
    substr(i.txn_id, 2)::BIGINT                                 AS txn_seq,      -- numeric part, tie-breaker
    i.cust_id                                                   AS customer_id,
    i.txn_date,
    i.txn_time,
    i.amount,
    -- C4: missing balance stays NULL (never zero-filled, AS-09); negative balance treated as invalid
    CASE WHEN i.balance_parsed >= 0 THEN i.balance_parsed END   AS balance,
    -- C8: placeholder (1/1/1800, < 1920) and future DOBs become NULL
    CASE WHEN i.dob_parsed >= DATE '1920-01-01' AND i.dob_parsed <= i.txn_date
         THEN i.dob_parsed END                                  AS dob,
    -- C2, C12: gender mapped to M / F / Unknown
    CASE upper(btrim(i.cust_gender)) WHEN 'M' THEN 'M' WHEN 'F' THEN 'F' ELSE 'Unknown' END AS gender,
    -- C3, C13: normalised location, mapped variants, blank -> UNKNOWN
    COALESCE(m.clean_city, i.location_norm, 'UNKNOWN')         AS clean_city,
    i.cust_location                                             AS raw_location,
    -- flags kept for the DQ scorecard
    (i.customer_dob IS NULL OR btrim(lower(i.customer_dob)) IN ('', 'nan')) AS dob_missing,  -- source writes missing DOB as 'nan'
    (i.dob_parsed < DATE '1920-01-01')                          AS dob_placeholder,
    (i.dob_parsed > i.txn_date)                                 AS dob_future,
    (i.balance_parsed IS NULL)                                  AS balance_missing,
    (i.balance_parsed < 0)                                      AS balance_negative,
    (i.transaction_time IS NOT NULL AND i.txn_time IS NULL)     AS time_invalid,
    (upper(btrim(coalesce(i.cust_gender, ''))) NOT IN ('M', 'F', '')) AS gender_other_value
FROM int_transactions i
LEFT JOIN location_map m ON m.variant = i.location_norm
WHERE i.reject_reason IS NULL;

ALTER TABLE clean_transactions ADD PRIMARY KEY (transaction_id);
CREATE INDEX ix_clean_cust ON clean_transactions (customer_id);

-- C6: identical rows under different TransactionIDs are flagged, not deleted [A]
ALTER TABLE clean_transactions ADD COLUMN is_possible_duplicate BOOLEAN;
UPDATE clean_transactions c
SET is_possible_duplicate = d.n > 1
FROM (
    SELECT transaction_id,
           COUNT(*) OVER (PARTITION BY customer_id, dob, gender, clean_city, balance,
                                       txn_date, txn_time, amount) AS n
    FROM clean_transactions
) d
WHERE d.transaction_id = c.transaction_id;

-- ---------------------------------------------------------------------
-- Step 4: row waterfall (FR-012) - must reconcile to the unit
-- ---------------------------------------------------------------------
INSERT INTO row_waterfall (step_no, step, rows)
SELECT 0, 'Raw rows in staging', COUNT(*) FROM stg_bank_transactions;

INSERT INTO row_waterfall (step_no, step, rows)
SELECT 10 + ROW_NUMBER() OVER (ORDER BY MIN(ord)), 'Rejected: ' || reject_reason, -COUNT(*)
FROM (
    SELECT reject_reason,
           array_position(ARRAY['MISSING_TRANSACTION_ID', 'DUPLICATE_TRANSACTION_ID', 'INVALID_CUSTOMER_ID',
                                'INVALID_TRANSACTION_DATE', 'PARTIAL_COVERAGE_PERIOD', 'DATE_OUTSIDE_WINDOW',
                                'MISSING_OR_INVALID_AMOUNT',
                                'NEGATIVE_AMOUNT', 'ZERO_AMOUNT'], reject_reason) AS ord
    FROM rejected_rows
) r
GROUP BY reject_reason;

INSERT INTO row_waterfall (step_no, step, rows)
SELECT 99, 'Clean rows', COUNT(*) FROM clean_transactions;

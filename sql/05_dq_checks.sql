-- =====================================================================
-- 05_dq_checks.sql : data quality scorecard (spec 24, FR-039, UC12)
-- Every check writes one row to dq_log. Status:
--   PASS      pass_pct >= threshold
--   EXCEPTION below threshold; explained in note (documented exception)
--   INFO      measurement only (profiling finding), no threshold
-- =====================================================================

DELETE FROM dq_log;

CREATE TEMP TABLE dq_raw (
    check_id TEXT, dimension TEXT, rule TEXT, checked_rows BIGINT, failed_rows BIGINT,
    threshold_pct NUMERIC, note TEXT
) ON COMMIT DROP;

-- ---- Load / waterfall ------------------------------------------------
INSERT INTO dq_raw
SELECT 'DQ-01', 'Completeness', 'Staging rows equal rows in source file (1,048,567)',
       1048567, ABS(1048567 - (SELECT rows_loaded FROM load_log ORDER BY loaded_at DESC LIMIT 1)), 100,
       'FR-001 / T-01';
INSERT INTO dq_raw
SELECT 'DQ-02', 'Accuracy', 'Row waterfall reconciles: raw - rejected = clean',
       (SELECT rows FROM row_waterfall WHERE step_no = 0),
       ABS((SELECT SUM(rows) FROM row_waterfall WHERE step_no < 99)
           - (SELECT rows FROM row_waterfall WHERE step_no = 99)), 100, 'FR-012';

-- ---- Completeness ----------------------------------------------------
INSERT INTO dq_raw
SELECT 'DQ-03', 'Completeness', 'CustomerID, Amount, TransactionDate non-null in fact',
       COUNT(*), COUNT(*) FILTER (WHERE customer_id IS NULL OR amount IS NULL OR txn_date IS NULL), 100, NULL
FROM fact_transaction;
INSERT INTO dq_raw
SELECT 'DQ-04', 'Completeness', 'DOB usable (not missing, not placeholder 1/1/1800, not future)',
       COUNT(*), COUNT(*) FILTER (WHERE dob IS NULL), 99,
       'Placeholder 1/1/1800 affects ~5.8% of rows; age set to NULL and age-based rules skip these customers (BR-12)'
FROM clean_transactions;
INSERT INTO dq_raw
SELECT 'DQ-05', 'Completeness', 'Gender non-null (M/F)',
       COUNT(*), COUNT(*) FILTER (WHERE gender = 'Unknown'), 99, NULL FROM clean_transactions;
INSERT INTO dq_raw
SELECT 'DQ-06', 'Completeness', 'Location non-null',
       COUNT(*), COUNT(*) FILTER (WHERE clean_city = 'UNKNOWN'), 99, NULL FROM clean_transactions;
INSERT INTO dq_raw
SELECT 'DQ-07', 'Completeness', 'Balance non-null',
       COUNT(*), COUNT(*) FILTER (WHERE balance IS NULL), 99, 'Missing balance kept as NULL, never zero (AS-09)'
FROM clean_transactions;

-- ---- Accuracy --------------------------------------------------------
INSERT INTO dq_raw
SELECT 'DQ-08', 'Accuracy', 'customer_360 reconciles to fact (customers, txns, value)',
       3,
       (CASE WHEN (SELECT COUNT(DISTINCT customer_id) FROM fact_transaction) = (SELECT COUNT(*) FROM customer_360) THEN 0 ELSE 1 END)
     + (CASE WHEN (SELECT COUNT(*) FROM fact_transaction) = (SELECT SUM(txn_count) FROM customer_360) THEN 0 ELSE 1 END)
     + (CASE WHEN (SELECT SUM(amount) FROM fact_transaction) = (SELECT SUM(total_txn_value) FROM customer_360) THEN 0 ELSE 1 END),
       100, 'FR-017 / RO-4';
INSERT INTO dq_raw
SELECT 'DQ-09', 'Accuracy', 'Spot check: 50 random fact rows match source text (amount, date, customer)',
       50,
       COUNT(*) FILTER (WHERE NOT (f.amount = s.transaction_amount_inr::NUMERIC
                                   AND f.customer_id = btrim(s.customer_id)
                                   AND to_char(f.txn_date, 'FMDD/FMMM/YY') = btrim(s.transaction_date))),
       100, 'Sample = 50 lowest md5(TransactionID)'
FROM (SELECT * FROM fact_transaction ORDER BY md5(transaction_id) LIMIT 50) f
JOIN stg_bank_transactions s ON btrim(s.transaction_id) = f.transaction_id;

-- ---- Consistency -----------------------------------------------------
INSERT INTO dq_raw
SELECT 'DQ-10', 'Consistency', 'Gender in {M, F, Unknown}',
       COUNT(*), COUNT(*) FILTER (WHERE gender NOT IN ('M', 'F', 'Unknown')), 100, NULL FROM dim_customer;
INSERT INTO dq_raw
SELECT 'DQ-11', 'Consistency', 'Every customer city exists in dim_location',
       COUNT(*), COUNT(*) FILTER (WHERE l.location_key IS NULL), 100, NULL
FROM dim_customer c LEFT JOIN dim_location l USING (location_key);
INSERT INTO dq_raw
SELECT 'DQ-12', 'Consistency', 'Each CustomerID has one resolved DOB / gender / location',
       COUNT(*), COUNT(*) - COUNT(DISTINCT customer_id), 100, 'Resolved by spec 8.3 rule' FROM dim_customer;

-- ---- Uniqueness ------------------------------------------------------
INSERT INTO dq_raw
SELECT 'DQ-13', 'Uniqueness', 'TransactionID unique in fact',
       COUNT(*), COUNT(*) - COUNT(DISTINCT transaction_id), 100, NULL FROM fact_transaction;
INSERT INTO dq_raw
SELECT 'DQ-14', 'Uniqueness', 'One row per CustomerID in customer_360',
       COUNT(*), COUNT(*) - COUNT(DISTINCT customer_id), 100, NULL FROM customer_360;

-- ---- Validity --------------------------------------------------------
INSERT INTO dq_raw
SELECT 'DQ-15', 'Validity', 'Amount > 0, balance >= 0, date within analysis window',
       COUNT(*),
       COUNT(*) FILTER (WHERE amount <= 0 OR balance < 0
                           OR txn_date NOT BETWEEN (SELECT window_start FROM project_params)
                                               AND (SELECT window_end FROM project_params)),
       99.9, NULL FROM fact_transaction;
INSERT INTO dq_raw
SELECT 'DQ-16', 'Validity', 'Age between 18 and 90 or NULL',
       COUNT(*), COUNT(*) FILTER (WHERE age IS NOT NULL AND age NOT BETWEEN 18 AND 90), 100, NULL FROM dim_customer;
INSERT INTO dq_raw
SELECT 'DQ-17', 'Validity', 'Rows rejected during cleaning (all logged in rejected_rows)',
       (SELECT COUNT(*) FROM stg_bank_transactions), (SELECT COUNT(*) FROM rejected_rows), NULL,
       'PARTIAL_COVERAGE_PERIOD: sparse tail after 15 Sep; ZERO_AMOUNT: amount = 0';

-- ---- Timeliness ------------------------------------------------------
INSERT INTO dq_raw
SELECT 'DQ-18', 'Timeliness', 'As-of date = last day of analysis window + 1',
       1, CASE WHEN as_of_date = window_end + 1 THEN 0 ELSE 1 END, 100,
       'As-of ' || as_of_date || '; window ' || window_start || ' to ' || window_end
FROM project_params;

-- ---- Profiling findings (INFO) ---------------------------------------
INSERT INTO dq_raw
SELECT 'DQ-19', 'Consistency', 'CustomerIDs with conflicting DOB / gender / location across rows (C17)',
       COUNT(*), COUNT(*) FILTER (WHERE dob_conflict OR gender_conflict OR location_conflict), NULL,
       'Resolved by most-frequent / latest rule; see DQ-20'
FROM dim_customer;
INSERT INTO dq_raw
SELECT 'DQ-20', 'Consistency', 'Repeat CustomerIDs whose DOB, gender and city agree on every row',
       COUNT(*), COUNT(*) FILTER (WHERE NOT (d_dob <= 1 AND d_g <= 1 AND d_city <= 1)), NULL,
       'FINDING: under 1% of repeat IDs are internally consistent, so a CustomerID does not reliably identify one person (AS-02). '
       || 'CustomerID is kept as the key per spec; repeat-customer features are interpreted with caution.'
FROM (SELECT customer_id, COUNT(DISTINCT dob) d_dob, COUNT(DISTINCT gender) d_g, COUNT(DISTINCT clean_city) d_city
      FROM clean_transactions GROUP BY customer_id HAVING COUNT(*) > 1) r;
INSERT INTO dq_raw
SELECT 'DQ-21', 'Uniqueness', 'Identical rows under different TransactionIDs (C6, flagged not deleted)',
       COUNT(*), COUNT(*) FILTER (WHERE is_possible_duplicate), NULL, NULL FROM fact_transaction;
INSERT INTO dq_raw
SELECT 'DQ-22', 'Validity', 'Zero / near-zero balance rows (C14, kept and flagged)',
       COUNT(*), COUNT(*) FILTER (WHERE is_zero_balance), NULL, NULL FROM fact_transaction;
INSERT INTO dq_raw
SELECT 'DQ-23', 'Consistency', 'Distinct locations: raw text vs cleaned city (C13)',
       (SELECT COUNT(DISTINCT cust_location) FROM stg_bank_transactions),
       (SELECT COUNT(DISTINCT cust_location) FROM stg_bank_transactions) - (SELECT COUNT(*) FROM dim_location),
       NULL, 'failed_rows = variants merged away by normalisation and the mapping table';
INSERT INTO dq_raw
SELECT 'DQ-24', 'Validity', 'Transaction time valid HHMMSS (C16)',
       COUNT(*), COUNT(*) FILTER (WHERE time_invalid), 100, 'AS-11 verified: all times parse as HHMMSS'
FROM clean_transactions;

INSERT INTO dq_log (check_id, dimension, rule, checked_rows, failed_rows, pass_pct, threshold_pct, status, note)
SELECT check_id, dimension, rule, checked_rows, failed_rows,
       ROUND(100.0 * (checked_rows - failed_rows) / NULLIF(checked_rows, 0), 3),
       threshold_pct,
       CASE
           WHEN threshold_pct IS NULL THEN 'INFO'
           WHEN 100.0 * (checked_rows - failed_rows) / NULLIF(checked_rows, 0) >= threshold_pct THEN 'PASS'
           ELSE 'EXCEPTION'
       END,
       note
FROM dq_raw;

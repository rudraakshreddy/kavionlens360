-- =====================================================================
-- 04_customer_360.sql : one row per customer with behaviour features,
-- scores and business-rule flags (spec 11, 21; FR-017..021)
-- Window / rule parameters come from project_params (46-day window).
-- =====================================================================

DROP TABLE IF EXISTS customer_360, customer_thresholds CASCADE;

CREATE TABLE customer_360 AS
WITH pp AS (SELECT * FROM project_params),
base AS (
    SELECT f.customer_id,
           COUNT(*)                                            AS txn_count,
           SUM(f.amount)                                       AS total_txn_value,
           MAX(f.amount)                                       AS max_txn_value,
           MIN(f.amount)                                       AS min_txn_value,
           COUNT(DISTINCT f.txn_date)                          AS active_days,
           MIN(f.txn_date)                                     AS first_txn_date,
           MAX(f.txn_date)                                     AS last_txn_date,
           AVG(f.balance)                                      AS avg_balance,
           MAX(f.balance)                                      AS max_balance,
           MIN(f.balance)                                      AS min_balance,
           COUNT(f.balance)                                    AS balance_obs,
           STDDEV_SAMP(f.balance)                              AS balance_sd,
           -- balance on the most recent transaction that has one (Latest_Balance)
           (ARRAY_AGG(f.balance ORDER BY f.order_key DESC) FILTER (WHERE f.balance IS NOT NULL))[1]
                                                               AS latest_balance,
           COUNT(*) FILTER (WHERE f.txn_hour >= 17 OR f.txn_hour < 6)::NUMERIC
               / NULLIF(COUNT(f.txn_hour), 0)                  AS evening_night_share,
           COUNT(*) FILTER (WHERE f.txn_date <  pp.trend_split_date) AS txns_first_half,
           COUNT(*) FILTER (WHERE f.txn_date >= pp.trend_split_date) AS txns_second_half,
           COUNT(*) FILTER (WHERE f.is_high_value_txn)         AS high_value_txn_count
    FROM fact_transaction f
    CROSS JOIN pp
    GROUP BY f.customer_id
),
feat AS (
    SELECT b.*,
           b.total_txn_value / b.txn_count                     AS avg_txn_value,
           b.txn_count / (pp.window_days / 30.0)               AS monthly_txn_frequency,
           (pp.as_of_date - b.last_txn_date)                   AS recency_days,
           CASE WHEN b.balance_obs >= 2 AND b.avg_balance > 0
                THEN b.balance_sd / b.avg_balance END          AS balance_volatility,
           CASE WHEN b.latest_balance >= 1
                THEN (b.total_txn_value / b.txn_count) / b.latest_balance END AS txn_to_balance_ratio
    FROM base b CROSS JOIN pp
),
scored AS (
    SELECT f.*,
           -- percent ranks used by Value_Score (spec 11)
           PERCENT_RANK() OVER (ORDER BY f.total_txn_value)    AS pct_total_value,
           CASE WHEN f.avg_balance IS NOT NULL
                THEN PERCENT_RANK() OVER (PARTITION BY (f.avg_balance IS NOT NULL) ORDER BY f.avg_balance)
           END                                                 AS pct_avg_balance,
           -- Engagement_Score = 100 x (0.5 F_n + 0.3 R_n + 0.2 D_n)
           100 * (  0.5 * LEAST(f.txn_count, 4) / 4.0
                  + 0.3 * (1 - LEAST(f.recency_days, pp.window_days)::NUMERIC / pp.window_days)
                  + 0.2 * LEAST(f.active_days, 4) / 4.0)       AS engagement_score,
           -- RFM (FR-018). CUME_DIST quintiles give tied values the same score (T-08).
           CEIL(CUME_DIST() OVER (ORDER BY f.recency_days DESC) * 5)::INT AS r_score,
           LEAST(f.txn_count, 5)::INT                          AS f_score,   -- adjusted bands: most customers have 1 txn
           CEIL(CUME_DIST() OVER (ORDER BY f.total_txn_value) * 5)::INT   AS m_score
    FROM feat f CROSS JOIN pp
)
SELECT s.customer_id,
       -- demographics (resolved in dim_customer)
       c.age, c.age_group, c.age_known, c.gender, c.location_key, c.clean_city, c.city_tier,
       -- activity
       s.txn_count, s.total_txn_value, s.avg_txn_value, s.max_txn_value, s.min_txn_value,
       s.active_days, s.first_txn_date, s.last_txn_date, s.monthly_txn_frequency, s.recency_days,
       s.high_value_txn_count, s.evening_night_share,
       s.txns_first_half, s.txns_second_half,
       CASE
           WHEN s.txn_count = 1                         THEN 'Single transaction'
           WHEN s.txns_second_half > s.txns_first_half  THEN 'Rising'
           WHEN s.txns_second_half < s.txns_first_half  THEN 'Declining'
           ELSE 'Stable'
       END                                              AS activity_trend,
       -- balance
       s.avg_balance, s.latest_balance, s.max_balance, s.min_balance,
       s.balance_volatility, s.txn_to_balance_ratio,
       -- scores
       ROUND((100 * PERCENT_RANK() OVER (
           ORDER BY COALESCE(0.5 * s.pct_avg_balance + 0.5 * s.pct_total_value, s.pct_total_value)
       ))::NUMERIC, 2)                                  AS value_score,
       ROUND(s.engagement_score::NUMERIC, 2)            AS engagement_score,
       s.r_score, s.f_score, s.m_score,
       s.r_score::TEXT || s.f_score::TEXT || s.m_score::TEXT AS rfm_code,
       -- bands and evidence (BR-06, BR-11)
       CASE WHEN s.txn_count = 1 THEN 'Single' WHEN s.txn_count = 2 THEN 'Repeat' ELSE 'Frequent' END AS freq_band,
       CASE WHEN s.txn_count = 1 THEN 'Low' WHEN s.txn_count = 2 THEN 'Medium' ELSE 'High' END       AS evidence_level,
       -- simple rule flags (thresholds that need percentiles are set below)
       (s.recency_days <= pp.active_days)                                   AS is_active,          -- BR-01
       (s.first_txn_date > pp.as_of_date - pp.newly_observed_days - 1)      AS is_newly_observed,  -- BR-04
       (s.recency_days > pp.dormant_days)                                   AS is_dormant,         -- BR-05
       (s.latest_balance < 1)                                               AS is_zero_balance,    -- C14
       NULL::BOOLEAN                                                        AS is_high_value,      -- BR-02
       NULL::BOOLEAN                                                        AS is_low_engagement   -- BR-03
FROM scored s
CROSS JOIN pp
JOIN dim_customer c USING (customer_id);

ALTER TABLE customer_360 ADD PRIMARY KEY (customer_id);
CREATE INDEX ix_c360_location ON customer_360 (location_key);

-- ---------------------------------------------------------------------
-- Percentile thresholds of the clean customer base (AS-07), kept as a table
-- so SQL, Python and the dashboards use identical cut-offs.
-- ---------------------------------------------------------------------
CREATE TABLE customer_thresholds AS
SELECT
    percentile_cont(0.90) WITHIN GROUP (ORDER BY latest_balance)    AS latest_balance_p90,
    percentile_cont(0.90) WITHIN GROUP (ORDER BY total_txn_value)   AS total_txn_value_p90,
    percentile_cont(0.25) WITHIN GROUP (ORDER BY engagement_score)  AS engagement_p25,
    percentile_cont(0.50) WITHIN GROUP (ORDER BY avg_balance)       AS avg_balance_p50,
    percentile_cont(0.75) WITHIN GROUP (ORDER BY avg_balance)       AS avg_balance_p75,
    percentile_cont(0.90) WITHIN GROUP (ORDER BY avg_balance)       AS avg_balance_p90,
    (SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY amount) FROM fact_transaction) AS txn_amount_p95
FROM customer_360;

-- BR-02 high value, BR-03 low engagement
UPDATE customer_360 c
SET is_high_value     = COALESCE(c.latest_balance >= t.latest_balance_p90, FALSE)
                        OR c.total_txn_value >= t.total_txn_value_p90,
    is_low_engagement = c.engagement_score < t.engagement_p25
FROM customer_thresholds t;

ANALYZE customer_360;

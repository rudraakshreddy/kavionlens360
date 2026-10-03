-- =====================================================================
-- 06_publish.sql : aggregated tables for Power BI, Excel MIS and the web
-- report (spec 9 "Loading to BI", 16 data source, R9, R13).
-- Runs after the Python step (needs customer_segment, customer_opportunity).
-- =====================================================================

DROP TABLE IF EXISTS agg_daily_city, agg_hour_weekday, agg_city_summary,
                     agg_segment_summary, agg_theme_segment, kpi_reconciliation CASCADE;

-- Pre-aggregated daily x city fact (Power BI trend visuals; never the 1M raw rows)
CREATE TABLE agg_daily_city AS
SELECT f.date_key, c.location_key,
       COUNT(*)                                    AS txns,
       SUM(f.amount)                               AS total_value,
       COUNT(*) FILTER (WHERE f.is_high_value_txn) AS high_value_txns,
       COUNT(DISTINCT f.customer_id)               AS customers
FROM fact_transaction f
JOIN dim_customer c USING (customer_id)
GROUP BY f.date_key, c.location_key;

-- Hour x weekday heat map (P8)
CREATE TABLE agg_hour_weekday AS
SELECT d.day_of_week_num, d.day_of_week, f.txn_hour,
       COUNT(*)      AS txns,
       SUM(f.amount) AS total_value
FROM fact_transaction f JOIN dim_date d USING (date_key)
GROUP BY d.day_of_week_num, d.day_of_week, f.txn_hour;

-- City scorecard (UC06, UC08; Excel sheet 4; Page 3 / 4)
CREATE TABLE agg_city_summary AS
SELECT c.location_key, c.clean_city, c.city_tier,
       COUNT(*)                                             AS customers,
       SUM(c.txn_count)                                     AS txns,
       SUM(c.total_txn_value)                               AS total_value,
       ROUND(SUM(c.total_txn_value) / COUNT(*), 2)          AS value_per_customer,
       ROUND(AVG(c.avg_balance), 2)                         AS mean_avg_balance,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY c.avg_balance) AS median_avg_balance,
       COUNT(*) FILTER (WHERE c.is_active)                  AS active_customers,
       COUNT(*) FILTER (WHERE c.is_high_value)              AS high_value_customers,
       ROUND(AVG(c.engagement_score), 2)                    AS avg_engagement,
       COUNT(*) FILTER (WHERE o.any_signal)                 AS opportunity_customers,
       COUNT(*) FILTER (WHERE o.tier = 'A')                 AS tier_a,
       COUNT(*) FILTER (WHERE o.tier = 'B')                 AS tier_b,
       SUM(c.latest_balance) FILTER (WHERE o.any_signal)    AS addressable_balance,
       RANK() OVER (ORDER BY SUM(c.total_txn_value) DESC)   AS value_rank
FROM customer_360 c
JOIN customer_opportunity o USING (customer_id)
WHERE c.clean_city <> 'UNKNOWN'          -- excluded from geo ranking, included in totals (T-16)
GROUP BY c.location_key, c.clean_city, c.city_tier;

-- Segment summary (Page 2, Excel sheet 3, deck slide 4)
CREATE TABLE agg_segment_summary AS
SELECT s.segment_id, s.segment_name,
       COUNT(*)                                                           AS customers,
       ROUND(100.0 * AVG((s.layer = 'Repeat')::INT), 2)                   AS pct_repeat,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)                 AS pct_customers,
       SUM(c.total_txn_value)                                             AS total_value,
       ROUND(100.0 * SUM(c.total_txn_value) / SUM(SUM(c.total_txn_value)) OVER (), 2) AS pct_value,
       ROUND(AVG(c.avg_balance), 2)                                       AS mean_avg_balance,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY c.avg_balance)         AS median_avg_balance,
       ROUND(AVG(c.txn_count), 3)                                         AS avg_txn_count,
       ROUND(SUM(c.total_txn_value) / SUM(c.txn_count), 2)               AS avg_txn_value,
       ROUND(AVG(c.recency_days), 2)                                      AS avg_recency_days,
       ROUND(100.0 * AVG(c.is_active::INT), 2)                            AS pct_active,
       ROUND(100.0 * AVG(c.is_high_value::INT), 2)                        AS pct_high_value,
       ROUND(100.0 * AVG(o.any_signal::INT), 2)                           AS pct_with_signal,
       COUNT(*) FILTER (WHERE o.tier = 'A')                               AS tier_a
FROM customer_segment s
JOIN customer_360 c USING (customer_id)
JOIN customer_opportunity o USING (customer_id)
GROUP BY s.segment_id, s.segment_name;

-- Product theme x segment matrix (Page 3, deck slide 5, P16)
CREATE TABLE agg_theme_segment AS
SELECT s.segment_id, s.segment_name, t.theme,
       COUNT(*) FILTER (WHERE t.flag)                          AS flagged_customers,
       SUM(c.latest_balance) FILTER (WHERE t.flag)            AS addressable_balance
FROM customer_segment s
JOIN customer_opportunity o USING (customer_id)
JOIN customer_360 c USING (customer_id)
CROSS JOIN LATERAL (VALUES
    ('Investment / MF', o.sig_investment),
    ('Premium account', o.sig_premium),
    ('Credit card', o.sig_credit_card),
    ('Insurance', o.sig_insurance),
    ('Personal loan (demand)', o.sig_personal_loan),
    ('Re-engagement', o.sig_reengagement)
) AS t(theme, flag)
GROUP BY s.segment_id, s.segment_name, t.theme;

-- Headline KPIs computed once in SQL: the reference for reconciliation (FR-038, T-12..15)
CREATE TABLE kpi_reconciliation AS
SELECT 'Total Customers'        AS kpi, COUNT(*)::NUMERIC                         AS sql_value FROM customer_360
UNION ALL SELECT 'Total Transactions',     SUM(txn_count)                         FROM customer_360
UNION ALL SELECT 'Total Txn Value',        SUM(total_txn_value)                   FROM customer_360
UNION ALL SELECT 'Avg Txn Value',          ROUND(SUM(total_txn_value) / SUM(txn_count), 4) FROM customer_360
UNION ALL SELECT 'Avg Balance',            ROUND(AVG(avg_balance), 4)             FROM customer_360
UNION ALL SELECT 'Median Balance',         percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_balance)::NUMERIC FROM customer_360
UNION ALL SELECT 'Active Customers',       COUNT(*) FILTER (WHERE is_active)      FROM customer_360
UNION ALL SELECT 'High Value Customers',   COUNT(*) FILTER (WHERE is_high_value)  FROM customer_360
UNION ALL SELECT 'Opportunity Count',      COUNT(*) FILTER (WHERE any_signal)     FROM customer_opportunity
UNION ALL SELECT 'Tier A Customers',       COUNT(*) FILTER (WHERE tier = 'A')     FROM customer_opportunity
UNION ALL SELECT 'Addressable Balance',    SUM(c.latest_balance)
          FROM customer_360 c JOIN customer_opportunity o USING (customer_id) WHERE o.any_signal;

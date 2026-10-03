-- =====================================================================
-- 07_analytical_questions.sql : the 26 business questions of spec 14.2
-- Each query is self-contained and commented. Results are exported by
-- src/c360/sql_answers.py to outputs/sql_answers/Qnn.csv.
-- Q23-Q26 need customer_segment / customer_opportunity (Python step).
-- Customer IDs are shown as-is (public data); the BI layer offers masking.
-- =====================================================================

-- Q01. Total clean transactions and distinct customers (reconcile to profiling / waterfall)
SELECT COUNT(*)                     AS clean_transactions,
       COUNT(DISTINCT customer_id)  AS distinct_customers,
       SUM(amount)                  AS total_txn_value_inr,
       (SELECT rows FROM row_waterfall WHERE step_no = 99) AS waterfall_clean_rows
FROM fact_transaction;

-- Q02. Rows rejected, by reason (waterfall view)
SELECT step_no, step, rows
FROM row_waterfall
ORDER BY step_no;

-- Q03. Top 100 customers by total transaction value
SELECT customer_id, clean_city, txn_count, total_txn_value, latest_balance,
       RANK() OVER (ORDER BY total_txn_value DESC) AS value_rank
FROM customer_360
ORDER BY total_txn_value DESC, customer_id
LIMIT 100;

-- Q04. Top 100 customers by average balance
SELECT customer_id, clean_city, avg_balance, latest_balance, txn_count,
       RANK() OVER (ORDER BY avg_balance DESC) AS balance_rank
FROM customer_360
WHERE avg_balance IS NOT NULL
ORDER BY avg_balance DESC, customer_id
LIMIT 100;

-- Q05. Cities with the highest total transaction value (UNKNOWN excluded from ranking, T-16)
SELECT clean_city, SUM(total_txn_value) AS total_txn_value, SUM(txn_count) AS txns,
       RANK() OVER (ORDER BY SUM(total_txn_value) DESC) AS city_rank
FROM customer_360
WHERE clean_city <> 'UNKNOWN'
GROUP BY clean_city
ORDER BY total_txn_value DESC
LIMIT 25;

-- Q06. Cities with the most customers, and value per customer (HAVING: cities with >= 1,000 customers)
SELECT clean_city,
       COUNT(*)                                   AS customers,
       SUM(total_txn_value)                       AS total_txn_value,
       ROUND(SUM(total_txn_value) / COUNT(*), 2)  AS value_per_customer
FROM customer_360
WHERE clean_city <> 'UNKNOWN'
GROUP BY clean_city
HAVING COUNT(*) >= 1000
ORDER BY customers DESC
LIMIT 25;

-- Q07. Share of transactions that are high-value (>= P95 amount, BR-07)
SELECT ROUND(100.0 * AVG(is_high_value_txn::INT), 2)                         AS pct_txns_high_value,
       ROUND(100.0 * SUM(amount) FILTER (WHERE is_high_value_txn) / SUM(amount), 2) AS pct_value_high_value,
       (SELECT txn_amount_p95 FROM customer_thresholds)                     AS p95_amount_inr
FROM fact_transaction;

-- Q08. Pareto: share of total value from the top 10% of customers (by value decile)
WITH d AS (
    SELECT total_txn_value, NTILE(10) OVER (ORDER BY total_txn_value DESC) AS value_decile
    FROM customer_360
)
SELECT value_decile,
       COUNT(*)                                                           AS customers,
       SUM(total_txn_value)                                               AS decile_value,
       ROUND(100.0 * SUM(total_txn_value) / SUM(SUM(total_txn_value)) OVER (), 2) AS pct_of_value,
       ROUND(100.0 * SUM(SUM(total_txn_value)) OVER (ORDER BY value_decile)
                   / SUM(SUM(total_txn_value)) OVER (), 2)                AS cumulative_pct
FROM d
GROUP BY value_decile
ORDER BY value_decile;

-- Q09. Average transaction value by gender and by age group (transaction level)
SELECT 'gender' AS dimension, c.gender AS value, COUNT(*) AS txns, ROUND(AVG(f.amount), 2) AS avg_txn_value,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY f.amount) AS median_txn_value
FROM fact_transaction f JOIN dim_customer c USING (customer_id)
GROUP BY c.gender
UNION ALL
SELECT 'age_group', c.age_group, COUNT(*), ROUND(AVG(f.amount), 2),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY f.amount)
FROM fact_transaction f JOIN dim_customer c USING (customer_id)
GROUP BY c.age_group
ORDER BY dimension, value;

-- Q10. Distribution of customers by transactions per customer (1, 2, 3+)
SELECT CASE WHEN txn_count >= 3 THEN '3+' ELSE txn_count::TEXT END AS txns_per_customer,
       COUNT(*)                                                     AS customers,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)           AS pct_customers
FROM customer_360
GROUP BY 1
ORDER BY 1;

-- Q11a. Monthly transaction counts and values (September is partial: 1-15 Sep)
SELECT d.month_key, d.month_name, COUNT(*) AS txns, SUM(f.amount) AS total_value,
       COUNT(DISTINCT d.date) AS days_in_window,
       ROUND(COUNT(*)::NUMERIC / COUNT(DISTINCT d.date), 0) AS txns_per_day
FROM fact_transaction f JOIN dim_date d USING (date_key)
GROUP BY d.month_key, d.month_name
ORDER BY d.month_key;

-- Q11b. Weekly transaction counts and values, with running total (window function)
SELECT d.week_start, COUNT(*) AS txns, SUM(f.amount) AS total_value,
       COUNT(DISTINCT d.date) AS days_in_week,
       SUM(COUNT(*)) OVER (ORDER BY d.week_start) AS running_txns
FROM fact_transaction f JOIN dim_date d USING (date_key)
GROUP BY d.week_start
ORDER BY d.week_start;

-- Q12. Activity by day of week and by hour band
SELECT 'day_of_week' AS dimension, d.day_of_week AS value, d.day_of_week_num AS sort_key,
       COUNT(*) AS txns, ROUND(COUNT(*)::NUMERIC / COUNT(DISTINCT d.date), 0) AS avg_txns_per_day
FROM fact_transaction f JOIN dim_date d USING (date_key)
GROUP BY d.day_of_week, d.day_of_week_num
UNION ALL
SELECT 'time_band', f.time_band, MIN(f.txn_hour), COUNT(*), NULL
FROM fact_transaction f
GROUP BY f.time_band
ORDER BY dimension, sort_key;

-- Q13. Customers with declining activity: second half of window vs first half (repeat customers only, UC11)
SELECT customer_id, clean_city, txn_count, txns_first_half, txns_second_half, last_txn_date, recency_days
FROM customer_360
WHERE activity_trend = 'Declining'
ORDER BY (txns_first_half - txns_second_half) DESC, total_txn_value DESC
LIMIT 100;

-- Q14. Rank customers within each city by total value (RANK ... PARTITION BY city); top 3 per top-10 city
WITH top_cities AS (
    SELECT clean_city FROM customer_360 WHERE clean_city <> 'UNKNOWN'
    GROUP BY clean_city ORDER BY SUM(total_txn_value) DESC LIMIT 10
),
ranked AS (
    SELECT customer_id, clean_city, total_txn_value,
           RANK() OVER (PARTITION BY clean_city ORDER BY total_txn_value DESC) AS rank_in_city
    FROM customer_360
    WHERE clean_city IN (SELECT clean_city FROM top_cities)
)
SELECT * FROM ranked WHERE rank_in_city <= 3 ORDER BY clean_city, rank_in_city;

-- Q15. Customer percentile and decile of balance (PERCENT_RANK, NTILE(10)) - decile summary
WITH b AS (
    SELECT customer_id, avg_balance,
           ROUND((100 * PERCENT_RANK() OVER (ORDER BY avg_balance))::NUMERIC, 2) AS balance_percentile,
           NTILE(10) OVER (ORDER BY avg_balance) AS balance_decile
    FROM customer_360
    WHERE avg_balance IS NOT NULL
)
SELECT balance_decile, COUNT(*) AS customers,
       MIN(avg_balance) AS min_balance, MAX(avg_balance) AS max_balance,
       ROUND(AVG(avg_balance), 2) AS mean_balance
FROM b
GROUP BY balance_decile
ORDER BY balance_decile;

-- Q16. RFM metrics and quintile scores (NTILE(5) shown beside the tie-safe CUME_DIST scores used in customer_360)
WITH rfm AS (
    SELECT customer_id, recency_days, txn_count, total_txn_value, r_score, f_score, m_score,
           NTILE(5) OVER (ORDER BY recency_days DESC)  AS r_ntile,
           NTILE(5) OVER (ORDER BY total_txn_value)    AS m_ntile
    FROM customer_360
)
SELECT r_score, m_score, COUNT(*) AS customers,
       ROUND(AVG(recency_days), 1) AS avg_recency, ROUND(AVG(txn_count), 2) AS avg_txns,
       ROUND(AVG(total_txn_value), 0) AS avg_value
FROM rfm
GROUP BY r_score, m_score
ORDER BY r_score DESC, m_score DESC;

-- Q17. Customers per balance band (latest balance)
SELECT CASE
           WHEN latest_balance IS NULL    THEN '0. Unknown'
           WHEN latest_balance < 1        THEN '1. Zero (< 1)'
           WHEN latest_balance < 1000     THEN '2. 1-999'
           WHEN latest_balance < 10000    THEN '3. 1K-9.9K'
           WHEN latest_balance < 50000    THEN '4. 10K-49.9K'
           WHEN latest_balance < 100000   THEN '5. 50K-99.9K'
           WHEN latest_balance < 1000000  THEN '6. 1L-9.9L'
           ELSE '7. 10L+'
       END AS balance_band,
       COUNT(*) AS customers,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_customers
FROM customer_360
GROUP BY 1
ORDER BY 1;

-- Q18. High balance but low activity: re-engagement candidates (balance >= P75, low engagement)
SELECT c.customer_id, c.clean_city, c.avg_balance, c.txn_count, c.recency_days, c.engagement_score
FROM customer_360 c, customer_thresholds t
WHERE c.avg_balance >= t.avg_balance_p75
  AND c.is_low_engagement
ORDER BY c.avg_balance DESC
LIMIT 100;

-- Q19. Average balance by city tier and for the top-20 cities by customers (subquery)
SELECT 'city_tier' AS level, city_tier AS name, COUNT(*) AS customers,
       ROUND(AVG(avg_balance), 0) AS mean_avg_balance,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_balance) AS median_avg_balance
FROM customer_360
GROUP BY city_tier
UNION ALL
SELECT 'top20_city', clean_city, COUNT(*), ROUND(AVG(avg_balance), 0),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_balance)
FROM customer_360
WHERE clean_city IN (SELECT clean_city FROM customer_360 WHERE clean_city <> 'UNKNOWN'
                     GROUP BY clean_city ORDER BY COUNT(*) DESC LIMIT 20)
GROUP BY clean_city
ORDER BY level, customers DESC;

-- Q20. Customers with a high Txn_to_Balance_Ratio (top 100; ratio >= P75 shown as flag basis)
SELECT customer_id, clean_city, avg_txn_value, latest_balance,
       ROUND(txn_to_balance_ratio, 4) AS txn_to_balance_ratio
FROM customer_360
WHERE txn_to_balance_ratio IS NOT NULL
ORDER BY txn_to_balance_ratio DESC
LIMIT 100;

-- Q21. Share of customers with missing DOB, gender or location
SELECT COUNT(*) AS customers,
       ROUND(100.0 * AVG((dob IS NULL)::INT), 2)               AS pct_dob_missing_or_invalid,
       ROUND(100.0 * AVG((gender = 'Unknown')::INT), 2)        AS pct_gender_unknown,
       ROUND(100.0 * AVG((clean_city = 'UNKNOWN')::INT), 2)    AS pct_location_unknown
FROM dim_customer;

-- Q22. Customers with conflicting attributes across rows
SELECT COUNT(*) FILTER (WHERE dob_conflict)      AS dob_conflicts,
       COUNT(*) FILTER (WHERE gender_conflict)   AS gender_conflicts,
       COUNT(*) FILTER (WHERE location_conflict) AS location_conflicts,
       COUNT(*) FILTER (WHERE dob_conflict OR gender_conflict OR location_conflict) AS any_conflict,
       (SELECT COUNT(*) FROM customer_360 WHERE txn_count > 1) AS repeat_customers
FROM dim_customer;

-- Q23. Segment size and value (after customer_segment is loaded)
SELECT s.segment_name,
       COUNT(*)                                                         AS customers,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)               AS pct_customers,
       SUM(c.total_txn_value)                                           AS total_value,
       ROUND(100.0 * SUM(c.total_txn_value) / SUM(SUM(c.total_txn_value)) OVER (), 2) AS pct_value,
       ROUND(AVG(c.avg_balance), 0)                                     AS mean_avg_balance
FROM customer_segment s JOIN customer_360 c USING (customer_id)
GROUP BY s.segment_name
ORDER BY total_value DESC;

-- Q24. Opportunity flags by product theme and by segment
SELECT s.segment_name,
       SUM(o.sig_investment::INT)     AS investment,
       SUM(o.sig_premium::INT)        AS premium_account,
       SUM(o.sig_credit_card::INT)    AS credit_card,
       SUM(o.sig_insurance::INT)      AS insurance,
       SUM(o.sig_personal_loan::INT)  AS personal_loan,
       SUM(o.sig_reengagement::INT)   AS reengagement,
       SUM(o.any_signal::INT)         AS any_signal,
       COUNT(*)                       AS customers
FROM customer_opportunity o JOIN customer_segment s USING (customer_id)
GROUP BY ROLLUP (s.segment_name)
ORDER BY s.segment_name NULLS LAST;

-- Q25. Top 20 Tier A customers per city (top 5 cities by Tier A count) with driving theme
WITH tier_a AS (
    SELECT o.customer_id, c.clean_city, o.overall_score, o.driving_theme,
           ROW_NUMBER() OVER (PARTITION BY c.clean_city ORDER BY o.overall_score DESC, o.customer_id) AS rn
    FROM customer_opportunity o JOIN customer_360 c USING (customer_id)
    WHERE o.tier = 'A' AND c.clean_city <> 'UNKNOWN'
),
top_cities AS (
    SELECT clean_city FROM tier_a GROUP BY clean_city ORDER BY COUNT(*) DESC LIMIT 5
)
SELECT clean_city, rn AS rank_in_city, customer_id, ROUND(overall_score::NUMERIC, 2) AS overall_score, driving_theme
FROM tier_a
WHERE rn <= 20 AND clean_city IN (SELECT clean_city FROM top_cities)
ORDER BY clean_city, rn;

-- Q26. Under-served cities: high share of Tier A/B customers but low average activity
WITH city AS (
    SELECT c.clean_city,
           COUNT(*)                                          AS customers,
           AVG((o.tier IN ('A', 'B'))::INT)                  AS share_tier_ab,
           AVG(c.engagement_score)                           AS avg_engagement,
           AVG(c.txn_count)                                  AS avg_txns
    FROM customer_360 c JOIN customer_opportunity o USING (customer_id)
    WHERE c.clean_city <> 'UNKNOWN'
    GROUP BY c.clean_city
    HAVING COUNT(*) >= 1000
)
SELECT clean_city, customers,
       ROUND(100 * share_tier_ab, 2) AS pct_tier_ab,
       ROUND(avg_engagement, 2)      AS avg_engagement,
       ROUND(avg_txns, 3)            AS avg_txns
FROM city
WHERE share_tier_ab > (SELECT AVG((tier IN ('A', 'B'))::INT) FROM customer_opportunity)
  AND avg_engagement < (SELECT AVG(engagement_score) FROM customer_360)
ORDER BY share_tier_ab DESC
LIMIT 20;

-- =====================================================================
-- 03_model.sql : star-style model (spec 8, FR-013..016)
--   dim_location, dim_date, dim_customer, fact_transaction
-- =====================================================================

-- ---------------------------------------------------------------------
-- dim_location (FR-013). CityTier is a derived [P] lookup:
--   'Tier 1 metro'    = the eight X-class cities (Delhi counted as DELHI and NEW DELHI)
--   'Metro satellite' = NCR / MMR / Hyderabad satellite locations
-- ---------------------------------------------------------------------
CREATE TABLE dim_location AS
SELECT ROW_NUMBER() OVER (ORDER BY clean_city)::INT AS location_key,
       clean_city,
       COUNT(DISTINCT raw_location)::INT            AS raw_variants_count,
       CASE
           WHEN clean_city = 'UNKNOWN' THEN 'Unknown'
           WHEN clean_city IN ('MUMBAI', 'NEW DELHI', 'DELHI', 'BANGALORE', 'CHENNAI',
                               'KOLKATA', 'HYDERABAD', 'PUNE', 'AHMEDABAD') THEN 'Tier 1 metro'
           WHEN clean_city IN ('GURGAON', 'NOIDA', 'GREATER NOIDA', 'GHAZIABAD', 'FARIDABAD',
                               'THANE', 'NAVI MUMBAI', 'SECUNDERABAD', 'RANGA REDDY') THEN 'Metro satellite'
           ELSE 'Other'
       END                                          AS city_tier
FROM clean_transactions
GROUP BY clean_city;

ALTER TABLE dim_location ADD PRIMARY KEY (location_key);
CREATE UNIQUE INDEX ux_dim_location_city ON dim_location (clean_city);

-- ---------------------------------------------------------------------
-- dim_date (FR-014): one row per day of the analysis window
-- ---------------------------------------------------------------------
CREATE TABLE dim_date AS
SELECT to_char(d, 'YYYYMMDD')::INT                  AS date_key,
       d::DATE                                      AS date,
       EXTRACT(YEAR FROM d)::INT                    AS year,
       EXTRACT(MONTH FROM d)::INT                   AS month,
       to_char(d, 'Mon YYYY')                       AS month_name,
       to_char(d, 'YYYY-MM')                        AS month_key,
       date_trunc('week', d)::DATE                  AS week_start,
       EXTRACT(WEEK FROM d)::INT                    AS iso_week,
       to_char(d, 'FMDay')                          AS day_of_week,
       EXTRACT(ISODOW FROM d)::INT                  AS day_of_week_num,
       EXTRACT(ISODOW FROM d) IN (6, 7)             AS is_weekend,
       (pp.as_of_date - d::DATE)                    AS days_before_as_of
FROM project_params pp,
     generate_series(pp.window_start, pp.window_end, INTERVAL '1 day') AS d;

ALTER TABLE dim_date ADD PRIMARY KEY (date_key);

-- ---------------------------------------------------------------------
-- fact_transaction (FR-016): cleaned transactions + derived fields (spec 7.4)
-- ---------------------------------------------------------------------
CREATE TABLE fact_transaction AS
WITH p95 AS (
    SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY amount) AS amount_p95
    FROM clean_transactions
)
SELECT c.transaction_id,
       c.txn_seq,
       -- sortable key: date, time, then TransactionID number (tie-breaker for "latest")
       (EXTRACT(EPOCH FROM c.txn_date + COALESCE(c.txn_time, TIME '00:00'))::BIGINT * 10000000
         + c.txn_seq)                                AS order_key,
       c.customer_id,
       to_char(c.txn_date, 'YYYYMMDD')::INT          AS date_key,
       c.txn_date,
       c.txn_time,
       EXTRACT(HOUR FROM c.txn_time)::INT            AS txn_hour,
       CASE
           WHEN c.txn_time IS NULL                 THEN 'Unknown'
           WHEN EXTRACT(HOUR FROM c.txn_time) < 6  THEN 'Early morning (00-05)'
           WHEN EXTRACT(HOUR FROM c.txn_time) < 12 THEN 'Morning (06-11)'
           WHEN EXTRACT(HOUR FROM c.txn_time) < 17 THEN 'Afternoon (12-16)'
           WHEN EXTRACT(HOUR FROM c.txn_time) < 21 THEN 'Evening (17-20)'
           ELSE 'Night (21-23)'
       END                                           AS time_band,
       to_char(c.txn_date, 'FMDay')                  AS day_of_week,
       c.amount,
       c.balance,
       CASE
           WHEN c.amount < 100    THEN '1. < 100'
           WHEN c.amount < 500    THEN '2. 100-499'
           WHEN c.amount < 1000   THEN '3. 500-999'
           WHEN c.amount < 5000   THEN '4. 1K-4.9K'
           WHEN c.amount < 25000  THEN '5. 5K-24.9K'
           ELSE '6. 25K+'
       END                                           AS amount_band,
       CASE
           WHEN c.balance IS NULL    THEN '0. Unknown'
           WHEN c.balance < 1        THEN '1. Zero (< 1)'
           WHEN c.balance < 1000     THEN '2. 1-999'
           WHEN c.balance < 10000    THEN '3. 1K-9.9K'
           WHEN c.balance < 50000    THEN '4. 10K-49.9K'
           WHEN c.balance < 100000   THEN '5. 50K-99.9K'
           WHEN c.balance < 1000000  THEN '6. 1L-9.9L'
           ELSE '7. 10L+'
       END                                           AS balance_band,
       (c.amount >= p95.amount_p95)                  AS is_high_value_txn,      -- BR-07
       (c.balance < 1)                               AS is_zero_balance,        -- C14
       c.is_possible_duplicate,
       l.location_key                                AS txn_location_key
FROM clean_transactions c
CROSS JOIN p95
JOIN dim_location l ON l.clean_city = c.clean_city;

ALTER TABLE fact_transaction ADD PRIMARY KEY (transaction_id);
CREATE INDEX ix_fact_customer ON fact_transaction (customer_id);
CREATE INDEX ix_fact_date ON fact_transaction (date_key);

-- ---------------------------------------------------------------------
-- dim_customer (FR-015). Conflicting DOB / gender / location across rows are
-- resolved per spec 8.3: most frequent non-null value; tie -> latest txn's value.
-- ---------------------------------------------------------------------
CREATE TABLE dim_customer AS
WITH keyed AS (
    SELECT c.customer_id, c.dob, c.gender, c.clean_city, f.order_key
    FROM clean_transactions c
    JOIN fact_transaction f USING (transaction_id)
),
pick_dob AS (
    SELECT DISTINCT ON (customer_id) customer_id, dob, n_values
    FROM (SELECT customer_id, dob, COUNT(*) AS n, MAX(order_key) AS latest,
                 COUNT(*) OVER (PARTITION BY customer_id) AS n_values
          FROM keyed WHERE dob IS NOT NULL GROUP BY customer_id, dob) x
    ORDER BY customer_id, n DESC, latest DESC
),
pick_gender AS (
    SELECT DISTINCT ON (customer_id) customer_id, gender, n_values
    FROM (SELECT customer_id, gender, COUNT(*) AS n, MAX(order_key) AS latest,
                 COUNT(*) OVER (PARTITION BY customer_id) AS n_values
          FROM keyed WHERE gender <> 'Unknown' GROUP BY customer_id, gender) x
    ORDER BY customer_id, n DESC, latest DESC
),
pick_city AS (
    SELECT DISTINCT ON (customer_id) customer_id, clean_city, n_values
    FROM (SELECT customer_id, clean_city, COUNT(*) AS n, MAX(order_key) AS latest,
                 COUNT(*) OVER (PARTITION BY customer_id) AS n_values
          FROM keyed WHERE clean_city <> 'UNKNOWN' GROUP BY customer_id, clean_city) x
    ORDER BY customer_id, n DESC, latest DESC
),
customers AS (SELECT DISTINCT customer_id FROM keyed),
resolved AS (
    SELECT c.customer_id,
           d.dob,
           DATE_PART('year', AGE(pp.as_of_date, d.dob))::INT AS raw_age,
           COALESCE(g.gender, 'Unknown')                     AS gender,
           COALESCE(l.clean_city, 'UNKNOWN')                 AS clean_city,
           COALESCE(d.n_values, 0) > 1                       AS dob_conflict,
           COALESCE(g.n_values, 0) > 1                       AS gender_conflict,
           COALESCE(l.n_values, 0) > 1                       AS location_conflict
    FROM customers c
    CROSS JOIN project_params pp
    LEFT JOIN pick_dob d    USING (customer_id)
    LEFT JOIN pick_gender g USING (customer_id)
    LEFT JOIN pick_city l   USING (customer_id)
)
SELECT r.customer_id,
       r.dob,
       CASE WHEN r.raw_age BETWEEN 18 AND 90 THEN r.raw_age END       AS age,          -- C15, AS-10
       CASE
           WHEN r.raw_age IS NULL OR r.raw_age NOT BETWEEN 18 AND 90 THEN 'Unknown'
           WHEN r.raw_age < 25 THEN '18-24'
           WHEN r.raw_age < 35 THEN '25-34'
           WHEN r.raw_age < 45 THEN '35-44'
           WHEN r.raw_age < 55 THEN '45-54'
           WHEN r.raw_age < 65 THEN '55-64'
           ELSE '65+'
       END                                                             AS age_group,
       (r.raw_age BETWEEN 18 AND 90)                                   AS age_known,    -- BR-12
       (r.raw_age IS NOT NULL AND r.raw_age NOT BETWEEN 18 AND 90)     AS age_out_of_range,
       r.gender,
       l.location_key,
       r.clean_city,
       l.city_tier,
       r.dob_conflict,
       r.gender_conflict,
       r.location_conflict,
       NULLIF(concat_ws(',',
           CASE WHEN r.dob IS NULL THEN 'DOB_MISSING' END,
           CASE WHEN r.raw_age IS NOT NULL AND r.raw_age NOT BETWEEN 18 AND 90 THEN 'AGE_OUT_OF_RANGE' END,
           CASE WHEN r.gender = 'Unknown' THEN 'GENDER_UNKNOWN' END,
           CASE WHEN r.clean_city = 'UNKNOWN' THEN 'LOCATION_UNKNOWN' END,
           CASE WHEN r.dob_conflict OR r.gender_conflict OR r.location_conflict THEN 'ATTRIBUTE_CONFLICT' END
       ), '')                                                          AS dq_flag
FROM resolved r
JOIN dim_location l ON l.clean_city = r.clean_city;

ALTER TABLE dim_customer ADD PRIMARY KEY (customer_id);
CREATE INDEX ix_dim_customer_location ON dim_customer (location_key);

ALTER TABLE fact_transaction
    ADD CONSTRAINT fk_fact_customer FOREIGN KEY (customer_id) REFERENCES dim_customer (customer_id),
    ADD CONSTRAINT fk_fact_date FOREIGN KEY (date_key) REFERENCES dim_date (date_key);
ALTER TABLE dim_customer
    ADD CONSTRAINT fk_customer_location FOREIGN KEY (location_key) REFERENCES dim_location (location_key);

ANALYZE dim_location; ANALYZE dim_date; ANALYZE fact_transaction; ANALYZE dim_customer;

# KavionLens360: end-to-end project guide

This guide explains the whole project: what it does, how every stage works, where each rule lives in the code,
what the results are, and how to change or rebuild anything. It is written for someone who will work on the logic.
For a short overview, see [README.md](README.md). For the published outputs, see the
[live report](https://rudraakshreddy.github.io/kavionlens360/) and
[dashboard](https://rudraakshreddy.github.io/kavionlens360/dashboard.html).

---

## Contents

1. [What the project is](#1-what-the-project-is)
2. [Stack and environment](#2-stack-and-environment)
3. [Repository map](#3-repository-map)
4. [The data and what profiling found](#4-the-data-and-what-profiling-found)
5. [Pipeline overview](#5-pipeline-overview)
6. [SQL stage, step by step](#6-sql-stage-step-by-step)
7. [Customer features, scores and business rules](#7-customer-features-scores-and-business-rules)
8. [Data quality scorecard](#8-data-quality-scorecard)
9. [Segmentation](#9-segmentation)
10. [Cross-sell opportunity signals, scores and tiers](#10-cross-sell-opportunity-signals-scores-and-tiers)
11. [Publish and exports](#11-publish-and-exports)
12. [The 26 analytical SQL questions](#12-the-26-analytical-sql-questions)
13. [Notebooks and statistics](#13-notebooks-and-statistics)
14. [Power BI report](#14-power-bi-report)
15. [Excel MIS](#15-excel-mis)
16. [Executive deck](#16-executive-deck)
17. [Website (report + dashboard)](#17-website-report--dashboard)
18. [Testing and reconciliation](#18-testing-and-reconciliation)
19. [Results](#19-results)
20. [Decisions, assumptions and limitations](#20-decisions-assumptions-and-limitations)
21. [How to run, rebuild and change things](#21-how-to-run-rebuild-and-change-things)
22. [Troubleshooting notes](#22-troubleshooting-notes)
23. [Glossary](#23-glossary)

---

## 1. What the project is

**Problem.** A bank stores activity as transactions, but relationship managers (RMs) think in customers and have limited
time. A transaction log cannot answer five questions: *who* to focus on, *why*, *what* conversation to have, *where* the
customers are, and *how large* the opportunity is.

**Solution.** Turn ~1M transactions into a customer-level analytical table (a small "Customer 360"), segment customers by
behaviour, flag product-interest *signals* with transparent rules, score and rank customers into priority tiers, and
deliver the result through SQL, Python, Power BI, an Excel MIS, an executive deck and a public website.

**Origin.** The scope comes from a requirements document (combined BRD + FRD + analytics + dashboard specification,
50 pages, kept privately in `reference/`, not in git). Section numbers such as "spec 13.3" or "FR-030" in code
comments refer to that document. Its evidence tags are kept in this guide:
`[D]` = verified dataset fact, `[A]` = project assumption, `[P]` = proposed / derived feature.

**Framing.** The data is a public Kaggle dataset from an Indian bank (2016). It is not ICICI Bank data, and nothing here
describes any bank's internal systems. Opportunity flags rank conversations; they are never eligibility or credit decisions.

**Value chain:** data → analysis → insight → business action. Every major output carries a "what we found / why it
matters / what a manager should do" reading.

---

## 2. Stack and environment

| Layer | Choice | Notes |
|---|---|---|
| Database | PostgreSQL 16 in Docker (`docker-compose.yml`, container `c360-postgres`) | `shm_size: 1gb` is required, or parallel queries fail with "could not resize shared memory segment" |
| Language | Python 3.13 | pandas, NumPy, SciPy, scikit-learn, matplotlib, SQLAlchemy, psycopg2, nbformat/nbconvert, pytest |
| BI | Power BI Desktop (Store build 2.158), PBIP format | Generated as text, validated with Microsoft tooling |
| MIS | Excel 2021 via COM (`pywin32`) | XLOOKUP / IFS need Excel 2021 or 365 |
| Deck | `python-pptx`; PDF via PowerPoint COM | |
| Web | Static HTML/CSS/JS on GitHub Pages from `/docs`; Chart.js 4.4.1 from cdnjs | |
| Browser printing | Headless Edge / Chrome / Brave | Prints the report page to PDF |

**Configuration.** Database credentials live in `.env` (git-ignored); `.env.example` shows the keys
(`PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE`). `src/c360/db.py` loads `.env`.

**Raw data.** Put `archive.zip` (containing `bank_transactions.csv`) in `data/raw/`. It is git-ignored; the loader streams
it straight out of the zip.

---

## 3. Repository map

```
.
├── run_pipeline.py            ordered pipeline runner (steps 00 → SITE)
├── docker-compose.yml         PostgreSQL 16
├── config/segments.json       segment design, names, actions, profile guards
├── sql/
│   ├── 00_schema.sql          project_params, staging, audit tables
│   ├── 01_location_map.sql    94 manual location-variant mappings
│   ├── 02_clean.sql           parsing functions, reject rules, clean_transactions, row waterfall
│   ├── 03_model.sql           dim_location, dim_date, fact_transaction, dim_customer
│   ├── 04_customer_360.sql    features, RFM, scores, thresholds, business-rule flags
│   ├── 05_dq_checks.sql       24-check data-quality scorecard → dq_log
│   ├── 06_publish.sql         aggregated tables + kpi_reconciliation
│   └── 07_analytical_questions.sql   the 26 business questions
├── src/c360/
│   ├── config.py  db.py  load.py
│   ├── segmentation.py        preprocessing, k evaluation, K-Means, profiles
│   ├── opportunity.py         signal rules, scores, tiers, reasons, sensitivity
│   ├── export.py              Power BI / Excel extracts, dashboard JSON
│   ├── sql_answers.py         runs the 26 questions → outputs/sql_answers/
│   ├── viz.py                 shared chart palette and style
│   ├── site.py                builds docs/index.html and docs/dashboard.html
│   └── report_pdf.py          prints the report page to PDF
├── notebooks/                 01-04 (.ipynb) + build_*.py authoring scripts + notes_*.json interpretations
├── powerbi/                   KavionLens360.pbip, generated model/report, build_pbip.py, README
├── excel/build_mis.py         Excel MIS builder (COM)
├── deck/build_deck.py         executive deck builder
├── site/assets/               source CSS/JS for the website (copied into docs/assets)
├── docs/                      GitHub Pages site + downloads (generated)
├── outputs/                   figures, sql_answers, k_selection.csv, stat_tests.csv, models/, test results
├── tests/                     test_pipeline.py (spec T-01..T-16 + extras), render_test_log.py
├── TEST_LOG.md                rendered test results
└── data/                      raw/ (ignored), exports/ (generated, ignored)
```

---

## 4. The data and what profiling found

**Source.** Kaggle "Bank Customer Segmentation (1M+ Transactions)", file `bank_transactions.csv`, 1,048,567 rows × 9 columns,
one row per transaction.

| Column | Meaning | Raw format | Cleaning |
|---|---|---|---|
| TransactionID | transaction id | `T1` … | unique; duplicates would keep first |
| CustomerID | customer id | `C5841053` | must match `^C[0-9]+$` |
| CustomerDOB | date of birth | `d/m/yy`; missing written as text `nan`; placeholder `1/1/1800` | century pivot; placeholder/future → NULL |
| CustGender | gender | `M`, `F`, blank, one `T` | M / F / Unknown |
| CustLocation | free-text location | 9,355 spellings | normalise + mapping → `clean_city` |
| CustAccountBalance | balance recorded with the transaction | decimal; 2,369 blanks | NULL stays NULL (never 0) |
| TransactionDate | date | `d/m/yy` | window filter |
| TransactionTime | time | integer HHMMSS without leading zeros (`143207`) | → TIME |
| TransactionAmount (INR) | amount | decimal; 835 zeros | amount = 0 rejected |

**Profiling results** (notebook 01; all spec 7.1 counts confirmed):

- 884,265 distinct CustomerIDs in the raw file; 83.8% appear once.
- 57,339 rows (5.47%) have the DOB placeholder `1/1/1800`; 3,397 DOBs are the text `nan`.
- `TransactionTime` is valid HHMMSS on every row; it is **not** a Unix timestamp as the dataset page suggests.
- **Coverage break.** Every day from 1 Aug to 15 Sep 2016 has about 17-27K transactions (mean 21,516/day). After that the
  file holds only 9 scattered days (58,826 rows, 5.6%) up to 21 Oct. This is an extract boundary, not behaviour.
- **CustomerID is not a stable person key.** Of 143,612 repeat CustomerIDs in the raw file, 99.1% carry more than one DOB,
  96.1% more than one location, 41.7% more than one gender; only 0.7% are consistent on all three. Two different
  CustomerIDs can carry an identical record (same DOB, gender, city, balance), which suggests IDs were shuffled when the
  dataset was anonymised. (A composite key of DOB + gender + city + exact balance resolves to about 157K "people" with a
  median of 3 transactions each; this was offered and **not** adopted. The spec's CustomerID key was kept; see section 20.)

---

## 5. Pipeline overview

`python run_pipeline.py` runs these steps in order (`--from` / `--to` take a step code such as `03`, `PYTHON`, `SITE`):

| Step | What it does | Main outputs | Time |
|---|---|---|---|
| `00` | Drop/create schema, `project_params` | staging + audit tables | <1 s |
| `01` | Location-variant mapping table | `location_map` | <1 s |
| `LOAD` | Stream the CSV from the zip with `COPY`; log size, SHA-256, row count | `stg_bank_transactions`, `load_log` | ~2 s |
| `02` | Parse, validate, reject, clean, waterfall | `int_transactions`, `rejected_rows`, `clean_transactions`, `row_waterfall` | ~60 s |
| `03` | Star model | `dim_location`, `dim_date`, `fact_transaction`, `dim_customer` | ~30 s |
| `04` | Customer features, scores, flags | `customer_360`, `customer_thresholds` | ~50 s |
| `05` | Data-quality scorecard | `dq_log` | ~8 s |
| `PYTHON` | Segmentation + opportunity scoring (written back to Postgres) | `customer_segment`, `segment_definition`, `segment_profile`, `customer_opportunity`, `opportunity_sensitivity` | ~75 s |
| `06` | Aggregates and reconciliation reference | `agg_*`, `kpi_reconciliation` | ~10 s |
| `EXPORT` | CSV extracts, dashboard JSON, 26 SQL answers | `data/exports/…`, `docs/data/dashboard.json`, `outputs/sql_answers/` | ~60-90 s |
| `SITE` | Rebuild the website | `docs/index.html`, `docs/dashboard.html`, `docs/figures/` | ~10 s |

Every SQL script is idempotent: it drops and recreates what it builds. Parameters that drive rules are stored once in
`project_params` so SQL, Python and the dashboards agree.

---

## 6. SQL stage, step by step

### 6.1 `00_schema.sql`: parameters, staging and audit

`project_params` (one row) is the single source of truth for the window and day-based rules:

| Column | Value | Used by |
|---|---|---|
| `window_start` / `window_end` | 2016-08-01 / 2016-09-15 | reject rule, dim_date, DQ |
| `extract_end` | 2016-10-21 | identifies the sparse tail |
| `as_of_date` | 2016-09-16 (window_end + 1) | recency, age |
| `window_days` | 46 | frequency, engagement, opportunity R |
| `active_days` | 15 | BR-01 active |
| `dormant_days` | 30 | BR-05 dormant |
| `newly_observed_days` | 15 | BR-04 newly observed |
| `trend_split_date` | 2016-08-24 | activity trend (23 days vs 23 days) |

Staging keeps all nine columns as `TEXT` plus `src_row` (file order, used for "keep first") and `load_ts`.
Audit tables: `load_log`, `dq_log`, `rejected_rows`, `row_waterfall`, `location_map`.

### 6.2 `01_location_map.sql`: location standardisation

Locations are first normalised by `f_norm_location`: upper case, punctuation → space, collapse spaces, trim, blank → NULL.
That alone takes 9,355 raw spellings to 9,061. Then 94 manual mappings fix the spelling variants found by a fuzzy review
of the 200 most frequent locations, e.g. `NEWDELHI`/`NEW DLEHI`/`N DELHI` → `NEW DELHI`, `GURGOAN`/`GURUGRAM` → `GURGAON`,
`BANGLORE`/`BENGALURU` → `BANGALORE`, `THANE W`/`THANE EAST` → `THANE`, `CALCUTTA` → `KOLKATA`, `BARODA` → `VADODARA`.
Places that only look alike are deliberately **not** merged (JAIPUR/RAIPUR, NELLORE/VELLORE, MANGALORE/BANGALORE), and
`DELHI` and `NEW DELHI` stay separate because the source records them separately. Result: 8,773 cities in `dim_location`.

### 6.3 `02_clean.sql`: parsing, rejects, clean table

**Helper functions** (pure SQL, `IMMUTABLE`, so fast on 1M rows):

| Function | Logic |
|---|---|
| `f_parse_dmy(txt, pivot_yy)` | regex `d/m/yy` or `d/m/yyyy`; 2-digit year: `yy <= pivot → 20yy`, else `19yy`; validates month and day-of-month (nested CASE so `make_date` never sees an invalid date); invalid → NULL. Transaction dates use pivot 99; DOBs use pivot 16, so `94` → 1994 and `05` → 2005 (later removed by the 18-90 age rule) |
| `f_parse_hhmmss(txt)` | left-pad to 6 digits, check HH<24, MM<60, SS<60 → `TIME` |
| `f_to_numeric(txt)` | numeric regex → `NUMERIC`, else NULL |
| `f_norm_location(txt)` | see 6.2 |

**Reject rules** (`int_transactions.reject_reason`, first matching rule wins, in this order):
`MISSING_TRANSACTION_ID` → `DUPLICATE_TRANSACTION_ID` (keep first by `src_row`) → `INVALID_CUSTOMER_ID` →
`INVALID_TRANSACTION_DATE` → `PARTIAL_COVERAGE_PERIOD` (16 Sep - 21 Oct) → `DATE_OUTSIDE_WINDOW` →
`MISSING_OR_INVALID_AMOUNT` → `NEGATIVE_AMOUNT` → `ZERO_AMOUNT`. Rejected rows are copied with their raw text and reason
into `rejected_rows`.

**Row-level fixes in `clean_transactions`:**

- balance: NULL stays NULL; negative → NULL (none exist).
- dob: kept only if between 1920-01-01 and the transaction date (removes `1/1/1800` and future DOBs).
- gender: `M`, `F`, else `Unknown`.
- `clean_city`: mapping → normalised text → `UNKNOWN`.
- flags for the scorecard: `dob_missing` (NULL, blank or `nan`), `dob_placeholder`, `dob_future`, `balance_missing`,
  `balance_negative`, `time_invalid`, `gender_other_value`, `is_possible_duplicate` (identical rows under different IDs;
  flagged, not deleted).

**Row waterfall** (reconciles to the unit):

| Step | Rows |
|---|---:|
| Raw rows in staging | 1,048,567 |
| Rejected: PARTIAL_COVERAGE_PERIOD | −58,826 |
| Rejected: ZERO_AMOUNT | −794 |
| Clean rows | 988,947 |

(835 zero amounts exist in the raw file; 41 of them fall in the sparse tail and are counted there.)

### 6.4 `03_model.sql`: star model

- **`dim_location`**: one row per clean city, `raw_variants_count`, and a derived `city_tier` [P]:
  *Tier 1 metro* (MUMBAI, NEW DELHI, DELHI, BANGALORE, CHENNAI, KOLKATA, HYDERABAD, PUNE, AHMEDABAD),
  *Metro satellite* (GURGAON, NOIDA, GREATER NOIDA, GHAZIABAD, FARIDABAD, THANE, NAVI MUMBAI, SECUNDERABAD, RANGA REDDY),
  *Other*, *Unknown*.
- **`dim_date`**: 46 days with month, ISO week, weekday, weekend flag, days before as-of.
- **`fact_transaction`**: one row per clean transaction with `order_key` (epoch of date+time × 10⁷ + TransactionID
  number, used to find the "latest" row), `txn_hour`, `time_band` (00-05, 06-11, 12-16, 17-20, 21-23), `amount_band`,
  `balance_band`, `is_high_value_txn` (amount ≥ P95 = ₹5,200, BR-07), `is_zero_balance` (balance < 1), duplicate flag,
  transaction city. Indexed on customer and date.
- **`dim_customer`**: one row per CustomerID. Conflicting DOB / gender / city across rows are resolved per attribute by
  spec 8.3: **most frequent non-null value; ties → value on the latest transaction**. Conflict flags and a `dq_flag` list
  are kept. Age = whole years at the as-of date; ages outside 18-90 → NULL (`age_out_of_range`); age groups 18-24, 25-34,
  35-44, 45-54, 55-64, 65+, Unknown.

Foreign keys: fact → dim_customer, fact → dim_date, dim_customer → dim_location.

---

## 7. Customer features, scores and business rules

`04_customer_360.sql` builds one row per customer (841,543 rows) from `fact_transaction` and `dim_customer`.

### 7.1 Features

| Feature | Formula | Notes |
|---|---|---|
| `txn_count` | COUNT(transactions) | RFM F |
| `total_txn_value` | SUM(amount) | RFM M |
| `avg_txn_value` | total / count | ticket size |
| `max_txn_value`, `min_txn_value` | MAX / MIN(amount) | |
| `active_days` | COUNT(DISTINCT date) | |
| `first_txn_date`, `last_txn_date` | MIN / MAX(date) | |
| `monthly_txn_frequency` | count / (46 / 30) | normalised frequency |
| `recency_days` | as_of − last_txn_date | RFM R (1-46) |
| `avg_balance`, `max_balance`, `min_balance` | over non-null balances | wealth proxy |
| `latest_balance` | balance on the latest transaction that has one (by `order_key`) | |
| `balance_volatility` | STDDEV(balance) / AVG(balance); NULL if < 2 balances or avg 0 | |
| `txn_to_balance_ratio` | avg_txn_value / latest_balance; NULL if latest_balance < 1 | spend vs balance |
| `evening_night_share` | share of transactions with hour ≥ 17 or < 6 | |
| `txns_first_half`, `txns_second_half` | count before / from 24 Aug | |
| `activity_trend` | Single transaction / Rising / Declining / Stable (second half vs first half) | repeat customers only |
| `high_value_txn_count` | count of transactions ≥ P95 | |
| demographics | age, age_group, age_known, gender, clean_city, city_tier, location_key | from dim_customer |

### 7.2 Scores

- **Value_Score** = 100 × PERCENT_RANK of (0.5 × pct_rank(avg_balance) + 0.5 × pct_rank(total_txn_value)).
  If the balance is missing, only the value percentile is used.
- **Engagement_Score** = 100 × (0.5 × min(txn_count, 4)/4 + 0.3 × (1 − recency/46) + 0.2 × min(active_days, 4)/4).
  Observed range 17.5-99.35.
- **RFM**: R = CEIL(CUME_DIST over recency descending × 5); M = CEIL(CUME_DIST over value × 5); F = min(txn_count, 5)
  (adjusted bands because most customers have one transaction). CUME_DIST is used instead of NTILE so **tied values always
  share a score** (test T-08). `rfm_code` = R‖F‖M.

### 7.3 Thresholds (`customer_thresholds`, percentiles of the clean customer base, AS-07)

| Threshold | Value |
|---|---:|
| latest_balance P90 | ₹197,671.55 |
| total_txn_value P90 | ₹3,526 |
| engagement P25 | 25.33 |
| avg_balance P50 / P75 / P90 | ₹18,461 / ₹61,116 / ₹202,428 |
| transaction amount P95 | ₹5,200 |

### 7.4 Business rules (spec 21; day thresholds scaled to the 46-day window)

| Rule | Condition | Column | Share of customers |
|---|---|---|---:|
| BR-01 Active | recency ≤ 15 days | `is_active` | 37.7% |
| BR-02 High value | latest_balance ≥ P90 OR total_value ≥ P90 | `is_high_value` | 18.0% |
| BR-03 Low engagement | engagement < P25 | `is_low_engagement` | 22.8% |
| BR-04 Newly observed | first txn in last 15 days | `is_newly_observed` | 30.3% |
| BR-05 Dormant | recency > 30 days (not "churned") | `is_dormant` | 33.0% |
| BR-06 Frequency band | 1 = Single, 2 = Repeat, ≥3 = Frequent | `freq_band` | 84.6 / 13.5 / 1.9% |
| BR-07 High-value txn | amount ≥ P95 | fact `is_high_value_txn` | 5% of txns |
| BR-08 Segment | cluster → name via `segment_definition` | `customer_segment` | |
| BR-09/10 Signals, tiers | section 10 | `customer_opportunity` | |
| BR-11 Evidence | 1 txn = Low, 2 = Medium, ≥3 = High | `evidence_level` | |
| BR-12 Age known | age 18-90 present | `age_known` | |

---

## 8. Data quality scorecard

`05_dq_checks.sql` writes 24 checks to `dq_log` with status PASS (≥ threshold), EXCEPTION (below threshold, explained) or
INFO (measurement only). Current result: **17 PASS, 1 EXCEPTION, 6 INFO.**

| ID | Dimension | Check | Result |
|---|---|---|---|
| DQ-01 | Completeness | staging rows = 1,048,567 | PASS |
| DQ-02 | Accuracy | waterfall reconciles | PASS |
| DQ-03 | Completeness | CustomerID, amount, date non-null | PASS |
| DQ-04 | Completeness | usable DOB ≥ 99% | **EXCEPTION** 94.2% (placeholder `1/1/1800`; age rules skip these customers) |
| DQ-05/06/07 | Completeness | gender, location, balance ≥ 99% | PASS (99.9, 99.98, 99.8%) |
| DQ-08 | Accuracy | customer_360 = fact (customers, txns, value) | PASS |
| DQ-09 | Accuracy | 50 sampled fact rows match source text | PASS |
| DQ-10/11/12 | Consistency | gender domain; city in dim_location; one resolved attribute set per customer | PASS |
| DQ-13/14 | Uniqueness | TransactionID; one row per customer | PASS |
| DQ-15/16 | Validity | amount > 0, balance ≥ 0, date in window; age 18-90 or NULL | PASS |
| DQ-17 | Validity | rejected rows logged (59,620) | INFO |
| DQ-18 | Timeliness | as-of = window end + 1 | PASS |
| DQ-19 | Consistency | customers with attribute conflicts (128,610) | INFO |
| DQ-20 | Consistency | repeat IDs consistent on DOB, gender, city: 0.9% | INFO (key finding) |
| DQ-21 | Uniqueness | identical rows under different IDs: 0 | INFO |
| DQ-22 | Validity | zero / near-zero balance rows (6,376) | INFO |
| DQ-23 | Consistency | 9,355 raw locations → 8,773 cities | INFO |
| DQ-24 | Validity | valid HHMMSS on all rows | PASS |

---

## 9. Segmentation

Code: `src/c360/segmentation.py`; design and names: `config/segments.json`; analysis: notebook 03.

### 9.1 Inputs and preprocessing (`Prep`)

Five behaviour features: `log1p(avg_balance)` (missing → median), `log1p(total_txn_value)`, `log1p(avg_txn_value)`,
`min(txn_count, 4)`, `recency_days`. Each is winsorised at P1/P99 and standardised (`StandardScaler`). Gender and city are
**never** inputs (they profile segments afterwards, risk R8). Age was tested as an input and rejected (it lowered
separation at every k). Preprocessing parameters (medians, winsor caps, scaler means/scales) are saved to
`outputs/models/segmentation_params.json`.

### 9.2 Choosing k (`evaluate_k`, results in `outputs/segmentation/k_selection.csv`)

For k = 3-10: inertia (elbow), silhouette and Calinski-Harabasz on a fixed 50K sample, and stability as the adjusted Rand
index (ARI) against 5 other seeds. Four designs were compared: joint (all customers), joint + age, and separate models for
single-transaction and repeat customers ("layered").

| k | Joint silhouette | Joint + age | ARI min (joint) | Smallest cluster |
|---:|---:|---:|---:|---:|
| 3 | 0.290 | 0.248 | 0.99 | 15.1% |
| 4 | 0.268 | 0.234 | 0.98 | 15.1% |
| **5** | **0.279** | 0.225 | **0.93** | **9.5%** |
| 6 | 0.279 | 0.232 | 0.98 | 8.5% |
| 7 | 0.265 | 0.230 | 1.00 | 8.2% |
| 8 | 0.259 | 0.214 | 0.99 | 7.4% |
| 9 | 0.263 | 0.209 | 0.71 | 5.1% |
| 10 | 0.252 | 0.196 | 0.55 | 4.8% |

**Decision: joint K-Means, k = 5** (approved at the naming checkpoint). k = 3 is below the 4-6 target; k = 5 and 6 tie on
silhouette and k = 5 is more interpretable; stability collapses above k = 8. The layered 3 + 3 alternative scored ~0.267
and produced a 1.9% segment, below the 3% rule. Single vs repeat (spec layer 1) is kept as the evidence tag.

**Algorithm note.** Full Lloyd `KMeans(n_init=10, random_state=42)` is used. It takes ~5 s per fit on 840K × 5 and is far
more stable than `MiniBatchKMeans`, which was tried first (ARI 0.3-0.8 across seeds).

### 9.3 Labels and naming

`fit_clusters` relabels clusters 0..k-1 by descending mean Value_Score, so cluster keys (`J0`…`J4`) are stable across
re-runs. Names were assigned **after** reading the profiles. Each entry in `segments.json` carries an `expect` rule (a
pandas query on the profile), and `check_expectations` raises an error if a re-run would attach a name to a cluster that
no longer fits it.

| Key | Segment | Customers | Value | Median balance | Txns/customer | Active | Driver (mean z-score) | Expect rule |
|---|---|---:|---:|---:|---:|---:|---|---|
| J0 | Engaged Repeat Users | 15.0% | 28.1% | ₹29,937 | 2.14 | 59% | frequency +2.24 | `mean_txn_count > 1.5` |
| J1 | Recent One-Time Spenders | 24.1% | 33.3% | ₹29,017 | 1.00 | 73% | recency −0.84 | single, active > 50%, ticket > 400 |
| J2 | Lapsed One-Time Spenders | 25.5% | 34.3% | ₹28,730 | 1.00 | 0% | recency +1.00 | single, active < 5%, ticket > 400 |
| J3 | Low-Ticket Occasional | 25.8% | 1.7% | ₹12,443 | 1.01 | 33% | ticket −1.12 | ticket < 200, balance > 1,000 |
| J4 | Near-Zero Balance | 9.5% | 2.7% | ₹86 | 1.01 | 29% | balance −2.19 | median balance < 1,000 |

Actions, owners, timing and KPIs per segment live in `segments.json` and flow into `segment_definition`, Power BI page 2,
the Excel MIS, the deck and the website.

### 9.4 Validation

Silhouette 0.279 (≥ 0.25 target); every segment ≥ 3% (smallest 9.5%); seed stability ARI min 0.93 / mean 0.97;
Kruskal-Wallis ε² 0.29-0.97 on the clustering features; Ward hierarchical clustering on a 15K sample agrees moderately
(ARI 0.49, expected with soft boundaries); gender mix barely differs (Cramér's V 0.065); age differs little (ε² 0.05).

---

## 10. Cross-sell opportunity signals, scores and tiers

Code: `src/c360/opportunity.py`; analysis: notebook 04. Outputs: `customer_opportunity`, `opportunity_sensitivity`.

### 10.1 Signal rules (spec 13.2; percentile thresholds of the clean base)

Percentile ranks are computed with `rank(pct=True, method="max")`; missing values fail the condition. Missing age fails
age conditions (BR-12).

| Theme | Rule | Flagged | % of base |
|---|---|---:|---:|
| Investment / MF interest | avg_balance ≥ P75 AND (txn_count ≥ 2 OR total_value ≥ P60) | 126,981 | 15.1% |
| Premium account interest | avg_balance ≥ P90 | 83,991 | 10.0% |
| Credit card interest | total_value ≥ P60 AND avg_balance ≥ P40 AND age 21-60 | 215,414 | 25.6% |
| Insurance interest | age 30-55 AND avg_balance ≥ P50 | 199,478 | 23.7% |
| Personal loan interest (*demand signal only*) | age 25-45 AND txn_to_balance_ratio ≥ P75 AND recency ≤ 15 | 51,725 | 6.1% |
| Re-engagement (service, not sale) | engagement < P25 AND avg_balance ≥ P50 | 87,724 | 10.4% |

The personal-loan recency condition is the spec's 30 days scaled to 15 for the 46-day window. 404,161 customers (48.0%)
carry at least one signal.

### 10.2 Rule fit (spec 13.3)

`Fit_p = 1` if all conditions hold; `0.5` if exactly one condition is missed **and** it is a percentile condition missed
by ≤ 10 percentile points; otherwise `0`. Age, recency and count conditions are hard (no near miss). The OR condition in
the investment rule counts as one condition.

### 10.3 Score and tiers

```
V = Value_Score / 100          E = Engagement_Score / 100          R = 1 − min(recency, 46) / 46
OS_p = 100 × (0.35·V + 0.25·E + 0.30·Fit_p + 0.10·R)
overall_score = max over themes of OS_p        driving_theme = theme with the highest Fit (spec order breaks ties; "none" if all 0)
```

Customers are ranked by overall score (then Value_Score, then CustomerID) and tiered: **A = top 5%, B = next 15%,
C = next 30%, Watch = rest.**

| Tier | Customers | Score range | Addressable balance |
|---|---:|---|---:|
| A | 42,077 | 82.0 - 99.5 | ₹1,721 Cr |
| B | 126,231 | 72.2 - 82.0 | ₹3,718 Cr |
| C | 252,463 | 50.7 - 72.2 | ₹3,513 Cr |
| Watch | 420,772 | 4.4 - 50.7 | ₹43 Cr |

*Addressable balance* = sum of latest balances of customers with at least one signal. It is a size proxy, not revenue.
Every Tier A and B customer has at least one full signal. 75% of Tier A customers have two or more transactions, against
7% of the Watch tier. Tier A is led by Engaged Repeat Users (31,607) and Recent One-Time Spenders (10,470).

### 10.4 Reason text, masking, evidence

`reason` explains the score in words, e.g. `avg balance Rs 593,183 (top 3%), 4 txns, last seen 1 day ago -> Investment / MF interest`.
`masked_id` keeps the first 2 and last 3 characters (`C5841053` → `C5***053`) for anything published.
`evidence_level` (Low/Medium/High) travels with every list.

### 10.5 Sensitivity (FR-031)

Each weight is moved by ±10 points and the weights renormalised; the top 1,000 is compared with the base ranking.
Overlap stays at 84-100% and the Spearman correlation at ≥ 0.99. The ranking is least sensitive to the Fit weight (100%)
and most sensitive to removing recency (83.7%).

---

## 11. Publish and exports

**`06_publish.sql`** builds:

| Table | Grain | Used by |
|---|---|---|
| `agg_daily_city` | date × location | Power BI trend, website trend |
| `agg_hour_weekday` | weekday × hour | heat map |
| `agg_city_summary` | city (UNKNOWN excluded from ranking) | city scorecard, Excel sheet 4 |
| `agg_segment_summary` | segment | Power BI page 2, deck, site |
| `agg_theme_segment` | theme × segment | cross-sell matrix |
| `kpi_reconciliation` | 11 headline KPIs | the reference every tool reconciles to |

**`src/c360/export.py`** writes:

- `data/exports/powerbi/*.csv`: 15 tables for the Power BI model (the three customer-level files total ~440 MB).
- `data/exports/excel/*.csv`: a 19,156-row cube (segment × age × gender × top-25 city × tier × evidence × balance band
  with sums), a customer lookup (top 2,000 priority + top 100 by value), the Tier A list (300), city top 25, KPI
  reference, segment definitions and parameters.
- `docs/data/dashboard.json` (~1.35 MB): a 6,064-row cube (segment × age × gender × city × tier × evidence, 18 measures
  coded as arrays), the daily trend by city, the top 2,000 priority customers with masked IDs, score histogram, segment
  definitions and profile, city summary, DQ, waterfall, sensitivity and reconciliation.

**Data minimisation (spec 26):** the public site and repository hold aggregates and masked IDs only. The raw file and the
customer-level extracts are git-ignored.

---

## 12. The 26 analytical SQL questions

`sql/07_analytical_questions.sql`; answers in `outputs/sql_answers/Qnn.csv` (customer IDs masked); every query runs in
under 1.5 s.

| # | Question | Main SQL features |
|---|---|---|
| Q01 | Clean transactions and distinct customers (reconciled to the waterfall) | aggregates, subquery |
| Q02 | Rejected rows by reason | waterfall table |
| Q03 | Top 100 customers by transaction value | `RANK()` |
| Q04 | Top 100 by average balance | `RANK()` |
| Q05 | Cities with the highest value | `GROUP BY`, `RANK()` |
| Q06 | Cities with most customers and value per customer (≥ 1,000 customers) | `HAVING` |
| Q07 | Share of high-value transactions (≥ P95) | `FILTER` |
| Q08 | Pareto: value share by customer decile | `NTILE(10)`, running `SUM() OVER` |
| Q09 | Average ticket by gender and age group | `UNION ALL`, `percentile_cont` |
| Q10 | Customers by transactions per customer (1, 2, 3+) | `CASE` |
| Q11a/b | Monthly and weekly counts and value | date dimension, running total |
| Q12 | Activity by weekday and time band | |
| Q13 | Declining-activity watchlist (repeat customers) | |
| Q14 | Rank within city (top 3 in top 10 cities) | `RANK() OVER (PARTITION BY city)` |
| Q15 | Balance percentile and decile | `PERCENT_RANK`, `NTILE(10)` |
| Q16 | RFM scores (NTILE shown beside tie-safe CUME_DIST) | `NTILE(5)` |
| Q17 | Customers by balance band | `CASE` |
| Q18 | High balance, low engagement (re-engagement) | threshold join |
| Q19 | Average balance by city tier and top-20 city | subquery |
| Q20 | Highest txn-to-balance ratio | |
| Q21 | Share with missing DOB, gender, location | |
| Q22 | Customers with conflicting attributes | |
| Q23 | Segment size and value | window share |
| Q24 | Signals by theme and segment | `ROLLUP` |
| Q25 | Top 20 Tier A per city (top 5 cities) with driving theme | `ROW_NUMBER() OVER (PARTITION BY)` |
| Q26 | Under-served cities: high Tier A/B share, low engagement | CTE + comparison to averages |

---

## 13. Notebooks and statistics

Notebooks are authored as Python cell lists (`notebooks/build_0N_*.py`, helper `_nb.py`) so they are reproducible.
Interpretations were written **after** the numbers existed and are stored in `notes_0N.json`. Each chart is followed by
*what we found / why it matters / what a manager should do*. Figures are saved to `outputs/figures/` (P0-P17).

| Notebook | Content |
|---|---|
| 01 Data profiling | raw-file profile, spec 7.1 check, coverage chart (P0), CustomerID consistency, decisions table |
| 02 EDA & statistics | P1-P10 (amount, balance, txns per customer, age, gender ticket, top cities, daily trend, hour × weekday, Lorenz, correlation), 4 tests, hypotheses H1-H4 |
| 03 Segmentation | k grid (P11/P12), profile heat map (P13), PCA panels (P14), size vs value (P15), validation, RFM overlay, definitions |
| 04 Opportunity scoring | thresholds, signals, theme × segment (P16), score distribution (P17), tiers, sensitivity, priority preview, Python-vs-SQL reconciliation |

**Statistical tests** (effect sizes reported because with 840K customers every p-value is ~0):

| Test | Question | Effect size | Reading |
|---|---|---|---|
| Mann-Whitney U | avg ticket, men vs women | rank-biserial r = 0.079 | median ₹473 vs ₹560: small |
| Kruskal-Wallis | avg balance across age groups | ε² = 0.062 | medians rise from ₹9,741 (18-24) to ₹54,368 (65+): modest |
| Spearman | balance vs transaction value | ρ = 0.296 | moderate: balance and spend carry different information |
| Chi-square | high-value share by city tier | Cramér's V = 0.052 | 19.8% Tier 1 metro, 18.8% satellite, 15.5% other: weak |
| Chi-square (nb 03) | gender × segment | Cramér's V = 0.065 | segments are not gender-driven |

**Hypotheses:** H1 small group holds a disproportionate share: *supported* (top 10% hold 76.8% of balance, 63.3% of
value). H2 most customers single-transaction, low-ticket: *supported* (84.6%; median ticket ₹460). H3 older customers
hold higher balances: *supported, modest*. H4 metro cities hold more high-value customers: *weakly supported*.

Other findings: Gini of transaction value 0.74; top 1% of customers → 26.9% of value; the base is young (72% aged 18-34);
top 5 cities hold 41.6% of value; weekends run 22% above weekdays; 62.6% of activity falls between 12:00 and 21:00.

---

## 14. Power BI report

Folder `powerbi/`: `KavionLens360.pbip`, `KavionLens360.SemanticModel/` (TMDL), `KavionLens360.Report/` (PBIR JSON),
generated by `powerbi/build_pbip.py`. See also `powerbi/README.md`.

**Model.** 11 tables imported from `data/exports/powerbi/*.csv` through Power Query, with the folder held in the
`DataFolder` parameter. Column types are inferred from the CSVs, with overrides such as `rfm_code` as text.
Relationships:

| From | To | Cardinality / filter |
|---|---|---|
| customer_360.location_key | dim_location.location_key | many:1 |
| customer_segment.customer_id | customer_360.customer_id | 1:1, both directions |
| customer_opportunity.customer_id | customer_360.customer_id | 1:1, both directions |
| customer_segment.segment_id | segment_definition.segment_id | many:1 |
| agg_daily_city.date_key | dim_date.date_key | many:1 |
| agg_daily_city.location_key | dim_location.location_key | many:1 |

**Measures (36, single-line DAX):** Total Customers, Total Txn Value, Total Txns, Avg Txn Value, Avg Balance, Median
Balance, Active Customers, Active Rate, High Value Customers, High Value Share, High Value Value Share, Dormant Customers,
Segment Size %, Segment Value %, Txn Frequency, Avg Recency Days, Avg Engagement Score, Opportunity Count, Cross-Sell Opp
Rate, Addressable Balance, Avg Opp Score, Tier A / Tier B Customers, six theme signal counts, Top City Value, Daily Txns,
Daily Value, SQL Total Customers / Value and two reconciliation-variance measures. Plus a calculated column `score_band`.

**Pages (1280 × 720):** 1 Executive Customer 360 · 2 Customer Segmentation · 3 Cross-Sell Opportunities (with the "signals,
not ownership" banner) · 4 Manager Action (ranked priority table: who, why, what, where, how large; drill-through target
for city) · 5 Data Quality & Reconciliation. Navigation buttons on every page, synced slicers, custom theme in the
project palette, one bookmark.

**Validation.** The report passes Microsoft's `powerbi-report-author validate` (0 errors, 0 warnings) and the model parses
with `TmdlSerializer`. Power BI Desktop opens the project without errors. The model must be refreshed once after opening;
a project with no data cache shows empty visuals until then.

**Gotchas found while generating** (useful if editing by hand): `syncGroup` belongs inside `visual`, not at the root; the
custom theme's `name`, the report's `customTheme.name` and the resource item name must all be the same `*.json` string;
slicers need ≥ 76 px height; page/visual folder names must equal their `name` property; multi-line DAX in TMDL is easy to
mis-indent (kept single-line on purpose).

---

## 15. Excel MIS

`excel/build_mis.py` drives Excel invisibly via COM and writes `docs/downloads/KavionLens360_MIS.xlsx` and `.pdf`.

| Sheet | Contents | Excel features |
|---|---|---|
| README | purpose, data, window, how to refresh | |
| 1 Executive Summary | 6 KPI tiles, reconciliation table (Excel vs SQL, variance, ✓), 5 insights, 3 charts | SUM over tables, XLOOKUP, IF, conditional formatting |
| 2 Customer Analysis | age × gender, balance bands, top 100 customers by value | SUMIFS, COUNTIFS, XLOOKUP calculated columns, data bars |
| 3 Segment Analysis | size, value share, averages, actions; chart | SUMIFS, XLOOKUP |
| 4 Geography | top 25 city scorecard with rank, value per customer, signals, Tier A | RANK.EQ, SUMIFS, colour scale, data bars, chart |
| 5 Cross-Sell | signal counts, theme × segment matrix, tier summary, Tier A list (300) | XLOOKUP, INDEX/MATCH (side by side), IFS contact plan, colour scale |
| 6 Pivot Analysis | segment × age and city × tier PivotTables with three shared slicers | PivotTables, slicers |
| 7 Data Dictionary | source columns and derived features | |
| Data | Power Query tables (`tbl_cube`, `tbl_customer_lookup`, …) | Power Query, named range `AsOfDate` |

**Refresh:** the CSV folder is the Power Query parameter `DataFolder`; queries refresh on open.

**COM gotchas found** (all handled in the code): use the full structured reference `[@[col]]`, not `[@col]`; pass optional
COM arguments positionally (named arguments are silently ignored or rejected); `Range.Offset(r, c)` is mis-resolved under
late binding, so the code uses `Cells(row, col)`; `Worksheets.Add()` always inserts before the active sheet, so sheets are
created in reverse; a pivot data-field caption cannot equal a source column name ("Customers (sum)", not "Customers");
the PDF is exported from the whole workbook with README/Data temporarily hidden, so pages follow tab order.

---

## 16. Executive deck

`deck/build_deck.py` writes `KavionLens360_Executive_Deck.pptx` (native, editable charts and speaker notes) and a PDF via
PowerPoint. Numbers are read from the database at build time.

| # | Slide | Headline |
|---|---|---|
| 1 | Business problem | Managers need a customer view, not a transaction log |
| 2 | Dataset & methodology | Public data, documented rules, every row accounted for |
| 3 | Customer 360 insights | A young, metro-heavy base where the top 10% drive 63% of value |
| 4 | Customer segmentation | Engaged Repeat Users: 15% of customers, 28% of value; a 35% tail adds 4% |
| 5 | Cross-sell opportunities | Signals are prioritised, not guaranteed |
| 6 | Dashboard | A manager can answer five questions on one screen |
| 7 | Key business insights | What we found, why it matters, what to do |
| 8 | Recommended actions | Pilot with Tier A, measure response, refine the rules |

Slide 6 uses a screenshot of the web dashboard's Manager Action view (`deck/assets/`), which mirrors Power BI page 4.
It can be swapped for a Power BI screenshot.

---

## 17. Website (report + dashboard)

Built by `src/c360/site.py` into `docs/` (GitHub Pages serves `main` → `/docs`). Source styles and scripts are in
`site/assets/` and copied on each build.

- **`index.html`, the report.** Every number is read from the database at build time. Sections: problem, data & quality
  (waterfall, scorecard, coverage chart), insights (figures, statistics table), segments, opportunity (tiers, signals,
  robustness), insight-to-action table, limitations, deliverables and code links. Download cards turn active when a file
  exists in `docs/downloads/`.
- **`dashboard.html` + `assets/dashboard.js`, the interactive dashboard.** It loads `data/dashboard.json` and filters the
  cube in the browser. Global filters: segment, age group, gender, city, tier, evidence. Five tabs mirror the Power BI
  pages. Every chart has a Table toggle (accessible view) and hover tooltips. The trend chart responds only to the City
  filter (it is built from `agg_daily_city`) and the score histogram covers all customers; both say so on screen. The
  priority list shows the top 2,000 with masked IDs, filters and paging. The Data Quality tab recomputes totals from the
  cube and reconciles them to SQL.
- **Design:** one validated palette across notebooks, site, Power BI, Excel and deck (categorical slots in fixed order,
  blue ordinal ramp for tiers, reserved status colours). Light and dark themes with a toggle; responsive down to phone
  width; print stylesheet (A4 landscape) used for the report PDF.

---

## 18. Testing and reconciliation

`python -m pytest -v` runs `tests/test_pipeline.py` (23 tests, all passing); `python tests/render_test_log.py` writes
[TEST_LOG.md](TEST_LOG.md) in the spec section 25 format.

| Test | Checks |
|---|---|
| T-01 | staging rows = file rows (1,048,567) |
| T-02 | date parsing incl. `1/1/1800`, `31/2/16`, `nan` |
| T-03 | no DOB before 1920; no age outside 18-90 |
| T-04 | no amount ≤ 0 in the fact; zero amounts logged |
| T-05 | TransactionID unique |
| T-06 | single-transaction customers: NULL volatility, evidence Low |
| T-07 | 5 random customers: features recomputed in pandas from the fact table |
| T-08 | RFM scores 1-5; tied values share a score |
| T-09 | zero/missing balances give no NaN after preprocessing |
| T-10 | fixed-seed re-fit gives identical labels (ARI = 1) |
| T-11 | sensitivity table: 8 scenarios, overlap ≥ 80% |
| T-12 | dashboard data total customers = SQL |
| T-13 | dashboard slice to MUMBAI = SQL for MUMBAI |
| T-14 | Excel cube totals = SQL |
| T-15 | SQL reference = customer table = fact table |
| T-16 | UNKNOWN city excluded from ranking, included in totals |
| extras | waterfall, score ranges, 5 segments ≥ 3%, near-miss Fit rule, ID masking, tier shares, only DQ-04 below threshold |

T-17 and T-18 are user-acceptance tests for a peer (find the top 5 customers in a city and why within 2 minutes; read the
Manager page and state who / why / what / where / how large); templates are in TEST_LOG.md.

**Reconciliation chain:** `kpi_reconciliation` (SQL) is the reference. Notebook 04 compares Python, Excel sheet 1
compares its formulas (XLOOKUP into the SQL table), the website's Data Quality tab compares the cube, and Power BI
page 5 shows variance measures. All variances are 0.

---

## 19. Results

| Metric | Value |
|---|---:|
| Raw rows → clean rows | 1,048,567 → 988,947 |
| Customers | 841,543 |
| Total transaction value | ₹155.5 Cr (₹1,554,774,113) |
| Average transaction | ₹1,572 (median ₹460) |
| Mean / median customer balance | ₹1.15 L / ₹18,461 |
| Active (≤ 15 days) | 37.7% |
| High-value customers | 151,113 (18.0%) |
| Value from top 1% / 10% / 20% | 26.9% / 63.3% / 77.0% |
| Gini (transaction value) | 0.74 |
| Single-transaction customers | 84.6% |
| Segments | 5 (silhouette 0.279, ARI ≥ 0.93) |
| Customers with ≥ 1 signal | 404,161 (48.0%) |
| Tier A | 42,077 customers, ₹1,721 Cr addressable |
| Total addressable balance | ₹8,995 Cr |
| Score robustness | 84-100% top-1,000 overlap under ±10-pt weights |

**Insight → action:**

| Output | Finding | Why it matters | Manager action |
|---|---|---|---|
| Value concentration | top 10% → 63% of value | effort pays off unevenly | named RM coverage for the top decile |
| Segment profiles | Engaged Repeat Users: 15% of customers, 28% of value | different needs per segment | deepen: needs review, cards, investments |
| Lapsed one-time spenders | 26% of customers, 34% of value, not seen 2+ weeks | valuable but going quiet | re-engagement call before any sale |
| Low-value tail | 35% of customers, 4.4% of value | RM time has little return | digital nurture; activation checks |
| Opportunity tiers | Tier A: 42,077 customers, ₹1,721 Cr | limited RM time | work Tier A first, review weekly |
| Geography | top 5 cities hold 42% of value | effort allocation | staff metro hubs; use the city scorecard for smaller cities |

---

## 20. Decisions, assumptions and limitations

**Decisions that differ from the spec** (each was confirmed with the project owner):

1. **Analysis window 1 Aug - 15 Sep 2016** instead of the full file range, because daily coverage ends on 15 Sep. The tail is
   logged, not silently dropped. Day-based rules are scaled: active ≤ 15 (spec 30), dormant > 30 (spec 60), newly observed
   ≤ 15, personal-loan recency ≤ 15, trend = second half vs first half.
2. **CustomerID kept as the key** despite <1% consistency for repeat IDs; reported as DQ-20 and in every deliverable.
3. **Joint K-Means k = 5** instead of the layered design (section 9.2).
4. **Full K-Means** instead of MiniBatchKMeans (stability).
5. **Zero amounts rejected** (validity rule amount > 0).
6. **CUME_DIST quintiles** for RFM instead of NTILE, so ties share a score (NTILE is still shown in Q16).

**Main assumptions [A]:** CustomerID is the analysis key (AS-02, known weak); amounts are absolute (direction unknown);
balance is recorded per transaction; percentile thresholds stand in for bank benchmarks; score weights are judgemental
(stress-tested); missing balance is not zero; age 18-90 is plausible; city is the lowest geography; balance and activity
are value proxies, not profit.

**Limitations:** public 2016 data from one bank; 46-day window (no seasonality, trend or tenure claims); no product
holdings, revenue or campaign outcomes (signals, not recommendations; no lift can be measured); repeat behaviour is weak
evidence; 48% signal rate is broad (credit-card and insurance rules are the first to tighten); clusters describe, they do
not predict.

**Responsible use:** gender and city are never model inputs; age is only a life-stage hint; flags start conversations
and never decide eligibility or credit; published outputs hold aggregates and masked IDs only.

**Version 2 ideas:** product holdings and campaign response → propensity models and measured lift; a longer window and
entity resolution for a reliable customer key; segment-drift monitoring and fairness checks on each refresh; learn the
score weights from outcomes.

---

## 21. How to run, rebuild and change things

### Full run

```bash
pip install -r requirements.txt
cp .env.example .env                      # set PGPASSWORD
docker compose up -d
python run_pipeline.py                    # ~5 minutes
python -m pytest -v && python tests/render_test_log.py
```

Partial runs: `python run_pipeline.py --from 04` (re-run from features onwards), `--from PYTHON`, `--from EXPORT --to SITE`.

### Office deliverables and Power BI (Windows)

```bash
python excel/build_mis.py
python deck/build_deck.py
PYTHONPATH=src python -m c360.report_pdf  # prints docs/index.html to the report PDF
PYTHONPATH=src python -m c360.site        # rebuild the site afterwards so download cards turn active
python powerbi/build_pbip.py              # then open powerbi/KavionLens360.pbip and Refresh
```

Notebooks: `cd notebooks && python build_0N_….py && python -m nbconvert --to notebook --execute --inplace 0N_….ipynb`.

### Where to change the logic

| To change… | Edit | Then re-run |
|---|---|---|
| Analysis window, active/dormant days, trend split | `project_params` insert in `sql/00_schema.sql` (and `WINDOW_*` in `src/c360/config.py`) | full pipeline |
| Cleaning / reject rules | `sql/02_clean.sql` | from `00` |
| Location mappings | `sql/01_location_map.sql` | full pipeline |
| City tiers | `dim_location` CASE in `sql/03_model.sql` | from `03` |
| Features, scores, BR flags, thresholds | `sql/04_customer_360.sql` | from `04` |
| DQ checks / thresholds | `sql/05_dq_checks.sql` | from `05` |
| Clustering features or k | `src/c360/segmentation.py` (`Prep`, `FEATURES`), `config/segments.json` (`k`, `design`) | re-evaluate k (notebook 03 / `evaluate_k`), then from `PYTHON` |
| Segment names / actions | `config/segments.json` (keep the `expect` rules true) | from `PYTHON` |
| Signal rules, weights, tiers | `src/c360/opportunity.py` (`compute_fits`, `BASE_WEIGHTS`, `TIER_CUTS`) | from `PYTHON` |
| Aggregates for BI | `sql/06_publish.sql`, `src/c360/export.py` | from `06` |
| Power BI measures/pages | `powerbi/build_pbip.py` (`MEASURES`, `build_report`) | regenerate, validate, open, refresh |
| Website text/layout | `src/c360/site.py`, `site/assets/*` | `SITE` |

After any logic change: re-run the tests, check `dq_log` and `kpi_reconciliation`, and update the notebook
interpretations (`notes_0N.json`) if the numbers moved.

---

## 22. Troubleshooting notes

| Symptom | Cause / fix |
|---|---|
| `could not resize shared memory segment … No space left on device` | Docker `/dev/shm` too small: keep `shm_size: 1gb` in `docker-compose.yml` |
| `relation "project_params" does not exist` | run from step `00` after schema changes |
| Silhouette run fails with `ArrayMemoryError` | `segmentation.py` sets `working_memory=256`; don't run many evaluations in parallel |
| Segment run raises "profiles no longer match their names" | the cluster structure changed; review profiles and update `config/segments.json` |
| Excel COM errors `0x800A03EC` / `DISP_E_PARAMNOTOPTIONAL` | see the COM gotchas in section 15 |
| Excel left running in the background after a crash | kill windowless `EXCEL.EXE` processes before re-running |
| Garbled characters (`Â·`) after editing a file with Python on Windows | always read/write with `encoding="utf-8"` (Windows defaults to cp1252) |
| Power BI shows empty visuals | Home → Refresh; check the `DataFolder` parameter |
| Site download card says "coming soon" | the file is missing in `docs/downloads/`; add it and rebuild the site |

---

## 23. Glossary

| Term | Meaning here |
|---|---|
| Customer 360 | one analytical row per customer combining profile and behaviour (`customer_360`) |
| Analysis window | 1 Aug - 15 Sep 2016 (46 days); as-of date 16 Sep 2016 |
| Active / dormant | seen in the last 15 days / not seen for more than 30 days (observed in the data, not account status) |
| Evidence level | Low = 1 transaction, Medium = 2, High = 3+ |
| RFM | recency, frequency, monetary scores (1-5) |
| Value_Score / Engagement_Score | 0-100 composite scores (section 7.2) |
| Signal | rule-based indication of possible product interest; not a recommendation |
| Fit | how fully a customer meets a signal rule (1, 0.5, 0) |
| Opportunity score | 100 × (0.35 V + 0.25 E + 0.30 Fit + 0.10 R), max over themes |
| Tier | A top 5%, B next 15%, C next 30%, Watch rest |
| Addressable balance | sum of latest balances of customers with at least one signal (size proxy, not revenue) |
| Silhouette | cluster separation quality (−1 to 1) |
| ARI | adjusted Rand index; agreement between two clusterings (1 = identical) |
| ε², Cramér's V, rank-biserial r | effect sizes for Kruskal-Wallis, chi-square and Mann-Whitney |
| PBIP / TMDL / PBIR | Power BI Project format; text model definition; text report definition |
| Masked ID | first 2 + last 3 characters of CustomerID (`C5***053`) |

"""
Spec section 25 tests (T-01 .. T-16) plus unit tests. Run after `python run_pipeline.py`:

    python -m pytest -v
"""
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from c360 import db, opportunity  # noqa: E402
from c360.config import RAW_MEMBER, RAW_ZIP  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="session")
def kpi():
    return db.query("SELECT kpi, sql_value::float AS v FROM kpi_reconciliation").set_index("kpi")["v"]


# --------------------------------------------------------------------------- load and cleaning
def test_T01_staging_rows_equal_file_rows():
    """FR-001: staging row count equals the number of data rows in the source file."""
    with zipfile.ZipFile(RAW_ZIP) as zf, zf.open(RAW_MEMBER) as f:
        file_rows = sum(1 for _ in io.TextIOWrapper(f, encoding="utf-8")) - 1
    assert db.scalar("SELECT COUNT(*) FROM stg_bank_transactions") == file_rows == 1_048_567


def test_T02_date_parsing_and_placeholders():
    """FR-003: d/m/yy parses; invalid dates return NULL; the 1/1/1800 placeholder parses to year 1800 (then flagged)."""
    r = db.query("""SELECT f_parse_dmy('2/8/16', 99) AS txn, f_parse_dmy('10/1/94', 16) AS dob,
                           f_parse_dmy('1/1/1800', 16) AS placeholder, f_parse_dmy('31/2/16', 99) AS bad,
                           f_parse_dmy('nan', 16) AS nan_text""").iloc[0]
    assert str(r.txn) == "2016-08-02" and str(r.dob) == "1994-01-10"
    assert str(r.placeholder) == "1800-01-01" and r.bad is None and r.nan_text is None


def test_T03_placeholder_and_future_dob_give_null_age():
    """FR-007/008: no customer keeps a DOB before 1920 or an age outside 18-90."""
    r = db.query("""SELECT COUNT(*) FILTER (WHERE dob < DATE '1920-01-01') AS old_dob,
                           COUNT(*) FILTER (WHERE age IS NOT NULL AND age NOT BETWEEN 18 AND 90) AS bad_age
                    FROM dim_customer""").iloc[0]
    assert r.old_dob == 0 and r.bad_age == 0


def test_T04_non_positive_amounts_rejected_with_reason():
    """FR-009: amounts <= 0 never reach the fact table and are logged with a reason."""
    assert db.scalar("SELECT COUNT(*) FROM fact_transaction WHERE amount <= 0") == 0
    assert db.scalar("SELECT COUNT(*) FROM rejected_rows WHERE reject_reason = 'ZERO_AMOUNT'") > 0


def test_T05_transaction_id_unique():
    """FR-011: one row per TransactionID after cleaning."""
    r = db.query("SELECT COUNT(*) AS n, COUNT(DISTINCT transaction_id) AS d FROM fact_transaction").iloc[0]
    assert r.n == r.d


def test_waterfall_reconciles():
    """FR-012: raw - rejected = clean, to the unit."""
    wf = db.query("SELECT step_no, rows FROM row_waterfall")
    assert wf.loc[wf.step_no < 99, "rows"].sum() == wf.loc[wf.step_no == 99, "rows"].iloc[0]


# --------------------------------------------------------------------------- features
def test_T06_single_transaction_customer_features():
    """FR-017: single-transaction customers have count 1, NULL volatility, evidence Low."""
    r = db.query("""SELECT COUNT(*) FILTER (WHERE balance_volatility IS NOT NULL) AS vol,
                           COUNT(*) FILTER (WHERE evidence_level <> 'Low') AS ev
                    FROM customer_360 WHERE txn_count = 1""").iloc[0]
    assert r.vol == 0 and r.ev == 0


def test_T07_features_match_hand_calculation():
    """FR-017: five random customers, features recomputed from the fact table in pandas."""
    ids = db.query("SELECT customer_id FROM customer_360 WHERE txn_count >= 2 ORDER BY md5(customer_id) LIMIT 5")["customer_id"].tolist()
    f = db.query("SELECT customer_id, txn_date, amount::float, balance::float, order_key FROM fact_transaction "
                 "WHERE customer_id = ANY(:ids)", {"ids": ids})
    c = db.query("SELECT * FROM customer_360 WHERE customer_id = ANY(:ids)", {"ids": ids}).set_index("customer_id")
    for cid, g in f.groupby("customer_id"):
        row = c.loc[cid]
        assert row.txn_count == len(g)
        assert float(row.total_txn_value) == pytest.approx(g.amount.sum())
        assert float(row.max_txn_value) == pytest.approx(g.amount.max())
        assert row.active_days == g.txn_date.nunique()
        assert row.recency_days == (pd.Timestamp("2016-09-16") - pd.Timestamp(g.txn_date.max())).days
        latest = g.dropna(subset=["balance"]).sort_values("order_key").balance.iloc[-1]
        assert float(row.latest_balance) == pytest.approx(latest)


def test_T08_rfm_ties_get_equal_scores():
    """FR-018: scores are 1-5 and tied values share one score."""
    r = db.query("""SELECT MIN(m_score) mn, MAX(m_score) mx,
                           (SELECT COUNT(*) FROM (SELECT total_txn_value FROM customer_360
                            GROUP BY total_txn_value HAVING COUNT(DISTINCT m_score) > 1) t) AS split_ties
                    FROM customer_360""").iloc[0]
    assert r.mn == 1 and r.mx == 5 and r.split_ties == 0


def test_scores_in_range():
    """FR-019/020: engagement and value scores stay within 0-100."""
    r = db.query("SELECT MIN(engagement_score) a, MAX(engagement_score) b, MIN(value_score) c, MAX(value_score) d FROM customer_360").iloc[0]
    assert 0 <= r.a <= r.b <= 100 and 0 <= r.c <= r.d <= 100


# --------------------------------------------------------------------------- segmentation
def test_T09_zero_balance_scaling_has_no_nan():
    """FR-024: log1p handles zero balances; the clustering matrix has no NaN or inf."""
    from c360.segmentation import Prep
    d = db.query("SELECT avg_balance::float, total_txn_value::float, avg_txn_value::float, txn_count, recency_days, age "
                 "FROM customer_360 WHERE latest_balance < 1 OR avg_balance IS NULL LIMIT 5000")
    assert len(d) > 0
    X = Prep().fit_transform(d)
    assert np.isfinite(X).all()


def test_T10_fixed_seed_rerun_gives_same_labels():
    """FR-026: two fits with the fixed seed on the same data give identical labels (ARI = 1)."""
    from sklearn.metrics import adjusted_rand_score
    from c360.segmentation import Prep, fit_clusters
    d = db.query("SELECT avg_balance::float, total_txn_value::float, avg_txn_value::float, txn_count, recency_days, "
                 "value_score::float, age FROM customer_360 ORDER BY md5(customer_id) LIMIT 60000")
    X = Prep().fit_transform(d)
    assert adjusted_rand_score(fit_clusters(X, 5, d), fit_clusters(X, 5, d)) == 1.0


def test_segments_valid():
    """FR-027/028: every customer has one named segment; each segment >= 3% of customers."""
    r = db.query("SELECT segment_name, COUNT(*) n FROM customer_segment GROUP BY 1")
    assert r["segment_name"].notna().all() and len(r) == 5
    assert (r["n"] / r["n"].sum()).min() >= 0.03
    assert db.scalar("SELECT COUNT(*) FROM customer_segment") == db.scalar("SELECT COUNT(*) FROM customer_360")


# --------------------------------------------------------------------------- opportunity
def test_fit_rule_near_miss():
    """Spec 13.3: Fit = 1 if all met; 0.5 if one percentile condition missed by <= 10 points; else 0."""
    met = pd.Series([True, True, False, False])
    pr = pd.Series([0.80, 0.80, 0.70, 0.50])                 # condition "pct >= 0.75"
    cond = opportunity._pct_cond(pr, 0.75)
    fit = opportunity._fit([cond, (met, None)])
    assert fit.tolist() == [1.0, 1.0, 0.0, 0.0]               # rows 3-4 miss two conditions
    fit2 = opportunity._fit([cond])
    assert fit2.tolist() == [1.0, 1.0, 0.5, 0.0]


def test_mask_id():
    assert opportunity.mask_id("C5841053") == "C5***053"


def test_T11_weight_sensitivity_reported():
    """FR-031: +-10 point weight changes are reported and the top-1,000 is stable."""
    s = db.query("SELECT * FROM opportunity_sensitivity")
    assert len(s) == 8 and s["top1000_overlap_pct"].min() >= 80


def test_tiers_follow_design():
    """FR-030: tier shares 5 / 15 / 30 / 50 %."""
    t = db.query("SELECT tier, COUNT(*)::float / SUM(COUNT(*)) OVER () AS share FROM customer_opportunity GROUP BY tier").set_index("tier")["share"]
    for tier, share in {"A": 0.05, "B": 0.15, "C": 0.30, "Watch": 0.50}.items():
        assert t[tier] == pytest.approx(share, abs=0.001)


# --------------------------------------------------------------------------- reconciliation (BI, Excel, site)
def test_T12_dashboard_total_customers_equals_sql(kpi):
    """FR-034: the published dashboard data reconciles to SQL."""
    d = json.loads((ROOT / "docs" / "data" / "dashboard.json").read_text(encoding="utf-8"))
    i = len(d["cube"]["dims"]) + d["cube"]["measures"].index("customers")
    assert sum(r[i] for r in d["cube"]["rows"]) == kpi["Total Customers"]


def test_T13_single_city_slice_matches_sql():
    """FR-034: slicing the cube to one city matches SQL for that city."""
    d = json.loads((ROOT / "docs" / "data" / "dashboard.json").read_text(encoding="utf-8"))
    ci = list(d["cube"]["dims"]).index("city")
    mi = len(d["cube"]["dims"]) + d["cube"]["measures"].index("customers")
    city = d["cube"]["dims"]["city"].index("MUMBAI")
    cube_n = sum(r[mi] for r in d["cube"]["rows"] if r[ci] == city)
    assert cube_n == db.scalar("SELECT COUNT(*) FROM customer_360 WHERE clean_city = 'MUMBAI'")


def test_T14_excel_extract_totals_equal_sql(kpi):
    """FR-036: the Excel cube (SUMIFS source) reconciles to SQL."""
    cube = pd.read_csv(ROOT / "data" / "exports" / "excel" / "cube.csv")
    assert cube["customers"].sum() == kpi["Total Customers"]
    assert cube["txns"].sum() == kpi["Total Transactions"]
    assert cube["value"].sum() == pytest.approx(kpi["Total Txn Value"], abs=1.0)


def test_T15_end_to_end_reconciliation(kpi):
    """FR-038: SQL reference = customer table = fact table, variance 0."""
    r = db.query("SELECT COUNT(*) AS c, SUM(txn_count) AS t, SUM(total_txn_value)::float AS v FROM customer_360").iloc[0]
    f = db.query("SELECT COUNT(DISTINCT customer_id) AS c, COUNT(*) AS t, SUM(amount)::float AS v FROM fact_transaction").iloc[0]
    assert r.c == f.c == kpi["Total Customers"]
    assert r.t == f.t == kpi["Total Transactions"]
    assert r.v == pytest.approx(f.v) and r.v == pytest.approx(kpi["Total Txn Value"])


def test_T16_unknown_city_excluded_from_rank_included_in_totals():
    """Edge case: UNKNOWN city is not ranked but still counted in totals."""
    assert db.scalar("SELECT COUNT(*) FROM agg_city_summary WHERE clean_city = 'UNKNOWN'") == 0
    ranked = db.scalar("SELECT SUM(customers) FROM agg_city_summary")
    unknown = db.scalar("SELECT COUNT(*) FROM customer_360 WHERE clean_city = 'UNKNOWN'")
    assert ranked + unknown == db.scalar("SELECT COUNT(*) FROM customer_360")


def test_dq_thresholds_met_or_documented():
    """FR-039: only documented exceptions (DQ-04 placeholder DOB) fall below threshold."""
    exc = db.query("SELECT check_id FROM dq_log WHERE status = 'EXCEPTION'")["check_id"].tolist()
    assert exc == ["DQ-04"]

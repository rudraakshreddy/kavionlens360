"""
Publish step: write extracts for Power BI / Excel (data/exports) and the JSON
that feeds the GitHub Pages report and dashboard (docs/data).

Data minimisation (spec 26): the public site gets aggregates plus a masked
top-N priority list only; customer-level extracts stay local (git-ignored).
"""
import json
from datetime import datetime

import numpy as np
import pandas as pd

from . import db
from .config import EXPORT_DIR, OUTPUT_DIR, SITE_DIR

PBI_DIR = EXPORT_DIR / "powerbi"
SITE_DATA = SITE_DIR / "data"
TOP_CITIES = 25
PRIORITY_N = 2000

AGE_ORDER = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+", "Unknown"]
TIER_ORDER = ["A", "B", "C", "Watch"]
EVIDENCE_ORDER = ["High", "Medium", "Low"]
THEMES = ["investment", "premium", "credit_card", "insurance", "personal_loan", "reengagement"]
THEME_NAMES = ["Investment / MF", "Premium account", "Credit card", "Insurance",
               "Personal loan (demand)", "Re-engagement"]


# --------------------------------------------------------------------------- Power BI / Excel
def export_powerbi():
    PBI_DIR.mkdir(parents=True, exist_ok=True)
    tables = {
        "dim_date": "SELECT * FROM dim_date ORDER BY date_key",
        "dim_location": "SELECT * FROM dim_location ORDER BY location_key",
        "customer_360": """SELECT customer_id, location_key, age, age_group, gender, clean_city, city_tier,
                                  txn_count, total_txn_value, avg_txn_value, max_txn_value, active_days,
                                  first_txn_date, last_txn_date, monthly_txn_frequency, recency_days,
                                  avg_balance, latest_balance, balance_volatility, txn_to_balance_ratio,
                                  activity_trend, value_score, engagement_score, r_score, f_score, m_score,
                                  rfm_code, freq_band, evidence_level, is_active, is_high_value,
                                  is_low_engagement, is_newly_observed, is_dormant
                           FROM customer_360""",
        "customer_segment": """SELECT customer_id, segment_id, segment_name, layer, cluster_key, method, run_id
                               FROM customer_segment""",
        "customer_opportunity": """SELECT customer_id, masked_id, sig_investment, sig_premium, sig_credit_card,
                                          sig_insurance, sig_personal_loan, sig_reengagement, signal_count,
                                          any_signal, overall_score, driving_theme, driving_theme_label,
                                          priority_rank, tier, reason
                                   FROM customer_opportunity""",
        "segment_definition": "SELECT * FROM segment_definition ORDER BY segment_id",
        "agg_daily_city": "SELECT * FROM agg_daily_city",
        "agg_hour_weekday": "SELECT * FROM agg_hour_weekday",
        "agg_city_summary": "SELECT * FROM agg_city_summary ORDER BY value_rank",
        "agg_segment_summary": "SELECT * FROM agg_segment_summary ORDER BY segment_id",
        "agg_theme_segment": "SELECT * FROM agg_theme_segment ORDER BY segment_id, theme",
        "kpi_reconciliation": "SELECT * FROM kpi_reconciliation",
        "dq_log": "SELECT check_id, dimension, rule, checked_rows, failed_rows, pass_pct, threshold_pct, status, note FROM dq_log ORDER BY check_id",
        "row_waterfall": "SELECT * FROM row_waterfall ORDER BY step_no",
        "opportunity_sensitivity": "SELECT * FROM opportunity_sensitivity",
    }
    counts = {}
    for name, sql in tables.items():
        df = db.query(sql)
        df.to_csv(PBI_DIR / f"{name}.csv", index=False)
        counts[name] = len(df)
    return counts


# --------------------------------------------------------------------------- web data
def _num(x, nd=2):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(float(x), nd)


def build_cube(c: pd.DataFrame) -> dict:
    """Pre-aggregated cube for client-side slicers (segment, age, gender, city, tier, evidence)."""
    top = (c[c.clean_city != "UNKNOWN"].groupby("clean_city")["total_txn_value"].sum()
           .sort_values(ascending=False).head(TOP_CITIES).index.tolist())
    c = c.assign(city=np.where(c.clean_city.isin(top), c.clean_city,
                               np.where(c.clean_city == "UNKNOWN", "Unknown", "Other cities")))
    seg_order = (c[["segment_id", "segment_name"]].drop_duplicates().sort_values("segment_id")["segment_name"].tolist())
    dims = {
        "segment": seg_order, "age_group": AGE_ORDER, "gender": ["F", "M", "Unknown"],
        "city": top + ["Other cities", "Unknown"], "tier": TIER_ORDER, "evidence": EVIDENCE_ORDER,
    }
    keys = ["segment_name", "age_group", "gender", "city", "tier", "evidence_level"]
    for k in THEMES:
        c[f"sig_{k}"] = c[f"sig_{k}"].astype(int)
    agg = c.groupby(keys, observed=True).agg(
        customers=("customer_id", "size"), txns=("txn_count", "sum"), value=("total_txn_value", "sum"),
        bal_sum=("avg_balance", "sum"), bal_n=("avg_balance", "count"),
        latest_bal=("latest_balance", "sum"), active=("is_active", "sum"), high_value=("is_high_value", "sum"),
        dormant=("is_dormant", "sum"), any_signal=("any_signal", "sum"),
        addressable=("addressable", "sum"), score_sum=("overall_score", "sum"),
        **{f"sig_{k}": (f"sig_{k}", "sum") for k in THEMES},
    ).reset_index()
    idx = {k: {v: i for i, v in enumerate(vals)} for k, vals in dims.items()}
    dim_cols = list(zip(keys, dims.keys()))
    rows = []
    for r in agg.itertuples(index=False):
        d = r._asdict()
        coded = [idx[dname][d[col]] for col, dname in dim_cols]
        meas = [int(d["customers"]), int(d["txns"]), round(float(d["value"]), 2), round(float(d["bal_sum"]), 2),
                int(d["bal_n"]), round(float(d["latest_bal"]), 2), int(d["active"]), int(d["high_value"]),
                int(d["dormant"]), int(d["any_signal"]), round(float(d["addressable"]), 2), round(float(d["score_sum"]), 3)]
        meas += [int(d[f"sig_{k}"]) for k in THEMES]
        rows.append(coded + meas)
    return {
        "dims": dims,
        "measures": ["customers", "txns", "value", "bal_sum", "bal_n", "latest_bal", "active", "high_value",
                     "dormant", "any_signal", "addressable", "score_sum"] + [f"sig_{k}" for k in THEMES],
        "themes": dict(zip(THEMES, THEME_NAMES)),
        "rows": rows,
    }


def export_site():
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    pp = db.query("SELECT * FROM project_params").iloc[0]
    c = db.query("""
        SELECT c.customer_id, c.age_group, c.gender, c.clean_city, c.city_tier, c.txn_count,
               c.total_txn_value::float, c.avg_balance::float, c.latest_balance::float, c.is_active, c.is_high_value,
               c.is_dormant, c.evidence_level, s.segment_id, s.segment_name, o.tier, o.any_signal,
               o.overall_score::float, o.sig_investment, o.sig_premium, o.sig_credit_card, o.sig_insurance,
               o.sig_personal_loan, o.sig_reengagement,
               CASE WHEN o.any_signal THEN c.latest_balance::float ELSE 0 END AS addressable
        FROM customer_360 c JOIN customer_segment s USING (customer_id) JOIN customer_opportunity o USING (customer_id)
    """)
    c["addressable"] = c["addressable"].fillna(0)
    cube = build_cube(c)

    top_cities = cube["dims"]["city"][:TOP_CITIES]
    daily = db.query("""
        SELECT d.date::text AS date, l.clean_city, SUM(a.txns) AS txns, SUM(a.total_value)::float AS value
        FROM agg_daily_city a JOIN dim_date d USING (date_key) JOIN dim_location l USING (location_key)
        GROUP BY d.date, l.clean_city
    """)
    daily["city"] = np.where(daily.clean_city.isin(top_cities), daily.clean_city,
                             np.where(daily.clean_city == "UNKNOWN", "Unknown", "Other cities"))
    daily = daily.groupby(["date", "city"], as_index=False)[["txns", "value"]].sum()
    dates = sorted(daily["date"].unique())
    trend = {city: {"txns": g.set_index("date").reindex(dates)["txns"].fillna(0).astype(int).tolist(),
                    "value": g.set_index("date").reindex(dates)["value"].fillna(0).round(0).tolist()}
             for city, g in daily.groupby("city")}

    pr = db.query(f"""
        SELECT o.priority_rank, o.masked_id, o.tier, ROUND(o.overall_score::numeric, 1)::float AS score,
               o.driving_theme_label AS theme, o.reason, c.clean_city AS city, s.segment_name AS segment,
               c.evidence_level AS evidence, c.age_group, c.gender,
               ROUND(c.latest_balance::numeric, 0)::float AS latest_balance, c.txn_count, c.recency_days
        FROM customer_opportunity o JOIN customer_360 c USING (customer_id) JOIN customer_segment s USING (customer_id)
        WHERE o.priority_rank <= {PRIORITY_N}
        ORDER BY o.priority_rank
    """)
    hist = db.query("""
        SELECT tier, width_bucket(overall_score, 0, 100, 40) AS bin, COUNT(*) AS n
        FROM customer_opportunity GROUP BY tier, bin ORDER BY bin
    """)
    seg_def = db.query("SELECT * FROM segment_definition ORDER BY segment_id")
    seg_sum = db.query("SELECT * FROM agg_segment_summary ORDER BY segment_id")
    seg_prof = db.query("SELECT * FROM segment_profile")
    theme_seg = db.query("SELECT segment_name, theme, flagged_customers, addressable_balance::float FROM agg_theme_segment")
    city_sum = db.query("SELECT * FROM agg_city_summary ORDER BY value_rank LIMIT 50")
    dq = db.query("SELECT check_id, dimension, rule, checked_rows, failed_rows, pass_pct::float, threshold_pct::float, status, note FROM dq_log ORDER BY check_id")
    wf = db.query("SELECT * FROM row_waterfall ORDER BY step_no")
    kpi = db.query("SELECT kpi, sql_value::float FROM kpi_reconciliation")
    sens = db.query("SELECT * FROM opportunity_sensitivity")
    hw = db.query("SELECT day_of_week_num, day_of_week, txn_hour, txns FROM agg_hour_weekday ORDER BY 1, 3")

    def records(df):
        return json.loads(df.to_json(orient="records", double_precision=4))

    payload = {
        "meta": {
            "project": "KavionLens360", "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "window_start": str(pp.window_start), "window_end": str(pp.window_end), "as_of": str(pp.as_of_date),
            "window_days": int(pp.window_days), "source": "Kaggle 'Bank Customer Segmentation (1M+ Transactions)', public data from an Indian bank, 2016. Not ICICI data.",
        },
        "kpi_reconciliation": records(kpi),
        "cube": cube,
        "trend": {"dates": dates, "series": trend},
        "priority": records(pr),
        "score_hist": records(hist),
        "segments": {"definition": records(seg_def), "summary": records(seg_sum), "profile": records(seg_prof)},
        "theme_segment": records(theme_seg),
        "cities": records(city_sum),
        "hour_weekday": records(hw),
        "dq": records(dq), "waterfall": records(wf), "sensitivity": records(sens),
    }
    (SITE_DATA / "dashboard.json").write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return {"cube_rows": len(cube["rows"]), "priority_rows": len(pr),
            "bytes": (SITE_DATA / "dashboard.json").stat().st_size}


def run():
    counts = export_powerbi()
    site = export_site()
    (OUTPUT_DIR / "export_log.json").write_text(json.dumps({"powerbi": counts, "site": site}, indent=2), encoding="utf-8")
    return counts, site


if __name__ == "__main__":
    print(run())

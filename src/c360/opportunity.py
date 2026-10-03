"""
Cross-sell opportunity signals, scores and priority tiers (spec 13; FR-029..032).

Signals are *Analytical Opportunity Signals* inferred from behaviour. Product
holdings are not in the data, so nothing here is a recommendation, an
eligibility check or a credit decision (spec 6, 26).
"""
import numpy as np
import pandas as pd

from . import db
from .config import WINDOW_DAYS

THEMES = ["investment", "premium", "credit_card", "insurance", "personal_loan", "reengagement"]
THEME_LABELS = {
    "investment": "Investment / MF interest",
    "premium": "Premium account interest",
    "credit_card": "Credit card interest",
    "insurance": "Insurance interest",
    "personal_loan": "Personal loan interest (demand signal only)",
    "reengagement": "Re-engagement (service)",
}
BASE_WEIGHTS = {"V": 0.35, "E": 0.25, "Fit": 0.30, "R": 0.10}
NEAR_MISS = 0.10            # one percentile condition missed by <= 10 points -> Fit 0.5
ACTIVE_RECENCY = 15         # spec's "Recency <= 30" scaled to the 46-day window [A]
TIER_CUTS = [("A", 0.05), ("B", 0.20), ("C", 0.50)]   # cumulative shares; rest = Watch


def load_customers() -> pd.DataFrame:
    return db.query("""
        SELECT customer_id, age, age_known, clean_city, txn_count, total_txn_value, avg_balance,
               latest_balance, recency_days, engagement_score, value_score, txn_to_balance_ratio,
               evidence_level
        FROM customer_360
    """)


def percentile_ranks(df: pd.DataFrame) -> pd.DataFrame:
    """Percentile rank (0-1) of each threshold variable within the clean customer base (AS-07)."""
    pr = pd.DataFrame(index=df.index)
    for col in ["avg_balance", "total_txn_value", "engagement_score", "txn_to_balance_ratio"]:
        pr[col] = df[col].rank(pct=True, method="max")      # NaN stays NaN -> condition fails
    return pr


def _fit(conds: list) -> pd.Series:
    """
    conds: list of (met: bool Series, gap: float Series or None).
    gap = percentile points by which a percentile condition is missed (NaN if not
    a percentile condition). Fit = 1 if all met; 0.5 if exactly one missed and that
    one is a percentile condition missed by <= NEAR_MISS; else 0.
    """
    met = pd.concat([c[0].fillna(False) for c in conds], axis=1)
    n_missed = (~met).sum(axis=1)
    near = pd.Series(False, index=met.index)
    for i, (_, gap) in enumerate(conds):
        if gap is not None:
            near |= (~met.iloc[:, i]) & (gap <= NEAR_MISS)
    fit = np.where(n_missed == 0, 1.0, np.where((n_missed == 1) & near, 0.5, 0.0))
    return pd.Series(fit, index=met.index)


def _pct_cond(pr: pd.Series, p: float):
    """'variable >= P(p)' expressed on percentile ranks, with its miss gap."""
    return pr >= p, (p - pr).where(pr < p)


def compute_fits(df: pd.DataFrame, pr: pd.DataFrame) -> pd.DataFrame:
    age = df["age"]
    age_ok = lambda lo, hi: (age.between(lo, hi) & df["age_known"].fillna(False), None)  # noqa: E731
    # Investment: Avg_Balance >= P75 AND (Txn_Count >= 2 OR Total_Txn_Value >= P60)
    inv_alt = (df["txn_count"] >= 2) | (pr["total_txn_value"] >= 0.60)
    inv_gap = (0.60 - pr["total_txn_value"]).where(~inv_alt)
    fits = pd.DataFrame({
        "investment": _fit([_pct_cond(pr["avg_balance"], 0.75), (inv_alt, inv_gap)]),
        "premium": _fit([_pct_cond(pr["avg_balance"], 0.90)]),
        "credit_card": _fit([_pct_cond(pr["total_txn_value"], 0.60),
                             _pct_cond(pr["avg_balance"], 0.40), age_ok(21, 60)]),
        "insurance": _fit([age_ok(30, 55), _pct_cond(pr["avg_balance"], 0.50)]),
        "personal_loan": _fit([age_ok(25, 45), _pct_cond(pr["txn_to_balance_ratio"], 0.75),
                               (df["recency_days"] <= ACTIVE_RECENCY, None)]),
        # Re-engagement: Engagement_Score < P25 AND Avg_Balance >= P50
        "reengagement": _fit([(pr["engagement_score"] < 0.25,
                               (pr["engagement_score"] - 0.25 + 1e-9).where(pr["engagement_score"] >= 0.25)),
                              _pct_cond(pr["avg_balance"], 0.50)]),
    })
    return fits


def score(df: pd.DataFrame, fits: pd.DataFrame, w=BASE_WEIGHTS) -> pd.DataFrame:
    """OS_p = 100 x (wV*V + wE*E + wFit*Fit_p + wR*R); overall = max over themes."""
    V = df["value_score"].astype(float) / 100
    E = df["engagement_score"].astype(float) / 100
    R = 1 - df["recency_days"].clip(upper=WINDOW_DAYS) / WINDOW_DAYS
    common = w["V"] * V + w["E"] * E + w["R"] * R
    os_ = pd.DataFrame({t: 100 * (common + w["Fit"] * fits[t]) for t in THEMES})
    out = pd.DataFrame(index=df.index)
    out["overall_score"] = os_.max(axis=1)
    # driving theme = highest Fit (ties -> spec order); none if no theme fits at all
    best = fits[THEMES].values.argmax(axis=1)
    out["driving_theme"] = np.where(fits[THEMES].max(axis=1) > 0, np.array(THEMES)[best], "none")
    return out, os_


def assign_tiers(df: pd.DataFrame, overall: pd.Series) -> tuple:
    order = pd.DataFrame({"s": overall, "v": df["value_score"].astype(float), "id": df["customer_id"]})
    order = order.sort_values(["s", "v", "id"], ascending=[False, False, True])
    rank = pd.Series(np.arange(1, len(order) + 1), index=order.index).reindex(df.index)
    share = rank / len(df)
    tier = pd.Series("Watch", index=df.index)
    for name, cut in reversed(TIER_CUTS):
        tier[share <= cut] = name
    return rank, tier


def reason_text(df: pd.DataFrame, pr: pd.DataFrame, theme: pd.Series) -> pd.Series:
    """Page-4 'Why?' column: the driver features in plain words."""
    bal_top = (100 * (1 - pr["avg_balance"])).clip(lower=1).round(0)
    bal = df["avg_balance"].map(lambda x: "balance unknown" if pd.isna(x) else f"avg balance Rs {x:,.0f}")
    txns = df["txn_count"].map(lambda n: f"{n} txn" + ("s" if n != 1 else ""))
    seen = df["recency_days"].map(lambda d: f"last seen {d} day" + ("s" if d != 1 else "") + " ago")
    top = bal_top.map(lambda t: "" if pd.isna(t) else f" (top {t:.0f}%)")
    label = theme.map(lambda t: THEME_LABELS.get(t, "No rule fully met"))
    return bal + top + ", " + txns + ", " + seen + " -> " + label


def mask_id(cid: str) -> str:
    return cid[:2] + "***" + cid[-3:]


def sensitivity(df, fits, base_rank, top_n=1000) -> pd.DataFrame:
    """FR-031 / T-11: shift each weight by +-10 points (renormalised) and compare the top-N."""
    base_top = set(df.loc[base_rank <= top_n, "customer_id"])
    rows = []
    for k in BASE_WEIGHTS:
        for delta in (+0.10, -0.10):
            w = dict(BASE_WEIGHTS)
            w[k] = max(w[k] + delta, 0.0)
            tot = sum(w.values())
            w = {kk: vv / tot for kk, vv in w.items()}
            s, _ = score(df, fits, w)
            r, t = assign_tiers(df, s["overall_score"])
            top = set(df.loc[r <= top_n, "customer_id"])
            rows.append({
                "scenario": f"{k} {'+' if delta > 0 else '-'}10 pts",
                **{f"w_{kk}": round(vv, 3) for kk, vv in w.items()},
                f"top{top_n}_overlap_pct": round(100 * len(top & base_top) / top_n, 1),
                "spearman_vs_base": round(pd.Series(r).corr(pd.Series(base_rank), method="spearman"), 4),
            })
    return pd.DataFrame(rows)


def build(df: pd.DataFrame | None = None):
    df = load_customers() if df is None else df
    pr = percentile_ranks(df)
    fits = compute_fits(df, pr)
    s, os_ = score(df, fits)
    rank, tier = assign_tiers(df, s["overall_score"])
    out = pd.DataFrame({"customer_id": df["customer_id"], "masked_id": df["customer_id"].map(mask_id)})
    for t in THEMES:
        out[f"sig_{t}"] = fits[t] == 1.0
        out[f"fit_{t}"] = fits[t]
        out[f"os_{t}"] = os_[t].round(3)
    out["signal_count"] = out[[f"sig_{t}" for t in THEMES]].sum(axis=1)
    out["any_signal"] = out["signal_count"] > 0
    out["overall_score"] = s["overall_score"].round(3)
    out["driving_theme"] = s["driving_theme"]
    out["driving_theme_label"] = s["driving_theme"].map(THEME_LABELS).fillna("No rule fully met")
    out["priority_rank"] = rank
    out["tier"] = tier
    out["evidence_level"] = df["evidence_level"]
    out["reason"] = reason_text(df, pr, s["driving_theme"])
    return out, df, fits, rank


def run(run_id: str = "manual"):
    out, df, fits, rank = build()
    out.insert(1, "run_id", run_id)
    db.write_df(out, "customer_opportunity")
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("ALTER TABLE customer_opportunity ADD PRIMARY KEY (customer_id)")
    sens = sensitivity(df, fits, rank)
    db.write_df(sens, "opportunity_sensitivity")
    return out, sens


if __name__ == "__main__":
    o, s = run()
    print(o["tier"].value_counts(), o["driving_theme"].value_counts(), s, sep="\n\n")

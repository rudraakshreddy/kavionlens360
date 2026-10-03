"""
Customer segmentation (spec 12; FR-024..028).

Layer 1  evidence level (rule): single-transaction vs repeat customers.
Layer 2  K-Means on log-scaled, winsorised, standardised behaviour features.
Layer 3  RFM scores describe the clusters afterwards (they do not create them).

Gender and city are never clustering inputs; they only profile clusters (R8).
Segment names are assigned after reviewing profiles, in config/segments.json.
"""
import json
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, calinski_harabasz_score, silhouette_score
from sklearn import set_config
from sklearn.preprocessing import StandardScaler

from . import db
from .config import OUTPUT_DIR, RANDOM_SEED, ROOT

set_config(working_memory=256)  # MB per pairwise-distance chunk (silhouette on 50K)

SEGMENTS_CONFIG = ROOT / "config" / "segments.json"
MODEL_DIR = OUTPUT_DIR / "models"

FEATURES = ["log_avg_balance", "log_total_value", "log_avg_txn", "txn_count_cap", "recency_days"]
SAMPLE_N = 50_000
STABILITY_SEEDS = (1, 2, 3, 4, 5)


def load_features() -> pd.DataFrame:
    return db.query("""
        SELECT customer_id, txn_count, total_txn_value, avg_txn_value, avg_balance, latest_balance,
               recency_days, active_days, age, age_group, gender, clean_city, city_tier,
               engagement_score, value_score, r_score, f_score, m_score, evidence_level,
               is_active, is_high_value, is_dormant
        FROM customer_360
    """)


class Prep:
    """Log transform -> winsorise at P1/P99 -> StandardScaler (FR-024). Parameters are saved."""

    def __init__(self, use_age=False):
        self.use_age = use_age
        self.caps = None
        self.scaler = StandardScaler()
        self.fill = {}

    def raw(self, d: pd.DataFrame) -> pd.DataFrame:
        bal = d["avg_balance"].fillna(self.fill.get("avg_balance", d["avg_balance"].median()))
        X = pd.DataFrame({
            "log_avg_balance": np.log1p(bal.astype(float)),
            "log_total_value": np.log1p(d["total_txn_value"].astype(float)),
            "log_avg_txn": np.log1p(d["avg_txn_value"].astype(float)),
            "txn_count_cap": d["txn_count"].clip(upper=4).astype(float),
            "recency_days": d["recency_days"].astype(float),
        }, index=d.index)
        if self.use_age:
            X["age"] = d["age"].fillna(self.fill.get("age", d["age"].median())).astype(float)
        return X

    def fit_transform(self, d: pd.DataFrame) -> np.ndarray:
        self.fill = {"avg_balance": float(d["avg_balance"].median()), "age": float(d["age"].median())}
        X = self.raw(d)
        self.caps = (X.quantile(0.01), X.quantile(0.99))
        X = X.clip(self.caps[0], self.caps[1], axis=1)
        return self.scaler.fit_transform(X)

    def to_json(self) -> dict:
        cols = list(self.caps[0].index)
        return {
            "features": cols, "use_age": self.use_age, "median_fill": self.fill,
            "winsor_p01": self.caps[0].round(6).tolist(), "winsor_p99": self.caps[1].round(6).tolist(),
            "scaler_mean": self.scaler.mean_.round(6).tolist(), "scaler_scale": self.scaler.scale_.round(6).tolist(),
        }


def _kmeans(k, seed):
    # Full Lloyd K-Means: ~5 s per fit on 840K x 5 features and far more seed-stable
    # than MiniBatchKMeans (ARI ~0.97 vs ~0.3-0.8 in testing), so no sampling is needed.
    return KMeans(n_clusters=k, random_state=seed, n_init=10)


def evaluate_k(X: np.ndarray, ks=range(3, 11), label="", seed=RANDOM_SEED) -> pd.DataFrame:
    """Elbow, silhouette and Calinski-Harabasz on a 50K sample, and 5-seed ARI stability (FR-025)."""
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(X), min(SAMPLE_N, len(X)), replace=False)
    rows = []
    for k in ks:
        m = _kmeans(k, seed).fit(X)
        lab = m.labels_
        aris = [adjusted_rand_score(lab[idx], _kmeans(k, s).fit(X).labels_[idx]) for s in STABILITY_SEEDS]
        sizes = np.bincount(lab, minlength=k) / len(lab)
        rows.append({
            "population": label, "k": k, "inertia": m.inertia_,
            "silhouette": silhouette_score(X[idx], lab[idx]),
            "calinski_harabasz": calinski_harabasz_score(X[idx], lab[idx]),
            "ari_min": min(aris), "ari_mean": float(np.mean(aris)),
            "min_cluster_share": sizes.min(),
        })
    return pd.DataFrame(rows)


def fit_clusters(X: np.ndarray, k: int, d: pd.DataFrame, seed=RANDOM_SEED) -> np.ndarray:
    """Fit K-Means and relabel clusters 0..k-1 by descending mean value score (stable IDs)."""
    lab = _kmeans(k, seed).fit(X).labels_
    order = pd.Series(d["value_score"].astype(float).values).groupby(lab).mean().sort_values(ascending=False)
    remap = {old: new for new, old in enumerate(order.index)}
    return np.vectorize(remap.get)(lab)


def profile(d: pd.DataFrame, seg: pd.Series) -> pd.DataFrame:
    """Segment profile (FR-027 / P13): size, value share and feature means / medians."""
    g = d.assign(segment=seg.values).groupby("segment")
    tot_val = d["total_txn_value"].sum()
    p = pd.DataFrame({
        "customers": g.size(),
        "pct_customers": 100 * g.size() / len(d),
        "pct_value": 100 * g["total_txn_value"].sum() / tot_val,
        "mean_txn_count": g["txn_count"].mean(),
        "median_total_value": g["total_txn_value"].median(),
        "median_avg_txn": g["avg_txn_value"].median(),
        "median_avg_balance": g["avg_balance"].median(),
        "mean_recency": g["recency_days"].mean(),
        "pct_active": 100 * g["is_active"].mean(),
        "pct_high_value": 100 * g["is_high_value"].mean(),
        "median_age": g["age"].median(),
        "pct_female": 100 * g["gender"].apply(lambda s: (s == "F").mean()),
        "pct_tier1_metro": 100 * g["city_tier"].apply(lambda s: (s == "Tier 1 metro").mean()),
        "mean_r": g["r_score"].mean(), "mean_f": g["f_score"].mean(), "mean_m": g["m_score"].mean(),
    })
    return p.round(2)


def zscore_profile(d: pd.DataFrame, seg: pd.Series, prep: Prep) -> pd.DataFrame:
    """Cluster means of the standardised features (heatmap P13)."""
    X = prep.scaler.transform(prep.raw(d).clip(prep.caps[0], prep.caps[1], axis=1))
    return pd.DataFrame(X, columns=list(prep.caps[0].index)).groupby(seg.values).mean().round(3)


def load_segment_config() -> dict:
    return json.loads(SEGMENTS_CONFIG.read_text(encoding="utf-8"))


def segment_customers(d: pd.DataFrame, cfg: dict):
    """
    Apply the configured design. cfg["design"] is "layered" (separate K-Means for
    single and repeat customers) or "joint" (one K-Means on everyone).
    Returns (cluster_key Series like 'S0'/'R2'/'J1', fitted prep objects, z-score profiles).
    """
    seg = pd.Series(index=d.index, dtype=object)
    preps, zprofiles = {}, {}
    if cfg["design"] == "layered":
        parts = {"S": d["txn_count"] == 1, "R": d["txn_count"] > 1}
    else:
        parts = {"J": pd.Series(True, index=d.index)}
    for prefix, mask in parts.items():
        sub = d[mask]
        prep = Prep(use_age=cfg.get("use_age", False))
        X = prep.fit_transform(sub)
        lab = fit_clusters(X, cfg["k"][prefix], sub)
        seg[mask] = [f"{prefix}{c}" for c in lab]
        preps[prefix] = prep
        zprofiles[prefix] = zscore_profile(sub, pd.Series(lab, index=sub.index), prep)
    return seg, preps, zprofiles


def check_expectations(prof_by_key: pd.DataFrame, defs: pd.DataFrame):
    """Guard: each configured name must still describe its cluster (profile 'expect' rule)."""
    failed = [r.cluster_key for r in defs.itertuples()
              if getattr(r, "expect", None) and prof_by_key.loc[[r.cluster_key]].query(r.expect).empty]
    if failed:
        raise ValueError(f"Segment profiles no longer match their names for {failed}; review config/segments.json")


def run(run_id: str = "manual"):
    cfg = load_segment_config()
    d = load_features()
    seg, preps, zprof = segment_customers(d, cfg)
    defs = pd.DataFrame(cfg["segments"])          # cluster_key, segment_name, description, action, ...
    missing = set(seg.unique()) - set(defs["cluster_key"])
    if missing:
        raise ValueError(f"segments.json has no definition for clusters {sorted(missing)}")

    run_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = pd.DataFrame({
        "customer_id": d["customer_id"], "run_id": run_id, "cluster_key": seg.values,
        "layer": np.where(d["txn_count"] == 1, "Single transaction", "Repeat"),
        "method": f"{cfg['design']} KMeans", "run_date": run_date,
    }).merge(defs[["cluster_key", "segment_id", "segment_name"]], on="cluster_key", how="left")
    db.write_df(out, "customer_segment")
    defs.assign(run_id=run_id).to_sql("segment_definition", db.engine(), if_exists="replace", index=False)
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("ALTER TABLE customer_segment ADD PRIMARY KEY (customer_id)")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (MODEL_DIR / "segmentation_params.json").write_text(json.dumps(
        {"run_id": run_id, "design": cfg["design"], "k": cfg["k"], "seed": RANDOM_SEED,
         "preprocessing": {p: prep.to_json() for p, prep in preps.items()},
         "zscore_profiles": {p: z.to_dict() for p, z in zprof.items()}}, indent=2), encoding="utf-8")
    prof = profile(d, out["segment_name"])
    check_expectations(profile(d, out["cluster_key"]), defs)
    db.write_df(prof.reset_index().rename(columns={"segment": "segment_name"}), "segment_profile")
    return out, prof

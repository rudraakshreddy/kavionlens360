"""Builds 03_segmentation.ipynb (spec 12; FR-024..028; plots P11-P15)."""
import json
from pathlib import Path

from _nb import SETUP, code, md, write

NOTES = json.loads(Path("notes_03.json").read_text(encoding="utf-8")) if Path("notes_03.json").exists() else {}


def note(key):
    return md(NOTES.get(key, f"*Interpretation for {key} pending.*"))


cells = [
    md("""
# 03 · Customer segmentation

**Method (spec 12.2-12.3).** K-Means on five behaviour features: log(avg balance), log(total value),
log(avg ticket), transaction count capped at 4, and recency. Each is winsorised at P1/P99 and standardised.
Gender and city are *not* inputs; they are used afterwards to profile the segments (risk R8).
The single-vs-repeat evidence layer (spec layer 1) is kept as a tag on every customer, and RFM scores describe
the segments (layer 3).

The k grid (3-10) was evaluated by `src/c360/segmentation.py::evaluate_k`. Each k takes 6 full K-Means fits
(about 30 s), so the grid was run once and saved to `outputs/segmentation/k_selection.csv`.
"""),
    SETUP,
    code("""
import json
from c360.segmentation import load_features, Prep, profile
ks = pd.read_csv(ROOT / "outputs" / "segmentation" / "k_selection.csv")
cfg = json.loads((ROOT / "config" / "segments.json").read_text())
ks.pivot(index="k", columns="population", values="silhouette").round(3)
"""),
    md("## P11 · Elbow (inertia) and P12 · silhouette by k"),
    code("""
j = ks[ks.population == "JOINT"]
fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
ax = axes[0]
ax.plot(j.k, j.inertia / 1e6, marker="o", color=viz.SERIES[0], markersize=6, markeredgecolor=viz.SURFACE, markeredgewidth=2)
ax.set_title("P11 · How many clusters?  Inertia (millions)"); ax.set_xlabel("k")
ax = axes[1]
labels = {"JOINT": "joint (chosen)", "JOINT_age": "joint + age", "SINGLE": "single-txn layer", "REPEAT": "repeat layer"}
for i, (pop, lab) in enumerate(labels.items()):
    s = ks[ks.population == pop]
    ax.plot(s.k, s.silhouette, marker="o", color=viz.SERIES[i], markersize=6, markeredgecolor=viz.SURFACE,
            markeredgewidth=2, label=lab, linewidth=2.4 if pop == "JOINT" else 1.6)
ax.axvline(5, color=viz.AXIS, linewidth=1); ax.annotate("k = 5", (5, ax.get_ylim()[0]), xytext=(4, 4), textcoords="offset points", fontsize=9, color=viz.INK_2)
ax.set_title("P12 · Separation quality: silhouette (50K sample)"); ax.set_xlabel("k"); ax.legend(loc="lower left")
fig.tight_layout()
viz.save(fig, "P11_P12_k_selection"); fig
"""),
    code("""
j[["k", "silhouette", "calinski_harabasz", "ari_min", "ari_mean", "min_cluster_share"]].assign(
    min_cluster_share=lambda d: (100 * d.min_cluster_share).round(1)).rename(columns={"min_cluster_share": "smallest cluster %"}).round(3)
"""),
    code("print(cfg['selection_note'])"),
    note("K"),
    md("## Fitted segments"),
    code("""
d = load_features()
seg = db.query("SELECT customer_id, segment_id, segment_name, cluster_key, layer FROM customer_segment")
d = d.merge(seg, on="customer_id")
for col in ["total_txn_value", "avg_txn_value", "avg_balance", "latest_balance", "value_score", "engagement_score"]:
    d[col] = d[col].astype(float)
names = d.drop_duplicates("segment_id").sort_values("segment_id")["segment_name"].tolist()
COL = {n: viz.SERIES[i] for i, n in enumerate(names)}       # color follows the segment everywhere
prof = profile(d, d["segment_name"]).loc[names]
prof
"""),
    md("## P13 · Segment profile heat map (z-scores of the clustering features)"),
    code("""
params = json.loads((ROOT / "outputs" / "models" / "segmentation_params.json").read_text())
z = pd.DataFrame(params["zscore_profiles"]["J"]); z.index = z.index.astype(int)
key_to_name = d.drop_duplicates("cluster_key").set_index("cluster_key")["segment_name"]
z.index = [key_to_name[f"J{i}"] for i in z.index]; z = z.loc[names]
z.columns = ["log avg balance", "log total value", "log avg ticket", "txn count (capped)", "recency days"]
from matplotlib.colors import LinearSegmentedColormap
cmap = LinearSegmentedColormap.from_list("div", [viz.DIVERGING[2], viz.DIVERGING[1], viz.DIVERGING[0]])
fig, ax = plt.subplots(figsize=(8.5, 3.6))
im = ax.imshow(z.values, cmap=cmap.reversed(), vmin=-2.2, vmax=2.2, aspect="auto")
ax.set_xticks(range(z.shape[1]), z.columns, rotation=20, ha="right"); ax.set_yticks(range(z.shape[0]), z.index)
ax.grid(False)
for i in range(z.shape[0]):
    for jx in range(z.shape[1]):
        ax.text(jx, i, f"{z.values[i, jx]:+.2f}", ha="center", va="center", fontsize=8,
                color="white" if abs(z.values[i, jx]) > 1.3 else viz.INK)
fig.colorbar(im, ax=ax, label="mean z-score", shrink=0.9)
ax.set_title("What defines each segment?  Mean standardised feature value")
viz.save(fig, "P13_segment_profile"); fig
"""),
    note("P13"),
    md("## P14 · PCA view of the segments (20K sample, one panel per segment)"),
    code("""
from sklearn.decomposition import PCA
prep = Prep(); X = prep.fit_transform(d)
rng = np.random.default_rng(42); idx = rng.choice(len(d), 20000, replace=False)
pc = PCA(n_components=2, random_state=42).fit(X)
P = pc.transform(X[idx]); lab = d["segment_name"].values[idx]
fig, axes = plt.subplots(1, len(names), figsize=(15, 3.3), sharex=True, sharey=True)
for ax, n in zip(axes, names):
    ax.scatter(P[:, 0], P[:, 1], s=2, color=viz.GRID, rasterized=True)
    m = lab == n
    ax.scatter(P[m, 0], P[m, 1], s=3, color=COL[n], rasterized=True)
    ax.set_title(n, fontsize=10); ax.grid(False)
axes[0].set_ylabel("PC2"); [a.set_xlabel("PC1") for a in axes]
fig.suptitle(f"Are the segments distinct?  First two principal components ({100 * pc.explained_variance_ratio_.sum():.0f}% of variance)",
             x=0.01, ha="left", fontweight="semibold")
fig.tight_layout()
viz.save(fig, "P14_pca_segments"); fig
"""),
    note("P14"),
    md("## P15 · Segment size vs value share"),
    code("""
fig, ax = plt.subplots(figsize=(9, 3.8))
x = np.arange(len(names)); w = 0.36
b1 = ax.bar(x - w / 2 - 0.01, prof["pct_customers"], w, color=viz.SERIES[0], label="% of customers")
b2 = ax.bar(x + w / 2 + 0.01, prof["pct_value"], w, color=viz.SERIES[1], label="% of transaction value")
for bars in (b1, b2):
    for r in bars:
        ax.annotate(f"{r.get_height():.1f}", (r.get_x() + r.get_width() / 2, r.get_height()), ha="center", va="bottom",
                    xytext=(0, 2), textcoords="offset points", fontsize=8, color=viz.INK_2)
ax.set_xticks(x, names); ax.set_ylabel("%"); ax.legend(loc="upper right")
ax.set_title("Where is the value?  Share of customers vs share of transaction value")
viz.save(fig, "P15_segment_size_value"); fig
"""),
    note("P15"),
    md("## Validation (FR-027)"),
    code("""
from scipy import stats
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score
val = {}
val["smallest segment (% of customers)"] = round(prof["pct_customers"].min(), 2)
row = j.set_index("k").loc[cfg["k"]["J"]]
val["silhouette (50K sample)"] = round(row.silhouette, 3)
val["ARI across 5 seeds (min / mean)"] = f"{row.ari_min:.3f} / {row.ari_mean:.3f}"
# Hierarchical (Ward) on a 15K sample as an independent check (spec 12.1)
hidx = rng.choice(len(d), 15000, replace=False)
ward = AgglomerativeClustering(n_clusters=cfg["k"]["J"], linkage="ward").fit_predict(X[hidx])
val["ARI K-Means vs Ward hierarchical (15K sample)"] = round(adjusted_rand_score(d["cluster_key"].values[hidx], ward), 3)
pd.Series(val, name="value").to_frame()
"""),
    code("""
# Kruskal-Wallis: do segment distributions differ on each feature? effect = epsilon squared
rows = []
for f in ["avg_balance", "total_txn_value", "avg_txn_value", "txn_count", "recency_days", "age"]:
    s = d.dropna(subset=[f])
    groups = [g[f].astype(float).values for _, g in s.groupby("segment_name")]
    h, p = stats.kruskal(*groups)
    rows.append((f, h, (h - len(groups) + 1) / (len(s) - len(groups))))
pd.DataFrame(rows, columns=["feature", "H", "epsilon²"]).round(3)
"""),
    code("""
# Chi-square gender x segment (spec 15d); effect = Cramer's V
ct = pd.crosstab(d.loc[d.gender != "Unknown", "segment_name"], d.loc[d.gender != "Unknown", "gender"]).loc[names]
chi2, p, dof, _ = stats.chi2_contingency(ct)
cv = np.sqrt(chi2 / (ct.values.sum() * (min(ct.shape) - 1)))
print(f"chi2 = {chi2:,.0f}, dof = {dof}, Cramer's V = {cv:.3f}")
(100 * ct.div(ct.sum(axis=1), axis=0)).round(1).rename(columns={"F": "% female", "M": "% male"})
"""),
    note("VAL"),
    md("## RFM overlay (layer 3) and segment definitions (spec 12.4)"),
    code("prof[['mean_r', 'mean_f', 'mean_m', 'pct_active', 'pct_high_value']]"),
    code("""
defs = pd.DataFrame(cfg["segments"]).set_index("segment_name").loc[names]
defs[["customer_characteristics", "transaction_characteristics", "financial_behaviour", "potential_needs", "action", "owner", "timing", "kpi"]]
"""),
    note("DEF"),
]

write("03_segmentation.ipynb", cells)

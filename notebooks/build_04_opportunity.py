"""Builds 04_opportunity_scoring.ipynb (spec 13; FR-029..031; P16-P17; reconciliation T-15)."""
import json
from pathlib import Path

from _nb import SETUP, code, md, write

NOTES = json.loads(Path("notes_04.json").read_text(encoding="utf-8")) if Path("notes_04.json").exists() else {}


def note(key):
    return md(NOTES.get(key, f"*Interpretation for {key} pending.*"))


cells = [
    md("""
# 04 · Cross-sell opportunity signals and priority tiers

> **Signals inferred from behaviour. Product ownership is unknown.** These are *Analytical Opportunity Signals*
> to prioritise conversations. They are not recommendations, eligibility checks or credit decisions (spec 6, 13, 26).

Rules (spec 13.2) use percentiles of the clean customer base [A]. The personal-loan recency condition is scaled
from 30 to 15 days to fit the 46-day window. Score per theme:
`OS_p = 100 × (0.35·V + 0.25·E + 0.30·Fit_p + 0.10·R)`. The overall score is the max over themes;
tiers are A = top 5%, B = next 15%, C = next 30%, Watch = the rest.
"""),
    SETUP,
    code("""
from c360.opportunity import THEMES, THEME_LABELS
o = db.query("SELECT * FROM customer_opportunity")
c = db.query("SELECT customer_id, avg_balance::float, latest_balance::float, total_txn_value::float, txn_count, recency_days FROM customer_360")
s = db.query("SELECT customer_id, segment_id, segment_name FROM customer_segment")
o = o.merge(c, on="customer_id").merge(s, on="customer_id")
names = o.drop_duplicates("segment_id").sort_values("segment_id")["segment_name"].tolist()
thr = db.query("SELECT * FROM customer_thresholds").T.rename(columns={0: "value (Rs or score)"})
thr
"""),
    md("## Signals by theme"),
    code("""
sig = pd.DataFrame({
    "customers flagged": [o[f"sig_{t}"].sum() for t in THEMES],
    "% of customers": [100 * o[f"sig_{t}"].mean() for t in THEMES],
    "near-miss (Fit = 0.5)": [(o[f"fit_{t}"] == 0.5).sum() for t in THEMES],
    "addressable balance (Rs Cr)": [o.loc[o[f"sig_{t}"], "latest_balance"].sum() / 1e7 for t in THEMES],
}, index=[THEME_LABELS[t] for t in THEMES])
print(f"Customers with at least one signal: {o.any_signal.sum():,} ({100 * o.any_signal.mean():.1f}%)")
print(f"Addressable balance (latest balance of flagged customers): Rs {o.loc[o.any_signal, 'latest_balance'].sum() / 1e7:,.0f} crore")
sig.round(1)
"""),
    md("## P16 · Which themes, in which segments? (share of segment flagged)"),
    code("""
rate = pd.DataFrame({THEME_LABELS[t].split(" (")[0]: o.groupby("segment_name")[f"sig_{t}"].mean() * 100 for t in THEMES}).loc[names]
from matplotlib.colors import LinearSegmentedColormap
seq = LinearSegmentedColormap.from_list("blue", [viz.BLUE[100], viz.BLUE[400], viz.BLUE[700]])
fig, ax = plt.subplots(figsize=(10, 3.6))
im = ax.imshow(rate.values, cmap=seq, vmin=0, vmax=100, aspect="auto")
ax.set_xticks(range(rate.shape[1]), rate.columns, rotation=15, ha="right"); ax.set_yticks(range(len(names)), names)
ax.grid(False)
for i in range(rate.shape[0]):
    for j in range(rate.shape[1]):
        ax.text(j, i, f"{rate.values[i, j]:.0f}%", ha="center", va="center", fontsize=8,
                color="white" if rate.values[i, j] > 55 else viz.INK)
fig.colorbar(im, ax=ax, label="% of segment flagged", shrink=0.9)
ax.set_title("Which product themes fit which segment?  Share of segment with each signal")
viz.save(fig, "P16_theme_by_segment"); fig
"""),
    note("P16"),
    md("## P17 · Score distribution by tier"),
    code("""
fig, ax = plt.subplots(figsize=(10, 3.6))
bins = np.linspace(0, 100, 51)
bottom = np.zeros(len(bins) - 1)
for t in ["Watch", "C", "B", "A"]:
    h, _ = np.histogram(o.loc[o.tier == t, "overall_score"], bins=bins)
    ax.bar(bins[:-1], h, width=np.diff(bins) * 0.92, align="edge", bottom=bottom, color=viz.TIER_COLORS[t], label=f"Tier {t}" if t != "Watch" else "Watch")
    bottom += h
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))
ax.set_xlabel("overall opportunity score"); ax.set_ylabel("customers"); ax.legend(loc="upper left")
ax.set_title("Does the score discriminate?  Customers by overall opportunity score and tier")
viz.save(fig, "P17_score_distribution"); fig
"""),
    code("""
tiers = o.groupby("tier").agg(customers=("customer_id", "size"), min_score=("overall_score", "min"),
                              max_score=("overall_score", "max"), with_signal=("any_signal", "mean"),
                              addressable_cr=("latest_balance", lambda s: s[o.loc[s.index, "any_signal"]].sum() / 1e7)).loc[["A", "B", "C", "Watch"]]
tiers["share %"] = 100 * tiers.customers / len(o); tiers["with_signal"] *= 100
ev = pd.crosstab(o.tier, o.evidence_level, normalize="index").loc[["A", "B", "C", "Watch"], ["High", "Medium", "Low"]] * 100
tiers.join(ev.add_prefix("evidence % ")).round(1)
"""),
    code("""
pd.crosstab(o.segment_name, o.tier).loc[names, ["A", "B", "C", "Watch"]]
"""),
    note("P17"),
    md("## Sensitivity of the ranking to the weights (FR-031, T-11)"),
    code("db.query('SELECT * FROM opportunity_sensitivity')"),
    note("SENS"),
    md("## Priority list (Page 4 preview, masked IDs)"),
    code("""
o.sort_values("priority_rank").head(15)[["priority_rank", "masked_id", "tier", "overall_score", "driving_theme_label", "segment_name", "evidence_level", "reason"]]
"""),
    md("## Reconciliation: Python vs SQL (FR-038, T-15)"),
    code("""
py = {
    "Total Customers": len(o), "Total Transactions": int(o.txn_count.sum()), "Total Txn Value": o.total_txn_value.sum(),
    "Avg Balance": o.avg_balance.mean(), "Median Balance": o.avg_balance.median(),
    "Opportunity Count": int(o.any_signal.sum()), "Tier A Customers": int((o.tier == "A").sum()),
    "Addressable Balance": o.loc[o.any_signal, "latest_balance"].sum(),
}
sqlk = db.query("SELECT kpi, sql_value::float AS sql FROM kpi_reconciliation").set_index("kpi")
rec = sqlk.join(pd.Series(py, name="python"), how="inner")
rec["variance"] = (rec["python"] - rec["sql"]).round(4)
rec["status"] = np.where(rec["variance"].abs() < 0.01, "PASS", "CHECK")
rec
"""),
    note("REC"),
]

write("04_opportunity_scoring.ipynb", cells)

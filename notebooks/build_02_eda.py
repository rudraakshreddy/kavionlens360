"""Builds 02_eda_statistics.ipynb (spec 15: EDA P1-P10, statistical tests, hypotheses H1-H4)."""
import json
import sys
from pathlib import Path

from _nb import SETUP, code, md, write

# Interpretation text is written after the analysis ran (spec 19: never pre-write numbers).
NOTES = json.loads(Path("notes_02.json").read_text(encoding="utf-8")) if Path("notes_02.json").exists() else {}


def note(key):
    """Markdown cell answering: what we found / why it matters / what a manager should do."""
    return md(NOTES.get(key, f"*Interpretation for {key} pending.*"))


cells = [
    md("""
# 02 · Exploratory analysis and statistics

Analysis window **1 Aug - 15 Sep 2016** (46 days), as-of date 16 Sep 2016. Source tables: `fact_transaction`,
`customer_360` (one row per CustomerID). Each chart is followed by *what we found · why it matters · what a manager should do*.
"""),
    SETUP,
    code("""
c = db.query("SELECT * FROM customer_360")
amounts = db.query("SELECT amount FROM fact_transaction")["amount"].astype(float)
for col in ["total_txn_value", "avg_txn_value", "avg_balance", "latest_balance", "max_balance",
            "engagement_score", "value_score", "txn_to_balance_ratio", "balance_volatility"]:
    c[col] = c[col].astype(float)
print(f"{len(c):,} customers · {len(amounts):,} transactions · total value Rs {amounts.sum():,.0f}")
"""),
    md("## P1 · Transaction amount distribution"),
    code("""
fig, ax = plt.subplots(figsize=(9, 3.6))
bins = np.logspace(0, np.log10(amounts.max()), 60)
ax.hist(amounts, bins=bins, color=viz.SERIES[0], edgecolor=viz.SURFACE, linewidth=0.6)
ax.set_xscale("log"); ax.xaxis.set_major_formatter(mticker.FuncFormatter(viz.inr))
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))
for q, lab in [(0.5, "median"), (0.95, "P95")]:
    v = amounts.quantile(q); ax.axvline(v, color=viz.INK_2, linewidth=1)
    ax.annotate(f"{lab} Rs {v:,.0f}", (v, ax.get_ylim()[1] * 0.9), xytext=(4, 0), textcoords="offset points", fontsize=9, color=viz.INK_2)
ax.set_title("What is a typical ticket size?  Transaction amount (log scale)")
ax.set_xlabel("amount (Rs)"); ax.set_ylabel("transactions")
viz.save(fig, "P1_amount_distribution"); fig
"""),
    code("amounts.describe(percentiles=[.25, .5, .75, .9, .95, .99]).to_frame('amount (Rs)').T"),
    note("P1"),
    md("## P2 · Balance distribution (customers)"),
    code("""
b = c["latest_balance"].dropna()
fig, ax = plt.subplots(figsize=(9, 3.6))
ax.hist(np.log10(b + 1), bins=60, color=viz.SERIES[0], edgecolor=viz.SURFACE, linewidth=0.6)
ticks = [0, 1, 2, 3, 4, 5, 6, 7, 8]
ax.set_xticks(ticks, [viz.inr(10 ** t) for t in ticks])
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))
ax.set_title("How is wealth spread?  Latest account balance per customer (log scale)")
ax.set_xlabel("latest balance (Rs)"); ax.set_ylabel("customers")
viz.save(fig, "P2_balance_distribution"); fig
"""),
    code("""
pd.Series({"median latest balance": b.median(), "mean latest balance": b.mean(),
           "P90": b.quantile(.9), "P99": b.quantile(.99),
           "zero / near-zero balance customers (%)": 100 * (b < 1).mean(),
           "top 10% share of total balance (%)": 100 * b.nlargest(int(len(b) * .1)).sum() / b.sum()},
          name="value").to_frame()
"""),
    note("P2"),
    md("## P3 · Transactions per customer"),
    code("""
dist = c["txn_count"].clip(upper=3).map({1: "1", 2: "2", 3: "3+"}).value_counts().reindex(["1", "2", "3+"])
fig, ax = plt.subplots(figsize=(6, 3.4))
bars = ax.bar(dist.index, dist.values, color=viz.SERIES[0], width=0.6)
for r, v in zip(bars, dist.values):
    ax.annotate(f"{100 * v / dist.sum():.1f}%", (r.get_x() + r.get_width() / 2, v), ha="center", va="bottom",
                xytext=(0, 3), textcoords="offset points", fontsize=9, color=viz.INK_2)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))
ax.set_title("How repeat is the base?  Customers by transactions in the window")
ax.set_xlabel("transactions per customer"); ax.set_ylabel("customers")
viz.save(fig, "P3_txns_per_customer"); fig
"""),
    note("P3"),
    md("## P4 · Age distribution"),
    code("""
order = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+", "Unknown"]
ag = c["age_group"].value_counts().reindex(order)
fig, ax = plt.subplots(figsize=(8, 3.4))
ax.bar(ag.index, ag.values, color=[viz.SERIES[0]] * 6 + [viz.AXIS], width=0.65)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))
ax.set_title("Who are the customers?  Customers by age group (age at 16 Sep 2016)")
ax.set_ylabel("customers")
viz.save(fig, "P4_age_distribution"); fig
"""),
    code("(100 * ag / ag.sum()).round(1).to_frame('% of customers').T"),
    note("P4"),
    md("## P5 · Average ticket by gender"),
    code("""
g = c[c["gender"].isin(["M", "F"])]
fig, ax = plt.subplots(figsize=(6, 3.8))
data = [np.log10(g.loc[g.gender == s, "avg_txn_value"]) for s in ["F", "M"]]
bp = ax.boxplot(data, tick_labels=["Female", "Male"], widths=0.45, showfliers=False, patch_artist=True,
                medianprops=dict(color=viz.INK, linewidth=1.5))
for patch, col in zip(bp["boxes"], [viz.SERIES[0], viz.SERIES[1]]):
    patch.set_facecolor(col); patch.set_alpha(0.35); patch.set_edgecolor(col)
ax.set_yticks([1, 2, 3, 4], ["Rs 10", "Rs 100", "Rs 1K", "Rs 10K"])
ax.set_title("Does ticket size differ by gender?  Avg transaction value per customer")
viz.save(fig, "P5_gender_ticket"); fig
"""),
    code("g.groupby('gender')['avg_txn_value'].describe(percentiles=[.25, .5, .75])"),
    note("P5"),
    md("## P6 · Top 15 cities by transaction value"),
    code("""
city = (c[c.clean_city != "UNKNOWN"].groupby("clean_city")
        .agg(customers=("customer_id", "size"), value=("total_txn_value", "sum")).sort_values("value", ascending=False))
city["value_share_%"] = 100 * city["value"] / c["total_txn_value"].sum()
top = city.head(15).iloc[::-1]
fig, ax = plt.subplots(figsize=(8, 5))
ax.barh(top.index, top["value"], color=viz.SERIES[0], height=0.65)
ax.xaxis.set_major_formatter(mticker.FuncFormatter(viz.inr))
ax.grid(axis="y", visible=False)
ax.set_title("Where is the value?  Top 15 cities by transaction value (Rs)")
viz.save(fig, "P6_top_cities"); fig
"""),
    code("""
print(f"Top 5 cities hold {city['value_share_%'].head(5).sum():.1f}% of value; top 15 hold {city['value_share_%'].head(15).sum():.1f}%")
city.head(15).style.format({"customers": "{:,.0f}", "value": "{:,.0f}", "value_share_%": "{:.2f}"})
"""),
    note("P6"),
    md("## P7 · Daily activity trend"),
    code("""
daily = db.query(\"\"\"SELECT d.date, COUNT(*) AS txns, SUM(f.amount) AS value
                     FROM fact_transaction f JOIN dim_date d USING (date_key) GROUP BY d.date ORDER BY d.date\"\"\")
daily["date"] = pd.to_datetime(daily["date"]); daily["value"] = daily["value"].astype(float)
fig, axes = plt.subplots(2, 1, figsize=(10, 5.2), sharex=True)
for ax, col, title, fmt in [(axes[0], "txns", "Transactions per day", lambda x, _: f"{x/1000:.0f}K"),
                            (axes[1], "value", "Transaction value per day (Rs)", viz.inr)]:
    ax.plot(daily["date"], daily[col], color=viz.SERIES[0], linewidth=1.2, alpha=0.45)
    ax.plot(daily["date"], daily[col].rolling(7, center=True).mean(), color=viz.SERIES[0], linewidth=2)
    ax.set_title(title); ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt))
axes[0].annotate("7-day average", (daily["date"].iloc[20], daily["txns"].rolling(7, center=True).mean().iloc[20]),
                 xytext=(0, 14), textcoords="offset points", fontsize=9, color=viz.INK_2)
fig.suptitle("Is activity changing?  Daily trend, 1 Aug - 15 Sep 2016", x=0.01, ha="left", fontweight="semibold")
fig.tight_layout()
viz.save(fig, "P7_daily_trend"); fig
"""),
    code("""
daily["weekend"] = daily["date"].dt.dayofweek >= 5
daily.groupby("weekend")[["txns", "value"]].mean().rename(index={False: "weekday", True: "weekend"})
"""),
    note("P7"),
    md("## P8 · Hour of day × day of week"),
    code("""
hw = db.query(\"\"\"SELECT d.day_of_week_num, d.day_of_week, f.txn_hour, COUNT(*)::FLOAT / COUNT(DISTINCT d.date) AS txns_per_day
                  FROM fact_transaction f JOIN dim_date d USING (date_key)
                  GROUP BY d.day_of_week_num, d.day_of_week, f.txn_hour\"\"\")
grid = hw.pivot_table(index=["day_of_week_num", "day_of_week"], columns="txn_hour", values="txns_per_day").fillna(0)
from matplotlib.colors import LinearSegmentedColormap
seq = LinearSegmentedColormap.from_list("blue", [viz.BLUE[100], viz.BLUE[400], viz.BLUE[700]])
fig, ax = plt.subplots(figsize=(10, 3.4))
im = ax.imshow(grid.values, aspect="auto", cmap=seq)
ax.set_yticks(range(7), [d for _, d in grid.index]); ax.set_xticks(range(0, 24, 2), [f"{h:02d}" for h in range(0, 24, 2)])
ax.grid(False); ax.set_xlabel("hour of day")
fig.colorbar(im, ax=ax, label="avg transactions per day", shrink=0.85)
ax.set_title("When are customers active?  Average transactions per hour, by weekday")
viz.save(fig, "P8_hour_weekday"); fig
"""),
    code("""
by_hour = hw.groupby("txn_hour")["txns_per_day"].sum()
band = pd.cut(by_hour.index, [-1, 5, 11, 16, 20, 23], labels=["00-05", "06-11", "12-16", "17-20", "21-23"])
(100 * by_hour.groupby(band, observed=True).sum() / by_hour.sum()).round(1).to_frame("% of transactions").T
"""),
    note("P8"),
    md("## P9 · Value concentration (Lorenz / Pareto)"),
    code("""
v = np.sort(c["total_txn_value"].values)[::-1]
cum = np.cumsum(v) / v.sum(); pop = np.arange(1, len(v) + 1) / len(v)
fig, ax = plt.subplots(figsize=(6.4, 5))
ax.plot(pop * 100, cum * 100, color=viz.SERIES[0])
ax.plot([0, 100], [0, 100], color=viz.AXIS, linewidth=1)
for p in (0.01, 0.10, 0.20):
    y = cum[int(p * len(v)) - 1] * 100
    ax.plot(p * 100, y, "o", color=viz.SERIES[0], markersize=6, markeredgecolor=viz.SURFACE, markeredgewidth=2)
    ax.annotate(f"top {p:.0%} → {y:.0f}% of value", (p * 100, y), xytext=(8, -4), textcoords="offset points", fontsize=9, color=viz.INK_2)
ax.set_xlabel("% of customers (ranked by value)"); ax.set_ylabel("% of total transaction value")
ax.set_title("How concentrated is value?  Cumulative share of transaction value")
gini = 1 - 2 * np.trapezoid(np.cumsum(np.sort(v)) / v.sum(), dx=1 / len(v))
viz.save(fig, "P9_lorenz"); fig
"""),
    code("""
pd.Series({f"top {int(p*100)}% of customers": round(cum[int(p * len(v)) - 1] * 100, 1) for p in (0.01, 0.05, 0.10, 0.20, 0.50)}
          | {"Gini coefficient": round(gini, 3)}, name="% of value").to_frame()
"""),
    note("P9"),
    md("## P10 · Feature correlation (Spearman)"),
    code("""
feats = ["txn_count", "total_txn_value", "avg_txn_value", "max_txn_value", "active_days", "recency_days",
         "avg_balance", "latest_balance", "txn_to_balance_ratio", "age", "engagement_score", "value_score"]
corr = c[feats].astype(float).corr(method="spearman")
fig, ax = plt.subplots(figsize=(8.4, 7))
from matplotlib.colors import LinearSegmentedColormap
cmap = LinearSegmentedColormap.from_list("div", [viz.DIVERGING[2], viz.DIVERGING[1], viz.DIVERGING[0]])
im = ax.imshow(corr.values, cmap=cmap, vmin=-1, vmax=1)
ax.set_xticks(range(len(feats)), feats, rotation=60, ha="right"); ax.set_yticks(range(len(feats)), feats)
ax.grid(False)
for i in range(len(feats)):
    for j in range(len(feats)):
        ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center", fontsize=7,
                color=viz.INK if abs(corr.values[i, j]) < 0.6 else "white")
fig.colorbar(im, ax=ax, shrink=0.7, label="Spearman rho")
ax.set_title("Which features are redundant?  Spearman correlation")
viz.save(fig, "P10_correlation"); fig
"""),
    note("P10"),
    md("""
## Statistical tests (spec 15)

With ~840K customers almost any difference is "significant", so every test reports an **effect size**
and the business reading rests on the effect size, not the p-value.
"""),
    code("""
from scipy import stats
rows = []

# (a) Mann-Whitney U: average ticket, male vs female (skewed data); effect = rank-biserial r
m = g.loc[g.gender == "M", "avg_txn_value"]; f = g.loc[g.gender == "F", "avg_txn_value"]
u, p = stats.mannwhitneyu(m, f, alternative="two-sided")
rows.append(("Mann-Whitney U", "Avg ticket differs between men and women", f"U={u:,.0f}", p,
             "rank-biserial r", 1 - 2 * u / (len(m) * len(f)), f"median M Rs {m.median():,.0f} vs F Rs {f.median():,.0f}"))

# (b) Kruskal-Wallis: balance across age groups; effect = epsilon squared
known = c[c.age_group != "Unknown"].dropna(subset=["avg_balance"])
groups = [grp["avg_balance"].values for _, grp in known.groupby("age_group")]
h, p = stats.kruskal(*groups)
eps2 = (h - len(groups) + 1) / (len(known) - len(groups))
rows.append(("Kruskal-Wallis", "Avg balance differs across age groups", f"H={h:,.0f}", p, "epsilon²", eps2,
             "medians: " + ", ".join(f"{k} Rs {v:,.0f}" for k, v in known.groupby('age_group')['avg_balance'].median().items())))

# (c) Spearman: balance vs transaction value
bb = c.dropna(subset=["avg_balance"])
rho, p = stats.spearmanr(bb["avg_balance"], bb["total_txn_value"])
rows.append(("Spearman", "Balance is associated with transaction value", f"rho={rho:.3f}", p, "rho", rho, ""))

# (d) Chi-square: city tier x high-value flag (H4); effect = Cramer's V
ct = pd.crosstab(c.loc[c.city_tier != "Unknown", "city_tier"], c.loc[c.city_tier != "Unknown", "is_high_value"])
chi2, p, dof, _ = stats.chi2_contingency(ct)
v_ = np.sqrt(chi2 / (ct.values.sum() * (min(ct.shape) - 1)))
hv_rate = (100 * ct[True] / ct.sum(axis=1)).round(1)
rows.append(("Chi-square", "High-value share differs by city tier", f"chi2={chi2:,.0f}, dof={dof}", p, "Cramer's V", v_,
             "high-value %: " + ", ".join(f"{k} {v}%" for k, v in hv_rate.items())))

tests = pd.DataFrame(rows, columns=["test", "hypothesis (H1 of the test)", "statistic", "p_value", "effect", "effect_size", "detail"])
tests["p_value"] = tests["p_value"].map(lambda x: "< 1e-300" if x == 0 else f"{x:.2e}")
tests.to_csv(ROOT / "outputs" / "stat_tests.csv", index=False)
tests
"""),
    code("""
# Chi-square gender x segment (spec 15d) is in notebook 03, after segments exist.
hyp = pd.DataFrame([
    ("H1", "A small group holds a disproportionate share of balance",
     f"top 10% of customers hold {100 * b.nlargest(int(len(b) * .1)).sum() / b.sum():.1f}% of total latest balance"),
    ("H2", "Most customers are single-transaction, low-ticket",
     f"{100 * (c.txn_count == 1).mean():.1f}% single-transaction; their median ticket Rs {c.loc[c.txn_count == 1, 'avg_txn_value'].median():,.0f}"),
    ("H3", "Older customers hold higher balances",
     "median avg balance by age group: " + ", ".join(f"{k} Rs {v:,.0f}" for k, v in known.groupby('age_group')['avg_balance'].median().items())),
    ("H4", "Metro cities hold more high-value customers",
     "high-value share: " + ", ".join(f"{k} {v}%" for k, v in hv_rate.items())),
], columns=["id", "hypothesis", "evidence"])
hyp
"""),
    note("HYP"),
]

write("02_eda_statistics.ipynb", cells)

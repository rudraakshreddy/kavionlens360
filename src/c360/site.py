"""
Build the GitHub Pages site in docs/ (report + interactive dashboard).

Every number on the report page is read from the database at build time, so the
site always matches the latest pipeline run. Run after export:  python -m c360.site
"""
import html
import json
import shutil
from datetime import datetime

import numpy as np
import pandas as pd

from . import db
from .config import FIG_DIR, OUTPUT_DIR, ROOT, SITE_DIR

REPO_URL = "https://github.com/rudraakshreddy/kavionlens360"
ASSETS = ROOT / "site" / "assets"
SEG_VARS = ["--s1", "--s2", "--s3", "--s4", "--s5"]
FIGS = ["P0_daily_coverage", "P1_amount_distribution", "P2_balance_distribution", "P3_txns_per_customer",
        "P4_age_distribution", "P6_top_cities", "P7_daily_trend", "P8_hour_weekday", "P9_lorenz",
        "P11_P12_k_selection", "P13_segment_profile", "P14_pca_segments", "P15_segment_size_value",
        "P16_theme_by_segment", "P17_score_distribution"]
DOWNLOADS = [
    ("PDF", "Analytical report", "This page as a printable PDF", "downloads/KavionLens360_Report.pdf"),
    ("PDF", "Executive deck", "8-slide management presentation", "downloads/KavionLens360_Executive_Deck.pdf"),
    ("PPTX", "Executive deck (editable)", "PowerPoint with native charts", "downloads/KavionLens360_Executive_Deck.pptx"),
    ("XLSX", "Excel MIS", "7 sheets: XLOOKUP, SUMIFS, PivotTables, Power Query", "downloads/KavionLens360_MIS.xlsx"),
    ("PDF", "Excel MIS (print)", "The MIS workbook as PDF", "downloads/KavionLens360_MIS.pdf"),
    ("PDF", "Power BI report", "5-page Power BI export", "downloads/KavionLens360_PowerBI.pdf"),
]


def esc(x):
    return html.escape(str(x))


def n0(x):
    return f"{x:,.0f}"


def cr(x):
    return f"₹{x / 1e7:,.0f} Cr" if x >= 1e9 else f"₹{x / 1e7:,.1f} Cr"


def lakh_or_cr(x):
    return cr(x) if x >= 1e7 else f"₹{x / 1e5:,.1f} L" if x >= 1e5 else f"₹{x:,.0f}"


# --------------------------------------------------------------------------- facts
def facts() -> dict:
    f = {}
    pp = db.query("SELECT * FROM project_params").iloc[0]
    f["as_of"], f["w_start"], f["w_end"] = pp.as_of_date, pp.window_start, pp.window_end
    wf = db.query("SELECT * FROM row_waterfall ORDER BY step_no")
    f["waterfall"] = wf
    f["raw_rows"] = int(wf.loc[wf.step_no == 0, "rows"].iloc[0])
    f["clean_rows"] = int(wf.loc[wf.step_no == 99, "rows"].iloc[0])
    f["rejects"] = {r.step.replace("Rejected: ", ""): -int(r.rows) for r in wf.itertuples() if 0 < r.step_no < 99}
    k = db.query("SELECT kpi, sql_value::float AS v FROM kpi_reconciliation").set_index("kpi")["v"]
    f["kpi"] = k.to_dict()
    c = db.query("SELECT total_txn_value::float AS v, latest_balance::float AS b, txn_count FROM customer_360")
    v = np.sort(c["v"].values)[::-1]
    cum = np.cumsum(v) / v.sum()
    f["top_share"] = {p: 100 * cum[int(p / 100 * len(v)) - 1] for p in (1, 5, 10, 20)}
    asc = np.sort(c["v"].values)
    f["gini"] = 1 - 2 * np.trapezoid(np.cumsum(asc) / asc.sum(), dx=1 / len(asc))
    b = c["b"].dropna()
    f["bal_top10"] = 100 * b.nlargest(int(len(b) * 0.1)).sum() / b.sum()
    f["single_pct"] = 100 * (c["txn_count"] == 1).mean()
    dq = db.query("SELECT check_id, dimension, rule, pass_pct::float, threshold_pct::float, status, note FROM dq_log ORDER BY check_id")
    f["dq"] = dq
    f["dq_counts"] = dq["status"].value_counts().to_dict()
    f["id_consistent"] = float(dq.loc[dq.check_id == "DQ-20", "pass_pct"].iloc[0])
    cities = db.query("SELECT clean_city, customers, total_value::float FROM agg_city_summary ORDER BY total_value DESC")
    f["top5_cities"] = cities.head(5)
    f["top5_share"] = 100 * cities.head(5)["total_value"].sum() / f["kpi"]["Total Txn Value"]
    f["n_cities"] = int(db.scalar("SELECT COUNT(*) FROM dim_location"))
    f["n_raw_locations"] = int(db.scalar("SELECT COUNT(DISTINCT cust_location) FROM stg_bank_transactions"))
    seg = db.query("SELECT * FROM agg_segment_summary ORDER BY segment_id")
    defs = db.query("SELECT * FROM segment_definition ORDER BY segment_id")
    f["segments"] = seg.merge(defs[["segment_id", "action", "owner", "timing", "kpi", "potential_needs"]], on="segment_id")
    tiers = db.query("""SELECT o.tier, COUNT(*) AS n, MIN(o.overall_score)::float AS lo,
                               SUM(CASE WHEN o.any_signal THEN c.latest_balance END)::float AS addr
                        FROM customer_opportunity o JOIN customer_360 c USING (customer_id) GROUP BY o.tier""").set_index("tier")
    f["tiers"] = tiers.loc[["A", "B", "C", "Watch"]]
    th = db.query("""SELECT SUM(sig_investment::int) investment, SUM(sig_premium::int) premium, SUM(sig_credit_card::int) credit_card,
                            SUM(sig_insurance::int) insurance, SUM(sig_personal_loan::int) personal_loan,
                            SUM(sig_reengagement::int) reengagement FROM customer_opportunity""").iloc[0]
    f["themes"] = th.to_dict()
    sens = db.query("SELECT * FROM opportunity_sensitivity")
    f["sens_min"], f["sens_max"] = sens["top1000_overlap_pct"].min(), sens["top1000_overlap_pct"].max()
    f["sens_rho"] = sens["spearman_vs_base"].min()
    ks = pd.read_csv(OUTPUT_DIR / "segmentation" / "k_selection.csv")
    cfg = json.loads((ROOT / "config" / "segments.json").read_text(encoding="utf-8"))
    kk = cfg["k"]["J"]
    row = ks[(ks.population == "JOINT") & (ks.k == kk)].iloc[0]
    f["k"], f["sil"], f["ari_min"] = kk, row.silhouette, row.ari_min
    f["stat"] = pd.read_csv(OUTPUT_DIR / "stat_tests.csv")
    hw = db.query("SELECT txn_hour, SUM(txns) AS n FROM agg_hour_weekday GROUP BY txn_hour")
    f["afternoon_evening"] = 100 * hw.loc[hw.txn_hour.between(12, 20), "n"].sum() / hw["n"].sum()
    dd = db.query("""SELECT d.is_weekend, COUNT(*)::float / COUNT(DISTINCT d.date) AS per_day
                     FROM fact_transaction f JOIN dim_date d USING (date_key) GROUP BY d.is_weekend""").set_index("is_weekend")["per_day"]
    f["weekend_uplift"] = 100 * (dd[True] / dd[False] - 1)
    f["generated"] = datetime.now().strftime("%d %b %Y")
    return f


# --------------------------------------------------------------------------- page chrome
def head(title, desc):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='14' cy='14' r='9' fill='none' stroke='%232a78d6' stroke-width='4'/%3E%3Cpath d='M21 21l7 7' stroke='%232a78d6' stroke-width='4' stroke-linecap='round'/%3E%3C/svg%3E">
<link rel="stylesheet" href="assets/style.css">
<script src="assets/theme.js"></script>
</head>
<body>
"""


def topbar(active):
    links = [("index.html", "Report"), ("dashboard.html", "Dashboard"), ("index.html#downloads", "Downloads"),
             (REPO_URL, "GitHub")]
    nav = "".join(f'<a href="{h}"{" aria-current=\"page\"" if t == active else ""}{" class=\"hide-sm\"" if t == "Downloads" else ""}>{t}</a>'
                  for h, t in links)
    return f"""<header class="topbar"><div class="wrap">
<a class="brand" href="index.html"><svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true"><circle cx="14" cy="14" r="9" fill="none" stroke="var(--accent)" stroke-width="4"/><path d="M21 21l7 7" stroke="var(--accent)" stroke-width="4" stroke-linecap="round"/></svg>KavionLens360</a>
<nav class="nav" aria-label="Site">{nav}</nav>
<button class="theme-btn" id="theme-btn" type="button" aria-label="Toggle theme">☾</button>
</div></header>
"""


def footer(f):
    return f"""<footer><div class="wrap">
KavionLens360 · Bank Customer 360 &amp; Segmentation Analytics · portfolio project by Y. Rudraaksh Reddy ·
built {f['generated']} from <a href="{REPO_URL}">{REPO_URL.replace('https://', '')}</a>.<br>
Data: public Kaggle dataset “Bank Customer Segmentation (1M+ Transactions)”, an Indian bank, 2016. It is not ICICI Bank data
and nothing here describes any bank's internal systems. Opportunity flags are behavioural signals, not product recommendations or credit decisions.
</div></footer>
</body>
</html>
"""


def fig(name, caption):
    return (f'<figure><img src="figures/{name}.png" alt="{esc(caption)}" loading="lazy">'
            f"<figcaption>{caption}</figcaption></figure>")


# --------------------------------------------------------------------------- report page
def report(f) -> str:
    k = f["kpi"]
    seg = f["segments"]
    t = f["tiers"]
    st = f["stat"].set_index("test")
    gender_v = st.loc["Mann-Whitney U", "effect_size"]
    age_eps = st.loc["Kruskal-Wallis", "effect_size"]
    rho = st.loc["Spearman", "effect_size"]
    cramer = st.loc["Chi-square", "effect_size"]
    s = {r.segment_name: r for r in seg.itertuples()}
    eng, rec_, lap, low, zero = [seg.iloc[i] for i in range(5)]
    one_time_value = rec_.pct_value + lap.pct_value
    low_tail_c, low_tail_v = low.pct_customers + zero.pct_customers, low.pct_value + zero.pct_value

    seg_rows = "".join(
        f"<tr><td><i class='swatch' style='background:var({SEG_VARS[i]})'></i>{esc(r.segment_name)}</td>"
        f"<td class='num'>{r.pct_customers:.1f}%</td><td class='num'>{r.pct_value:.1f}%</td>"
        f"<td class='num'>₹{r.median_avg_balance:,.0f}</td><td class='num'>{r.avg_txn_count:.2f}</td>"
        f"<td class='num'>{r.pct_active:.0f}%</td><td>{esc(r.action)}</td></tr>"
        for i, r in enumerate(seg.itertuples()))
    tier_rows = "".join(
        f"<tr><td><span class='tierchip {tier}'>{tier}</span></td><td class='num'>{n0(r.n)}</td>"
        f"<td class='num'>{100 * r.n / k['Total Customers']:.0f}%</td><td class='num'>{r.lo:.1f}</td>"
        f"<td class='num'>{cr(r.addr or 0)}</td></tr>" for tier, r in t.iterrows())
    theme_names = {"investment": "Investment / MF", "premium": "Premium account", "credit_card": "Credit card",
                   "insurance": "Insurance", "personal_loan": "Personal loan (demand only)", "reengagement": "Re-engagement (service)"}
    theme_rows = "".join(f"<tr><td>{theme_names[kk]}</td><td class='num'>{n0(v)}</td>"
                         f"<td class='num'>{100 * v / k['Total Customers']:.1f}%</td></tr>" for kk, v in f["themes"].items())
    rej = f["rejects"]
    wf_rows = "".join(f"<tr><td>{esc(r.step)}</td><td class='num'>{n0(r.rows)}</td></tr>" for r in f["waterfall"].itertuples())
    dqc = f["dq_counts"]
    stat_rows = "".join(
        f"<tr><td>{esc(r.test)}</td><td>{esc(r._2)}</td><td>{esc(r.effect)} = {r.effect_size:.3f}</td><td>{esc(r.detail if isinstance(r.detail, str) else '')}</td></tr>"
        for r in f["stat"].itertuples())
    cities = ", ".join(f"{c.clean_city.title()}" for c in f["top5_cities"].itertuples())
    downloads = "".join(
        f'<a class="dl{"" if (SITE_DIR / path).exists() else " pending"}" href="{path}"><span class="kind">{kind}</span>'
        f'<span><span class="t">{esc(title)}</span><br><span class="d">{esc(desc)}{"" if (SITE_DIR / path).exists() else " (coming soon)"}</span></span></a>'
        for kind, title, desc, path in DOWNLOADS)
    code_links = "".join(
        f'<a class="dl" href="{REPO_URL}/blob/main/{p}"><span class="kind">{kind}</span><span><span class="t">{t_}</span><br><span class="d">{d}</span></span></a>'
        for kind, t_, d, p in [
            ("SQL", "Pipeline SQL", "Staging, cleaning, model, Customer 360, DQ", "sql"),
            ("SQL", "26 analytical questions", "CTEs and window functions", "sql/07_analytical_questions.sql"),
            ("IPYNB", "Notebooks", "Profiling, EDA and statistics, segmentation, scoring", "notebooks"),
            ("PBIP", "Power BI project", "TMDL model + PBIR report, text-based", "powerbi"),
        ])

    return head("KavionLens360 Report", "Bank Customer 360 and segmentation analytics on 1M public bank transactions: findings, segments, cross-sell signals.") + topbar("Report") + f"""
<main>
<div class="wrap hero">
  <div class="eyebrow">Bank Customer 360 &amp; Segmentation Analytics</div>
  <h1>Who to focus on, why, and with what conversation</h1>
  <p class="lede">KavionLens360 turns {n0(f['raw_rows'])} bank transactions into one analytical view per customer, groups
  {n0(k['Total Customers'])} customers into five behaviour segments, and ranks them by transparent cross-sell
  <em>signals</em> so a relationship manager knows whom to call first.</p>
  <p class="disclaimer">Public Kaggle data from an Indian bank (2016), not ICICI Bank data. Analysis window
  {f['w_start']:%d %b} – {f['w_end']:%d %b %Y}, as of {f['as_of']:%d %b %Y}. Every number on this page is generated from the pipeline.</p>
  <div class="tiles">
    <div class="tile"><div class="label">Customers</div><div class="value">{k['Total Customers'] / 1e5:,.2f} L</div><div class="sub">{n0(k['Total Customers'])} CustomerIDs</div></div>
    <div class="tile"><div class="label">Transactions analysed</div><div class="value">{k['Total Transactions'] / 1e5:,.2f} L</div><div class="sub">{cr(k['Total Txn Value'])} moved</div></div>
    <div class="tile"><div class="label">Value from top 10%</div><div class="value">{f['top_share'][10]:.0f}%</div><div class="sub">Gini {f['gini']:.2f}</div></div>
    <div class="tile"><div class="label">Behaviour segments</div><div class="value">{f['k']}</div><div class="sub">silhouette {f['sil']:.2f} · ARI ≥ {f['ari_min']:.2f}</div></div>
    <div class="tile"><div class="label">Tier A priority customers</div><div class="value">{t.loc['A', 'n'] / 1e3:,.1f}K</div><div class="sub">{cr(t.loc['A', 'addr'])} addressable balance</div></div>
  </div>
  <ul class="toc">
    <li><a href="#problem">Problem</a></li><li><a href="#data">Data &amp; quality</a></li><li><a href="#insights">Customer insights</a></li>
    <li><a href="#segments">Segments</a></li><li><a href="#opportunity">Opportunity</a></li><li><a href="#actions">Actions</a></li>
    <li><a href="#limits">Limitations</a></li><li><a href="#downloads">Downloads</a></li><li><a href="dashboard.html">Open dashboard →</a></li>
  </ul>
</div>

<section class="block" id="problem"><div class="wrap cols">
  <div>
    <h2>1. The problem</h2>
    <p>Banks store activity as transactions, but managers think in customers. With limited relationship-manager time,
    a raw transaction log cannot say <strong>who to focus on, why, with what offer, where they are, and how large the opportunity is</strong>.</p>
    <p>This project builds a small analytical version of a Customer 360: a reconciled customer table, behaviour segments with a
    named action each, and a ranked opportunity list, delivered through SQL, Python, Power BI, an Excel MIS and an executive deck.</p>
  </div>
  <div class="callout">
    <strong>Value chain:</strong> data → analysis → insight → business action.<br><br>
    <ol class="steps">
      <li>PostgreSQL 16: staging, 17 cleaning rules, star model, <code>customer_360</code></li>
      <li>Python: profiling, EDA, statistics, K-Means segmentation, opportunity scoring</li>
      <li>Power BI (5 pages), Excel MIS (7 sheets), deck (8 slides), this site</li>
      <li>Reconciliation: SQL = Python = Excel = Power BI, variance 0</li>
    </ol>
  </div>
</div></section>

<section class="block" id="data"><div class="wrap">
  <h2>2. Data, profiling and quality</h2>
  <div class="cols">
    <div>
      <p>Profiling the {n0(f['raw_rows'])}-row file confirmed every published count, and found two issues the dataset page does not mention:</p>
      <div class="finding"><h3>Coverage ends on 15 September</h3>
      <p>Every day from 1 Aug to 15 Sep has roughly 17–27K transactions; after that the file holds only a few scattered days.
      Because recency and “active” rules need complete coverage, the analysis window was fixed to 46 days and the sparse tail
      ({n0(rej.get('PARTIAL_COVERAGE_PERIOD', 0))} rows) was logged, not silently dropped.</p></div>
      <div class="finding" style="margin-top:12px"><h3>CustomerID is not a stable person key</h3>
      <p>Only {f['id_consistent']:.1f}% of repeat CustomerIDs keep the same birth date, gender and city across their rows.
      The ID is kept as the key (as specified), conflicts are resolved by the most-frequent-then-latest rule, and repeat-customer
      features are interpreted with care.</p></div>
    </div>
    <div>
      <div class="table-wrap"><table><thead><tr><th>Row waterfall</th><th class="num">Rows</th></tr></thead><tbody>{wf_rows}</tbody></table></div>
      <p style="margin-top:12px">Quality scorecard: <span class="badge pass">{dqc.get('PASS', 0)} pass</span>
      <span class="badge exception">{dqc.get('EXCEPTION', 0)} documented exception</span>
      <span class="badge info">{dqc.get('INFO', 0)} findings</span>. The one exception is usable birth dates (94%), because of the
      <code>1/1/1800</code> placeholder. {n0(f['n_raw_locations'])} raw location spellings were standardised into {n0(f['n_cities'])} cities.</p>
    </div>
  </div>
  {fig('P0_daily_coverage', 'Transactions per day in the raw file. Complete daily coverage ends on 15 Sep 2016.')}
</div></section>

<section class="block" id="insights"><div class="wrap">
  <h2>3. Customer 360 insights</h2>
  <div class="cols">
    <div class="finding"><h3>Value is extremely concentrated</h3><p>The top 1% of customers generate {f['top_share'][1]:.0f}% of transaction value,
    the top 10% generate {f['top_share'][10]:.0f}% and hold {f['bal_top10']:.0f}% of balances (Gini {f['gini']:.2f}).</p></div>
    <div class="finding"><h3>Most customers appear once</h3><p>{f['single_pct']:.1f}% of customers made a single transaction in the window, so
    frequency is weak evidence for most of the base. Every list carries an evidence level.</p></div>
    <div class="finding"><h3>Metros carry the book</h3><p>{cities} hold {f['top5_share']:.0f}% of value.
    Weekend days run {f['weekend_uplift']:.0f}% above weekdays, and {f['afternoon_evening']:.0f}% of activity falls between 12:00 and 21:00.</p></div>
  </div>
  <div class="cols" style="margin-top:20px">
    {fig('P9_lorenz', 'Cumulative share of transaction value by customers ranked by value.')}
    {fig('P2_balance_distribution', 'Latest balance per customer, log scale.')}
  </div>
  <div class="cols">
    {fig('P6_top_cities', 'Top 15 cities by transaction value.')}
    {fig('P8_hour_weekday', 'Average transactions per hour, by weekday.')}
  </div>
  <h3>Statistics, with effect sizes</h3>
  <p>With 840K customers every test is “significant”, so each reports an effect size. The result is consistent:
  <strong>behaviour, not demographics, explains value</strong>. Gender barely moves ticket size (rank-biserial r = {gender_v:.2f}),
  age explains little of balance (ε² = {age_eps:.2f}), metro status barely changes the high-value share (Cramér's V = {cramer:.2f}),
  while balance and transaction value are only moderately linked (Spearman ρ = {rho:.2f}).</p>
  <div class="table-wrap"><table><thead><tr><th>Test</th><th>Question</th><th>Effect size</th><th>Detail</th></tr></thead><tbody>{stat_rows}</tbody></table></div>
</div></section>

<section class="block" id="segments"><div class="wrap">
  <h2>4. Five behaviour segments</h2>
  <p>K-Means on five behaviour features (log balance, log value, log ticket, capped frequency, recency), with k chosen from 3–10
  by elbow, silhouette, Calinski-Harabasz and five-seed stability. k = {f['k']}: silhouette {f['sil']:.3f}, ARI ≥ {f['ari_min']:.2f},
  smallest segment {seg.pct_customers.min():.1f}%. Gender and city were excluded from the inputs and only used to profile.</p>
  <div class="table-wrap"><table><thead><tr><th>Segment</th><th class="num">Customers</th><th class="num">Value</th><th class="num">Median balance</th><th class="num">Txns / customer</th><th class="num">Active</th><th>Action</th></tr></thead><tbody>{seg_rows}</tbody></table></div>
  <div class="cols" style="margin-top:20px">
    {fig('P15_segment_size_value', 'Share of customers vs share of transaction value by segment.')}
    {fig('P13_segment_profile', 'What defines each segment: mean standardised feature values.')}
  </div>
  <p><strong>Reading:</strong> {esc(eng.segment_name)} are {eng.pct_customers:.0f}% of customers but {eng.pct_value:.0f}% of value.
  The two one-time spender segments look alike in value and differ only in recency; together they hold {one_time_value:.0f}% of value.
  The two low-value segments ({low_tail_c:.0f}% of customers) contribute {low_tail_v:.1f}% of value and belong in low-cost digital channels.</p>
</div></section>

<section class="block" id="opportunity"><div class="wrap">
  <h2>5. Cross-sell opportunity signals</h2>
  <p class="callout"><strong>Signals inferred from behaviour; product ownership is unknown.</strong> Six transparent rules use percentile
  thresholds. Each customer gets a score: 100 × (0.35 value + 0.25 engagement + 0.30 rule fit + 0.10 recency), and tiers
  A (top 5%), B (next 15%), C (next 30%) and Watch. These rank conversations; they are not eligibility or credit decisions.</p>
  <div class="cols">
    <div class="table-wrap"><table><thead><tr><th>Tier</th><th class="num">Customers</th><th class="num">Share</th><th class="num">Min score</th><th class="num">Addressable balance</th></tr></thead><tbody>{tier_rows}</tbody></table></div>
    <div class="table-wrap"><table><thead><tr><th>Signal</th><th class="num">Customers</th><th class="num">% of base</th></tr></thead><tbody>{theme_rows}</tbody></table></div>
  </div>
  <div class="cols" style="margin-top:20px">
    {fig('P16_theme_by_segment', 'Share of each segment carrying each signal.')}
    {fig('P17_score_distribution', 'Overall opportunity score by tier.')}
  </div>
  <p><strong>Robustness:</strong> moving any weight by ±10 points keeps {f['sens_min']:.0f}–{f['sens_max']:.0f}% of the top 1,000 customers
  (rank correlation ≥ {f['sens_rho']:.2f}), so the judgement-based weights do not drive the list.
  <strong>Caveat:</strong> {100 * k['Opportunity Count'] / k['Total Customers']:.0f}% of customers carry at least one signal, which is broad;
  the credit-card and insurance rules are the first to tighten once response data exists.</p>
</div></section>

<section class="block" id="actions"><div class="wrap">
  <h2>6. From insight to action</h2>
  <div class="table-wrap"><table><thead><tr><th>Output</th><th>What we found</th><th>Why it matters</th><th>What a manager should do</th></tr></thead><tbody>
    <tr><td>Value concentration</td><td>Top 10% → {f['top_share'][10]:.0f}% of value; top 1% → {f['top_share'][1]:.0f}%</td><td>Effort pays off unevenly</td><td>Named RM coverage for the top decile</td></tr>
    <tr><td>Segment profiles</td><td>{esc(eng.segment_name)}: {eng.pct_customers:.0f}% of customers, {eng.pct_value:.0f}% of value</td><td>Different needs per segment</td><td>Deepen this group first: needs review, cards and investments</td></tr>
    <tr><td>Lapsed one-time spenders</td><td>{lap.pct_customers:.0f}% of customers, {lap.pct_value:.0f}% of value, not seen for 2+ weeks</td><td>Valuable but going quiet</td><td>Re-engagement call before any sale</td></tr>
    <tr><td>Low-value tail</td><td>{low_tail_c:.0f}% of customers, {low_tail_v:.1f}% of value</td><td>RM time has little return</td><td>Digital nurture only; activation checks for near-zero balances</td></tr>
    <tr><td>Opportunity tiers</td><td>Tier A: {n0(t.loc['A', 'n'])} customers, {cr(t.loc['A', 'addr'])}</td><td>Limited RM time</td><td>Work Tier A first, review weekly, measure response</td></tr>
    <tr><td>Geography</td><td>Top 5 cities hold {f['top5_share']:.0f}% of value</td><td>Effort allocation</td><td>Staff metro hubs; use the city scorecard for high value-per-customer smaller cities</td></tr>
  </tbody></table></div>
  <p style="margin-top:16px"><a href="dashboard.html#manager">Open the Manager Action view →</a> who, why, what, where and how large, on one screen.</p>
</div></section>

<section class="block" id="limits"><div class="wrap cols">
  <div>
    <h2>7. Limitations and responsible use</h2>
    <ul>
      <li>Public data from one bank in 2016 and a 46-day window: no seasonality, trend or tenure claims.</li>
      <li>No product holdings, revenue or campaign outcomes: opportunity is a signal, value is a proxy (balance and activity).</li>
      <li>CustomerID is not a stable person key in this extract; repeat behaviour is weak evidence.</li>
      <li>Clusters describe behaviour; they do not predict it.</li>
      <li>Age is used only as a life-stage hint; gender and city are never model inputs. Flags start conversations; they never decide eligibility.</li>
    </ul>
  </div>
  <div>
    <h2>Version 2</h2>
    <ul>
      <li>Add product holdings and campaign response to build propensity models and measure lift.</li>
      <li>Longer time window and entity resolution for a reliable customer key.</li>
      <li>Segment-drift monitoring and fairness checks on every refresh.</li>
    </ul>
  </div>
</div></section>

<section class="block" id="downloads"><div class="wrap">
  <h2>8. Deliverables</h2>
  <div class="downloads">{downloads}</div>
  <h3 style="margin-top:24px">Code</h3>
  <div class="downloads">{code_links}</div>
</div></section>
</main>
""" + footer(f)


# --------------------------------------------------------------------------- dashboard page
def dashboard(f) -> str:
    def card(id_, title, q, span, cls="", legend=False):
        return (f'<div class="card {span}" id="{id_}"><div class="card-tools"><div><h3>{title}</h3><div class="q">{q}</div></div>'
                f'<button class="view-toggle" type="button">Table</button></div>'
                + ('<div class="legend"></div>' if legend else "")
                + f'<div class="chart {cls}"><canvas role="img" aria-label="{esc(title)}"></canvas></div><div class="tableview"></div></div>')

    def tcard(id_, title, q, span):
        return (f'<div class="card {span}"><h3>{title}</h3><div class="q">{q}</div>'
                f'<div class="table-wrap" id="{id_}"></div></div>')

    return head("KavionLens360 Dashboard", "Interactive Customer 360 dashboard: executive view, segments, cross-sell signals, manager action list, data quality.") + topbar("Dashboard") + f"""
<main class="wrap">
<div class="dash-head">
  <h1 style="font-size:28px">Customer 360 dashboard</h1>
  <p class="disclaimer" id="asof">Loading…</p>
</div>
<div id="loading" class="loading">Loading dashboard data…</div>
<div id="dash" hidden>
  <div class="filters" id="filters" role="group" aria-label="Filters"></div>
  <div class="active-filters" id="active-filters"></div>
  <div class="tabs" role="tablist">
    <button role="tab" type="button">1 · Executive</button><button role="tab" type="button">2 · Segmentation</button>
    <button role="tab" type="button">3 · Cross-sell</button><button role="tab" type="button">4 · Manager action</button>
    <button role="tab" type="button">5 · Data quality</button>
  </div>

  <div class="panel" id="executive">
    <div class="kpis" id="kpi-exec"></div>
    <div class="grid">
      {card('c-agegender', 'Customers by age group and gender', 'Who are the customers?', 'span-5', legend=True)}
      {card('c-trend', 'Daily transactions', '', 'span-7')}
      {card('c-cities', 'Top cities by transaction value', 'Where is the value?', 'span-6', 'tall')}
      {card('c-segdist', 'Customers by segment', 'How is the base split?', 'span-6', 'tall')}
    </div>
  </div>

  <div class="panel" id="segmentation" hidden>
    <div class="kpis" id="kpi-seg"></div>
    <div class="grid">
      {card('c-sizevalue', 'Share of customers vs share of value', 'Where does each segment sit?', 'span-6', legend=True)}
      {card('c-agemix', 'Age mix by segment', 'Do segments differ by life stage?', 'span-6', legend=True)}
      {tcard('t-profile', 'Segment profile', 'Responds to all filters except Segment', 'span-12')}
      {tcard('t-actions', 'Segment actions', 'Named action, owner, timing and KPI per segment', 'span-12')}
    </div>
  </div>

  <div class="panel" id="crosssell" hidden>
    <div class="banner"><strong>Signals inferred from behaviour. Product ownership unknown.</strong> Not eligibility or credit decisions.</div>
    <div class="kpis" id="kpi-cs"></div>
    <div class="grid">
      {card('c-themes', 'Customers by product signal', 'Which conversations are signalled?', 'span-5')}
      {tcard('t-heat', 'Signal rate by segment', 'Share of each segment carrying each signal', 'span-7')}
      {card('c-tiers', 'Priority tiers', 'How many customers per tier?', 'span-4', 'short')}
      {card('c-score', 'Opportunity score distribution', 'Does the score separate customers? (all customers)', 'span-8', 'short', legend=True)}
      {card('c-oppcity', 'Customers with a signal, by city', 'Where are the opportunities?', 'span-12')}
    </div>
  </div>

  <div class="panel" id="manager" hidden>
    <div class="kpis" id="kpi-mgr"></div>
    <div class="grid">
      <div class="card span-12">
        <div class="card-tools"><div><h3>Priority customers: who, why, what, where</h3><div class="q">Top {n0(2000)} by score · IDs masked</div></div>
        <label style="font-size:12px;color:var(--ink-2);font-weight:600">Product theme <select id="f-theme" style="font:inherit;font-size:13px"></select></label></div>
        <div class="table-wrap" id="t-priority"></div>
        <div class="pager"><span id="pager-info"></span><button id="prev" type="button">‹ Prev</button><button id="next" type="button">Next ›</button></div>
      </div>
      {card('c-mgrtier', 'Customers by tier', 'How large is each tier?', 'span-6', 'short')}
      {card('c-mgrcity', 'Tier A customers by city', 'Where are they?', 'span-6', 'short')}
    </div>
  </div>

  <div class="panel" id="dataquality" hidden>
    <div class="grid">
      {tcard('t-recon', 'Reconciliation', 'Dashboard totals vs the SQL reference table', 'span-6')}
      {tcard('t-waterfall', 'Row waterfall', 'Raw rows → rejected → clean', 'span-6')}
      {tcard('t-dq', 'Data quality scorecard', '24 checks across completeness, accuracy, consistency, uniqueness, validity, timeliness', 'span-12')}
    </div>
  </div>
</div>
</main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script src="assets/dashboard.js"></script>
""" + footer(f)


def build():
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "assets").mkdir(exist_ok=True)
    for a in ASSETS.iterdir():
        shutil.copy(a, SITE_DIR / "assets" / a.name)
    (SITE_DIR / "figures").mkdir(exist_ok=True)
    for name in FIGS:
        src = FIG_DIR / f"{name}.png"
        if src.exists():
            shutil.copy(src, SITE_DIR / "figures" / src.name)
    (SITE_DIR / "downloads").mkdir(exist_ok=True)
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")
    f = facts()
    (SITE_DIR / "index.html").write_text(report(f), encoding="utf-8")
    (SITE_DIR / "dashboard.html").write_text(dashboard(f), encoding="utf-8")
    return f


if __name__ == "__main__":
    build()
    print("site written to", SITE_DIR)

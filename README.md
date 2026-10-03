# KavionLens360 · Bank Customer 360 & Segmentation Analytics

**Who to focus on, why, and with what conversation.** KavionLens360 turns ~1 million bank transactions into one
analytical view per customer, groups customers into behaviour segments, and ranks them by transparent cross-sell
*signals*, so a relationship manager knows whom to call first.

- **Live report:** <https://rudraakshreddy.github.io/kavionlens360/>
- **Interactive dashboard:** <https://rudraakshreddy.github.io/kavionlens360/dashboard.html>
- **Downloads:** [report PDF](docs/downloads/KavionLens360_Report.pdf) · [executive deck PDF](docs/downloads/KavionLens360_Executive_Deck.pdf) / [PPTX](docs/downloads/KavionLens360_Executive_Deck.pptx) · [Excel MIS](docs/downloads/KavionLens360_MIS.xlsx) / [PDF](docs/downloads/KavionLens360_MIS.pdf)

> Public Kaggle data ("Bank Customer Segmentation (1M+ Transactions)", an Indian bank, 2016). **Not ICICI Bank data**,
> and nothing here describes any bank's internal systems. Opportunity flags are behavioural signals for prioritising
> conversations, not product recommendations, eligibility checks or credit decisions.

## Results at a glance

| | |
|---|---|
| Transactions profiled → clean | 1,048,567 → 988,947 (every rejected row logged with a reason) |
| Customers (one row each) | 841,543 |
| Data-quality scorecard | 24 checks: 17 pass, 1 documented exception, 6 profiling findings |
| Value concentration | top 10% of customers → 63% of transaction value, 77% of balances (Gini 0.74) |
| Segmentation | K-Means k = 5 (chosen from 3-10): silhouette 0.28, 5-seed ARI ≥ 0.93, smallest segment 9.5% |
| Key segment | Engaged Repeat Users: 15% of customers, 28% of value |
| Priority list | 42,077 Tier A customers (top 5%), ₹1,721 Cr addressable balance |
| Score robustness | ±10-pt weight changes keep 84-100% of the top 1,000 (Spearman ≥ 0.99) |
| Reconciliation | SQL = Python = Excel = dashboard, variance 0 |
| Tests | 23 automated tests pass ([TEST_LOG.md](TEST_LOG.md)) |

| Segment | Customers | Value | Action |
|---|---:|---:|---|
| Engaged Repeat Users | 15.0% | 28.1% | Deepen: RM introduction, needs review, bundle offer |
| Recent One-Time Spenders | 24.1% | 33.3% | Convert to repeat use while the visit is recent |
| Lapsed One-Time Spenders | 25.5% | 34.3% | Win-back service call before any sale |
| Low-Ticket Occasional | 25.8% | 1.7% | Low-cost digital nurture only |
| Near-Zero Balance | 9.5% | 2.7% | Service and activation check; exclude from cross-sell |

## Architecture

```
Kaggle CSV (zip, read-only)
   └─ PostgreSQL 16 (Docker)
        staging (all text) → 17 cleaning rules + rejected_rows + row_waterfall
        → dim_location · dim_date · dim_customer · fact_transaction
        → customer_360 (features, RFM, scores, business-rule flags) → dq_log (24 checks)
   └─ Python: profiling · EDA + statistics · K-Means segmentation · opportunity signals, scores, tiers
   └─ publish: aggregated tables → extracts for Power BI / Excel, dashboard JSON, 26 SQL answers
   └─ Power BI (PBIP, 5 pages) · Excel MIS (7 sheets) · executive deck (8 slides) · GitHub Pages report + dashboard
```

| Layer | Tools |
|---|---|
| Database | PostgreSQL 16 in Docker; SQL with CTEs and window functions (`RANK`, `NTILE`, `PERCENT_RANK`, `CUME_DIST`, `percentile_cont`) |
| Analysis | Python 3.13, pandas, NumPy, SciPy, scikit-learn, matplotlib, Jupyter |
| BI | Power BI Desktop (PBIP: TMDL model + PBIR report, generated as text and schema-validated) |
| MIS | Excel 2021 via COM: Power Query, SUMIFS, COUNTIFS, XLOOKUP, INDEX/MATCH, IFS, PivotTables + slicers |
| Deck | python-pptx with native charts; PDF via PowerPoint |
| Web | Static site on GitHub Pages; Chart.js dashboard over a pre-aggregated cube |

## Run it

Prerequisites: Docker Desktop, Python 3.11+. Excel, PowerPoint and Power BI Desktop are needed only for those deliverables.

```bash
pip install -r requirements.txt
cp .env.example .env                    # set a local password
# put the Kaggle archive.zip (bank_transactions.csv) in data/raw/
docker compose up -d                    # PostgreSQL 16
python run_pipeline.py                  # load → clean → model → features → DQ → segments → scores → publish → site (~5 min)
python -m pytest -v                     # 23 tests; then python tests/render_test_log.py
```

Optional deliverables (Windows + Office):

```bash
python excel/build_mis.py               # docs/downloads/KavionLens360_MIS.xlsx + .pdf
python deck/build_deck.py               # docs/downloads/KavionLens360_Executive_Deck.pptx + .pdf
python -m c360.report_pdf               # docs/downloads/KavionLens360_Report.pdf (run from src/ or with PYTHONPATH=src)
python powerbi/build_pbip.py            # regenerate the Power BI project (see powerbi/README.md)
```

Notebooks (`notebooks/01-04`) are built by the `build_*.py` scripts next to them and executed with
`python -m nbconvert --to notebook --execute --inplace <notebook>`.

## Repository

| Path | Contents |
|---|---|
| `sql/` | `00_schema` · `01_location_map` · `02_clean` · `03_model` · `04_customer_360` · `05_dq_checks` · `06_publish` · `07_analytical_questions` (26 questions) |
| `src/c360/` | loader, segmentation, opportunity scoring, exports, site and PDF builders |
| `config/segments.json` | segment design, names, actions; profile guards so a re-run cannot mislabel a cluster |
| `notebooks/` | 01 profiling · 02 EDA and statistics · 03 segmentation · 04 opportunity scoring (executed, with interpretations) |
| `outputs/` | figures, SQL answers (masked IDs), k-selection grid, statistical tests, model parameters |
| `powerbi/` | Power BI project (`KavionLens360.pbip`) and its generator |
| `excel/`, `deck/` | MIS and deck builders |
| `docs/` | the GitHub Pages site and downloadable deliverables |
| `tests/` | spec section 25 tests and the test-log renderer |

## Decisions that differ from the original spec (and why)

1. **Analysis window 1 Aug - 15 Sep 2016 (46 days), not to 21 Oct.** Profiling showed complete daily coverage (~21K
   transactions a day) only to 15 Sep; the remaining 5.6% of rows sit on a few scattered days. Recency, "active" and trend
   need complete coverage, so the tail is logged as `PARTIAL_COVERAGE_PERIOD` and day-based rules are scaled
   (active ≤ 15 days, dormant > 30 days, trend = second half vs first half).
2. **CustomerID kept as the key, with a documented caveat.** Fewer than 1% of repeat CustomerIDs keep the same birth
   date, gender and city across rows (DQ-20). Conflicts are resolved by the spec's most-frequent-then-latest rule and
   repeat-customer features are read with caution.
3. **Joint K-Means (k = 5) instead of separate single/repeat models.** The joint model had higher silhouette, and the
   layered alternative produced a 1.9% segment (below the 3% rule). Single vs repeat is kept as the evidence tag.
   Age lowered separation at every k, so it profiles segments but is not an input.
4. **Full K-Means instead of MiniBatchKMeans.** About 5 s per fit on 840K × 5 features, and far more stable across seeds
   (ARI ≈ 0.97 vs 0.3-0.8).
5. **Zero-amount transactions rejected** (validity rule amount > 0); missing birth dates arrive as the text `nan` and are
   treated as missing.

## Limitations

Public 2016 data from one bank and a 46-day window: no seasonality, tenure or trend claims. No product holdings, revenue
or campaign outcomes, so opportunity is a signal and value is a proxy (balance and activity). 48% of customers carry at
least one signal, which is broad; the credit-card and insurance rules are the first to tighten once response data exists.
Clusters describe behaviour; they do not predict it.

## Responsible use

Gender and city are never model inputs; age is only a life-stage hint. Published outputs contain aggregates and masked
IDs only; the raw file is not in the repository. Credentials live in `.env` (git-ignored).

---

Portfolio project by **Y. Rudraaksh Reddy**.

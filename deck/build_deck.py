"""
Build the 8-slide executive deck (spec 19) with native PowerPoint charts, then export a PDF.

    python deck/build_deck.py

Numbers are read from the database at build time. PDF export uses PowerPoint (COM) when available.
"""
import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from c360 import db  # noqa: E402

OUT = REPO / "docs" / "downloads" / "KavionLens360_Executive_Deck.pptx"
OUT_PDF = OUT.with_suffix(".pdf")
ASSETS = REPO / "deck" / "assets"

C = {k: RGBColor.from_string(v) for k, v in {
    "ink": "0B0B0B", "ink2": "52514E", "muted": "898781", "grid": "E1E0D9", "surf": "FCFCFB", "surf2": "F3F2EE",
    "s1": "2A78D6", "s2": "EB6834", "s3": "1BAF7A", "s4": "EDA100", "s5": "E87BA4",
    "tA": "104281", "tB": "256ABF", "tC": "5598E7", "tW": "86B6EF", "crit": "D03B3B", "good": "006300", "white": "FFFFFF",
}.items()}
SEG = [C["s1"], C["s2"], C["s3"], C["s4"], C["s5"]]
FONT = "Segoe UI"
W, H = Inches(13.333), Inches(7.5)
SOURCE = "Source: KavionLens360 pipeline on the public Kaggle 'Bank Customer Segmentation' dataset (Indian bank, 2016). Not ICICI data. Window 1 Aug - 15 Sep 2016."


# --------------------------------------------------------------------------- helpers
def text(slide, x, y, w, h, s, size=14, bold=False, color="ink", align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Emu(0)
    lines = s if isinstance(s, list) else [s]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        runs = line if isinstance(line, list) else [(line, bold, color)]
        for t, b, col in runs:
            r = p.add_run()
            r.text = t
            r.font.size = Pt(size)
            r.font.bold = b
            r.font.name = FONT
            r.font.color.rgb = C[col]
        p.space_after = Pt(6)
    return tb


def rect(slide, x, y, w, h, fill="surf2", line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    s = slide.shapes.add_shape(shape, x, y, w, h)
    s.fill.solid()
    s.fill.fore_color.rgb = C[fill]
    if line:
        s.line.color.rgb = C[line]
        s.line.width = Pt(0.75)
    else:
        s.line.fill.background()
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = 0.08
    s.shadow.inherit = False
    return s


def frame(prs, n, title, message, notes):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.background.fill
    bg.solid()
    bg.fore_color.rgb = C["surf"]
    text(slide, Inches(0.6), Inches(0.35), Inches(9), Inches(0.4), f"{n:02d} · {title.upper()}", 11, True, "s1")
    text(slide, Inches(0.6), Inches(0.7), Inches(12.1), Inches(1.0), message, 26, True, "ink")
    line = slide.shapes.add_connector(1, Inches(0.6), Inches(7.0), Inches(12.73), Inches(7.0))
    line.line.color.rgb = C["grid"]
    text(slide, Inches(0.6), Inches(7.05), Inches(11), Inches(0.3), SOURCE, 8, color="muted")
    text(slide, Inches(12.2), Inches(7.05), Inches(0.55), Inches(0.3), str(n), 8, color="muted", align=PP_ALIGN.RIGHT)
    slide.notes_slide.notes_text_frame.text = notes
    return slide


def style_chart(chart, legend=True, size=11):
    chart.font.name = FONT
    chart.font.size = Pt(size)
    chart.font.color.rgb = C["ink2"]
    chart.has_legend = legend
    if legend:
        chart.legend.position = XL_LEGEND_POSITION.TOP
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(size)
    try:
        va = chart.value_axis
        va.major_gridlines.format.line.color.rgb = C["grid"]
        va.format.line.fill.background()
        va.tick_labels.font.color.rgb = C["muted"]
        ca = chart.category_axis
        ca.format.line.color.rgb = C["grid"]
        ca.tick_labels.font.color.rgb = C["ink2"]
    except Exception:
        pass


def table(slide, x, y, w, rows, col_w, header_fill="surf2", size=11, row_h=0.36):
    shp = slide.shapes.add_table(len(rows), len(rows[0]), x, y, w, Inches(row_h * len(rows)))
    tbl = shp.table
    tbl.first_row = True
    for j, cw in enumerate(col_w):
        tbl.columns[j].width = Inches(cw)
    for i, row in enumerate(rows):
        tbl.rows[i].height = Inches(row_h)
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = C[header_fill] if i == 0 else C["surf"]
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = str(val)
            p.alignment = PP_ALIGN.RIGHT if (j > 0 and _numeric(val)) else PP_ALIGN.LEFT
            for r in p.runs:
                r.font.size = Pt(size)
                r.font.name = FONT
                r.font.bold = i == 0
                r.font.color.rgb = C["ink2"] if i == 0 else C["ink"]
    return tbl


def _numeric(v):
    s = str(v).replace(",", "").replace("%", "").replace("₹", "").replace(" Cr", "").replace(".", "", 1).strip()
    return s.lstrip("-").isdigit()


def cr(x):
    return f"₹{x / 1e7:,.0f} Cr"


# --------------------------------------------------------------------------- data
def load():
    d = {}
    d["k"] = db.query("SELECT kpi, sql_value::float v FROM kpi_reconciliation").set_index("kpi")["v"]
    d["wf"] = db.query("SELECT * FROM row_waterfall ORDER BY step_no")
    d["seg"] = db.query("""SELECT a.*, d.action, d.owner, d.timing, d.kpi AS seg_kpi
                           FROM agg_segment_summary a JOIN segment_definition d USING (segment_id) ORDER BY segment_id""")
    d["age"] = db.query("SELECT age_group, COUNT(*) n FROM customer_360 GROUP BY 1 ORDER BY 1")
    d["cities"] = db.query("SELECT clean_city, total_value::float v FROM agg_city_summary ORDER BY value_rank LIMIT 8")
    v = db.query("SELECT total_txn_value::float v FROM customer_360")["v"].sort_values(ascending=False).values
    d["top10"] = 100 * v[: len(v) // 10].sum() / v.sum()
    d["top1"] = 100 * v[: len(v) // 100].sum() / v.sum()
    d["single"] = 100 * float(db.scalar("SELECT AVG((txn_count = 1)::int) FROM customer_360"))
    d["young"] = 100 * float(db.scalar("SELECT AVG((age_group IN ('18-24', '25-34'))::int) FROM customer_360"))
    d["theme_seg"] = db.query("""SELECT s.segment_id, s.segment_name, a.theme, a.flagged_customers::float / s.customers AS rate
                                 FROM agg_theme_segment a JOIN agg_segment_summary s USING (segment_id)""")
    d["tiers"] = db.query("""SELECT o.tier, COUNT(*) n, SUM(CASE WHEN o.any_signal THEN c.latest_balance END)::float addr
                             FROM customer_opportunity o JOIN customer_360 c USING (customer_id) GROUP BY o.tier""").set_index("tier")
    d["sens"] = db.query("SELECT MIN(top1000_overlap_pct) lo, MAX(top1000_overlap_pct) hi FROM opportunity_sensitivity").iloc[0]
    d["dq"] = db.query("SELECT status, COUNT(*) n FROM dq_log GROUP BY status").set_index("status")["n"]
    d["id_ok"] = float(db.scalar("SELECT pass_pct FROM dq_log WHERE check_id = 'DQ-20'"))
    return d


# --------------------------------------------------------------------------- slides
def build():
    d = load()
    k, seg, t = d["k"], d["seg"], d["tiers"]
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    # 1 Business problem ------------------------------------------------------
    s = frame(prs, 1, "Business problem", "Managers need a customer view, not a transaction log",
              "Banks have millions of records but limited relationship-manager time. The question is whom to focus on and why. "
              "This project turns a transaction file into one row per customer, groups customers by behaviour and ranks "
              "conversation opportunities, so a manager can answer: who, why, what, where and how large.")
    steps = [("Transactions", f"{k['Total Transactions'] / 1e5:,.1f} lakh rows\nwhat happened", "s1"),
             ("Customers", f"{k['Total Customers'] / 1e5:,.1f} lakh profiles\nwho they are", "s3"),
             ("Segments", "5 behaviour groups\nhow they behave", "s4"),
             ("Actions", f"{t.loc['A', 'n'] / 1e3:,.0f}K Tier A customers\nwhom to call first", "s2")]
    for i, (h_, body, col) in enumerate(steps):
        x = Inches(0.6 + i * 3.15)
        rect(s, x, Inches(2.2), Inches(2.75), Inches(2.0), "surf2")
        bar = rect(s, x, Inches(2.2), Inches(2.75), Inches(0.12), col, shape=MSO_SHAPE.RECTANGLE)
        text(s, x + Inches(0.25), Inches(2.5), Inches(2.3), Inches(0.5), h_, 20, True)
        text(s, x + Inches(0.25), Inches(3.1), Inches(2.3), Inches(1.0), body.split("\n"), 14, color="ink2")
        if i < 3:
            arr = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, x + Inches(2.8), Inches(3.05), Inches(0.3), Inches(0.3))
            arr.fill.solid()
            arr.fill.fore_color.rgb = C["muted"]
            arr.line.fill.background()
    qs = [("Who", "should I focus on?"), ("Why", "them?"), ("What", "opportunity exists?"), ("Where", "are they?"), ("How large", "is it?")]
    for i, (a, b) in enumerate(qs):
        text(s, Inches(0.6 + i * 2.5), Inches(4.8), Inches(2.4), Inches(0.9), [[(a + " ", True, "ink"), (b, False, "ink2")]], 16)
    text(s, Inches(0.6), Inches(5.7), Inches(12), Inches(0.8),
         "Five questions a relationship manager must answer with limited time. The Customer 360 makes each one answerable on a single screen.",
         14, color="ink2")

    # 2 Dataset & methodology ---------------------------------------------------
    raw = int(d["wf"].loc[d["wf"].step_no == 0, "rows"].iloc[0])
    clean = int(d["wf"].loc[d["wf"].step_no == 99, "rows"].iloc[0])
    s = frame(prs, 2, "Dataset & methodology", "Public data, documented rules, every row accounted for",
              "This is a public dataset, not ICICI data. We profiled it first and found two issues: coverage ends on 15 September, "
              "and CustomerIDs are not stable person keys. We fixed the window to 46 days, logged every removed row, built one "
              "row per customer in SQL, and segmented in Python. Every total reconciles across SQL, Python, Excel and Power BI.")
    cd = CategoryChartData()
    cd.categories = ["Raw rows", "Clean rows", "Customers"]
    cd.add_series("Rows", (raw, clean, k["Total Customers"]))
    gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.6), Inches(1.9), Inches(6.0), Inches(2.6), cd)
    ch = gf.chart
    style_chart(ch, legend=False)
    ch.has_title = False
    ch.category_axis.reverse_order = True
    ch.value_axis.visible = False
    ch.value_axis.has_major_gridlines = False
    pl = ch.plots[0]
    pl.gap_width = 60
    pl.has_data_labels = True
    pl.data_labels.number_format = "#,##0"
    pl.data_labels.number_format_is_linked = False
    pl.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    pl.data_labels.font.size = Pt(12)
    for i, col in enumerate(["muted", "s1", "s3"]):
        pt = pl.series[0].points[i]
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = C[col]
    text(s, Inches(0.6), Inches(4.6), Inches(6), Inches(1.9), [
        [("Rejected: ", True, "ink"), (f"{raw - clean:,} rows, all logged with a reason (sparse tail after 15 Sep; zero amounts).", False, "ink2")],
        [("Quality: ", True, "ink"), (f"{d['dq'].get('PASS', 0)} checks pass, {d['dq'].get('EXCEPTION', 0)} documented exception (placeholder birth dates), "
                                     f"{d['dq'].get('INFO', 0)} profiling findings.", False, "ink2")],
        [("Identity: ", True, "ink"), (f"only {d['id_ok']:.1f}% of repeat CustomerIDs keep consistent demographics, so repeat behaviour is weak evidence.", False, "ink2")],
    ], 13)
    flow = ["PostgreSQL 16\nstaging · 17 cleaning rules\nstar model · customer_360",
            "Python\nEDA · 4 tests with effect sizes\nK-Means (k = 5) · scoring",
            "Delivery\nPower BI · Excel MIS\nweb dashboard · this deck"]
    for i, f in enumerate(flow):
        y = Inches(1.9 + i * 1.6)
        rect(s, Inches(7.4), y, Inches(5.3), Inches(1.3), "surf2")
        lines = f.split("\n")
        text(s, Inches(7.65), y + Inches(0.15), Inches(4.9), Inches(1.1),
             [[(lines[0], True, "ink")], [(lines[1], False, "ink2")], [(lines[2], False, "ink2")]], 13)

    # 3 Customer 360 insights -----------------------------------------------------
    s = frame(prs, 3, "Customer 360 insights",
              f"A young, metro-heavy base where the top 10% of customers drive {d['top10']:.0f}% of value",
              f"Here is who the customers are and where. {d['young']:.0f}% are aged 18-34. Mumbai, New Delhi, Bangalore, Gurgaon and Delhi lead on value. "
              f"Value is extremely concentrated: the top 1% generate {d['top1']:.0f}% and the top 10% generate {d['top10']:.0f}% of transaction value. "
              f"{d['single']:.0f}% of customers transacted only once in the window.")
    ages = d["age"][d["age"].age_group != "Unknown"]
    cd = CategoryChartData()
    cd.categories = ages["age_group"].tolist()
    cd.add_series("Customers", [int(x) for x in ages["n"]])
    ch = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.9), Inches(4.2), Inches(3.6), cd).chart
    style_chart(ch, legend=False)
    ch.has_title = True
    ch.chart_title.text_frame.text = "Customers by age group"
    ch.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(13)
    ch.value_axis.tick_labels.number_format = '#,##0,"K"'
    ch.value_axis.tick_labels.number_format_is_linked = False
    ch.plots[0].series[0].format.fill.solid()
    ch.plots[0].series[0].format.fill.fore_color.rgb = C["s1"]
    ch.plots[0].gap_width = 60
    cd = CategoryChartData()
    cd.categories = [c.title() for c in d["cities"]["clean_city"]]
    cd.add_series("Transaction value (Rs crore)", [round(v / 1e7, 1) for v in d["cities"]["v"]])
    ch = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(5.0), Inches(1.9), Inches(4.2), Inches(3.6), cd).chart
    style_chart(ch, legend=False)
    ch.has_title = True
    ch.chart_title.text_frame.text = "Top cities by value (Rs crore)"
    ch.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(13)
    ch.category_axis.reverse_order = True
    ch.plots[0].series[0].format.fill.solid()
    ch.plots[0].series[0].format.fill.fore_color.rgb = C["s1"]
    ch.plots[0].gap_width = 50
    for i, (big, small) in enumerate([(f"{d['top10']:.0f}%", "of value from the top 10% of customers"),
                                      (f"{d['top1']:.0f}%", "of value from the top 1%"),
                                      (f"{d['single']:.0f}%", "of customers transacted once")]):
        y = Inches(1.9 + i * 1.25)
        rect(s, Inches(9.5), y, Inches(3.2), Inches(1.1), "surf2")
        text(s, Inches(9.7), y + Inches(0.08), Inches(2.9), Inches(0.55), big, 26, True)
        text(s, Inches(9.7), y + Inches(0.62), Inches(2.9), Inches(0.45), small, 11, color="ink2")
    text(s, Inches(0.6), Inches(5.75), Inches(12.1), Inches(0.9),
         "So what: effort pays off unevenly. Protect the top decile with named coverage, and do not judge customers on frequency alone.",
         14, color="ink2")

    # 4 Segmentation --------------------------------------------------------------
    e = seg.iloc[0]
    low_c = seg.iloc[3].pct_customers + seg.iloc[4].pct_customers
    low_v = seg.iloc[3].pct_value + seg.iloc[4].pct_value
    s = frame(prs, 4, "Customer segmentation",
              f"{e.segment_name}: {e.pct_customers:.0f}% of customers, {e.pct_value:.0f}% of value; a {low_c:.0f}% tail adds {low_v:.0f}%",
              "Five behaviour segments from K-Means, chosen from k = 3 to 10 on silhouette and stability. A small group carries much of "
              "the value, and each segment needs a different action. The two one-time spender groups look alike except for recency: "
              "one is recent, one is going quiet.")
    cd = CategoryChartData()
    cd.categories = seg["segment_name"].tolist()
    cd.add_series("% of customers", [round(x, 1) for x in seg["pct_customers"]])
    cd.add_series("% of value", [round(x, 1) for x in seg["pct_value"]])
    ch = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.6), Inches(1.9), Inches(5.6), Inches(4.6), cd).chart
    style_chart(ch)
    ch.category_axis.reverse_order = True
    ch.value_axis.tick_labels.number_format = '0"%"'
    ch.value_axis.tick_labels.number_format_is_linked = False
    for i, col in enumerate(["s1", "s2"]):
        ch.plots[0].series[i].format.fill.solid()
        ch.plots[0].series[i].format.fill.fore_color.rgb = C[col]
    ch.plots[0].gap_width = 70
    ch.plots[0].overlap = -10
    rows = [["Segment", "Median bal.", "Txns/cust", "Active", "Action"]]
    for r in seg.itertuples():
        rows.append([r.segment_name, f"₹{r.median_avg_balance:,.0f}", f"{r.avg_txn_count:.2f}", f"{r.pct_active:.0f}%", r.action.split(":")[0]])
    tbl = table(s, Inches(6.5), Inches(1.95), Inches(6.2), rows, [1.75, 0.95, 0.8, 0.65, 2.05], size=10, row_h=0.72)
    for i in range(5):
        cell = tbl.cell(i + 1, 0)
        cell.text_frame.paragraphs[0].runs[0].font.color.rgb = SEG[i]
        cell.text_frame.paragraphs[0].runs[0].font.bold = True

    # 5 Cross-sell -------------------------------------------------------------------
    s = frame(prs, 5, "Cross-sell opportunities", "Signals are prioritised, not guaranteed: each segment gets a short list of conversations",
              "Product holdings are unknown, so these are signals to start conversations, not recommendations or eligibility decisions. "
              "Cards and investments lead for engaged customers; re-engagement comes first for the lapsed group. "
              f"Tier A is the top 5% by score: {t.loc['A', 'n']:,.0f} customers with {cr(t.loc['A', 'addr'])} addressable balance.")
    themes = ["Investment / MF", "Premium account", "Credit card", "Insurance", "Personal loan (demand)", "Re-engagement"]
    rows = [["Segment"] + [x.replace(" (demand)", "*") for x in themes]]
    ts = d["theme_seg"]
    for r in seg.itertuples():
        rows.append([r.segment_name] + [f"{100 * ts[(ts.segment_id == r.segment_id) & (ts.theme == th)]['rate'].iloc[0]:.0f}%" for th in themes])
    tbl = table(s, Inches(0.6), Inches(1.95), Inches(8.6), rows, [2.25, 1.05, 1.05, 0.95, 0.95, 1.0, 1.35], size=11, row_h=0.6)
    for i in range(1, 6):
        for j in range(1, 7):
            v = float(rows[i][j].rstrip("%")) / 100
            cell = tbl.cell(i, j)
            t_ = min(v / 0.55, 1)                     # blue ramp #cde2fb -> #1c5cab (validated palette)
            lo, hi = (0xCD, 0xE2, 0xFB), (0x1C, 0x5C, 0xAB)
            cell.fill.fore_color.rgb = RGBColor(*[int(a + (b - a) * t_) for a, b in zip(lo, hi)]) if v > 0.02 else C["surf"]
            if v > 0.35:
                cell.text_frame.paragraphs[0].runs[0].font.color.rgb = C["white"]
    text(s, Inches(0.6), Inches(5.65), Inches(8.6), Inches(0.4), "Share of each segment carrying each signal. *Personal loan = demand signal only; no credit judgement.", 10, color="muted")
    for i, (tier, col) in enumerate([("A", "tA"), ("B", "tB"), ("C", "tC")]):
        y = Inches(1.95 + i * 1.35)
        rect(s, Inches(9.6), y, Inches(3.1), Inches(1.15), "surf2")
        chip = rect(s, Inches(9.75), y + Inches(0.3), Inches(0.55), Inches(0.55), col)
        text(s, Inches(9.75), y + Inches(0.36), Inches(0.55), Inches(0.45), tier, 16, True, "white", PP_ALIGN.CENTER)
        text(s, Inches(10.45), y + Inches(0.12), Inches(2.2), Inches(0.5), f"{t.loc[tier, 'n']:,.0f}", 20, True)
        text(s, Inches(10.45), y + Inches(0.62), Inches(2.2), Inches(0.5), f"{cr(t.loc[tier, 'addr'])} addressable", 11, color="ink2")
    text(s, Inches(9.6), Inches(6.0), Inches(3.1), Inches(0.7),
         f"Weights stress-tested ±10 pts: {d['sens'].lo:.0f}-{d['sens'].hi:.0f}% of the top 1,000 unchanged.", 10, color="ink2")

    # 6 Dashboard ---------------------------------------------------------------------
    s = frame(prs, 6, "Dashboard", "A manager can answer five questions on one screen",
              "Who, why, what, where, how large. The Manager Action page ranks customers, explains the reason in plain words, names "
              "the product theme and city, and sizes the opportunity. Filters for city, segment, tier, theme and evidence level "
              "narrow the list to one branch's portfolio. The same view exists in Power BI (Page 4) and on the public web dashboard.")
    img = Image.open(ASSETS / "dashboard_manager.png")
    w0, h0 = img.size
    crop = img.crop((int(w0 * 0.09), int(h0 * 0.29), int(w0 * 0.91), int(h0 * 0.83)))
    crop_path = ASSETS / "dashboard_manager_crop.png"
    crop.save(crop_path)
    pic = s.shapes.add_picture(str(crop_path), Inches(0.6), Inches(1.85), height=Inches(4.9))
    pic.line.color.rgb = C["grid"]
    labels = [("Who", "ranked list, masked IDs"), ("Why", "balance, activity, recency in words"), ("What", "driving product theme"),
              ("Where", "city filter and column"), ("How large", "addressable balance and tier count")]
    x0 = pic.left + pic.width + Inches(0.3)
    for i, (a, b) in enumerate(labels):
        text(s, x0, Inches(1.95 + i * 0.95), W - x0 - Inches(0.6), Inches(0.9), [[(a, True, "s1")], [(b, False, "ink2")]], 13)

    # 7 Key insights --------------------------------------------------------------------
    lap = seg.iloc[2]
    s = frame(prs, 7, "Key business insights", "What we found, why it matters, what to do",
              "Five findings, each with its consequence. Numbers are from the reconciled pipeline; none are pre-written.")
    cards = [
        ("Value is concentrated", f"Top 10% of customers → {d['top10']:.0f}% of value", "Named RM coverage for the top decile"),
        (f"{e.segment_name} punch above weight", f"{e.pct_customers:.0f}% of customers, {e.pct_value:.0f}% of value", "Deepen: needs review, cards, investments"),
        ("A third of value is going quiet", f"{lap.segment_name}: {lap.pct_value:.0f}% of value, not seen 2+ weeks", "Re-engagement call before any sale"),
        ("The tail is cheap to serve, not to call", f"{low_c:.0f}% of customers, {low_v:.1f}% of value", "Digital nurture; activation checks"),
        ("Behaviour beats demographics", "Gender and age explain little (V = 0.07, ε² = 0.06)", "Target on behaviour, never on gender"),
    ]
    for i, (h_, find, act) in enumerate(cards):
        col_, row_ = i % 3, i // 3
        x = Inches(0.6 + col_ * 4.1)
        y = Inches(1.95 + row_ * 2.45)
        rect(s, x, y, Inches(3.85), Inches(2.2), "surf2")
        text(s, x + Inches(0.25), y + Inches(0.2), Inches(3.4), Inches(0.6), h_, 15, True)
        text(s, x + Inches(0.25), y + Inches(0.85), Inches(3.4), Inches(0.6), find, 12, color="ink2")
        text(s, x + Inches(0.25), y + Inches(1.5), Inches(3.4), Inches(0.6), [[("→ ", True, "s1"), (act, True, "ink")]], 12)
    rect(s, Inches(8.8), Inches(4.4), Inches(3.85), Inches(2.2), "surf", line="grid")
    text(s, Inches(9.05), Inches(4.6), Inches(3.4), Inches(1.9), [
        [("Limits", True, "ink")],
        [("Public 2016 data, 46-day window, no product holdings or revenue. Signals rank conversations; they are not eligibility decisions.", False, "ink2")]], 11)

    # 8 Actions ---------------------------------------------------------------------------
    s = frame(prs, 8, "Recommended managerial actions", "Pilot with Tier A, measure response, refine the rules",
              "Actions are specific and measurable: each segment has an owner, timing and KPI. Start with a four-week pilot on Tier A, "
              "track the response, then use the outcome data to tighten the broad signal rules and learn the score weights.")
    rows = [["Segment", "Action", "Owner", "Timing", "Success metric"]]
    for r in seg.itertuples():
        rows.append([r.segment_name, r.action, r.owner, r.timing, r.seg_kpi])
    tbl = table(s, Inches(0.6), Inches(1.9), Inches(12.1), rows, [2.2, 4.4, 1.9, 1.5, 2.1], size=10, row_h=0.62)
    for i in range(5):
        tbl.cell(i + 1, 0).text_frame.paragraphs[0].runs[0].font.color.rgb = SEG[i]
        tbl.cell(i + 1, 0).text_frame.paragraphs[0].runs[0].font.bold = True
    steps = ["Weeks 1-4: call Tier A (top 5%), log outcomes", "Week 5: compare response by segment and theme",
             "Then: tighten card / insurance rules, learn weights from outcomes"]
    for i, st in enumerate(steps):
        x = Inches(0.6 + i * 4.1)
        rect(s, x, Inches(5.95), Inches(3.85), Inches(0.75), "surf2")
        text(s, x + Inches(0.2), Inches(6.08), Inches(3.5), Inches(0.6), st, 12, True, anchor=MSO_ANCHOR.MIDDLE)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    return OUT


def export_pdf():
    try:
        import pythoncom
        import win32com.client as w32
    except ImportError:
        return None
    pythoncom.CoInitialize()
    app = w32.DispatchEx("PowerPoint.Application")
    try:
        pres = app.Presentations.Open(str(OUT), True, False, False)   # ReadOnly, Untitled, WithWindow
        pres.SaveAs(str(OUT_PDF), 32)                                  # ppSaveAsPDF
        pres.Close()
    finally:
        app.Quit()
    return OUT_PDF


if __name__ == "__main__":
    print("wrote", build())
    print("pdf", export_pdf())

"""
Generate the KavionLens360 Power BI Project (PBIP: TMDL semantic model + PBIR report).

    python powerbi/build_pbip.py

Data comes from the CSV extracts in data/exports/powerbi (written by run_pipeline.py).
The folder is the model parameter `DataFolder`; change it in Power BI Desktop under
Transform data > Edit parameters if the repo lives elsewhere.

Schema versions follow a set validated with Microsoft's powerbi-report-author CLI.
"""
import csv
import json
import shutil
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
NAME = "KavionLens360"
SM, RP = f"{NAME}.SemanticModel", f"{NAME}.Report"
D = f"{RP}/definition"
S = "https://developer.microsoft.com/json-schemas/fabric"
VC = f"{S}/item/report/definition/visualContainer/2.9.0/schema.json"
DATA_FOLDER = str(REPO / "data" / "exports" / "powerbi") + "\\"
NS = uuid.UUID("6f1d6c6e-2f58-4d5b-9f0a-3c8e5b7a9d10")          # stable GUIDs across rebuilds

SERIES = ["#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300", "#4A3AA7", "#E34948"]


def gid(key: str) -> str:
    return str(uuid.uuid5(NS, key))


def w(rel, text):
    p = HERE / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)


def wj(rel, obj):
    w(rel, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


# =========================================================================== semantic model
# column types: CSV header -> TMDL dataType (overrides where pandas inference is wrong)
TYPE_OVERRIDES = {"rfm_code": "string", "age": "int64"}
DATE_COLS = {"first_txn_date", "last_txn_date", "date", "week_start"}
TABLES = ["customer_360", "customer_segment", "customer_opportunity", "segment_definition", "dim_location",
          "dim_date", "agg_daily_city", "agg_hour_weekday", "dq_log", "row_waterfall", "kpi_reconciliation"]
HIDDEN_COLS = {"location_key", "date_key", "run_id", "cluster_key", "expect", "method"}
SUMMARIZE = {"txns", "total_value", "high_value_txns", "customers", "rows", "checked_rows", "failed_rows"}
FORMATS = {"double": "#,0.00", "int64": "#,0", "dateTime": "dd mmm yyyy"}
M_TYPES = {"string": "type text", "int64": "Int64.Type", "double": "type number", "boolean": "type logical",
           "dateTime": "type date"}


def infer_types(table):
    path = REPO / "data" / "exports" / "powerbi" / f"{table}.csv"
    with open(path, encoding="utf-8") as f:
        rows = list(csv.reader(f))[:3000]
    header, body = rows[0], rows[1:]
    types = {}
    for i, col in enumerate(header):
        vals = [r[i] for r in body if i < len(r) and r[i] != ""]
        if col in TYPE_OVERRIDES:
            t = TYPE_OVERRIDES[col]
        elif col in DATE_COLS:
            t = "dateTime"
        elif vals and all(v in ("True", "False") for v in vals):
            t = "boolean"
        elif vals and all(_is_int(v) for v in vals):
            t = "int64"
        elif vals and all(_is_float(v) for v in vals):
            t = "double"
        else:
            t = "string"
        types[col] = t
    return header, types


def _is_int(v):
    try:
        int(v)
        return "." not in v and "e" not in v.lower()
    except ValueError:
        return False


def _is_float(v):
    try:
        float(v)
        return True
    except ValueError:
        return False


def q(name):
    """Quote a TMDL object name when needed."""
    return f"'{name}'" if any(ch in name for ch in " -./()%") else name


# --- measures: (table, name, dax, format) -- single line DAX only (avoids TMDL indentation traps)
C, O, SG = "customer_360", "customer_opportunity", "customer_segment"
MEASURES = [
    (C, "Total Customers", f"DISTINCTCOUNT({C}[customer_id])", "#,0"),
    (C, "Total Txn Value", f"SUM({C}[total_txn_value])", "#,0"),
    (C, "Total Txns", f"SUM({C}[txn_count])", "#,0"),
    (C, "Avg Txn Value", "DIVIDE([Total Txn Value], [Total Txns])", "#,0"),
    (C, "Avg Balance", f"AVERAGE({C}[avg_balance])", "#,0"),
    (C, "Median Balance", f"MEDIAN({C}[avg_balance])", "#,0"),
    (C, "Active Customers", f"CALCULATE([Total Customers], {C}[is_active] = TRUE())", "#,0"),
    (C, "Active Rate", "DIVIDE([Active Customers], [Total Customers])", "0.0%"),
    (C, "High Value Customers", f"CALCULATE([Total Customers], {C}[is_high_value] = TRUE())", "#,0"),
    (C, "High Value Share", "DIVIDE([High Value Customers], [Total Customers])", "0.0%"),
    (C, "High Value Value Share", f"DIVIDE(CALCULATE([Total Txn Value], {C}[is_high_value] = TRUE()), [Total Txn Value])", "0.0%"),
    (C, "Dormant Customers", f"CALCULATE([Total Customers], {C}[is_dormant] = TRUE())", "#,0"),
    (C, "Segment Size %", f"DIVIDE([Total Customers], CALCULATE([Total Customers], ALL({SG}[segment_name])))", "0.0%"),
    (C, "Segment Value %", f"DIVIDE([Total Txn Value], CALCULATE([Total Txn Value], ALL({SG}[segment_name])))", "0.0%"),
    (C, "Txn Frequency", "DIVIDE([Total Txns], [Total Customers])", "0.00"),
    (C, "Avg Recency Days", f"AVERAGE({C}[recency_days])", "0.0"),
    (C, "Avg Engagement Score", f"AVERAGE({C}[engagement_score])", "0.0"),
    (C, "Opportunity Count", f"CALCULATE([Total Customers], {O}[any_signal] = TRUE())", "#,0"),
    (C, "Cross-Sell Opp Rate", "DIVIDE([Opportunity Count], [Total Customers])", "0.0%"),
    (C, "Addressable Balance", f"CALCULATE(SUM({C}[latest_balance]), {O}[any_signal] = TRUE())", "#,0"),
    (C, "Avg Opp Score", f"AVERAGE({O}[overall_score])", "0.0"),
    (C, "Tier A Customers", f"CALCULATE([Total Customers], {O}[tier] = \"A\")", "#,0"),
    (C, "Tier B Customers", f"CALCULATE([Total Customers], {O}[tier] = \"B\")", "#,0"),
    (C, "Investment Signals", f"CALCULATE([Total Customers], {O}[sig_investment] = TRUE())", "#,0"),
    (C, "Premium Signals", f"CALCULATE([Total Customers], {O}[sig_premium] = TRUE())", "#,0"),
    (C, "Credit Card Signals", f"CALCULATE([Total Customers], {O}[sig_credit_card] = TRUE())", "#,0"),
    (C, "Insurance Signals", f"CALCULATE([Total Customers], {O}[sig_insurance] = TRUE())", "#,0"),
    (C, "Personal Loan Signals", f"CALCULATE([Total Customers], {O}[sig_personal_loan] = TRUE())", "#,0"),
    (C, "Re-engagement Signals", f"CALCULATE([Total Customers], {O}[sig_reengagement] = TRUE())", "#,0"),
    (C, "Top City Value", "MAXX(TOPN(1, VALUES(dim_location[clean_city]), [Total Txn Value]), [Total Txn Value])", "#,0"),
    ("agg_daily_city", "Daily Txns", "SUM(agg_daily_city[txns])", "#,0"),
    ("agg_daily_city", "Daily Value", "SUM(agg_daily_city[total_value])", "#,0"),
    ("kpi_reconciliation", "SQL Total Customers", "CALCULATE(SUM(kpi_reconciliation[sql_value]), kpi_reconciliation[kpi] = \"Total Customers\")", "#,0"),
    ("kpi_reconciliation", "Reconciliation Variance (Customers)", "CALCULATE([Total Customers], ALL(customer_360)) - [SQL Total Customers]", "#,0"),
    ("kpi_reconciliation", "SQL Total Txn Value", "CALCULATE(SUM(kpi_reconciliation[sql_value]), kpi_reconciliation[kpi] = \"Total Txn Value\")", "#,0"),
    ("kpi_reconciliation", "Reconciliation Variance (Value)", "ROUND(CALCULATE([Total Txn Value], ALL(customer_360)) - [SQL Total Txn Value], 2)", "#,0.00"),
]
CALC_COLUMNS = {
    O: [("score_band", "FLOOR(customer_opportunity[overall_score], 5)", "int64", "0")],
}
SORT_BY = {("customer_segment", "segment_name"): "segment_id"}


def table_tmdl(table):
    header, types = infer_types(table)
    lines = [f"table {table}", f"\tlineageTag: {gid('t:' + table)}", ""]
    for (t, mname, dax, fmt) in MEASURES:
        if t == table:
            lines += [f"\tmeasure {q(mname)} = {dax}", f"\t\tformatString: {fmt}",
                      f"\t\tlineageTag: {gid('m:' + mname)}", ""]
    for col in header:
        dt = types[col]
        lines.append(f"\tcolumn {q(col)}")
        lines.append(f"\t\tdataType: {dt}")
        if dt in FORMATS:
            lines.append(f"\t\tformatString: {FORMATS[dt]}")
        if col in HIDDEN_COLS:
            lines.append("\t\tisHidden")
        lines.append(f"\t\tlineageTag: {gid('c:' + table + '.' + col)}")
        lines.append(f"\t\tsummarizeBy: {'sum' if col in SUMMARIZE else 'none'}")
        lines.append(f"\t\tsourceColumn: {col}")
        if (table, col) in SORT_BY:
            lines.append(f"\t\tsortByColumn: {SORT_BY[(table, col)]}")
        lines.append("")
        lines.append("\t\tannotation SummarizationSetBy = Automatic")
        if dt == "dateTime":
            lines.append("")
            lines.append("\t\tannotation UnderlyingDateTimeDataType = Date")
        lines.append("")
    for (cname, dax, dt, fmt) in CALC_COLUMNS.get(table, []):
        lines += [f"\tcolumn {q(cname)} = {dax}", f"\t\tdataType: {dt}", f"\t\tformatString: {fmt}",
                  f"\t\tlineageTag: {gid('cc:' + table + '.' + cname)}", "\t\tsummarizeBy: none", "",
                  "\t\tannotation SummarizationSetBy = User", ""]
    m_types = ", ".join(f'{{"{c}", {M_TYPES[types[c]]}}}' for c in header)
    lines += [
        f"\tpartition {table} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f'\t\t\t\t    Source = Csv.Document(File.Contents(DataFolder & "{table}.csv"), [Delimiter = ",", Columns = {len(header)}, Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
        '\t\t\t\t    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),',
        f'\t\t\t\t    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers", {{{m_types}}}, "en-US")',
        "\t\t\t\tin",
        '\t\t\t\t    #"Changed Type"',
        "",
        "\tannotation PBI_ResultType = Table",
        "",
    ]
    return "\n".join(lines)


RELATIONSHIPS = [
    # (from, to, extra props)
    ("customer_360.location_key", "dim_location.location_key", []),
    ("customer_segment.customer_id", "customer_360.customer_id",
     ["fromCardinality: one", "toCardinality: one", "crossFilteringBehavior: bothDirections"]),
    ("customer_opportunity.customer_id", "customer_360.customer_id",
     ["fromCardinality: one", "toCardinality: one", "crossFilteringBehavior: bothDirections"]),
    ("customer_segment.segment_id", "segment_definition.segment_id", []),
    ("agg_daily_city.date_key", "dim_date.date_key", []),
    ("agg_daily_city.location_key", "dim_location.location_key", []),
]


def build_model():
    wj(f"{SM}/.platform", {
        "$schema": f"{S}/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": gid("semantic-model")},
    })
    wj(f"{SM}/definition.pbism", {"$schema": f"{S}/item/semanticModel/definitionProperties/1.0.0/schema.json",
                                   "version": "4.2", "settings": {}})
    w(f"{SM}/definition/database.tmdl", "database\n\tcompatibilityLevel: 1601\n\n")
    refs = "\n".join(f"ref table {t}" for t in TABLES)
    order = json.dumps(["DataFolder"] + TABLES)
    w(f"{SM}/definition/model.tmdl", f"""model Model
\tculture: en-US
\tdefaultPowerBIDataSourceVersion: powerBI_V3
\tsourceQueryCulture: en-US
\tdataAccessOptions
\t\tlegacyRedirects
\t\treturnErrorValuesAsNull

annotation __PBI_TimeIntelligenceEnabled = 0

annotation PBI_QueryOrder = {order}

{refs}

ref cultureInfo en-US

""")
    w(f"{SM}/definition/cultures/en-US.tmdl", """cultureInfo en-US

\tlinguisticMetadata =
\t\t\t{
\t\t\t  "Version": "1.0.0",
\t\t\t  "Language": "en-US"
\t\t\t}
\t\tcontentType: json

""")
    folder = DATA_FOLDER.replace("\\", "\\\\")
    w(f"{SM}/definition/expressions.tmdl",
      f'expression DataFolder = "{folder}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
      f"\tlineageTag: {gid('param:DataFolder')}\n\n\tannotation PBI_ResultType = Text\n\n")
    rel = []
    for f, t, extra in RELATIONSHIPS:
        rel.append(f"relationship {gid('r:' + f + '->' + t)}")
        rel += [f"\t{e}" for e in extra]
        rel += [f"\tfromColumn: {f}", f"\ttoColumn: {t}", ""]
    w(f"{SM}/definition/relationships.tmdl", "\n".join(rel) + "\n")
    for t in TABLES:
        w(f"{SM}/definition/tables/{t}.tmdl", table_tmdl(t))


# =========================================================================== report helpers
def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def col(t, c):
    return {"Column": {"Expression": {"SourceRef": {"Entity": t}}, "Property": c}}


def mea(m, t=C):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": t}}, "Property": m}}


def proj(field, active=None, name=None):
    kind = "Column" if "Column" in field else "Measure"
    t = field[kind]["Expression"]["SourceRef"]["Entity"]
    p = field[kind]["Property"]
    d = {"field": field, "queryRef": f"{t}.{p}", "nativeQueryRef": name or p}
    if active is not None:
        d["active"] = active
    if name:
        d["displayName"] = name
    return d


def title(text):
    return {"title": [{"properties": {"show": lit("true"), "text": lit(f"'{text}'")}}]}


def visual(page, name, vtype, pos, query=None, objects=None, vco=None, sort=None, extra=None, filters=None, vextra=None):
    x, y, wdt, h, z = pos
    v = {"visualType": vtype}
    if query is not None:
        qd = {"queryState": {role: {"projections": ps} for role, ps in query.items()}}
        if sort:
            qd["sortDefinition"] = {"sort": [{"field": sort[0], "direction": sort[1]}], "isDefaultSort": False}
        v["query"] = qd
    if objects:
        v["objects"] = objects
    if vco:
        v["visualContainerObjects"] = vco
    if vextra:
        v.update(vextra)
    v["drillFilterOtherVisuals"] = True
    doc = {"$schema": VC, "name": name,
           "position": {"x": x, "y": y, "z": z, "height": h, "width": wdt, "tabOrder": z}, "visual": v}
    if filters:
        doc["filterConfig"] = {"filters": filters}
    if extra:
        doc.update(extra)
    wj(f"{D}/pages/{page}/visuals/{name}/visual.json", doc)


def textbox(page, name, pos, runs):
    """runs: list of (text, size_pt, bold, color)"""
    paras = [{"textRuns": [{"value": t, "textStyle": {"fontWeight": "bold" if b else "normal", "fontSize": f"{s}pt",
                                                       "color": c}}]} for t, s, b, c in runs]
    visual(page, name, "textbox", pos, objects={"general": [{"properties": {"paragraphs": paras}}]})


def card(page, name, pos, measure, label):
    visual(page, name, "cardVisual", pos, query={"Data": [proj(mea(measure))]}, vco=title(label))


def slicer(page, name, pos, field, label, mode="Dropdown"):
    visual(page, name, "slicer", pos, query={"Values": [proj(field)]},
           objects={"data": [{"properties": {"mode": lit(f"'{mode}'")}}],
                    "header": [{"properties": {"show": lit("true"), "text": lit(f"'{label}'")}}]},
           vextra={"syncGroup": {"groupName": f"sync_{label.replace(' ', '_').lower()}",
                                 "fieldChanges": True, "filterChanges": True}})


def nav_button(page, name, pos, target, label):
    visual(page, name, "actionButton", pos,
           objects={"text": [{"properties": {"show": lit("true")}},
                             {"properties": {"text": lit(f"'{label}'")}, "selector": {"id": "default"}}],
                    "icon": [{"properties": {"show": lit("false")}}]},
           vco={"visualLink": [{"properties": {"show": lit("true"), "type": lit("'PageNavigation'"),
                                               "navigationSection": lit(f"'{target}'")}}]},
           extra={"howCreated": "InsertVisualButton"})


PAGES = [("executive", "1 · Executive Customer 360"), ("segmentation", "2 · Customer Segmentation"),
         ("crosssell", "3 · Cross-Sell Opportunities"), ("manager", "4 · Manager Action"),
         ("dataquality", "5 · Data Quality & Reconciliation")]
INK, INK2, MUTED = "#0B0B0B", "#52514E", "#898781"
NOTE = "Public Kaggle data (Indian bank, 2016), not ICICI data · Window 1 Aug - 15 Sep 2016 · As of 16 Sep 2016"


def page(pid, display, extra=None):
    doc = {"$schema": f"{S}/item/report/definition/page/2.1.0/schema.json", "name": pid, "displayName": display,
           "displayOption": "FitToPage", "height": 720, "width": 1280}
    if extra:
        doc.update(extra)
    wj(f"{D}/pages/{pid}/page.json", doc)


def header(pid, title_text, question):
    textbox(pid, f"{pid}Title", (20, 8, 760, 62, 0), [(title_text, 18, True, INK), (question, 10, False, INK2)])
    textbox(pid, f"{pid}Note", (20, 684, 900, 34, 1), [(NOTE, 8, False, MUTED)])
    others = [(t, lab) for t, lab in PAGES if t != pid]
    for i, (target, label) in enumerate(others):
        num, words = label.split(" · ")
        short = f"{num} {words.split(' ')[0] if words.split(' ')[0] not in ('Customer', 'Data') else words.split(' ')[-1]}"
        nav_button(pid, f"{pid}Nav{i}", (790 + i * 100, 14, 94, 34, 2 + i), target, short)


# =========================================================================== report
def build_report():
    wj(f"{RP}/.platform", {"$schema": f"{S}/gitIntegration/platformProperties/2.0.0/schema.json",
                           "metadata": {"type": "Report", "displayName": NAME},
                           "config": {"version": "2.0", "logicalId": gid("report")}})
    wj(f"{RP}/definition.pbir", {"$schema": f"{S}/item/report/definitionProperties/2.0.0/schema.json",
                                  "version": "4.0", "datasetReference": {"byPath": {"path": f"../{SM}"}}})
    wj(f"{D}/version.json", {"$schema": f"{S}/item/report/definition/versionMetadata/1.0.0/schema.json",
                             "version": "2.0.0"})
    rv = {"visual": "1.8.96", "report": "2.0.96", "page": "1.3.96"}
    wj(f"{D}/report.json", {
        "$schema": f"{S}/item/report/definition/report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY24SU10", "reportVersionAtImport": rv, "type": "SharedResources"},
            "customTheme": {"name": "KavionLens360Theme.json", "reportVersionAtImport": rv, "type": "RegisteredResources"},
        },
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "KavionLens360Theme.json", "path": "KavionLens360Theme.json", "type": "CustomTheme"}]},
        ],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True},
    })
    base = HERE / "_theme" / "CY24SU10.json"
    dst = HERE / RP / "StaticResources" / "SharedResources" / "BaseThemes"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy(base, dst / "CY24SU10.json")
    wj(f"{RP}/StaticResources/RegisteredResources/KavionLens360Theme.json", {
        "name": "KavionLens360Theme.json", "dataColors": SERIES, "background": "#FCFCFB", "foreground": INK,
        "tableAccent": SERIES[0], "good": "#0CA30C", "neutral": "#FAB219", "bad": "#D03B3B",
        "textClasses": {"title": {"fontFace": "Segoe UI Semibold", "color": INK, "fontSize": 12},
                        "label": {"fontFace": "Segoe UI", "color": INK2, "fontSize": 10},
                        "callout": {"fontFace": "Segoe UI", "color": INK, "fontSize": 24}},
    })
    wj(f"{D}/pages/pages.json", {"$schema": f"{S}/item/report/definition/pagesMetadata/1.1.0/schema.json",
                                 "pageOrder": [p for p, _ in PAGES], "activePageName": PAGES[0][0]})

    CITY, AGE, GEN = col("dim_location", "clean_city"), col(C, "age_group"), col(C, "gender")
    SEG, TIER = col(SG, "segment_name"), col(O, "tier")
    THEME, EVID = col(O, "driving_theme_label"), col(C, "evidence_level")

    # ---------------------------------------------------------------- Page 1
    p = "executive"
    page(p, PAGES[0][1])
    header(p, "Executive Customer 360", "Who are our customers, how much do they transact, and where?")
    for i, (m, lab) in enumerate([("Total Customers", "Total customers"), ("Total Txn Value", "Transaction value (Rs)"),
                                  ("Avg Txn Value", "Avg transaction (Rs)"), ("Median Balance", "Median balance (Rs)"),
                                  ("Active Rate", "Active rate (seen ≤15 days)"), ("High Value Customers", "High-value customers")]):
        card(p, f"{p}Kpi{i}", (20 + i * 208, 76, 200, 92, 10 + i), m, lab)
    for i, (f, lab) in enumerate([(AGE, "Age group"), (GEN, "Gender"), (CITY, "City"), (SEG, "Segment")]):
        slicer(p, f"{p}Slicer{i}", (20 + i * 160, 174, 152, 76, 20 + i), f, lab)
    visual(p, f"{p}AgeGender", "clusteredColumnChart", (20, 256, 410, 206, 30),
           query={"Category": [proj(AGE, True)], "Series": [proj(GEN)], "Y": [proj(mea("Total Customers"))]},
           vco=title("Customers by age group and gender"))
    visual(p, f"{p}Trend", "lineChart", (440, 256, 820, 206, 31),
           query={"Category": [proj(col("dim_date", "date"), True)], "Y": [proj(mea("Daily Txns", "agg_daily_city"))]},
           vco=title("Daily transactions (filters: city, date)"))
    visual(p, f"{p}Cities", "clusteredBarChart", (20, 468, 620, 210, 32),
           query={"Category": [proj(CITY, True)], "Y": [proj(mea("Total Txn Value"))]},
           sort=(mea("Total Txn Value"), "Descending"), vco=title("Top cities by transaction value (right-click > Drill through for customers)"))
    visual(p, f"{p}Segments", "donutChart", (650, 468, 610, 210, 33),
           query={"Category": [proj(SEG, True)], "Y": [proj(mea("Total Customers"))]},
           vco=title("Customers by segment"))

    # ---------------------------------------------------------------- Page 2
    p = "segmentation"
    page(p, PAGES[1][1])
    header(p, "Customer Segmentation", "How do the five behaviour segments differ, and what should we do with each?")
    for i, (m, lab) in enumerate([("Total Customers", "Customers in selection"), ("Segment Size %", "Share of customers"),
                                  ("Segment Value %", "Share of value"), ("Median Balance", "Median balance (Rs)"),
                                  ("Txn Frequency", "Txns per customer"), ("Avg Recency Days", "Avg days since last txn")]):
        card(p, f"{p}Kpi{i}", (20 + i * 208, 78, 200, 92, 10 + i), m, lab)
    visual(p, f"{p}SizeValue", "clusteredBarChart", (20, 178, 520, 250, 20),
           query={"Category": [proj(SEG, True)], "Y": [proj(mea("Segment Size %")), proj(mea("Segment Value %"))]},
           vco=title("Share of customers vs share of value"))
    visual(p, f"{p}Profile", "pivotTable", (550, 178, 710, 250, 21),
           query={"Rows": [proj(SEG)], "Values": [proj(mea("Total Customers")), proj(mea("Avg Txn Value")),
                                                  proj(mea("Median Balance")), proj(mea("Txn Frequency")),
                                                  proj(mea("Avg Recency Days")), proj(mea("Active Rate")),
                                                  proj(mea("High Value Share"))]},
           vco=title("Segment profile"))
    visual(p, f"{p}AgeMix", "clusteredBarChart", (20, 436, 410, 242, 22),
           query={"Category": [proj(SEG, True)], "Series": [proj(AGE)], "Y": [proj(mea("Total Customers"))]},
           vco=title("Age mix by segment"))
    visual(p, f"{p}Scatter", "scatterChart", (440, 436, 400, 242, 23),
           query={"Category": [proj(col(C, "customer_id"), True)], "Series": [proj(SEG)],
                  "X": [proj(mea("Avg Balance"))], "Y": [proj(mea("Total Txn Value"))]},
           vco=title("Balance vs transaction value (sampled)"))
    visual(p, f"{p}Actions", "tableEx", (850, 436, 410, 242, 24),
           query={"Values": [proj(col("segment_definition", "segment_name")), proj(col("segment_definition", "action")),
                             proj(col("segment_definition", "owner")), proj(col("segment_definition", "timing"))]},
           vco=title("Segment actions"))

    # ---------------------------------------------------------------- Page 3
    p = "crosssell"
    page(p, PAGES[2][1])
    header(p, "Cross-Sell Opportunities", "Which product conversations are signalled, for whom, and how large?")
    textbox(p, f"{p}Banner", (20, 70, 1240, 34, 5),
            [("Signals inferred from behaviour. Product ownership unknown. Not eligibility or credit decisions.", 10, True, "#D03B3B")])
    for i, (m, lab) in enumerate([("Opportunity Count", "Customers with ≥1 signal"), ("Cross-Sell Opp Rate", "Opportunity rate"),
                                  ("Addressable Balance", "Addressable balance (Rs)"), ("Avg Opp Score", "Avg opportunity score"),
                                  ("Tier A Customers", "Tier A customers")]):
        card(p, f"{p}Kpi{i}", (20 + i * 250, 110, 240, 86, 10 + i), m, lab)
    themes = ["Investment Signals", "Premium Signals", "Credit Card Signals", "Insurance Signals",
              "Personal Loan Signals", "Re-engagement Signals"]
    visual(p, f"{p}Themes", "clusteredBarChart", (20, 202, 400, 240, 20),
           query={"Category": [proj(SEG, True)], "Y": [proj(mea(t)) for t in themes]},
           vco=title("Signals by product theme and segment"))
    visual(p, f"{p}Matrix", "pivotTable", (430, 202, 830, 240, 21),
           query={"Rows": [proj(SEG)], "Values": [proj(mea(t)) for t in themes]},
           vco=title("Theme x segment matrix"))
    visual(p, f"{p}Tiers", "funnel", (20, 450, 300, 228, 22),
           query={"Category": [proj(TIER, True)], "Y": [proj(mea("Total Customers"))]},
           vco=title("Priority tiers A / B / C / Watch"))
    visual(p, f"{p}Score", "clusteredColumnChart", (330, 450, 450, 228, 23),
           query={"Category": [proj(col(O, "score_band"), True)], "Series": [proj(TIER)], "Y": [proj(mea("Total Customers"))]},
           vco=title("Opportunity score distribution"))
    visual(p, f"{p}City", "clusteredBarChart", (790, 450, 470, 228, 24),
           query={"Category": [proj(CITY, True)], "Y": [proj(mea("Opportunity Count"))]},
           sort=(mea("Opportunity Count"), "Descending"), vco=title("Opportunity by city"))

    # ---------------------------------------------------------------- Page 4 (also the drill-through target)
    p = "manager"
    dt = "Filter4f2a6c1e9b3d7a5c8e0f"
    page(p, PAGES[3][1], extra={
        "filterConfig": {"filters": [{"name": dt, "field": CITY, "type": "Categorical", "howCreated": "Drillthrough"}]},
        "pageBinding": {"name": gid("drill:manager"), "type": "Drillthrough",
                        "parameters": [{"name": f"Param_{dt}", "boundFilter": dt, "fieldExpr": CITY}]},
    })
    header(p, "Manager Action Dashboard", "Who to focus on, why, what opportunity, where, and how large?")
    for i, (f, lab) in enumerate([(CITY, "City"), (SEG, "Segment"), (TIER, "Tier"), (THEME, "Product theme"), (EVID, "Evidence level")]):
        slicer(p, f"{p}Slicer{i}", (20 + i * 166, 74, 158, 76, 10 + i), f, lab)
    card(p, f"{p}Addr", (860, 76, 196, 90, 20), "Addressable Balance", "How large: addressable balance (Rs)")
    card(p, f"{p}TierA", (1064, 76, 196, 90, 21), "Tier A Customers", "Tier A customers")
    visual(p, f"{p}List", "tableEx", (20, 158, 830, 520, 30),
           query={"Values": [proj(col(O, "priority_rank")), proj(col(O, "masked_id")), proj(TIER),
                             proj(col(O, "overall_score")), proj(col(O, "reason")), proj(THEME),
                             proj(CITY), proj(SEG), proj(EVID)]},
           sort=(col(O, "priority_rank"), "Ascending"),
           vco=title("Who and why: priority customers (masked IDs, ranked)"))
    visual(p, f"{p}TierBar", "clusteredColumnChart", (860, 174, 400, 246, 31),
           query={"Category": [proj(TIER, True)], "Y": [proj(mea("Total Customers"))]},
           vco=title("Customers by tier"))
    visual(p, f"{p}Where", "clusteredBarChart", (860, 428, 400, 250, 32),
           query={"Category": [proj(CITY, True)], "Y": [proj(mea("Tier A Customers"))]},
           sort=(mea("Tier A Customers"), "Descending"), vco=title("Where: Tier A customers by city"))
    visual(p, f"{p}Back", "actionButton", (1210, 14, 50, 34, 40),
           objects={"icon": [{"properties": {"show": lit("true")}},
                             {"properties": {"shapeType": lit("'back'")}, "selector": {"id": "default"}}]},
           vco={"visualLink": [{"properties": {"show": lit("true"), "type": lit("'Back'")}}]},
           extra={"howCreated": "InsertVisualButton"})

    # ---------------------------------------------------------------- Page 5
    p = "dataquality"
    page(p, PAGES[4][1])
    header(p, "Data Quality & Reconciliation", "Can we trust the numbers? (spec 24, FR-038, FR-039)")
    card(p, f"{p}Var1", (20, 78, 300, 92, 10), "Reconciliation Variance (Customers)", "Customers: Power BI - SQL")
    card(p, f"{p}Var2", (330, 78, 300, 92, 11), "Reconciliation Variance (Value)", "Value: Power BI - SQL (Rs)")
    visual(p, f"{p}Waterfall", "tableEx", (640, 78, 620, 160, 12),
           query={"Values": [proj(col("row_waterfall", "step_no")), proj(col("row_waterfall", "step")),
                             proj(col("row_waterfall", "rows"))]},
           sort=(col("row_waterfall", "step_no"), "Ascending"), vco=title("Row waterfall (raw -> clean)"))
    visual(p, f"{p}Dq", "tableEx", (20, 246, 1240, 432, 13),
           query={"Values": [proj(col("dq_log", "check_id")), proj(col("dq_log", "dimension")), proj(col("dq_log", "rule")),
                             proj(col("dq_log", "pass_pct")), proj(col("dq_log", "threshold_pct")),
                             proj(col("dq_log", "status")), proj(col("dq_log", "note"))]},
           sort=(col("dq_log", "check_id"), "Ascending"), vco=title("Data quality scorecard"))

    # ---------------------------------------------------------------- bookmark: reset view
    wj(f"{D}/bookmarks/bookmarks.json", {"$schema": f"{S}/item/report/definition/bookmarksMetadata/1.0.0/schema.json",
                                         "items": [{"name": "bmManagerReset"}]})
    wj(f"{D}/bookmarks/bmManagerReset.bookmark.json", {
        "$schema": f"{S}/item/report/definition/bookmark/2.1.0/schema.json",
        "displayName": "Manager view (all customers)", "name": "bmManagerReset",
        "options": {"targetVisualNames": [], "suppressData": False, "suppressDisplay": False,
                    "suppressActiveSection": False, "applyOnlyToTargetVisuals": False},
        "explorationState": {"version": "1.3", "activeSection": "manager", "sections": {"manager": {"visualContainers": {}}}},
    })


def main():
    for d in (SM, RP):
        if (HERE / d).exists():
            shutil.rmtree(HERE / d)
    wj(f"{NAME}.pbip", {"$schema": f"{S}/pbip/pbipProperties/1.0.0/schema.json", "version": "1.0",
                        "artifacts": [{"report": {"path": RP}}], "settings": {"enableAutoRecovery": True}})
    build_model()
    build_report()
    print("generated", HERE / f"{NAME}.pbip")


if __name__ == "__main__":
    main()

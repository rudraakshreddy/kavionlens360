"""
Build the 7-sheet Excel MIS (spec 18) with live formulas, Power Query, PivotTables and slicers.

    python excel/build_mis.py

Requires Microsoft Excel (2021 / 365 for XLOOKUP and IFS). Excel runs invisibly in its own
process. Data comes from data/exports/excel/*.csv through Power Query; the folder is the
query parameter `DataFolder` (Data > Queries & Connections > DataFolder) and the workbook
refreshes on open.
"""
import json
import sys
from pathlib import Path

import pythoncom
import win32com.client as w32

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from c360 import db  # noqa: E402

DATA_FOLDER = str(REPO / "data" / "exports" / "excel") + "\\"
OUT_XLSX = REPO / "docs" / "downloads" / "KavionLens360_MIS.xlsx"
OUT_PDF = REPO / "docs" / "downloads" / "KavionLens360_MIS.pdf"

# palette (validated chart palette) as Excel BGR integers
def rgb(h):
    h = h.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r + g * 256 + b * 65536


INK, INK2, MUTED, GRID, SURF2 = rgb("0b0b0b"), rgb("52514e"), rgb("898781"), rgb("e1e0d9"), rgb("f3f2ee")
S1, S2, S3, S4, S5 = rgb("2a78d6"), rgb("eb6834"), rgb("1baf7a"), rgb("eda100"), rgb("e87ba4")
SEG_COLORS = [S1, S2, S3, S4, S5]
TIER_COLORS = {"A": rgb("104281"), "B": rgb("256abf"), "C": rgb("5598e7"), "Watch": rgb("86b6ef")}
INR = '[>=10000000]##\\,##\\,##\\,##0;[>=100000]##\\,##\\,##0;##,##0'
PCT = "0.0%"
FONT = "Segoe UI"

# Excel constants
xlSrcExternal, xlCmdSql = 0, 2
xlBarClustered, xlColumnClustered = 57, 51
xlDatabase, xlLandscape = 1, 2
xlTypePDF = 0
xlRowField, xlColumnField, xlSum = 1, 2, -4157
xlCenter, xlLeft = -4108, -4131
xlContinuous, xlThin = 1, 2
xlEdgeBottom = 9

QUERIES = {
    # name: (csv file, {column: M type})
    "cube": ("cube.csv", None),
    "customer_lookup": ("customer_lookup.csv", None),
    "tier_a_list": ("tier_a_list.csv", None),
    "top100_value": ("top100_value.csv", None),
    "city_top25": ("city_top25.csv", None),
    "kpi_sql": ("kpi_sql.csv", None),
    "segment_definition": ("segment_definition.csv", None),
    "params": ("params.csv", None),
}
TEXT_COLS = {"segment_name", "age_group", "gender", "city", "city_tier", "tier", "evidence_level", "balance_band",
             "masked_id", "segment", "theme", "clean_city", "kpi", "potential_needs", "action", "owner", "timing"}
DATE_COLS = {"as_of_date", "window_start", "window_end"}


def m_query(name, file):
    import csv
    with open(REPO / "data" / "exports" / "excel" / file, encoding="utf-8") as f:
        header = next(csv.reader(f))
    types = ", ".join(
        f'{{"{c}", {"type text" if c in TEXT_COLS else "type date" if c in DATE_COLS else "type number"}}}' for c in header)
    return (f'let\n    Source = Csv.Document(File.Contents(DataFolder & "{file}"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),\n'
            f'    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),\n'
            f'    Typed = Table.TransformColumnTypes(Promoted, {{{types}}}, "en-US")\nin\n    Typed')


class MIS:
    def __init__(self):
        pythoncom.CoInitialize()
        self.xl = w32.DispatchEx("Excel.Application")
        self.xl.Visible = False
        self.xl.DisplayAlerts = False
        self.xl.ScreenUpdating = False
        self.wb = self.xl.Workbooks.Add()
        while self.wb.Worksheets.Count > 1:
            self.wb.Worksheets(self.wb.Worksheets.Count).Delete()
        self.tables = {}

    # ------------------------------------------------------------------ helpers
    SHEETS = ["README", "1 Executive Summary", "2 Customer Analysis", "3 Segment Analysis", "4 Geography",
              "5 Cross-Sell", "6 Pivot Analysis", "7 Data Dictionary", "Data"]

    def create_sheets(self):
        """Create every sheet once, in final tab order. Late-bound Worksheets.Add() always inserts
        before the active sheet, so start from the last sheet and add the others in reverse."""
        self.wb.Worksheets(1).Name = self.SHEETS[-1]
        for name in reversed(self.SHEETS[:-1]):
            self.wb.Worksheets.Add().Name = name

    def sheet(self, name, tab_color=None):
        ws = self.wb.Worksheets(name)
        ws.Activate()
        self.xl.ActiveWindow.DisplayGridlines = False
        ws.Cells.Font.Name = FONT
        ws.Cells.Font.Size = 10
        if tab_color:
            ws.Tab.Color = tab_color
        return ws

    def title(self, ws, text, sub):
        ws.Range("B2").Value = text
        ws.Range("B2").Font.Size = 18
        ws.Range("B2").Font.Bold = True
        ws.Range("B3").Formula = f'="{sub}  ·  As of "&TEXT(AsOfDate,"dd mmm yyyy")&"  ·  Public Kaggle data (Indian bank, 2016), not ICICI data"'
        ws.Range("B3").Font.Color = INK2
        ws.Columns("A").ColumnWidth = 2

    def header_row(self, rng):
        rng.Font.Bold = True
        rng.Font.Color = INK2
        rng.Interior.Color = SURF2
        rng.Borders(xlEdgeBottom).Color = GRID

    def table(self, ws, top_left, headers, rows=None, widths=None):
        r0 = ws.Range(top_left).Row
        c0 = ws.Range(top_left).Column
        for j, h in enumerate(headers):
            ws.Cells(r0, c0 + j).Value = h
        self.header_row(ws.Range(ws.Cells(r0, c0), ws.Cells(r0, c0 + len(headers) - 1)))
        return r0, c0

    def load_query(self, name, ws, cell):
        src = f'OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;Location={name};Extended Properties=""'
        # positional: SourceType, Source, LinkSource, XlListObjectHasHeaders, Destination
        lo = ws.ListObjects.Add(xlSrcExternal, src, True, 1, ws.Range(cell))
        lo.QueryTable.CommandType = xlCmdSql
        lo.QueryTable.CommandText = [f"SELECT * FROM [{name}]"]
        lo.QueryTable.AdjustColumnWidth = True
        lo.QueryTable.PreserveColumnInfo = True
        lo.QueryTable.RefreshOnFileOpen = True
        lo.QueryTable.Refresh(False)
        lo.Name = f"tbl_{name}"
        lo.TableStyle = "TableStyleLight1"
        self.tables[name] = lo
        return lo

    def chart(self, ws, kind, left_cell, width, height, source, title, colors=None, series_by_cols=True):
        anchor = ws.Range(left_cell)
        shp = ws.Shapes.AddChart2(-1, kind, anchor.Left, anchor.Top, width, height)
        ch = shp.Chart
        ch.SetSourceData(source, 2 if series_by_cols else 1)
        ch.HasTitle = True
        ch.ChartTitle.Text = title
        ch.ChartTitle.Format.TextFrame2.TextRange.Font.Size = 11
        ch.ChartTitle.Format.TextFrame2.TextRange.Font.Bold = True
        ch.ChartArea.Format.TextFrame2.TextRange.Font.Name = FONT
        ch.ChartArea.Format.Line.Visible = False
        for i in range(1, ch.SeriesCollection().Count + 1):
            s = ch.SeriesCollection(i)
            s.Format.Fill.ForeColor.RGB = (colors or [S1, S2, S3, S4, S5])[(i - 1) % 5]
        try:
            ch.Axes(2).MajorGridlines.Format.Line.ForeColor.RGB = GRID
        except Exception:
            pass
        ch.PlotVisibleOnly = False          # helper ranges are hidden columns
        if kind == xlBarClustered:
            ch.Axes(1).ReversePlotOrder = True   # first category at the top
        ch.HasLegend = ch.SeriesCollection().Count > 1
        if ch.HasLegend:
            ch.Legend.Position = -4160  # top
        return ch

    def kpi(self, ws, cell, label, formula, fmt):
        """A 3-column x 4-row tile. Uses Cells(row, col): late-bound Range.Offset(r, c) is
        resolved as Offset.Item(r, c) by pywin32 and lands on the wrong cell."""
        r, col_ = ws.Range(cell).Row, ws.Range(cell).Column
        ws.Range(ws.Cells(r, col_), ws.Cells(r + 3, col_ + 2)).Interior.Color = SURF2
        lab = ws.Cells(r, col_)
        lab.Value = label
        lab.Font.Color = INK2
        lab.Font.Size = 9
        ws.Range(ws.Cells(r + 1, col_), ws.Cells(r + 2, col_ + 2)).Merge()
        v = ws.Cells(r + 1, col_)
        v.HorizontalAlignment = xlLeft
        v.VerticalAlignment = xlCenter
        v.Formula2 = formula
        v.NumberFormat = fmt
        v.Font.Size = 18
        v.Font.Bold = True

    # ------------------------------------------------------------------ build
    def build(self, facts):
        wb, xl = self.wb, self.xl
        wb.Queries.Add("DataFolder", f'"{DATA_FOLDER}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]')
        for name, (file, _) in QUERIES.items():
            wb.Queries.Add(name, m_query(name, file))

        self.create_sheets()
        rd = self.sheet("README")
        # --- data sheets (loaded by Power Query)
        data = self.sheet("Data", tab_color=rgb("c3c2b7"))
        col = 1
        for name in QUERIES:
            if name in ("top100_value", "tier_a_list"):   # loaded on their display sheets instead
                continue
            lo = self.load_query(name, data, data.Cells(1, col).Address)
            col += lo.ListColumns.Count + 1
        wb.Names.Add("AsOfDate", "=tbl_params[as_of_date]")

        rd.Range("B2").Value = "KavionLens360 · Customer 360 MIS"
        rd.Range("B2").Font.Size = 18
        rd.Range("B2").Font.Bold = True
        lines = [
            ("Purpose", "Management information pack for the Customer 360 & segmentation project (spec section 18)."),
            ("Data", "Public Kaggle dataset 'Bank Customer Segmentation (1M+ Transactions)', an Indian bank, 2016. Not ICICI data."),
            ("Window", "1 Aug - 15 Sep 2016 (46 days); as-of date 16 Sep 2016."),
            ("Source", "Aggregated extracts written by run_pipeline.py to data/exports/excel (no raw rows; IDs masked)."),
            ("How to refresh", "1) Run python run_pipeline.py.  2) If the repo is elsewhere, edit the DataFolder query parameter "
                               "(Data > Queries & Connections > DataFolder).  3) Data > Refresh All. PivotTables and formulas update automatically."),
            ("Sheets", "1 Executive Summary · 2 Customer Analysis · 3 Segment Analysis · 4 Geography · 5 Cross-Sell · 6 Pivot Analysis · 7 Data Dictionary."),
            ("Excel features", "Power Query, SUMIFS, COUNTIFS, XLOOKUP, INDEX/MATCH, IFS, PivotTables with slicers, conditional formatting, charts, named range AsOfDate."),
            ("Reconciliation", "Sheet 1 compares every headline KPI with the SQL reference table (tbl_kpi_sql); variance must be 0."),
            ("Responsible use", "Opportunity flags are behavioural signals for prioritising conversations, not product recommendations or credit decisions."),
        ]
        for i, (k, v) in enumerate(lines):
            rd.Cells(4 + i * 2, 2).Value = k
            rd.Cells(4 + i * 2, 2).Font.Bold = True
            rd.Cells(4 + i * 2, 3).Value = v
            rd.Cells(4 + i * 2, 3).WrapText = True
        rd.Columns("A").ColumnWidth = 2
        rd.Columns("B").ColumnWidth = 18
        rd.Columns("C").ColumnWidth = 110

        C = "tbl_cube"
        segs = facts["segments"]
        ages = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+", "Unknown"]

        # ================================================================ 3 Segment Analysis (built first: sheet 1 charts use it)
        s3 = self.sheet("3 Segment Analysis", tab_color=S3)
        self.title(s3, "Segment Analysis", "Five behaviour segments (K-Means, k = 5)")
        hdr = ["Segment", "Customers", "% customers", "Txn value (Rs)", "% value", "Avg txn (Rs)", "Mean balance (Rs)",
               "Txns / customer", "Active %", "High-value %", "With signal %", "Action (XLOOKUP)"]
        r0, c0 = self.table(s3, "B5", hdr)
        for i, sname in enumerate(segs):
            r = r0 + 1 + i
            s3.Cells(r, 2).Value = sname
            k = f'{C}[segment_name],$B{r}'
            s3.Cells(r, 3).Formula2 = f"=SUMIFS({C}[customers],{k})"
            s3.Cells(r, 4).Formula2 = f"=C{r}/SUM(C$6:C$10)"
            s3.Cells(r, 5).Formula2 = f"=SUMIFS({C}[value],{k})"
            s3.Cells(r, 6).Formula2 = f"=E{r}/SUM(E$6:E$10)"
            s3.Cells(r, 7).Formula2 = f"=E{r}/SUMIFS({C}[txns],{k})"
            s3.Cells(r, 8).Formula2 = f"=SUMIFS({C}[balance_sum],{k})/SUMIFS({C}[balance_n],{k})"
            s3.Cells(r, 9).Formula2 = f"=SUMIFS({C}[txns],{k})/C{r}"
            s3.Cells(r, 10).Formula2 = f"=SUMIFS({C}[active],{k})/C{r}"
            s3.Cells(r, 11).Formula2 = f"=SUMIFS({C}[high_value],{k})/C{r}"
            s3.Cells(r, 12).Formula2 = f"=SUMIFS({C}[any_signal],{k})/C{r}"
            s3.Cells(r, 13).Formula2 = f'=XLOOKUP($B{r},tbl_segment_definition[segment_name],tbl_segment_definition[action],"n/a")'
            s3.Cells(r, 1).Interior.Color = SEG_COLORS[i]
        last = r0 + len(segs)
        s3.Cells(last + 1, 2).Value = "Total"
        s3.Cells(last + 1, 3).Formula2 = f"=SUM(C6:C{last})"
        s3.Cells(last + 1, 5).Formula2 = f"=SUM(E6:E{last})"
        s3.Range(f"B{last + 1}:M{last + 1}").Font.Bold = True
        for col_, fmt in [("C", INR), ("E", INR), ("G", INR), ("H", INR), ("D", PCT), ("F", PCT), ("I", "0.00"),
                          ("J", PCT), ("K", PCT), ("L", PCT)]:
            s3.Range(f"{col_}6:{col_}{last + 1}").NumberFormat = fmt
        s3.Range("B5:L11").Columns.AutoFit()
        s3.Columns("M").ColumnWidth = 70
        s3.Range("M6:M10").WrapText = True
        # helper range for chart: segment, % customers, % value
        s3.Range("O5").Value = "Segment"
        s3.Range("P5").Value = "% of customers"
        s3.Range("Q5").Value = "% of value"
        for i in range(5):
            s3.Cells(6 + i, 15).Formula2 = f"=B{6 + i}"
            s3.Cells(6 + i, 16).Formula2 = f"=D{6 + i}"
            s3.Cells(6 + i, 17).Formula2 = f"=F{6 + i}"
        s3.Range("P6:Q10").NumberFormat = PCT
        s3.Columns("O:Q").Hidden = True
        ch = self.chart(s3, xlBarClustered, "B14", 620, 300, s3.Range("O5:Q10"), "Share of customers vs share of value", [S1, S2])
        ch.Axes(2).TickLabels.NumberFormat = "0%"
        s3.Range("B37").Value = "Reading: the Engaged Repeat Users segment carries roughly twice its share of customers in value; the two low-value segments together hold under 5% of value."
        s3.Range("B37").Font.Color = INK2

        # ================================================================ 2 Customer Analysis
        s2 = self.sheet("2 Customer Analysis", tab_color=S1)
        self.title(s2, "Customer Analysis", "Who the customers are: age, gender, balance")
        hdr = ["Age group", "Female", "Male", "Unknown", "Total", "% of total", "Priority top-2,000 (COUNTIFS)"]
        r0, _ = self.table(s2, "B5", hdr)
        for i, a in enumerate(ages):
            r = r0 + 1 + i
            s2.Cells(r, 2).Value = a
            for j, g in enumerate(["F", "M", "Unknown"]):
                s2.Cells(r, 3 + j).Formula2 = f'=SUMIFS({C}[customers],{C}[age_group],$B{r},{C}[gender],"{g}")'
            s2.Cells(r, 6).Formula2 = f"=SUM(C{r}:E{r})"
            s2.Cells(r, 7).Formula2 = f"=F{r}/SUM($F$6:$F$12)"
            s2.Cells(r, 8).Formula2 = f'=COUNTIFS(tbl_customer_lookup[age_group],$B{r},tbl_customer_lookup[customer_ref],"<=2000")'
        s2.Range("B13").Value = "Total"
        for j, colL in enumerate("CDEFH"):
            s2.Range(f"{colL}13").Formula2 = f"=SUM({colL}6:{colL}12)"
        s2.Range("B13:H13").Font.Bold = True
        s2.Range("C6:F13").NumberFormat = INR
        s2.Range("G6:G12").NumberFormat = PCT
        s2.Range("H6:H13").NumberFormat = "#,##0"
        # balance bands
        bands = ["0. Unknown", "1. Zero (< 1)", "2. 1-999", "3. 1K-9.9K", "4. 10K-49.9K", "5. 50K-99.9K", "6. 1L-9.9L", "7. 10L+"]
        r0, _ = self.table(s2, "J5", ["Latest balance band", "Customers", "% customers", "Txn value (Rs)", "% value"])
        for i, b in enumerate(bands):
            r = r0 + 1 + i
            s2.Cells(r, 10).Value = b
            s2.Cells(r, 11).Formula2 = f"=SUMIFS({C}[customers],{C}[balance_band],$J{r})"
            s2.Cells(r, 12).Formula2 = f"=K{r}/SUM($K$6:$K$13)"
            s2.Cells(r, 13).Formula2 = f"=SUMIFS({C}[value],{C}[balance_band],$J{r})"
            s2.Cells(r, 14).Formula2 = f"=M{r}/SUM($M$6:$M$13)"
        s2.Range("K6:K13").NumberFormat = INR
        s2.Range("M6:M13").NumberFormat = INR
        s2.Range("L6:L13").NumberFormat = PCT
        s2.Range("N6:N13").NumberFormat = PCT
        s2.Range("K6:K13").FormatConditions.AddDatabar()
        self.chart(s2, xlColumnClustered, "B16", 520, 260, s2.Range("B5:D12"), "Customers by age group and gender (F, M)", [S1, S2])
        # top 100 by value: query table + XLOOKUP calculated columns
        s2.Range("B36").Value = "Top 100 customers by transaction value (masked IDs; details via XLOOKUP on customer_ref)"
        s2.Range("B36").Font.Bold = True
        lo = self.load_query("top100_value", s2, "B37")
        for name, f in [("Masked ID", "masked_id"), ("City", "city"), ("Segment", "segment"), ("Txn value (Rs)", "total_value"),
                        ("Latest balance (Rs)", "latest_balance"), ("Tier", "tier")]:
            c = lo.ListColumns.Add()
            c.Name = name
            c.DataBodyRange.Formula2 = f'=XLOOKUP([@[customer_ref]],tbl_customer_lookup[customer_ref],tbl_customer_lookup[{f}],"n/a")'
        lo.ListColumns("Txn value (Rs)").DataBodyRange.NumberFormat = INR
        lo.ListColumns("Latest balance (Rs)").DataBodyRange.NumberFormat = INR
        s2.Range("B5:N13").Columns.AutoFit()
        s2.Range("B37:H137").Columns.AutoFit()

        # ================================================================ 4 Geography
        s4 = self.sheet("4 Geography", tab_color=S4)
        self.title(s4, "Geography", "Top 25 cities by transaction value (city scorecard)")
        hdr = ["Rank", "City", "City tier", "Customers", "Txn value (Rs)", "Value / customer (Rs)", "Mean balance (Rs)",
               "Active %", "Customers with signal", "Tier A", "Addressable balance (Rs)"]
        r0, _ = self.table(s4, "B5", hdr)
        cities = facts["cities"]
        for i, city in enumerate(cities):
            r = r0 + 1 + i
            k = f"{C}[city],$C{r}"
            s4.Cells(r, 2).Formula2 = f"=RANK.EQ(F{r},$F$6:$F$30)"
            s4.Cells(r, 3).Value = city
            s4.Cells(r, 4).Formula2 = f'=XLOOKUP($C{r},tbl_city_top25[clean_city],tbl_city_top25[city_tier],"")'
            s4.Cells(r, 5).Formula2 = f"=SUMIFS({C}[customers],{k})"
            s4.Cells(r, 6).Formula2 = f"=SUMIFS({C}[value],{k})"
            s4.Cells(r, 7).Formula2 = f"=F{r}/E{r}"
            s4.Cells(r, 8).Formula2 = f"=SUMIFS({C}[balance_sum],{k})/SUMIFS({C}[balance_n],{k})"
            s4.Cells(r, 9).Formula2 = f"=SUMIFS({C}[active],{k})/E{r}"
            s4.Cells(r, 10).Formula2 = f"=SUMIFS({C}[any_signal],{k})"
            s4.Cells(r, 11).Formula2 = f'=SUMIFS({C}[customers],{k},{C}[tier],"A")'
            s4.Cells(r, 12).Formula2 = f"=SUMIFS({C}[addressable],{k})"
        end = r0 + len(cities)
        for col_, fmt in [("E", INR), ("F", INR), ("G", INR), ("H", INR), ("J", INR), ("K", INR), ("L", INR), ("I", PCT)]:
            s4.Range(f"{col_}6:{col_}{end}").NumberFormat = fmt
        s4.Range(f"F6:F{end}").FormatConditions.AddDatabar()
        cs = s4.Range(f"G6:G{end}").FormatConditions.AddColorScale(2)
        cs.ColorScaleCriteria(1).FormatColor.Color = rgb("fcfcfb")
        cs.ColorScaleCriteria(2).FormatColor.Color = rgb("86b6ef")
        s4.Range(f"K6:K{end}").FormatConditions.AddDatabar()
        s4.Range("B5:L30").Columns.AutoFit()
        s4.Range("N5").Value = "City"
        s4.Range("O5").Value = "Txn value (Rs Cr)"
        for i in range(10):
            s4.Cells(6 + i, 14).Formula2 = f"=C{6 + i}"
            s4.Cells(6 + i, 15).Formula2 = f"=F{6 + i}/10^7"
        s4.Columns("N:O").Hidden = True
        self.chart(s4, xlBarClustered, "B33", 560, 300, s4.Range("N5:O15"), "Top 10 cities by transaction value (Rs crore)", [S1])

        # ================================================================ 5 Cross-Sell Opportunities
        s5 = self.sheet("5 Cross-Sell", tab_color=S2)
        self.title(s5, "Cross-Sell Opportunities", "Signals inferred from behaviour. Product ownership unknown")
        themes = [("Investment / MF", "sig_investment"), ("Premium account", "sig_premium"), ("Credit card", "sig_credit_card"),
                  ("Insurance", "sig_insurance"), ("Personal loan (demand only)", "sig_personal_loan"), ("Re-engagement (service)", "sig_reengagement")]
        r0, _ = self.table(s5, "B5", ["Signal", "Customers flagged", "% of customers"])
        for i, (lab, colname) in enumerate(themes):
            r = r0 + 1 + i
            s5.Cells(r, 2).Value = lab
            s5.Cells(r, 3).Formula2 = f"=SUM({C}[{colname}])"
            s5.Cells(r, 4).Formula2 = f"=C{r}/SUM({C}[customers])"
        s5.Range("C6:C11").NumberFormat = INR
        s5.Range("D6:D11").NumberFormat = PCT
        s5.Range("C6:C11").FormatConditions.AddDatabar()
        # theme x segment matrix (share of segment flagged)
        r0, _ = self.table(s5, "F5", ["Segment"] + [t[0] for t in themes])
        for i, sname in enumerate(segs):
            r = r0 + 1 + i
            s5.Cells(r, 6).Value = sname
            for j, (_, colname) in enumerate(themes):
                s5.Cells(r, 7 + j).Formula2 = (f"=SUMIFS({C}[{colname}],{C}[segment_name],$F{r})"
                                               f"/SUMIFS({C}[customers],{C}[segment_name],$F{r})")
        s5.Range("G6:L10").NumberFormat = "0%"
        cs = s5.Range("G6:L10").FormatConditions.AddColorScale(2)
        cs.ColorScaleCriteria(1).FormatColor.Color = rgb("fcfcfb")
        cs.ColorScaleCriteria(2).FormatColor.Color = rgb("3987e5")
        # tier summary
        r0, _ = self.table(s5, "B14", ["Tier", "Customers", "% of customers", "Avg score", "Addressable balance (Rs)"])
        for i, t in enumerate(["A", "B", "C", "Watch"]):
            r = r0 + 1 + i
            s5.Cells(r, 2).Value = t
            s5.Cells(r, 2).Interior.Color = TIER_COLORS[t]
            s5.Cells(r, 2).Font.Color = rgb("ffffff") if t != "Watch" else INK
            s5.Cells(r, 3).Formula2 = f'=SUMIFS({C}[customers],{C}[tier],$B{r})'
            s5.Cells(r, 4).Formula2 = f"=C{r}/SUM($C$15:$C$18)"
            s5.Cells(r, 5).Formula2 = f'=SUMIFS({C}[score_sum],{C}[tier],$B{r})/C{r}'
            s5.Cells(r, 6).Formula2 = f'=SUMIFS({C}[addressable],{C}[tier],$B{r})'
        s5.Range("C15:C18").NumberFormat = INR
        s5.Range("D15:D18").NumberFormat = PCT
        s5.Range("E15:E18").NumberFormat = "0.0"
        s5.Range("F15:F18").NumberFormat = INR
        ch = self.chart(s5, xlColumnClustered, "H13", 420, 220, s5.Range("B14:C18"), "Customers by priority tier", [S1])
        pts = ch.SeriesCollection(1).Points()
        for i, t in enumerate(["A", "B", "C", "Watch"]):
            ch.SeriesCollection(1).Points(i + 1).Format.Fill.ForeColor.RGB = TIER_COLORS[t]
        # Tier A list with XLOOKUP, INDEX/MATCH and IFS
        s5.Range("B30").Value = "Tier A priority list (top 300). City and segment via XLOOKUP; INDEX/MATCH shown as the classic alternative."
        s5.Range("B30").Font.Bold = True
        lo = self.load_query("tier_a_list", s5, "B31")
        for name, formula in [
            ("City (XLOOKUP)", '=XLOOKUP([@[customer_ref]],tbl_customer_lookup[customer_ref],tbl_customer_lookup[city],"n/a")'),
            ("Segment (XLOOKUP)", '=XLOOKUP([@[customer_ref]],tbl_customer_lookup[customer_ref],tbl_customer_lookup[segment],"n/a")'),
            ("Segment (INDEX/MATCH)", "=INDEX(tbl_customer_lookup[segment],MATCH([@[customer_ref]],tbl_customer_lookup[customer_ref],0))"),
            ("Evidence", '=XLOOKUP([@[customer_ref]],tbl_customer_lookup[customer_ref],tbl_customer_lookup[evidence_level],"n/a")'),
            ("Contact plan (IFS)", '=IFS([@[score]]>=95,"Call this week",[@[score]]>=90,"Call within 2 weeks",TRUE,"Include in campaign")'),
        ]:
            c = lo.ListColumns.Add()
            c.Name = name
            c.DataBodyRange.Formula2 = formula
        lo.ListColumns("latest_balance").DataBodyRange.NumberFormat = INR
        lo.ListColumns("score").DataBodyRange.FormatConditions.AddDatabar()
        # shared columns hold three tables, so fixed widths instead of AutoFit
        for col_, w_ in zip("BCDEFGHIJKLM", [26, 14, 14, 26, 26, 18, 22, 22, 14, 20, 22, 22]):
            s5.Columns(col_).ColumnWidth = w_

        # ================================================================ 6 Pivot Analysis
        s6 = self.sheet("6 Pivot Analysis", tab_color=rgb("4a3aa7"))
        self.title(s6, "Pivot Analysis", "PivotTables on the customer cube, with shared slicers")
        cache = wb.PivotCaches().Create(xlDatabase, "tbl_cube")
        pt1 = cache.CreatePivotTable(s6.Range("B18"), "pvtSegmentAge")
        pt1.PivotFields("segment_name").Orientation = xlRowField
        pt1.PivotFields("age_group").Orientation = xlColumnField
        df = pt1.AddDataField(pt1.PivotFields("customers"), "Customers (sum)", xlSum)
        df.NumberFormat = "#,##0"
        pt1.RowAxisLayout(1)
        pt2 = cache.CreatePivotTable(s6.Range("B31"), "pvtCityTier")
        pt2.PivotFields("city").Orientation = xlRowField
        pt2.PivotFields("tier").Orientation = xlColumnField
        df2 = pt2.AddDataField(pt2.PivotFields("customers"), "Customers (sum)", xlSum)
        df2.NumberFormat = "#,##0"
        pt2.RowAxisLayout(1)
        for pt in (pt1, pt2):
            pt.TableStyle2 = "PivotStyleLight16"
        top, left0 = s6.Range("B7").Top, s6.Range("B7").Left
        for i, (fld, w_) in enumerate([("segment_name", 200), ("gender", 120), ("evidence_level", 130)]):
            sc = wb.SlicerCaches.Add2(pt1, fld)
            sc.PivotTables.AddPivotTable(pt2)
            sl = sc.Slicers.Add(s6, pythoncom.Missing, f"slc_{fld}", fld.replace("_", " ").title())
            sl.Top, sl.Left, sl.Width, sl.Height = top, left0 + [0, 210, 340][i], w_, 140
        s6.Range("B5").Value = "Use the slicers to filter both PivotTables at once (segment, gender, evidence level)."
        s6.Range("B5").Font.Color = INK2

        # ================================================================ 7 Data Dictionary
        s7 = self.sheet("7 Data Dictionary", tab_color=rgb("898781"))
        self.title(s7, "Data Dictionary", "Source columns (spec 7.3) and derived customer features (spec 11)")
        r0, _ = self.table(s7, "B5", ["Field", "Level", "Type", "Definition / formula", "Notes"])
        for i, row in enumerate(facts["dictionary"]):
            for j, v in enumerate(row):
                s7.Cells(r0 + 1 + i, 2 + j).Value = v
        s7.Columns("B").ColumnWidth = 24
        s7.Columns("C").ColumnWidth = 12
        s7.Columns("D").ColumnWidth = 12
        s7.Columns("E").ColumnWidth = 70
        s7.Columns("F").ColumnWidth = 50
        s7.Range(f"E6:F{r0 + len(facts['dictionary'])}").WrapText = True

        # ================================================================ 1 Executive Summary (first visible sheet)
        s1 = self.sheet("1 Executive Summary", tab_color=rgb("0b0b0b"))
        self.title(s1, "Executive Summary", "KavionLens360 Customer 360 MIS")
        for j in range(2, 19):
            s1.Columns(j).ColumnWidth = 9.5
        tiles = [
            ("B5", "Customers", f"=SUM({C}[customers])", INR),
            ("E5", "Transaction value (Rs)", f"=SUM({C}[value])", INR),
            ("H5", "Avg transaction (Rs)", f"=SUM({C}[value])/SUM({C}[txns])", INR),
            ("K5", "Active rate (≤15 days)", f"=SUM({C}[active])/SUM({C}[customers])", PCT),
            ("N5", "Tier A customers", f'=SUMIFS({C}[customers],{C}[tier],"A")', INR),
            ("Q5", "Addressable balance (Rs Cr)", f"=SUM({C}[addressable])/10^7", "#,##0"),
        ]
        for cell, lab, f, fmt in tiles:
            self.kpi(s1, cell, lab, f, fmt)
        # reconciliation
        r0, _ = self.table(s1, "B11", ["KPI", "", "", "Excel", "", "SQL (XLOOKUP)", "", "Variance", "Status"])
        rec = [("Total Customers", f"=SUM({C}[customers])"), ("Total Transactions", f"=SUM({C}[txns])"),
               ("Total Txn Value", f"=SUM({C}[value])"), ("Opportunity Count", f"=SUM({C}[any_signal])"),
               ("Tier A Customers", f'=SUMIFS({C}[customers],{C}[tier],"A")'), ("Addressable Balance", f"=SUM({C}[addressable])")]
        for i, (k, f) in enumerate(rec):
            r = r0 + 1 + i
            s1.Cells(r, 2).Value = k
            s1.Cells(r, 5).Formula2 = f
            s1.Cells(r, 7).Formula2 = f'=XLOOKUP($B{r},tbl_kpi_sql[kpi],tbl_kpi_sql[sql_value],NA())'
            s1.Cells(r, 9).Formula2 = f"=ROUND(E{r}-G{r},0)"
            s1.Cells(r, 10).Formula2 = f'=IF(ABS(I{r})<1,"✓ reconciled","✗ check")'
            s1.Range(f"E{r}:I{r}").NumberFormat = INR
            s1.Range(f"E{r}:F{r}").Merge()
            s1.Range(f"G{r}:H{r}").Merge()
        good = s1.Range(f"J{r0 + 1}:J{r0 + len(rec)}").FormatConditions.Add(2, 1, '=LEFT($J12,1)="✓"')
        good.Font.Color = rgb("006300")
        # insights
        s1.Range("L11").Value = "Key insights"
        s1.Range("L11").Font.Bold = True
        for i, line in enumerate(facts["insights"]):
            c = s1.Cells(12 + i * 2, 12)
            c.Value = f"• {line}"
            s1.Range(s1.Cells(12 + i * 2, 12), s1.Cells(13 + i * 2, 19)).Merge()
            s1.Range(s1.Cells(12 + i * 2, 12), s1.Cells(13 + i * 2, 19)).WrapText = True
            s1.Range(s1.Cells(12 + i * 2, 12), s1.Cells(13 + i * 2, 19)).VerticalAlignment = -4160
        # charts on sheet 1
        ch = self.chart(s1, xlBarClustered, "B23", 330, 230, s3.Range("O5:Q10"), "Segments: share of customers vs value", [S1, S2])
        ch.Axes(2).TickLabels.NumberFormat = "0%"
        self.chart(s1, xlBarClustered, "H23", 300, 230, s4.Range("N5:O15"), "Top 10 cities by value (Rs crore)", [S1])
        ch = self.chart(s1, xlColumnClustered, "N23", 280, 230, s5.Range("B14:C18"), "Customers by priority tier", [S1])
        for i, t in enumerate(["A", "B", "C", "Watch"]):
            ch.SeriesCollection(1).Points(i + 1).Format.Fill.ForeColor.RGB = TIER_COLORS[t]

        # page setup for printing / PDF
        printable = ["1 Executive Summary", "2 Customer Analysis", "3 Segment Analysis", "4 Geography",
                     "5 Cross-Sell", "6 Pivot Analysis", "7 Data Dictionary"]
        for name in printable:
            ws = wb.Worksheets(name)
            ps = ws.PageSetup
            ps.Orientation = xlLandscape
            ps.Zoom = False
            ps.FitToPagesWide = 1
            ps.FitToPagesTall = 1 if name in ("1 Executive Summary", "3 Segment Analysis", "4 Geography",
                                              "6 Pivot Analysis", "7 Data Dictionary") else False
            ps.CenterFooter = "KavionLens360 MIS · &A · page &P of &N"
        wb.Worksheets("1 Executive Summary").Activate()
        xl.Calculate()
        return printable

    def save(self, printable):
        OUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
        self.wb.SaveAs(str(OUT_XLSX), 51)  # xlOpenXMLWorkbook
        for name in ("README", "Data"):
            self.wb.Worksheets(name).Visible = 0
        self.wb.ExportAsFixedFormat(xlTypePDF, str(OUT_PDF), 0, True, False)
        for name in ("README", "Data"):
            self.wb.Worksheets(name).Visible = -1
        self.wb.Worksheets("1 Executive Summary").Activate()
        self.wb.Save()

    def close(self):
        try:
            self.wb.Close(False)
        finally:
            self.xl.Quit()


def gather_facts():
    seg = db.query("SELECT segment_name FROM segment_definition ORDER BY segment_id")["segment_name"].tolist()
    cities = db.query("SELECT clean_city FROM agg_city_summary ORDER BY value_rank LIMIT 25")["clean_city"].tolist()
    s = db.query("SELECT segment_name, pct_customers, pct_value FROM agg_segment_summary ORDER BY segment_id")
    k = db.query("SELECT kpi, sql_value::float v FROM kpi_reconciliation").set_index("kpi")["v"]
    c = db.query("SELECT total_txn_value::float v FROM customer_360")["v"].sort_values(ascending=False)
    top10 = 100 * c.head(len(c) // 10).sum() / c.sum()
    single = 100 * float(db.scalar("SELECT AVG((txn_count = 1)::int) FROM customer_360"))
    tierA = db.query("SELECT COUNT(*) n FROM customer_opportunity WHERE tier = 'A'")["n"].iloc[0]
    insights = [
        f"Value is concentrated: the top 10% of customers generate {top10:.0f}% of transaction value.",
        f"{s.iloc[0].segment_name}: {s.iloc[0].pct_customers:.0f}% of customers, {s.iloc[0].pct_value:.0f}% of value. Deepen with RM contact.",
        f"{s.iloc[2].segment_name}: {s.iloc[2].pct_value:.0f}% of value not seen for 2+ weeks. Re-engage before selling.",
        f"{single:.0f}% of customers transacted once; every list carries an evidence level.",
        f"Work the {tierA:,} Tier A customers first; {100 * k['Opportunity Count'] / k['Total Customers']:.0f}% of the base has at least one signal (broad by design).",
    ]
    dictionary = [
        ("TransactionID", "Source", "Text", "Unique id of a transaction (T + number)", "Unique, not null; duplicates kept first"),
        ("CustomerID", "Source", "Text", "Customer identifier (C + digits)", "Not a stable person key in this extract (DQ-20)"),
        ("CustomerDOB", "Source", "Date", "Date of birth, d/m/yy; century pivot yy<=16 -> 20yy", "1/1/1800 placeholder and 'nan' -> NULL"),
        ("CustGender", "Source", "Text", "M / F; other values -> Unknown", ""),
        ("CustLocation", "Source", "Text", "Free-text location", "Normalised + manual mapping -> clean_city"),
        ("CustAccountBalance", "Source", "Number", "Balance recorded with the transaction (Rs)", "NULL kept as NULL, never zero"),
        ("TransactionDate", "Source", "Date", "Transaction date, d/m/yy", "Window 1 Aug - 15 Sep 2016"),
        ("TransactionTime", "Source", "Time", "HHMMSS integer (leading zeros dropped)", "All rows valid"),
        ("TransactionAmount (INR)", "Source", "Number", "Transaction amount (Rs)", "Amount = 0 rejected"),
        ("txn_count", "Customer", "Integer", "COUNT(TransactionID)", "RFM F"),
        ("total_txn_value", "Customer", "Number", "SUM(amount)", "RFM M"),
        ("avg_txn_value", "Customer", "Number", "total_txn_value / txn_count", "Typical ticket"),
        ("active_days", "Customer", "Integer", "COUNT(DISTINCT txn_date)", ""),
        ("monthly_txn_frequency", "Customer", "Number", "txn_count / (46 / 30)", ""),
        ("recency_days", "Customer", "Integer", "as_of_date (16 Sep 2016) - last_txn_date", "RFM R"),
        ("avg_balance / latest_balance", "Customer", "Number", "AVG(balance) / balance on latest transaction", "Value proxy, not revenue"),
        ("balance_volatility", "Customer", "Number", "STDDEV(balance) / AVG(balance); NULL if < 2 balances", ""),
        ("txn_to_balance_ratio", "Customer", "Number", "avg_txn_value / latest_balance (NULL if balance < 1)", ""),
        ("age, age_group", "Customer", "Integer/Text", "Years at as-of date; 18-24 ... 65+; outside 18-90 -> Unknown", ""),
        ("activity_trend", "Customer", "Text", "Second-half vs first-half txns (repeat customers only)", ""),
        ("value_score", "Customer", "0-100", "100 x percent_rank(0.5 pct(avg_balance) + 0.5 pct(total_value))", ""),
        ("engagement_score", "Customer", "0-100", "100 x (0.5 min(cnt,4)/4 + 0.3 (1 - recency/46) + 0.2 min(days,4)/4)", ""),
        ("is_active / is_dormant", "Customer", "Flag", "recency <= 15 / recency > 30 days", "BR-01 / BR-05 (scaled)"),
        ("is_high_value", "Customer", "Flag", "latest_balance >= P90 OR total_value >= P90", "BR-02"),
        ("segment_name", "Customer", "Text", "K-Means (k=5) cluster, named after profiling", "config/segments.json"),
        ("sig_*", "Customer", "Flag", "Six behaviour-based opportunity rules (spec 13.2)", "Signals, not recommendations"),
        ("overall_score", "Customer", "0-100", "max over themes of 100 x (0.35 V + 0.25 E + 0.30 Fit + 0.10 R)", ""),
        ("tier", "Customer", "Text", "A top 5%, B next 15%, C next 30%, Watch rest", ""),
    ]
    return {"segments": seg, "cities": cities, "insights": insights, "dictionary": dictionary}


def main():
    facts = gather_facts()
    mis = MIS()
    try:
        printable = mis.build(facts)
        mis.save(printable)
    finally:
        mis.close()
    print("wrote", OUT_XLSX, "and", OUT_PDF)


if __name__ == "__main__":
    main()

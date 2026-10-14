"""Generate the Power BI Project (PBIP) in dashboard/: TMDL semantic model + PBIR report.

    python src/build_dashboard.py            # (re)write dashboard/ and dashboard/measures.dax

Everything is generated from the CSVs in data/processed/powerbi/ and from the specs below,
so the project can be rebuilt after the analysis changes. IDs and lineage tags are derived
deterministically from names, so a rebuild only changes what actually changed.

Model rules (see the step-4 brief):
  * Star schema: dim_series (one) -> monthly_long, risk_summary, yearly_real, closure_summary
    on series_code (single direction). dim_month (one) -> monthly_long on month.
  * correlation_long and context have no relationships.
  * Auto date/time is OFF. dim_month is the only time dimension (month grain).
  * Every measure lives in _Measures and is copied to dashboard/measures.dax.
  * Sector indices never appear in the report: every page has a locked page filter on
    dim_series[type] that excludes sector_index.
"""
from __future__ import annotations

import hashlib
import re
import json
import shutil
import sys
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "powerbi"
DASH = ROOT / "dashboard"
NAME = "tse_inflation"
SM = DASH / f"{NAME}.SemanticModel"
RP = DASH / f"{NAME}.Report"
BASE_THEME_SRC = Path("E:/BI/mini/online-retail-analysis/dashboard/online_retail.Report/"
                      "StaticResources/SharedResources/BaseThemes/CY26SU07.json")
BASE_THEME = "CY26SU07"
CUSTOM_THEME = "TSE_Inflation.json"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"

PCT = "0.0%;-0.0%;0.0%"

# Right-to-left mark. Power BI lays out text left-to-right, so Persian strings get a
# trailing RLM (and a leading one when they start with a digit, a Latin letter or a
# bracket) to keep punctuation and numbers on the correct side.
RLM = "\u200f"
_PERSIAN = re.compile(r"[\u0600-\u06FF]")


def rtl(text: str) -> str:
    """Wrap a Persian string with RLM marks (idempotent); other strings are returned as is."""
    if not isinstance(text, str) or not _PERSIAN.search(text):
        return text
    t = text.strip(RLM)
    first = t[0]
    lead = RLM if (first.isdigit() or first.isascii() and first.isalpha()
                   or first in "([{«<\"'") else ""
    return lead + t + RLM


def m_text(text: str) -> str:
    """M string literal of rtl(text), with RLM written as the M escape #(200F)."""
    return '"' + rtl(text).replace('"', '""').replace(RLM, "#(200F)") + '"'
PCT0 = "0%"


def uid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "tse-inflation/" + "/".join(parts)))


def hid(*parts: str) -> str:
    return hashlib.sha1("/".join(parts).encode("utf-8")).hexdigest()[:20]


# =========================================================================== #
# Semantic model specification
# =========================================================================== #
DATES = {"month_end_gregorian"}
BOOLS = {"is_base_month", "flag_any", "flag_market_closure", "flag_long_suspension",
         "flag_no_trade", "comparable"}
INTS = {"sort_order", "jalali_year", "sort_key", "months", "flagged_months",
        "rank_among_stocks", "n_bonds", "window_order", "series_a_order", "series_b_order"}
NUM_FORMAT = {"nominal_index_1402_06_eq_100": "0.0", "real_index_1402_06_eq_100": "0.0",
              "corr_real_return_per_month": "0.00"}
FACT_DESCRIPTIVE = {"series", "series_fa", "type", "sector", "usage_note", "series_code"}

# Extra Power Query steps per table: renames and added (computed) columns.
RENAMES = {"risk_summary": {"code": "series_code"}, "yearly_real": {"code": "series_code"}}
BLOCK_FA = {"1402-07..1403-06": "سال اول: مهر ۱۴۰۲ تا شهریور ۱۴۰۳",
            "1403-07..1404-06": "سال دوم: مهر ۱۴۰۳ تا شهریور ۱۴۰۴",
            "1404-07..1405-06": "سال سوم: مهر ۱۴۰۴ تا شهریور ۱۴۰۵"}
WINDOW_FA = {"on_reopening": "تا بازگشایی", "after_20_days": "۲۰ روز معاملاتی پس از بازگشایی"}
ADDED = {  # table -> list of (column, M expression, M type)
    "yearly_real": [
        ("block_fa", "each " + " else ".join(f'if [block] = "{k}" then {m_text(v)}'
                                             for k, v in BLOCK_FA.items()) + " else [block]", "type text"),
    ],
    "closure_summary": [
        ("window_fa", f'each if [window] = "on_reopening" then {m_text(WINDOW_FA["on_reopening"])} '
                      f'else {m_text(WINDOW_FA["after_20_days"])}', "type text"),
        ("window_order", 'each if [window] = "on_reopening" then 1 else 2', "Int64.Type"),
    ],
}
# Persian text columns shown in visuals: wrapped in RLM marks in Power Query.
RLM_COLUMNS = {"dim_series": ["series_fa"], "dim_month": ["month_label_fa"],
               "correlation_long": ["series_a_fa", "series_b_fa"]}
SORT_BY = {("dim_month", "month_label_fa"): "sort_key", ("dim_month", "month"): "sort_key",
           ("dim_series", "series_fa"): "sort_order", ("dim_series", "series"): "sort_order",
           ("yearly_real", "block_fa"): "block", ("closure_summary", "window_fa"): "window_order",
           ("correlation_long", "series_a_fa"): "series_a_order",
           ("correlation_long", "series_b_fa"): "series_b_order"}
HIDDEN = {("dim_month", "sort_key"), ("dim_series", "sort_order"),
          ("closure_summary", "window_order"), ("correlation_long", "series_a_order"),
          ("correlation_long", "series_b_order")}
KEYS = {("dim_series", "series_code"), ("dim_month", "month")}

TABLES = ["dim_series", "dim_month", "monthly_long", "risk_summary", "yearly_real",
          "closure_summary", "correlation_long", "context"]
FACTS = ["monthly_long", "risk_summary", "yearly_real", "closure_summary"]
RELATIONSHIPS = [(f, "series_code", "dim_series", "series_code") for f in FACTS] + \
                [("monthly_long", "month", "dim_month", "month")]


def table_columns(table: str) -> list[dict]:
    """Columns of a model table: from the CSV header (+ renames + added columns)."""
    df = pd.read_csv(DATA / f"{table}.csv", encoding="utf-8")
    cols = []
    names = [RENAMES.get(table, {}).get(c, c) for c in df.columns]
    for raw, name in zip(df.columns, names):
        s = df[raw]
        if name in DATES:
            dt = "dateTime"
        elif name in BOOLS:
            dt = "boolean"
        elif name in INTS:
            dt = "int64"
        elif pd.api.types.is_numeric_dtype(s):
            dt = "double"
        else:
            dt = "string"
        cols.append({"name": name, "dataType": dt})
    for name, _, mtype in ADDED.get(table, []):
        cols.append({"name": name, "dataType": "int64" if "Int64" in mtype else "string",
                     "computed": True})
    for c in cols:
        n = c["name"]
        if c["dataType"] == "double":
            c["format"] = NUM_FORMAT.get(n, PCT)
        elif c["dataType"] == "dateTime":
            c["format"] = "yyyy-mm-dd"
        elif c["dataType"] == "int64":
            c["format"] = "0"
        c["hidden"] = ((table, n) in HIDDEN or
                       (table in FACTS and n in FACT_DESCRIPTIVE) or
                       (table == "monthly_long" and n in {"month", "month_end_gregorian"}))
        c["key"] = (table, n) in KEYS
        c["sortBy"] = SORT_BY.get((table, n))
    return cols


M_TYPE = {"string": "type text", "double": "type number", "int64": "Int64.Type",
          "boolean": "type logical", "dateTime": "type date"}


def m_query(table: str, cols: list[dict]) -> list[str]:
    raw = [c for c in cols if not c.get("computed")]
    steps = [
        f'Source = Csv.Document(File.Contents(DataFolder & "{table}.csv"), '
        f'[Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv])',
        'Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true])',
    ]
    prev = "Promoted"
    if table in RENAMES:
        pairs = ", ".join(f'{{"{a}", "{b}"}}' for a, b in RENAMES[table].items())
        steps.append(f"Renamed = Table.RenameColumns({prev}, {{{pairs}}})")
        prev = "Renamed"
    types = ", ".join(f'{{"{c["name"]}", {M_TYPE[c["dataType"]]}}}' for c in raw)
    steps.append(f'Typed = Table.TransformColumnTypes({prev}, {{{types}}}, "en-US")')
    prev = "Typed"
    if table in RLM_COLUMNS:
        tr = ", ".join(f'{{"{c}", each if _ = null then null else "#(200F)" & _ & "#(200F)", type text}}'
                       for c in RLM_COLUMNS[table])
        steps.append(f"Rtl = Table.TransformColumns({prev}, {{{tr}}})")
        prev = "Rtl"
    for i, (name, expr, mtype) in enumerate(ADDED.get(table, []), 1):
        steps.append(f'Added{i} = Table.AddColumn({prev}, "{name}", {expr}, {mtype})')
        prev = f"Added{i}"
    lines = ["let"]
    for i, st in enumerate(steps):
        lines.append("    " + st + ("," if i < len(steps) - 1 else ""))
    lines += ["in", "    " + prev]
    return lines


# --------------------------------------------------------------------------- #
# Measures: (name, folder, description, DAX lines, format)
# --------------------------------------------------------------------------- #
def M(name, folder, desc, dax, fmt=None):
    return {"name": name, "folder": folder, "desc": desc,
            "dax": dax.strip("\n").splitlines(), "format": fmt}


def fixed(table, col, code, extra=""):
    return (f"CALCULATE (\n    MAX ( {table}[{col}] ),\n    REMOVEFILTERS ( dim_series ),\n"
            f"    {table}[series_code] = \"{code}\"{extra}\n)")


def selected(col):
    return (f"VAR SeriesCode = [Selected series code]\nRETURN\n    CALCULATE (\n"
            f"        MAX ( risk_summary[{col}] ),\n        REMOVEFILTERS ( dim_series ),\n"
            f"        risk_summary[series_code] = SeriesCode\n    )")


MEASURES = [
    # ---- headline (ignore slicers and page filters on dim_series) ----
    M("CPI growth (×)", "1 Headline",
      "CPI 1405-06 divided by CPI 1402-06 (3.62 = prices multiplied by 3.62 in 3 years).",
      "VAR CpiCum3y =\n" + "\n".join("    " + x for x in fixed("risk_summary", "nominal_cum_3y", "cpi").splitlines())
      + "\nRETURN\n    1 + CpiCum3y", "0.00×"),
    M("Index real cum 3y", "1 Headline",
      "Overall index (شاخص کل): real return, cumulative over 3 years (1402-06 to 1405-06).",
      fixed("risk_summary", "real_cum_3y", "index_total"), PCT),
    M("Equal-weight real cum 3y", "1 Headline",
      "Equal-weight index: real return, cumulative over 3 years (1402-06 to 1405-06).",
      fixed("risk_summary", "real_cum_3y", "index_equal_weight"), PCT),
    M("Stocks beating inflation", "1 Headline",
      "How many of the 8 sample stocks had a positive real return, cumulative over 3 years, as '3 / 8'.",
      """VAR Stocks =
    CALCULATETABLE (
        risk_summary,
        REMOVEFILTERS ( dim_series ),
        dim_series[type] = "stock"
    )
VAR Winners = COUNTROWS ( FILTER ( Stocks, risk_summary[real_cum_3y] > 0 ) )
VAR Total = COUNTROWS ( Stocks )
RETURN
    FORMAT ( Winners, "0" ) & " / " & FORMAT ( Total, "0" )"""),
    M("Closure real loss (pro-rated)", "1 Headline",
      "Overall index, real change from the last close before the closure (1404-12-06) to the first "
      "close after it (1405-02-29), CPI pro-rated to those dates. Cumulative over the closure.",
      fixed("closure_summary", "real_prorated", "index_total",
            ',\n    closure_summary[window] = "on_reopening"'), PCT),
    M("Closure real loss (whole months)", "1 Headline",
      "Sensitivity for the closure loss: CPI from end of 1404-11 to end of 1405-02.",
      fixed("closure_summary", "real_whole_months", "index_total",
            ',\n    closure_summary[window] = "on_reopening"'), PCT),

    # ---- selected series (slicer on page 2; default = overall index) ----
    M("Selected series code", "2 Selected series",
      "series_code of the single series in the filter context; the overall index when none or several.",
      'IF (\n    HASONEVALUE ( dim_series[series_code] ),\n    VALUES ( dim_series[series_code] ),\n    "index_total"\n)'),
    M("Selected series", "2 Selected series", "Persian name of the selected series.",
      "VAR SeriesCode = [Selected series code]\nRETURN\n    CALCULATE (\n        MAX ( dim_series[series_fa] ),\n"
      "        REMOVEFILTERS ( dim_series ),\n        dim_series[series_code] = SeriesCode\n    )"),
    M("Selected real CAGR", "2 Selected series", "Real CAGR of the selected series, per year.",
      selected("real_cagr"), PCT),
    M("Selected real vol", "2 Selected series",
      "Volatility of monthly real returns of the selected series, annualized (per year).",
      selected("real_vol_per_year"), PCT),
    M("Selected max drawdown", "2 Selected series",
      "Largest peak-to-trough fall of the selected series' real cumulative index.",
      selected("real_max_drawdown_peak_to_trough"), PCT),
    M("Selected months beating inflation", "2 Selected series",
      "Share of the 36 months in which the selected series beat that month's inflation.",
      selected("pct_months_beat_inflation"), PCT0),
    M("Selected real cum 3y", "2 Selected series",
      "Real return of the selected series, cumulative over 3 years.", selected("real_cum_3y"), PCT),

    # ---- values that follow the filter context (one row per series / month) ----
    M("Real growth index", "3 Series values",
      "Real growth of 100 invested at the end of 1402-06 (CPI = 100).",
      "AVERAGE ( monthly_long[real_index_1402_06_eq_100] )", "0.0"),
    M("Nominal growth index", "3 Series values", "Nominal growth of 100 invested at the end of 1402-06.",
      "AVERAGE ( monthly_long[nominal_index_1402_06_eq_100] )", "0.0"),
    M("Real return rolling 12m", "3 Series values",
      "Real return over the 12 months ending in the month (per year).",
      "AVERAGE ( monthly_long[real_return_rolling_12m] )", PCT),
    M("Real return per month", "3 Series values", "Real return of one month.",
      "AVERAGE ( monthly_long[real_return_per_month] )", PCT),
    M("Real CAGR", "3 Series values", "Real CAGR over 36 months, per year.",
      "AVERAGE ( risk_summary[real_cagr] )", PCT),
    M("Real CAGR color", "3 Series values",
      "Bar colour for real returns: green above 0, red below 0, grey at 0. Used as conditional "
      "formatting (field value).",
      """VAR RealCagr = [Real CAGR]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( RealCagr ), BLANK (),
        RealCagr > 0, "#2E7D32",
        RealCagr < 0, "#C62828",
        "#8C8C8C"
    )"""),
    M("Correlation (real, monthly)", "3 Series values",
      "Correlation of monthly real returns between two series (correlation_long, 36 months).",
      "AVERAGE ( correlation_long[corr_real_return_per_month] )", "0.00"),
    M("Nominal CAGR", "3 Series values", "Nominal CAGR over 36 months, per year.",
      "AVERAGE ( risk_summary[nominal_cagr] )", PCT),
    M("Real cum 3y", "3 Series values", "Real return, cumulative over 3 years.",
      "AVERAGE ( risk_summary[real_cum_3y] )", PCT),
    M("Real vol per year", "3 Series values", "Volatility of monthly real returns, annualized.",
      "AVERAGE ( risk_summary[real_vol_per_year] )", PCT),
    M("Real max drawdown", "3 Series values", "Largest peak-to-trough fall of the real cumulative index.",
      "AVERAGE ( risk_summary[real_max_drawdown_peak_to_trough] )", PCT),
    M("Months beating inflation", "3 Series values", "Share of months beating that month's inflation.",
      "AVERAGE ( risk_summary[pct_months_beat_inflation] )", PCT0),
    M("Real return per year (block)", "3 Series values",
      "Real return of one 12-month block (per year).",
      "AVERAGE ( yearly_real[real_return_per_year] )", PCT),

    # ---- closure (cumulative over the window) ----
    M("Closure nominal", "4 Closure", "Nominal change over the window (cumulative).",
      "AVERAGE ( closure_summary[nominal] )", PCT),
    M("Closure CPI (pro-rated)", "4 Closure", "CPI change over the window, pro-rated to the dates.",
      "AVERAGE ( closure_summary[cpi_prorated] )", PCT),
    M("Closure real (pro-rated)", "4 Closure", "Real change over the window, CPI pro-rated (primary).",
      "AVERAGE ( closure_summary[real_prorated] )", PCT),
    M("Closure CPI (whole months)", "4 Closure", "CPI change over whole calendar months (sensitivity).",
      "AVERAGE ( closure_summary[cpi_whole_months] )", PCT),
    M("Closure real (whole months)", "4 Closure", "Real change with whole-month CPI (sensitivity).",
      "AVERAGE ( closure_summary[real_whole_months] )", PCT),

    # ---- risk-free context (one-row table) ----
    M("Bond YTM", "5 Context", "Median yield to maturity of government Murabaha bonds (اراد), per year. "
      "Forward-looking snapshot.", "MAX ( context[bond_ytm] )", PCT),
    M("Inflation 12m avg", "5 Context", "Trailing inflation, 12-month average, per year.",
      "MAX ( context[inflation_12m_avg] )", PCT),
    M("Inflation point-to-point", "5 Context", "Trailing inflation, point to point over 12 months.",
      "MAX ( context[inflation_point_to_point] )", PCT),
    M("Bond real yield (avg)", "5 Context",
      "Implied real yield per year if inflation stays at last year's 12-month average.",
      "MAX ( context[real_yield_avg] )", PCT),
    M("Bond real yield (p2p)", "5 Context",
      "Implied real yield per year if inflation stays at last year's point-to-point rate.",
      "MAX ( context[real_yield_p2p] )", PCT),
    M("Bond source note", "5 Context", "Source and snapshot date of the bond yield. Text.",
      '"منبع: " & MAX ( context[source_url] ) & "  |  تاریخ داده: " & MAX ( context[snapshot_date] )'
      ' & UNICHAR ( 8207 )'),
    M("Bond conditional statement", "5 Context", "The bond comparison as a conditional sentence. Text.",
      '"اگر تورم در سطح سال گذشته بماند، بازده امروز اوراق دولتی به معنای بازده واقعی حدود "\n'
      '    & FORMAT ( [Bond real yield (avg)], "0%" ) & " در سال است ("\n'
      '    & FORMAT ( [Bond real yield (p2p)], "0%" ) & " در برابر تورم نقطه به نقطه)."\n'
      '    & UNICHAR ( 8207 )'),
]


def q(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def tmdl_table(table: str) -> str:
    cols = table_columns(table)
    L = [f"table {table}", f"\tlineageTag: {uid('table', table)}", ""]
    for c in cols:
        L.append(f"\tcolumn {c['name']}")
        L.append(f"\t\tdataType: {c['dataType']}")
        if c["hidden"]:
            L.append("\t\tisHidden")
        if c.get("format"):
            L.append(f"\t\tformatString: {c['format']}")
        if c["key"]:
            L.append("\t\tisKey")
        L.append(f"\t\tlineageTag: {uid('column', table, c['name'])}")
        L.append("\t\tsummarizeBy: none")
        L.append(f"\t\tsourceColumn: {c['name']}")
        if c["sortBy"]:
            L.append(f"\t\tsortByColumn: {c['sortBy']}")
        L += ["", "\t\tannotation SummarizationSetBy = User", ""]
        if c["dataType"] == "dateTime":
            L += ["\t\tannotation UnderlyingDateTimeDataType = Date", ""]
    L += [f"\tpartition {table} = m", "\t\tmode: import", "\t\tsource ="]
    L += ["\t\t\t\t" + x for x in m_query(table, cols)]
    L += ["", "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(L) + "\n"


def tmdl_measures() -> str:
    L = ["table _Measures", f"\tlineageTag: {uid('table', '_Measures')}", ""]
    for m in MEASURES:
        L.append(f"\t/// {m['desc']}")
        if len(m["dax"]) == 1:
            L.append(f"\tmeasure {q(m['name'])} = {m['dax'][0]}")
        else:
            L.append(f"\tmeasure {q(m['name'])} =")
            L += ["\t\t\t" + x for x in m["dax"]]
        if m["format"]:
            L.append(f"\t\tformatString: {m['format']}")
        L.append(f"\t\tdisplayFolder: {m['folder']}")
        L.append(f"\t\tlineageTag: {uid('measure', m['name'])}")
        L.append("")
    L += ["\tpartition _Measures = m", "\t\tmode: import", "\t\tsource =",
          "\t\t\t\tlet",
          '\t\t\t\t    Source = Table.FromRows(Json.Document(Binary.Decompress(Binary.FromText("i44FAA==", '
          'BinaryEncoding.Base64), Compression.Deflate)), let _t = ((type nullable text) meta '
          '[Serialized.Text = true]) in type table [Column1 = _t]),',
          '\t\t\t\t    #"Changed Type" = Table.TransformColumnTypes(Source,{{"Column1", type text}}),',
          '\t\t\t\t    #"Removed Columns" = Table.RemoveColumns(#"Changed Type",{"Column1"})',
          "\t\t\t\tin", '\t\t\t\t    #"Removed Columns"', "",
          "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(L) + "\n"


def measures_dax() -> str:
    out = ["// DAX measures of the tse_inflation semantic model (table _Measures).",
           "// Generated by src/build_dashboard.py; identical to _Measures.tmdl.",
           "// Units: CAGR and vol are per year; 'cum 3y' is cumulative 1402-06 to 1405-06;",
           "// closure figures are cumulative over the stated window.", ""]
    for m in MEASURES:
        out.append(f"// [{m['folder']}] {m['desc']}" + (f"  Format: {m['format']}" if m["format"] else ""))
        out.append(f"{q(m['name'])} =")
        out += ["    " + x for x in m["dax"]]
        out.append("")
    return "\n".join(out)


def write_model(data_folder: str) -> None:
    d = SM / "definition"
    (d / "tables").mkdir(parents=True, exist_ok=True)
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1606\n\n", encoding="utf-8")
    query_order = json.dumps(["DataFolder"] + TABLES + ["_Measures"], ensure_ascii=False)
    model = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
             "\tsourceQueryCulture: en-US", "\tdataAccessOptions", "\t\tlegacyRedirects",
             "\t\treturnErrorValuesAsNull", "",
             "annotation __PBI_TimeIntelligenceEnabled = 0", "",
             f"annotation PBI_QueryOrder = {query_order}", "",
             'annotation PBI_ProTooling = ["DevMode"]', ""]
    model += [f"ref table {t}" for t in TABLES + ["_Measures"]] + [""]
    if (d / "cultures" / "en-US.tmdl").exists():   # written by Power BI Desktop on save
        model += ["ref cultureInfo en-US", ""]
    (d / "model.tmdl").write_text("\n".join(model), encoding="utf-8")
    folder = data_folder.replace('"', '""')
    (d / "expressions.tmdl").write_text(
        f'expression DataFolder = "{folder}" meta [IsParameterQuery=true, Type="Text", '
        f'IsParameterQueryRequired=true]\n\tlineageTag: {uid("expression", "DataFolder")}\n\n'
        "\tannotation PBI_NavigationStepName = Navigation\n\n\tannotation PBI_ResultType = Text\n\n",
        encoding="utf-8")
    rel = []
    for f, fc, t, tc in RELATIONSHIPS:
        rel += [f"relationship {uid('rel', f, fc, t, tc)}", f"\tfromColumn: {f}.{fc}",
                f"\ttoColumn: {t}.{tc}", ""]
    (d / "relationships.tmdl").write_text("\n".join(rel), encoding="utf-8")
    for old in (d / "tables").glob("*.tmdl"):
        old.unlink()
    for t in TABLES:
        (d / "tables" / f"{t}.tmdl").write_text(tmdl_table(t), encoding="utf-8")
    (d / "tables" / "_Measures.tmdl").write_text(tmdl_measures(), encoding="utf-8")
    (SM / "definition.pbism").write_text(json.dumps({"version": "4.2", "settings": {}}, indent=2),
                                         encoding="utf-8")
    (SM / ".platform").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": uid("logical", "model")}}, indent=2), encoding="utf-8")
    (SM / ".pbi").mkdir(exist_ok=True)
    # Parallel loading of tables is OFF: with it on, refresh crashed on a low-memory machine
    # ("Container unexpectedly exited", 0x800705AF). Same keys Desktop writes.
    (SM / ".pbi" / "editorSettings.json").write_text(json.dumps({
        "version": "1.0", "parallelQueryLoading": False,
        "shouldNotifyUserOfNameConflictResolution": True}, indent=2), encoding="utf-8")


# =========================================================================== #
# Report specification (PBIR)
# =========================================================================== #
INK, INK2, NAVY = "#1A1A1A", "#52514E", "#0D366B"
BLUE_DARK, BLUE, BLUE_LIGHT, BLUE_PALE = "#1F4E79", "#2A78D6", "#6DA7EC", "#A9CCF3"
GREEN, RED, GREY, WHITE = "#2E7D32", "#C62828", "#8C8C8C", "#FFFFFF"
# keys are dim_series[series_fa] as loaded (Power Query wraps them in RLM marks)
SERIES_COLORS = {"شاخص کل": BLUE_DARK, "شاخص کل (هم‌وزن)": BLUE_LIGHT,
                 "شاخص قیمت مصرف‌کننده (تورم)": GREY}
FOOTER = "منبع: TSETMC و شاخص قیمت مصرف‌کننده مرکز آمار ایران (۱۴۰۰=۱۰۰)"
HINDSIGHT_NOTE = "۸ سهم با نگاه به گذشته انتخاب شده‌اند و نمایندهٔ کل بازار نیستند."
WILDCARD = [{"dataViewWildcard": {"matchingOption": 1}}]

# Page geometry (1280 x 720). Content sits between CONTENT_TOP and CONTENT_BOTTOM; the
# footer box ends 8 px above the canvas edge so its text is never cut off.
PAGE_W, PAGE_H = 1280, 720
CONTENT_TOP, CONTENT_BOTTOM = 100, 674
FOOTER_Y, FOOTER_H = 682, 30
CARD_H = 92

# Card labels: short, no parentheses (they sit under the value at 9pt).
CARDS_P1 = [("CPI growth (×)", "رشد قیمت‌ها در ۳ سال، برابر"),
            ("Index real cum 3y", "بازده واقعی شاخص کل، ۳ ساله"),
            ("Equal-weight real cum 3y", "بازده واقعی شاخص هم‌وزن، ۳ ساله"),
            ("Stocks beating inflation", "سهام نمونهٔ جلوتر از تورم"),
            ("Closure real loss (pro-rated)", "زیان واقعی تعطیلی تا بازگشایی")]
CARDS_P2 = [("Selected series", "سری انتخاب‌شده"),
            ("Selected real CAGR", "بازده واقعی سالانه"),
            ("Selected real vol", "نوسان واقعی سالانه"),
            ("Selected max drawdown", "بیشترین افت واقعی از اوج"),
            ("Selected months beating inflation", "ماه‌های جلوتر از تورم")]
CARDS_P3 = [("Bond YTM", "بازده اوراق دولتی، سالانه"),
            ("Inflation 12m avg", "تورم ۱۲ ماهه، میانگین"),
            ("Inflation point-to-point", "تورم نقطه به نقطه"),
            ("Bond real yield (avg)", "بازده واقعی با تورم میانگین"),
            ("Bond real yield (p2p)", "بازده واقعی با تورم نقطه به نقطه")]


def data_fa(name: str) -> str:
    """A Persian data value as Power Query loads it (wrapped in RLM marks)."""
    return RLM + name + RLM


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def s(text):
    return lit("'" + str(text).replace("'", "''") + "'")


def num(v):
    return lit(f"{v}D")


def color(hexv):
    return {"solid": {"color": s(hexv)}}


def col_field(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def meas_field(prop):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": prop}}


def measure_color(measure):
    """Colour taken from a measure that returns a hex code (conditional formatting by field value)."""
    return {"solid": {"color": {"expr": meas_field(measure)}}}


def gradient3(measure, low, mid, high, mid_value="0D"):
    """Diverging colour scale (low - mid - high), mid fixed at mid_value, min/max automatic."""
    c = lambda h: {"Literal": {"Value": f"'{h}'"}}
    return {"solid": {"color": {"expr": {"FillRule": {
        "Input": meas_field(measure),
        "FillRule": {"linearGradient3": {
            "min": {"color": c(low)},
            "mid": {"color": c(mid), "value": {"Literal": {"Value": mid_value}}},
            "max": {"color": c(high)},
            "nullColoringStrategy": {"strategy": {"Literal": {"Value": "'asZero'"}}}}}}}}}}


def gradient2(measure, low, high, low_value="0D", high_value="1D"):
    c = lambda h: {"Literal": {"Value": f"'{h}'"}}
    return {"solid": {"color": {"expr": {"FillRule": {
        "Input": meas_field(measure),
        "FillRule": {"linearGradient2": {
            "min": {"color": c(low), "value": {"Literal": {"Value": low_value}}},
            "max": {"color": c(high), "value": {"Literal": {"Value": high_value}}},
            "nullColoringStrategy": {"strategy": {"Literal": {"Value": "'asZero'"}}}}}}}}}}


def proj(field, display=None, active=None):
    kind = "Column" if "Column" in field else "Measure"
    ent = field[kind]["Expression"]["SourceRef"]["Entity"]
    prop = field[kind]["Property"]
    p = {"field": field, "queryRef": f"{ent}.{prop}", "nativeQueryRef": prop}
    if active is not None:
        p["active"] = active
    if display:
        p["displayName"] = rtl(display)
    return p


def padding(px):
    return [{"properties": {k: num(px) for k in ("top", "bottom", "left", "right")}}]


def title_objects(text, size=11):
    return {"title": [{"properties": {
        "show": lit("true"), "text": s(rtl(text)), "fontColor": color(INK), "fontSize": num(size),
        "fontFamily": s("Segoe UI"), "alignment": s("right"), "titleWrap": lit("true")}}],
        "padding": padding(6)}


def axis_objects(font=9):
    """Readable axes: 9pt labels, no axis titles (the visual title names the measure)."""
    return {"categoryAxis": [{"properties": {"fontSize": num(font), "showAxisTitle": lit("false")}}],
            "valueAxis": [{"properties": {"fontSize": num(font), "showAxisTitle": lit("false")}}]}


def in_filter(name, entity, prop, values, locked=False):
    f = {"name": name, "field": col_field(entity, prop), "type": "Categorical",
         "filter": {"Version": 2, "From": [{"Name": "d", "Entity": entity, "Type": 0}],
                    "Where": [{"Condition": {"In": {
                        "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "d"}},
                                                    "Property": prop}}],
                        "Values": [[{"Literal": {"Value": "'" + v + "'"}}] for v in values]}}}]},
         "howCreated": "User"}
    if locked:
        f["isLockedInViewMode"] = True
    return f


class Page:
    def __init__(self, key, display, type_values):
        self.key = key
        self.id = hid("page", key)
        self.display = rtl(display)
        self.type_values = type_values
        self.visuals: list[dict] = []
        self.interactions: list[dict] = []
        self.z = 0

    def add(self, key, x, y, w, h, visual, filters=None):
        name = hid("visual", self.id, key)
        v = {"$schema": f"{SCHEMA}/visualContainer/2.11.0/schema.json", "name": name,
             "position": {"x": int(round(x)), "y": int(round(y)), "z": self.z,
                          "height": int(round(h)), "width": int(round(w)), "tabOrder": self.z},
             "visual": visual}
        if filters:
            v["filterConfig"] = {"filters": filters}
        self.z += 1
        self.visuals.append(v)
        return name

    def header(self, title, finding, note):
        """Title, one-line main finding, method note and the source footer."""
        self.add("title", 24, 6, 1232, 36, textbox([(title, 18, True, NAVY)]))
        self.add("subtitle", 24, 42, 1232, 28, textbox([(finding, 11, False, BLUE_DARK)]))
        self.add("note", 24, 70, 1232, 26, textbox([(note, 9, False, INK2)]))
        self.add("footer", 24, FOOTER_Y, 1232, FOOTER_H, textbox([(FOOTER, 9, False, INK2)]))

    def page_json(self):
        p = {"$schema": f"{SCHEMA}/page/2.1.0/schema.json", "name": self.id,
             "displayName": self.display, "displayOption": "FitToPage",
             "height": PAGE_H, "width": PAGE_W,
             "filterConfig": {"filters": [in_filter(hid("pf", self.id), "dim_series", "type",
                                                    self.type_values, locked=True)]}}
        if self.interactions:
            p["visualInteractions"] = self.interactions
        return p


def textbox(paragraphs):
    """Right-aligned text box; every Persian run is wrapped in RLM marks."""
    paras = []
    for text, size, bold, col in paragraphs:
        style = {"fontFamily": "Segoe UI", "fontSize": f"{size}pt", "color": col}
        if bold:
            style["fontWeight"] = "bold"
        paras.append({"textRuns": [{"value": rtl(text), "textStyle": style}],
                      "horizontalTextAlignment": "right"})
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paras}}]},
            "visualContainerObjects": {"padding": padding(0)},
            "drillFilterOtherVisuals": True}


def card(measure, label, value_pt=20, label_pt=9):
    """Card: value 20pt, label 9pt under it, minimal padding."""
    return {"visualType": "cardVisual",
            "query": {"queryState": {"Data": {"projections": [proj(meas_field(measure), label)]}}},
            "objects": {"value": [{"properties": {"fontSize": num(value_pt)}, "selector": {"id": "default"}}],
                        "label": [{"properties": {"fontSize": num(label_pt)}, "selector": {"id": "default"}}]},
            "visualContainerObjects": {"padding": padding(4)},
            "drillFilterOtherVisuals": True}


def series_color_objects():
    out = []
    for name, c in SERIES_COLORS.items():
        out.append({"properties": {"fill": color(c)},
                    "selector": {"data": [{"scopeId": {"Comparison": {
                        "ComparisonKind": 0, "Left": col_field("dim_series", "series_fa"),
                        "Right": {"Literal": {"Value": "'" + data_fa(name) + "'"}}}}}]}})
    return out


def line_chart(measure, label, title, zero_line=False):
    v = {"visualType": "lineChart",
         "query": {"queryState": {
             "Category": {"projections": [proj(col_field("dim_month", "month_label_fa"), "ماه", True)]},
             "Y": {"projections": [proj(meas_field(measure), label)]},
             "Series": {"projections": [proj(col_field("dim_series", "series_fa"), "سری")]}},
             "sortDefinition": {"sort": [{"field": col_field("dim_month", "month_label_fa"),
                                          "direction": "Ascending"}]}},
         "objects": {"lineStyles": [{"properties": {"strokeWidth": num(2)}}],
                     "legend": [{"properties": {"show": lit("true"), "position": s("Top"),
                                                "fontSize": num(9)}}],
                     "dataPoint": series_color_objects(), **axis_objects()},
         "visualContainerObjects": title_objects(title),
         "drillFilterOtherVisuals": True}
    if zero_line:
        v["objects"]["y1AxisReferenceLine"] = [{"properties": {
            "show": lit("true"), "displayName": s(rtl("صفر: هم‌پای تورم")), "value": lit("0D"),
            "lineColor": color(INK2), "transparency": lit("0D"), "style": s("dashed"),
            "position": s("front"), "dataLabelShow": lit("true")}, "selector": {"id": "1"}}]
    return v


def bar_chart(measures, title, sort_measure=None, colors=None, sign_colored=None):
    """Clustered bar by series. sign_colored: measure whose bars take green/red from
    [Real CAGR color] (conditional formatting by field value)."""
    v = {"visualType": "clusteredBarChart",
         "query": {"queryState": {
             "Category": {"projections": [proj(col_field("dim_series", "series_fa"), "سری", True)]},
             "Y": {"projections": [proj(meas_field(m), lab) for m, lab in measures]}}},
         "objects": {"labels": [{"properties": {"show": lit("true"), "fontSize": num(8)}}],
                     "legend": [{"properties": {"show": lit("true" if len(measures) > 1 else "false"),
                                                "position": s("Top"), "fontSize": num(9)}}],
                     "dataPoint": [], **axis_objects()},
         "visualContainerObjects": title_objects(title),
         "drillFilterOtherVisuals": True}
    if sort_measure:
        v["query"]["sortDefinition"] = {"sort": [{"field": meas_field(sort_measure), "direction": "Descending"}]}
    colors = colors or {}
    for m, _ in measures:
        if m == sign_colored:
            v["objects"]["dataPoint"].append({"properties": {"fill": measure_color("Real CAGR color")},
                                              "selector": {"data": WILDCARD, "metadata": f"_Measures.{m}"}})
        elif m in colors:
            v["objects"]["dataPoint"].append({"properties": {"fill": color(colors[m])},
                                              "selector": {"metadata": f"_Measures.{m}"}})
    return v


def matrix_text_objects(font=9):
    return {"columnHeaders": [{"properties": {"fontSize": num(font), "wordWrap": lit("true")}}],
            "rowHeaders": [{"properties": {"fontSize": num(font), "wordWrap": lit("true")}}],
            "values": [{"properties": {"fontSize": num(font)}}]}


def fa(x: float, fmt: str) -> str:
    """Number in Persian digits, Persian decimal separator and a real minus sign."""
    t = format(x, fmt).replace("-", "−").replace(".", "٫")
    return t.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def findings() -> dict[str, str]:
    """One-line main finding per page, computed from the CSVs at build time."""
    rs = pd.read_csv(DATA / "risk_summary.csv").set_index("code")
    cl = pd.read_csv(DATA / "closure_summary.csv").set_index(["series_code", "window"])
    ctx = pd.read_csv(DATA / "context.csv").iloc[0]
    ml = pd.read_csv(DATA / "monthly_long.csv")
    corr = pd.read_csv(DATA / "correlation_long.csv")
    st = rs[rs["type"] == "stock"]
    roll = ml[(ml["series_code"] == "index_total")]["real_return_rolling_12m"].dropna()
    ci = corr[(corr["series_b_code"] == "index_total") &
              corr["series_a_code"].isin(st.index)]["corr_real_return_per_month"]
    clo = cl.loc[("index_total", "on_reopening")]
    return {
        "overview": (f"قیمت‌ها در ۳ سال {fa(1 + rs.loc['cpi', 'nominal_cum_3y'], '.2f')} برابر شد؛ "
                     f"شاخص کل {fa(-rs.loc['index_total', 'real_cum_3y'] * 100, '.1f')}٪ و شاخص هم‌وزن "
                     f"{fa(-rs.loc['index_equal_weight', 'real_cum_3y'] * 100, '.1f')}٪ از قدرت خرید را "
                     f"در این ۳ سال از دست دادند."),
        "dispersion": (f"فقط {fa((st['real_cum_3y'] > 0).sum(), 'd')} سهم از {fa(len(st), 'd')} سهم نمونه از "
                       f"تورم جلو زدند؛ بازده واقعی سالانه از {fa(st['real_cagr'].min() * 100, '.1f')}٪ تا "
                       f"+{fa(st['real_cagr'].max() * 100, '.1f')}٪ پراکنده است."),
        "closure": (f"تعطیلی بازار تا بازگشایی {fa(-clo['real_prorated'] * 100, '.1f')}٪ زیان واقعی داشت؛ "
                    f"اگر تورم در سطح سال گذشته بماند، اوراق دولتی هم بازده واقعی حدود "
                    f"{fa(ctx['real_yield_avg'] * 100, '.0f')}٪ در سال دارند."),
        "timing": (f"بازده واقعی ۱۲ ماههٔ شاخص کل فقط در {fa((roll > 0).sum(), 'd')} ماه از "
                   f"{fa(len(roll), 'd')} ماه مثبت بود؛ همبستگی ماهانهٔ سهام با شاخص کل "
                   f"{fa(ci.min(), '.2f')} تا {fa(ci.max(), '.2f')} است و بیشتر سهام همراه بازار بالا و پایین رفتند."),
    }


def bond_statement() -> tuple[str, str]:
    """Static text for page 3 (the bond figures are a dated snapshot)."""
    ctx = pd.read_csv(DATA / "context.csv").iloc[0]
    line1 = (f"اگر تورم در سطح سال گذشته بماند، بازده امروز اوراق دولتی به معنای بازده واقعی حدود "
             f"{fa(ctx['real_yield_avg'] * 100, '.0f')}٪ در سال است و در برابر تورم نقطه به نقطه حدود "
             f"{fa(ctx['real_yield_p2p'] * 100, '.0f')}٪.")
    line2 = (f"بازده تا سررسید {fa(ctx['bond_ytm'] * 100, '.1f')}٪ در سال، میانهٔ "
             f"{fa(int(ctx['n_bonds']), 'd')} ورقهٔ اراد معامله‌شده در ۳۰ روز پیش از "
             f"{ctx['snapshot_date'].translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))}؛ "
             f"منبع: فرابورس ایران، ifb.ir")
    return line1, line2


def build_report() -> list[Page]:
    F = findings()
    stock_pf = ["stock", "market_index", "portfolio"]
    TOP, BOTTOM = CONTENT_TOP, CONTENT_BOTTOM

    # ---------------- page 1 ----------------
    p1 = Page("overview", "نمای کلی: بورس در برابر تورم", ["market_index", "cpi"])
    p1.header("آیا بورس تهران از تورم جلو زد؟ مهر ۱۴۰۲ تا شهریور ۱۴۰۵", F["overview"],
              "نتیجه‌گیری دربارهٔ بازار فقط بر اساس شاخص کل و شاخص کل هم‌وزن است. واقعی یعنی "
              "تعدیل‌شده با شاخص قیمت مصرف‌کنندهٔ مرکز آمار ایران.")
    w = (1232 - 4 * 16) / 5
    for i, (m, lab) in enumerate(CARDS_P1):
        p1.add(f"card{i}", 24 + i * (w + 16), TOP, w, CARD_H, card(m, lab))
    p1.add("hindsight", 24, TOP + CARD_H + 6, 1232, 26, textbox([(HINDSIGHT_NOTE, 10, True, RED)]))
    charts_top = TOP + CARD_H + 38
    p1.add("growth", 24, charts_top, 760, BOTTOM - charts_top, line_chart(
        "Real growth index", "رشد واقعی، ۱۰۰ = پایان شهریور ۱۴۰۲",
        "رشد واقعی ۱۰۰ واحد سرمایه از پایان شهریور ۱۴۰۲؛ خط تورم = ۱۰۰"))
    p1.add("cagr", 800, charts_top, 456, BOTTOM - charts_top, bar_chart(
        [("Nominal CAGR", "اسمی سالانه"), ("Real CAGR", "واقعی سالانه")],
        "رشد سالانه: اسمی در برابر واقعی",
        colors={"Nominal CAGR": BLUE_PALE, "Real CAGR": BLUE_DARK}))

    # ---------------- page 2 ----------------
    p2 = Page("dispersion", "پراکندگی: ۸ سهم نمونه، نه کل بازار", stock_pf)
    p2.header("پراکندگی بازده: ۸ سهم نمونه، یک سهم از هر صنعت", F["dispersion"],
              "این ۸ سهم پراکندگی میان صنایع را نشان می‌دهند، نه بازار را. سبد هم‌وزن با نگاه به گذشته "
              "انتخاب شده است. سبز یعنی بالای صفر و قرمز یعنی زیر صفر. شاخص‌های صنایع نمایش داده نمی‌شوند.")
    slicer_name = p2.add("slicer", 24, TOP, 240, CARD_H, {
        "visualType": "slicer",
        "query": {"queryState": {"Values": {"projections": [
            proj(col_field("dim_series", "series_fa"), "انتخاب سری", True)]}}},
        "objects": {"data": [{"properties": {"mode": s("Dropdown")}}],
                    "selection": [{"properties": {"singleSelect": lit("true")}}],
                    "header": [{"properties": {"show": lit("true"), "text": s(rtl("انتخاب سری")),
                                               "fontSize": num(9)}}],
                    "items": [{"properties": {"fontSize": num(9)}}]},
        "visualContainerObjects": {"padding": padding(4)},
        "drillFilterOtherVisuals": True})
    w2 = (1256 - 280 - 4 * 12) / 5
    for i, (m, lab) in enumerate(CARDS_P2):
        p2.add(f"sel{i}", 280 + i * (w2 + 12), TOP, w2, CARD_H, card(m, lab))
    row_top = TOP + CARD_H + 12
    targets = [p2.add("bar", 24, row_top, 400, BOTTOM - row_top, bar_chart(
        [("Real CAGR", "بازده واقعی سالانه")], "بازده واقعی سالانهٔ هر سری",
        sort_measure="Real CAGR", sign_colored="Real CAGR"))]
    mid = row_top + (BOTTOM - row_top) // 2
    targets.append(p2.add("scatter", 440, row_top, 400, mid - row_top - 6, {
        "visualType": "scatterChart",
        "query": {"queryState": {
            "Category": {"projections": [proj(col_field("dim_series", "series_fa"), "سری", True)]},
            "X": {"projections": [proj(meas_field("Real vol per year"), "نوسان واقعی سالانه")]},
            "Y": {"projections": [proj(meas_field("Real CAGR"), "بازده واقعی سالانه")]}}},
        "objects": {"categoryLabels": [{"properties": {"show": lit("true"), "fontSize": num(8)}}],
                    "dataPoint": [{"properties": {"fill": color(BLUE)}}], **axis_objects()},
        "visualContainerObjects": title_objects("ریسک در برابر بازده واقعی سالانه"),
        "drillFilterOtherVisuals": True}))
    block_measure = "Real return per year (block)"
    mobj = matrix_text_objects()
    mobj["values"].append({"properties": {"backColor": gradient3(block_measure, RED, WHITE, GREEN)},
                           "selector": {"data": WILDCARD, "metadata": f"_Measures.{block_measure}"}})
    targets.append(p2.add("matrix", 440, mid + 6, 400, BOTTOM - mid - 6, {
        "visualType": "pivotTable",
        "query": {"queryState": {
            "Rows": {"projections": [proj(col_field("dim_series", "series_fa"), "سری", True)]},
            "Columns": {"projections": [proj(col_field("yearly_real", "block_fa"), "دورهٔ ۱۲ ماهه", True)]},
            "Values": {"projections": [proj(meas_field(block_measure), "بازده واقعی سالانه")]}}},
        "objects": mobj,
        "visualContainerObjects": title_objects("بازده واقعی هر دورهٔ ۱۲ ماهه"),
        "drillFilterOtherVisuals": True}))
    risk_cols = [("Nominal CAGR", "اسمی سالانه"), ("Real CAGR", "واقعی سالانه"),
                 ("Real cum 3y", "واقعی ۳ ساله"), ("Real vol per year", "نوسان سالانه"),
                 ("Real max drawdown", "بیشترین افت"), ("Months beating inflation", "ماه‌های برنده")]
    targets.append(p2.add("table", 856, row_top, 400, BOTTOM - row_top, {
        "visualType": "tableEx",
        "query": {"queryState": {"Values": {"projections":
            [proj(col_field("dim_series", "series_fa"), "سری")] +
            [proj(meas_field(m), lab) for m, lab in risk_cols]}},
            "sortDefinition": {"sort": [{"field": meas_field("Real CAGR"), "direction": "Descending"}]}},
        "objects": {"columnHeaders": [{"properties": {"fontSize": num(9), "wordWrap": lit("true")}}],
                    "values": [{"properties": {"fontSize": num(9)}}]},
        "visualContainerObjects": title_objects("جدول بازده و ریسک"),
        "drillFilterOtherVisuals": True}))
    p2.interactions = [{"source": slicer_name, "target": t, "type": "NoFilter"} for t in targets]

    # ---------------- page 3 ----------------
    p3 = Page("closure", "تعطیلی بازار و دارایی امن", ["market_index", "stock"])
    p3.header("تعطیلی بازار از ۹ اسفند ۱۴۰۴ تا ۲۸ اردیبهشت ۱۴۰۵ و بازده اوراق دولتی", F["closure"],
              "ارقام تعطیلی تجمعی در همان بازه‌اند. روش اصلی تورم روزشمار است و ماه کامل فقط آزمون "
              "حساسیت است. فولاد تا ۱۷ مرداد ۱۴۰۵ متوقف بود و قابل مقایسه نیست.")
    p3.add("closurebar", 24, TOP, 600, 300, bar_chart(
        [("Closure nominal", "تغییر اسمی"), ("Closure CPI (pro-rated)", "تورم روزشمار"),
         ("Closure real (pro-rated)", "تغییر واقعی روزشمار")],
        "شاخص‌های بازار از آخرین معامله تا بازگشایی، تجمعی",
        colors={"Closure nominal": BLUE, "Closure CPI (pro-rated)": GREY, "Closure real (pro-rated)": RED}),
        filters=[in_filter(hid("vf", "p3bar_type"), "dim_series", "type", ["market_index"]),
                 in_filter(hid("vf", "p3bar_window"), "closure_summary", "window", ["on_reopening"])])
    w3 = (616 - 2 * 12) / 3
    for i, (m, lab) in enumerate(CARDS_P3[:3]):
        p3.add(f"ctx{i}", 640 + i * (w3 + 12), TOP, w3, CARD_H, card(m, lab))
    w3b = (616 - 12) / 2
    for i, (m, lab) in enumerate(CARDS_P3[3:]):
        p3.add(f"ctx{i + 3}", 640 + i * (w3b + 12), TOP + CARD_H + 12, w3b, CARD_H, card(m, lab))
    line1, line2 = bond_statement()
    st_top = TOP + 2 * CARD_H + 24
    p3.add("statement", 640, st_top, 616, TOP + 300 - st_top, textbox([
        (line1, 11, True, BLUE_DARK), (line2, 9, False, INK2)]))
    closure_cols = [("closure_summary", "nominal", "تغییر اسمی"),
                    ("closure_summary", "cpi_prorated", "تورم روزشمار"),
                    ("closure_summary", "real_prorated", "واقعی روزشمار، اصلی"),
                    ("closure_summary", "cpi_whole_months", "تورم ماه کامل"),
                    ("closure_summary", "real_whole_months", "واقعی ماه کامل، حساسیت"),
                    ("closure_summary", "comparable", "قابل مقایسه")]
    p3.add("closuretable", 24, TOP + 312, 1232, BOTTOM - TOP - 312, {
        "visualType": "tableEx",
        "query": {"queryState": {"Values": {"projections":
            [proj(col_field("dim_series", "series_fa"), "سری"),
             proj(col_field("closure_summary", "window_fa"), "بازه"),
             proj(col_field("closure_summary", "window_start"), "از"),
             proj(col_field("closure_summary", "window_end"), "تا")] +
            [proj(col_field(e, c), lab) for e, c, lab in closure_cols]}}},
        "objects": {"columnHeaders": [{"properties": {"fontSize": num(9), "wordWrap": lit("true")}}],
                    "values": [{"properties": {"fontSize": num(9)}}]},
        "visualContainerObjects": title_objects("تعطیلی بازار: شاخص‌ها و ۸ سهم نمونه، تجمعی در هر بازه"),
        "drillFilterOtherVisuals": True})

    # ---------------- page 4 ----------------
    p4 = Page("timing", "زمان ورود", ["market_index", "stock"])
    p4.header("زمان ورود: بازده واقعی ۱۲ ماههٔ غلتان و همبستگی", F["timing"],
              "هر نقطهٔ نمودار بازده واقعی ۱۲ ماهِ منتهی به آن ماه است؛ زیر خط صفر یعنی عقب‌ماندن از تورم. "
              "همبستگی بر پایهٔ بازده واقعی ماهانه در ۳۶ ماه است.")
    p4.add("rolling", 24, TOP, 700, BOTTOM - TOP, line_chart(
        "Real return rolling 12m", "بازده واقعی ۱۲ ماهه",
        "بازده واقعی ۱۲ ماههٔ غلتان شاخص کل و شاخص هم‌وزن", zero_line=True),
        filters=[in_filter(hid("vf", "p4rolling"), "dim_series", "type", ["market_index"])])
    corr_measure = "Correlation (real, monthly)"
    hobj = matrix_text_objects(8)
    hobj["values"].append({"properties": {"backColor": gradient2(corr_measure, WHITE, BLUE_DARK, "0D", "1D"),
                                          "fontColor": color(INK)},
                           "selector": {"data": WILDCARD, "metadata": f"_Measures.{corr_measure}"}})
    hobj["subTotals"] = [{"properties": {"rowSubtotals": lit("false"), "columnSubtotals": lit("false")}}]
    p4.add("corr", 740, TOP, 516, BOTTOM - TOP, {
        "visualType": "pivotTable",
        "query": {"queryState": {
            "Rows": {"projections": [proj(col_field("correlation_long", "series_a_fa"), "سری", True)]},
            "Columns": {"projections": [proj(col_field("correlation_long", "series_b_fa"), "در برابر", True)]},
            "Values": {"projections": [proj(meas_field(corr_measure), "همبستگی")]}}},
        "objects": hobj,
        "visualContainerObjects": title_objects("همبستگی بازده واقعی ماهانه: ۸ سهم و ۲ شاخص"),
        "drillFilterOtherVisuals": True})
    return [p1, p2, p3, p4]


def theme() -> dict:
    font = "Segoe UI"
    return {
        "name": "TSE Inflation Blue",
        "dataColors": [BLUE_DARK, BLUE, BLUE_LIGHT, BLUE_PALE, NAVY, "#4F81BD", GREEN, RED],
        "background": WHITE, "foreground": INK, "tableAccent": BLUE,
        "good": GREEN, "neutral": "#F2C94C", "bad": RED,
        "minimum": RED, "center": WHITE, "maximum": GREEN, "null": "#E0E0E0",
        "textClasses": {
            "callout": {"fontSize": 24, "fontFace": font, "color": BLUE_DARK},
            "title": {"fontSize": 12, "fontFace": font, "color": INK},
            "header": {"fontSize": 11, "fontFace": font, "color": INK},
            "label": {"fontSize": 10, "fontFace": font, "color": INK2},
            "largeTitle": {"fontSize": 18, "fontFace": font, "color": NAVY}},
        "visualStyles": {
            "*": {"*": {
                "background": [{"show": True, "color": {"solid": {"color": WHITE}}, "transparency": 0}],
                "border": [{"show": True, "color": {"solid": {"color": "#E3E8EF"}}, "radius": 4}],
                "dropShadow": [{"show": False}],
                "title": [{"show": True, "fontColor": {"solid": {"color": INK}}, "fontSize": 12,
                           "fontFamily": font, "alignment": "right"}],
                "valueAxis": [{"gridlineColor": {"solid": {"color": "#E3E8EF"}},
                               "labelColor": {"solid": {"color": INK2}}, "fontFamily": font}],
                "categoryAxis": [{"labelColor": {"solid": {"color": INK2}}, "fontFamily": font}],
                "legend": [{"labelColor": {"solid": {"color": INK2}}, "fontFamily": font}]}},
            "textbox": {"*": {"background": [{"show": False}], "border": [{"show": False}]}},
            "page": {"*": {"background": [{"color": {"solid": {"color": "#F5F8FC"}}, "transparency": 0}]}}},
    }


def write_report(pages: list[Page]) -> None:
    if RP.exists():
        shutil.rmtree(RP / "definition", ignore_errors=True)
    d = RP / "definition"
    (d / "pages").mkdir(parents=True, exist_ok=True)
    def js(path: Path, obj) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    js(RP / "definition.pbir", {"version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    js(RP / ".platform", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": uid("logical", "report")}})
    js(d / "version.json", {"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    imp = {"visual": "2.11.0", "report": "3.4.0", "page": "2.3.1"}
    js(d / "report.json", {
        "$schema": f"{SCHEMA}/report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": BASE_THEME, "reportVersionAtImport": imp, "type": "SharedResources"},
            "customTheme": {"name": CUSTOM_THEME, "reportVersionAtImport": imp, "type": "RegisteredResources"}},
        "objects": {"outspacePane": [{"properties": {"expanded": lit("false")}}]},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": BASE_THEME, "path": f"BaseThemes/{BASE_THEME}.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": CUSTOM_THEME, "path": CUSTOM_THEME, "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True}})
    js(d / "pages" / "pages.json", {"$schema": f"{SCHEMA}/pagesMetadata/1.1.0/schema.json",
                                    "pageOrder": [p.id for p in pages], "activePageName": pages[0].id})
    for p in pages:
        pd_ = d / "pages" / p.id
        js(pd_ / "page.json", p.page_json())
        for v in p.visuals:
            js(pd_ / "visuals" / v["name"] / "visual.json", v)
    sr = RP / "StaticResources"
    (sr / "SharedResources" / "BaseThemes").mkdir(parents=True, exist_ok=True)
    (sr / "RegisteredResources").mkdir(parents=True, exist_ok=True)
    base_dst = sr / "SharedResources" / "BaseThemes" / f"{BASE_THEME}.json"
    if BASE_THEME_SRC.exists():
        shutil.copyfile(BASE_THEME_SRC, base_dst)
    elif not base_dst.exists():
        sys.exit(f"base theme {BASE_THEME}.json not found; copy it from any PBIP saved by Power BI Desktop")
    js(sr / "RegisteredResources" / CUSTOM_THEME, theme())
    js(DASH / "theme.json", theme())


# =========================================================================== #
# BUILD_GUIDE.md (Persian), expected values computed from the CSVs
# =========================================================================== #
def _pct(x: float, digits: int = 1) -> str:
    return fa(x * 100, f".{digits}f") + "٪"


def build_guide() -> str:
    rs = pd.read_csv(DATA / "risk_summary.csv").set_index("code")
    cl = pd.read_csv(DATA / "closure_summary.csv").set_index(["series_code", "window"])
    ctx = pd.read_csv(DATA / "context.csv").iloc[0]
    st = rs[rs["type"] == "stock"]
    folder = str(DATA) + "\\"
    clo = cl.loc[("index_total", "on_reopening")]
    values1 = {
        "CPI growth (×)": fa(1 + rs.loc["cpi", "nominal_cum_3y"], ".2f") + "×",
        "Index real cum 3y": _pct(rs.loc["index_total", "real_cum_3y"]),
        "Equal-weight real cum 3y": _pct(rs.loc["index_equal_weight", "real_cum_3y"]),
        "Stocks beating inflation": f"{(st['real_cum_3y'] > 0).sum()} / {len(st)}",
        "Closure real loss (pro-rated)": _pct(clo["real_prorated"]),
    }
    values3 = {
        "Bond YTM": _pct(ctx["bond_ytm"]), "Inflation 12m avg": _pct(ctx["inflation_12m_avg"]),
        "Inflation point-to-point": _pct(ctx["inflation_point_to_point"]),
        "Bond real yield (avg)": _pct(ctx["real_yield_avg"]),
        "Bond real yield (p2p)": _pct(ctx["real_yield_p2p"]),
    }
    tbl = lambda cards, vals: "\n".join(f"| {lab} | `{m}` | {vals[m]} | ☐ |" for m, lab in cards)

    def sel(code):
        r = rs.loc[code]
        return [_pct(r["real_cagr"]), _pct(r["real_vol_per_year"]),
                _pct(r["real_max_drawdown_peak_to_trough"]), _pct(r["pct_months_beat_inflation"], 0)]

    s_idx, s_fam = sel("index_total"), sel("fameli")
    F = findings()
    line1, line2 = bond_statement()
    p2_labels = " | ".join(lab for _, lab in CARDS_P2[1:])
    return f"""# راهنمای ساخت و بررسی داشبورد «بورس در برابر تورم»

این پوشه یک پروژهٔ Power BI (`.pbip`) با مدل معنایی TMDL و گزارش PBIR است. همهٔ فایل‌ها را
`src/build_dashboard.py` از روی CSVهای پوشهٔ `data/processed/powerbi/` می‌سازد. اعداد همان
اعداد تحلیل‌اند و در داشبورد تغییری نمی‌کنند.

> هشدار: اجرای دوبارهٔ `python src/build_dashboard.py` همهٔ فایل‌های گزارش را از نو می‌نویسد.
> هر اصلاح ماندگار باید در `src/build_dashboard.py` انجام شود. اگر در Power BI Desktop تغییر
> دستی داده‌اید، پیش از اجرای دوباره از آن نسخه پشتیبان بگیرید.

## ۱. باز کردن پروژه و تنظیم DataFolder

1. Power BI Desktop نسخهٔ ژوئن ۲۰۲۶ یا جدیدتر را نصب کنید. در نسخه‌های جدید قالب‌های PBIP، TMDL و
   PBIR به‌طور پیش‌فرض فعال‌اند. اگر هنگام باز کردن خطای قالب دیدید، در
   **File > Options and settings > Options > Preview features** این سه گزینه را روشن کنید:
   «Power BI Project (.pbip) save option»، «Store semantic model using TMDL format» و
   «Store reports using enhanced metadata format (PBIR)». سپس Desktop را دوباره باز کنید.
2. فایل `dashboard/tse_inflation.pbip` را باز کنید.
3. مسیر CSVها یک پارامتر به نام `DataFolder` است. مقدار فعلی آن:
   `{folder}`
   در رایانهٔ دیگر: **Home > Transform data > Edit parameters**، مقدار `DataFolder` را مسیر کامل
   پوشهٔ `data\\processed\\powerbi\\` بگذارید. **بک‌اسلش پایانی `\\` را حذف نکنید.** سپس OK.

## ۲. بارگذاری دوبارهٔ داده (Refresh)

1. **Home > Refresh** را بزنید. هشت جدول از CSV خوانده می‌شوند. جدول `_Measures` داده ندارد.
2. اگر پنجرهٔ «Privacy levels» باز شد، برای پوشهٔ محلی **Organizational** را انتخاب کنید.
3. اگر داده‌ها عوض شده‌اند، پیش از Refresh این دو فرمان را اجرا کنید:
   ```
   python src/analysis.py
   python src/build_dashboard.py
   ```
   اولی CSVها را می‌سازد و دومی پروژه را. بعد پروژه را در Desktop ببندید و دوباره باز کنید.

### رفع اشکال بارگذاری

- **Refresh با خطای «Container unexpectedly exited» یا کد `0x800705AF` قطع می‌شود.** این خطا از
  کمبود حافظه هنگام اجرای هم‌زمان چند پرس‌وجوی Power Query است.
  - بارگذاری موازی جدول‌ها در خود پروژه خاموش است: در `tse_inflation.SemanticModel/.pbi/editorSettings.json`
    مقدار `"parallelQueryLoading": false` نوشته شده است. در Desktop می‌توانید آن را در
    **File > Options and settings > Options > CURRENT FILE > Data Load > Parallel loading of
    tables** ببینید؛ باید روی Disabled یا Custom با عدد ۱ باشد.
  - تنظیم دوم سراسری است و در فایل پروژه ذخیره نمی‌شود. در هر رایانه یک بار تنظیم کنید:
    **Options > GLOBAL > Data Load > Maximum number of simultaneous evaluations = 1** (و در صورت
    نیاز **Maximum memory used per simultaneous evaluation** را بالا ببرید). Desktop را دوباره
    باز کنید و Refresh را تکرار کنید.
  - برنامه‌های سنگین دیگر را ببندید.
- **خطای نوع داده روی یک ستون** (مثلاً True/False یا عدد اعشاری): مرحلهٔ `Typed` در Power Query
  با فرهنگ `en-US` نوشته شده است. مطمئن شوید CSV با UTF-8 ذخیره شده و ستون‌ها تغییر نکرده‌اند.

## ۳. چک‌لیست مقدار کارت‌ها

پس از Refresh، هر کارت باید همین عدد را نشان دهد (با گرد کردن قالب). Desktop اعداد را با رقم
لاتین نشان می‌دهد؛ مثلاً −۶٫۶٪ در کارت به شکل -6.6% دیده می‌شود. ستون آخر برای تیک زدن است.

**صفحهٔ ۱: نمای کلی**

| برچسب کارت | سنجه | مقدار درست | ✓ |
|---|---|---|---|
{tbl(CARDS_P1, values1)}

**صفحهٔ ۲: پراکندگی** (کارت «{CARDS_P2[0][1]}» و چهار کارت کنار آن: {p2_labels})

| حالت | سری | بازده واقعی سالانه | نوسان واقعی سالانه | بیشترین افت | ماه‌های جلوتر از تورم | ✓ |
|---|---|---|---|---|---|---|
| بدون انتخاب در اسلایسر | شاخص کل | {s_idx[0]} | {s_idx[1]} | {s_idx[2]} | {s_idx[3]} | ☐ |
| انتخاب «فملی» | فملی | {s_fam[0]} | {s_fam[1]} | {s_fam[2]} | {s_fam[3]} | ☐ |

**صفحهٔ ۳: تعطیلی بازار و دارایی امن**

| برچسب کارت | سنجه | مقدار درست | ✓ |
|---|---|---|---|
{tbl(CARDS_P3, values3)}

متن کنار کارت‌ها ثابت است (از `context.csv` هنگام ساخت):
«{line1}»
«{line2}»

## ۴. چه چیزی را در هر صفحه بررسی کنیم

همهٔ صفحه‌ها:
- عنوان، یک خط «یافتهٔ اصلی» و یک خط یادداشت روش بالای صفحه است. پانویس «{FOOTER}» کامل
  و بریده‌نشده پایین صفحه دیده شود.
- متن‌های فارسی راست‌چین باشند و نقطه و پرانتز در جای درست (انتهای جمله، سمت چپ) بیایند، نه در
  ابتدای خط.
- برچسب زیر عدد هر کارت کامل دیده شود (عدد ۲۰pt، برچسب ۹pt).
- هیچ دو ویژوالی روی هم نیفتند و چیزی بیرون از صفحه نباشد.
- در پنل Filters یک فیلتر صفحهٔ قفل‌شده روی `dim_series[type]` باشد. شاخص‌های صنایع
  (`sector_index`) در هیچ صفحه‌ای نباید دیده شوند.
- نام سری‌ها فارسی باشد (`series_fa`) و ماه‌ها به ترتیب زمانی (شهریور ۱۴۰۲ تا شهریور ۱۴۰۵) بیایند،
  نه به ترتیب الفبا.

**صفحهٔ ۱. نمای کلی: بورس در برابر تورم**
- یافتهٔ اصلی: «{F['overview']}»
- پنج کارت جدول بالا و زیر آن متن قرمز: «{HINDSIGHT_NOTE}»
- نمودار خطی رشد واقعی (سمت چپ): فقط شاخص کل (آبی تیره)، شاخص هم‌وزن (آبی روشن) و تورم
  (خاکستری، خط صاف روی ۱۰۰).
- نمودار میله‌ای «رشد سالانه: اسمی در برابر واقعی» کل ستون راست را پر می‌کند: میلهٔ اسمی آبی
  کم‌رنگ و میلهٔ واقعی آبی تیره، برای شاخص کل، شاخص هم‌وزن و تورم.
- نمودار بازده ۱۲ ماههٔ غلتان در این صفحه نیست؛ در صفحهٔ ۴ است.

**صفحهٔ ۲. پراکندگی: ۸ سهم نمونه، نه کل بازار**
- یافتهٔ اصلی: «{F['dispersion']}»
- اسلایسر تک‌انتخابی فقط کارت‌ها را تغییر می‌دهد. نمودارها و جدول‌ها با آن **نباید** فیلتر شوند.
- نمودار میله‌ای بازده واقعی سالانه: ۸ سهم، ۲ شاخص و سبد هم‌وزن. میلهٔ مثبت **سبز**، منفی **قرمز**.
- نمودار پراکنش ریسک و بازده: ۱۱ نقطه با برچسب.
- ماتریس سری × دورهٔ ۱۲ ماهه: سه ستون (سال اول تا سوم). خانه‌های منفی قرمز، نزدیک صفر سفید و
  مثبت سبز. فملی در سال سوم باید پررنگ‌ترین سبز باشد.
- جدول بازده و ریسک: مرتب‌شده بر اساس بازده واقعی سالانه، فملی در بالا.

**صفحهٔ ۳. تعطیلی بازار و دارایی امن**
- یافتهٔ اصلی: «{F['closure']}»
- نمودار میله‌ای تعطیلی: فقط دو شاخص، بازهٔ «تا بازگشایی». تغییر اسمی حدود صفر، تورم روزشمار
  {_pct(clo['cpi_prorated'])} و تغییر واقعی {_pct(clo['real_prorated'])}.
- پنج کارت اوراق و متن ثابت کنار آن‌ها (جدول و متن بالا).
- جدول تعطیلی: ۲ شاخص و ۸ سهم، هر کدام دو ردیف («تا بازگشایی» و «۲۰ روز معاملاتی پس از
  بازگشایی»). فولاد «قابل مقایسه = False» و ستون‌های واقعی آن خالی است.

**صفحهٔ ۴. زمان ورود**
- یافتهٔ اصلی: «{F['timing']}»
- نمودار خطی بازده واقعی ۱۲ ماههٔ غلتان برای شاخص کل و شاخص هم‌وزن، با **خط چین صفر**.
- نقشهٔ حرارتی همبستگی: ۱۰ × ۱۰ (۸ سهم و ۲ شاخص)، قطر اصلی ۱٫۰۰ و پررنگ‌ترین آبی.
  رنگ از سفید (صفر) تا آبی تیره (یک) است.

## ۵. رفع دستی اگر یک ویژوال درست نمایش داده نشد

قالب‌بندی‌ها در فایل‌های گزارش نوشته شده‌اند، ولی Desktop گاهی بعضی را نمی‌خواند. اگر چنین شد،
دستی تنظیم کنید و ذخیره کنید، و همان اصلاح را در `src/build_dashboard.py` هم بیاورید:

1. **میله‌های سبز و قرمز (صفحهٔ ۲):** ویژوال را انتخاب کنید و به **Format > Bars > Colors**
   بروید. روی **fx** بزنید: Format style = **Field value**، What field = `_Measures[Real CAGR color]`.
2. **ماتریس دوره‌ها (صفحهٔ ۲):** **Format > Cell elements**، **Background color** روشن و **fx**:
   Format style = **Gradient**، تیک **Add a middle color**. Minimum = Lowest value با `#C62828`،
   Center = **Number 0** با `#FFFFFF`، Maximum = Highest value با `#2E7D32`.
3. **نقشهٔ حرارتی همبستگی (صفحهٔ ۴):** مانند بند ۲ ولی بدون رنگ میانی: Minimum = Number 0 با
   `#FFFFFF` و Maximum = Number 1 با `#1F4E79`. ردیف و ستون جمع را از
   **Format > Row subtotals / Column subtotals** خاموش کنید.
4. **خط صفر (صفحهٔ ۴):** در پنل **Analytics** گزینهٔ **Constant line** (محور Y) را اضافه کنید،
   Value = 0، سبک خط‌چین.
5. **رنگ خطوط سری‌ها:** **Format > Lines > Colors**. شاخص کل `#1F4E79`، شاخص کل (هم‌وزن)
   `#6DA7EC` و شاخص قیمت مصرف‌کننده `#8C8C8C`.
6. **برچسب کارت بریده شده است:** کارت را انتخاب کنید: **Format > Visual > Callout value > Font
   size = 20**، **Label > Font size = 9**، **General > Properties > Padding = 4px**. اگر باز هم
   بریده بود، ارتفاع کارت را بیشتر کنید (اکنون {CARD_H} پیکسل).
7. **نقطه یا پرانتز در ابتدای خط فارسی آمده است:** متن را انتخاب کنید، تراز را راست بگذارید و در
   انتهای جمله یک کاراکتر RLM (U+200F) اضافه کنید. در `src/build_dashboard.py` همهٔ متن‌ها از
   تابع `rtl()` می‌گذرند؛ متن جدید را هم از آن عبور دهید.
8. **اسلایسر صفحهٔ ۲ نمودارها را هم فیلتر می‌کند:** اسلایسر را انتخاب کنید و به
   **Format > Edit interactions** بروید. برای نمودار میله‌ای، پراکنش، ماتریس و جدول، گزینهٔ
   **None** را بزنید.
9. **پوسته اعمال نشده است:** **View > Themes > Browse for themes** و فایل `dashboard/theme.json`.
10. **ویژوالی خطای «Can't display this visual» می‌دهد:** آن را حذف کنید و با همان فیلدها دوباره
    بسازید. فیلدهای هر ویژوال در تابع `build_report` در `src/build_dashboard.py` آمده است. همهٔ
    سنجه‌ها در جدول `_Measures` هستند و در `dashboard/measures.dax` هم کپی شده‌اند.
11. **ترتیب ماه‌ها الفبایی است:** در Data view ستون `dim_month[month_label_fa]` را انتخاب کنید و
    **Column tools > Sort by column = sort_key** را بگذارید.

## ۶. بررسی خودکار (بدون باز کردن Desktop)

```
python -m pytest -q tests
```
این آزمون‌ها فایل‌های گزارش را با طرح‌وارهٔ (schema) رسمی PBIR اعتبارسنجی می‌کنند، TMDL را با
کتابخانهٔ خودِ Power BI Desktop می‌خوانند و هم‌پوشانی ویژوال‌ها، جای پانویس و قاعده‌های متن فارسی
را بررسی می‌کنند. همهٔ سنجه‌ها هم روی موتور محلی Power BI (`msmdsrv.exe`) اجرا و با CSVها مقایسه
می‌شوند (`dashboard/tools/`). ظاهر نهایی صفحه‌ها را فقط خودِ Desktop نشان می‌دهد؛ برای همین
بخش‌های ۳ و ۴ را دستی بررسی کنید.
"""


# =========================================================================== #
# Consistency check: every field used in the report exists in the model
# =========================================================================== #
def model_fields() -> dict[str, set[str]]:
    f = {t: {c["name"] for c in table_columns(t)} for t in TABLES}
    f["_Measures"] = {m["name"] for m in MEASURES}
    return f


def report_field_refs(obj, out=None):
    """Collect (entity, property, kind) for every Column/Measure with an Entity SourceRef."""
    out = set() if out is None else out
    if isinstance(obj, dict):
        for kind in ("Column", "Measure"):
            if kind in obj and isinstance(obj[kind], dict):
                ref = obj[kind].get("Expression", {}).get("SourceRef", {})
                if "Entity" in ref:
                    out.add((ref["Entity"], obj[kind]["Property"], kind))
        for v in obj.values():
            report_field_refs(v, out)
    elif isinstance(obj, list):
        for v in obj:
            report_field_refs(v, out)
    return out


def check_report_fields() -> list[str]:
    fields = model_fields()
    errs = []
    for f in sorted((RP / "definition").rglob("*.json")):
        refs = report_field_refs(json.loads(f.read_text(encoding="utf-8")))
        for ent, prop, kind in refs:
            if ent not in fields or prop not in fields[ent]:
                errs.append(f"{f.relative_to(DASH)}: {kind} {ent}[{prop}] not in model")
            if kind == "Measure" and ent != "_Measures":
                errs.append(f"{f.relative_to(DASH)}: measure outside _Measures")
    return errs


# =========================================================================== #
# Test copy of the model for a standalone engine (no Power Query available)
# =========================================================================== #
# Python equivalents of the Power Query renames / added columns above. Used ONLY by the
# engine test model; tests/test_dashboard.py checks they match the M expressions' outputs.
ADDED_PY = {
    "yearly_real": {"block_fa": lambda df: df["block"].map(lambda b: rtl(BLOCK_FA[b]) if b in BLOCK_FA else b)},
    "closure_summary": {
        "window_fa": lambda df: df["window"].map(lambda w: rtl(WINDOW_FA["on_reopening"] if w == "on_reopening"
                                                               else WINDOW_FA["after_20_days"])),
        "window_order": lambda df: df["window"].map(lambda w: 1 if w == "on_reopening" else 2)},
}
DT_DAX = {"string": "STRING", "double": "DOUBLE", "int64": "INTEGER", "boolean": "BOOLEAN",
          "dateTime": "DATETIME"}


def table_frame(table: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{table}.csv", encoding="utf-8").rename(columns=RENAMES.get(table, {}))
    for col in RLM_COLUMNS.get(table, []):
        df[col] = df[col].map(lambda v: v if pd.isna(v) else RLM + v + RLM)
    for col, fn in ADDED_PY.get(table, {}).items():
        df[col] = fn(df)
    return df


def dax_literal(v, dt: str) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)) or (dt != "string" and str(v) == ""):
        return "BLANK()"
    if dt == "boolean":
        return "TRUE" if str(v).lower() == "true" else "FALSE"
    if dt == "int64":
        return str(int(v))
    if dt == "double":
        return repr(float(v))
    return '"' + str(v).replace('"', '""') + '"'


def write_engine_test_model(dest: Path) -> None:
    """Same model, but every table is a DAX DATATABLE built from the CSVs."""
    d = dest / "definition"
    if d.exists():
        shutil.rmtree(d)
    (d / "tables").mkdir(parents=True)
    src = SM / "definition"
    (d / "database.tmdl").write_text((src / "database.tmdl").read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copyfile(src / "relationships.tmdl", d / "relationships.tmdl")
    # Only culture, the auto-date/time switch and table refs: data-access options and the
    # Power BI data-source version make a standalone engine demand Power Query.
    model = ["model Model", "\tculture: en-US", "",
             "annotation __PBI_TimeIntelligenceEnabled = 0", ""]
    model += [x for x in (src / "model.tmdl").read_text(encoding="utf-8").splitlines()
              if x.startswith("ref table")]
    (d / "model.tmdl").write_text("\n".join(model) + "\n", encoding="utf-8")
    for t in TABLES:
        cols = table_columns(t)
        df = table_frame(t)
        L = [f"table {t}", f"\tlineageTag: {uid('table', t)}", ""]
        for c in cols:
            L.append(f"\tcolumn {c['name']}")
            if c.get("format"):
                L.append(f"\t\tformatString: {c['format']}")
            if c["hidden"]:
                L.append("\t\tisHidden")
            if c["key"]:
                L.append("\t\tisKey")
            L += [f"\t\tlineageTag: {uid('column', t, c['name'])}", "\t\tsummarizeBy: none",
                  "\t\tisNameInferred", f"\t\tsourceColumn: [{c['name']}]"]
            if c["sortBy"]:
                L.append(f"\t\tsortByColumn: {c['sortBy']}")
            L.append("")
        header = ", ".join(f'"{c["name"]}", {DT_DAX[c["dataType"]]}' for c in cols)
        rows = []
        for _, r in df.iterrows():
            rows.append("{" + ", ".join(dax_literal(r[c["name"]], c["dataType"]) for c in cols) + "}")
        L += [f"\tpartition {t} = calculated", "\t\tmode: import", "\t\tsource =",
              f"\t\t\t\tDATATABLE ( {header}, {{"]
        L += ["\t\t\t\t    " + row + ("," if i < len(rows) - 1 else "") for i, row in enumerate(rows)]
        L += ["\t\t\t\t} )", ""]
        (d / "tables" / f"{t}.tmdl").write_text("\n".join(L) + "\n", encoding="utf-8")
    meas = (src / "tables" / "_Measures.tmdl").read_text(encoding="utf-8")
    meas = meas[:meas.index("\tpartition _Measures = m")]
    meas += ("\tcolumn dummy\n\t\tisHidden\n\t\tisNameInferred\n\t\tsourceColumn: [dummy]\n\n"
             "\tpartition _Measures = calculated\n\t\tmode: import\n\t\tsource = ROW ( \"dummy\", 0 )\n")
    (d / "tables" / "_Measures.tmdl").write_text(meas, encoding="utf-8")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) == 3 and sys.argv[1] == "--test-model":
        write_engine_test_model(Path(sys.argv[2]))
        print(f"wrote engine test model to {sys.argv[2]}")
        return 0
    DASH.mkdir(exist_ok=True)
    data_folder = str(DATA) + "\\"
    write_model(data_folder)
    pages = build_report()
    write_report(pages)
    (DASH / f"{NAME}.pbip").write_text(json.dumps({
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}}, indent=2), encoding="utf-8")
    (DASH / "measures.dax").write_text(measures_dax(), encoding="utf-8")
    (DASH / "BUILD_GUIDE.md").write_text(build_guide(), encoding="utf-8")
    errs = check_report_fields()
    for e in errs:
        print("FIELD ERROR:", e)
    n_vis = sum(len(p.visuals) for p in pages)
    print(f"wrote {DASH.relative_to(ROOT)}: {len(TABLES) + 1} tables, {len(MEASURES)} measures, "
          f"{len(RELATIONSHIPS)} relationships, {len(pages)} pages, {n_vis} visuals")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())

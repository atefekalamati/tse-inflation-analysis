"""Build the processed daily and monthly panels from data/raw and data/external.

data/raw is read only, never written. Outputs:
  data/processed/prices_daily.parquet    long daily panel, all series x index calendar
  data/processed/prices_monthly.parquet  long monthly panel with CPI, real returns, growth indices
  reports/corrections.md                 every value changed (and every known issue left as is)
  reports/data_dictionary.md             every column, unit and definition

Usage:  python src/process_data.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_quality as dq  # noqa: E402

ROOT = dq.ROOT
PROC = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
DAILY = PROC / "prices_daily.parquet"
MONTHLY = PROC / "prices_monthly.parquet"
BASE_MONTH = "1402-06"


def real_return(nominal, inflation):
    """Real return deflated by CPI: (1 + nominal) / (1 + inflation) - 1."""
    return (1 + nominal) / (1 + inflation) - 1


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


# --------------------------------------------------------------------------- #
# Corrections
# --------------------------------------------------------------------------- #
def apply_corrections(df: pd.DataFrame, file: str, cfg: dict, log: list[dict]) -> pd.DataFrame:
    """Apply configured corrections to one raw file (in memory). Adds was_corrected."""
    df = df.copy()
    df["was_corrected"] = False
    for c in cfg["processing"].get("corrections", []):
        if c["file"] != file:
            continue
        dates = set(c["dates"])
        missing = dates - set(df["J-Date"])
        if missing:
            raise ValueError(f"{file}: correction dates not in file: {sorted(missing)}")
        for col in [x for x in c["columns"] if x in df.columns]:
            # sanity: after the fix the value must sit near the median of the
            # surrounding uncorrected days, otherwise refuse to apply it
            clean = df[col].where(~df["J-Date"].isin(dates) & (df[col] > 0))
            ref = clean.rolling(11, center=True, min_periods=3).median()
            for i in df.index[df["J-Date"].isin(dates)]:
                orig = float(df.at[i, col])
                new = orig * c["multiply_by"]
                if not abs(new / ref.at[i] - 1) < 0.15:
                    raise ValueError(f"{file} {df.at[i, 'J-Date']} {col}: corrected value {new} "
                                     f"is not close to surrounding median {ref.at[i]}")
                df.at[i, col] = new
                df.at[i, "was_corrected"] = True
                log.append({"file": file, "date_jalali": df.at[i, "J-Date"], "column": col,
                            "original": orig, "corrected": new,
                            "surrounding_median": float(ref.at[i]), "reason": c["reason"]})
    return df


# --------------------------------------------------------------------------- #
# Series loading
# --------------------------------------------------------------------------- #
def load_series(meta: dict, cfg: dict, corr_log: list[dict]) -> list[dict]:
    """Return a list of series dicts: symbol, code, type, sector, frame.

    frame columns: J-Date, close_adj, close_unadj, volume, value, was_corrected
    """
    out = []
    sym_cfg = {s["symbol"]: s for s in cfg["symbols"]}
    for sym, paths in dq.stock_pairs(meta).items():
        a = dq.read_raw(paths["adjusted"])
        u = dq.read_raw(paths["unadjusted"])
        a = apply_corrections(a, paths["adjusted"], cfg, corr_log)
        u = apply_corrections(u, paths["unadjusted"], cfg, corr_log)
        f = pd.DataFrame({"J-Date": a["J-Date"], "close_adj": a["Final"].astype(float),
                          "close_unadj": u["Final"].astype(float),
                          "volume": u["Volume"].astype(float), "value": u["Value"].astype(float),
                          "was_corrected": a["was_corrected"] | u["was_corrected"]})
        ev = dq.adjustment_events(a, u, cfg["quality"]["adjustment_ratio_tolerance"])
        ev = ev[(ev["factor"] - 1).abs() >= cfg["processing"]["min_adjustment_event"]]
        f["adj_factor"] = f["J-Date"].map(dict(zip(ev["ex_date"], ev["factor"]))).fillna(1.0)
        out.append({"symbol": sym, "code": sym_cfg[sym]["code"], "type": "stock",
                    "sector": sym_cfg[sym]["sector_index"], "frame": f})

    for file, info in meta["files"].items():
        if info["kind"] not in ("index", "sector_index"):
            continue
        df = apply_corrections(dq.read_raw(file), file, cfg, corr_log)
        name = info["index_name"]
        is_total = name == "شاخص کل"
        f = pd.DataFrame({"J-Date": df["J-Date"], "close_adj": df["Close"].astype(float),
                          "close_unadj": df["Close"].astype(float),
                          # the index files carry whole-market volume; keep it once only
                          "volume": df["Volume"].astype(float) if is_total else np.nan,
                          "value": np.nan, "was_corrected": df["was_corrected"],
                          "adj_factor": 1.0})
        if info["kind"] == "index":
            out.append({"symbol": name, "code": Path(file).stem, "type": "market_index",
                        "sector": None, "frame": f})
        else:
            en = meta["index_resolution"][name].get("tsetmc_name", name)
            out.append({"symbol": name, "code": "sector_" + _slug(en), "type": "sector_index",
                        "sector": name, "frame": f})
    return out


# --------------------------------------------------------------------------- #
# Daily panel
# --------------------------------------------------------------------------- #
def build_daily(meta: dict, cfg: dict, series: list[dict]) -> pd.DataFrame:
    idx = dq.read_raw(dq.total_index_file(meta))
    cal = idx[["J-Date", "Date"]].rename(columns={"J-Date": "date_jalali", "Date": "date_greg"})
    closed = set(dq.market_closed_days(meta))
    cal["market_closed"] = cal["date_jalali"].isin(closed)
    frames = []
    for s in series:
        f = s["frame"].rename(columns={"J-Date": "date_jalali"})
        d = cal.merge(f, on="date_jalali", how="left")
        extra = set(f["date_jalali"]) - set(cal["date_jalali"])
        if extra:
            raise ValueError(f"{s['symbol']}: dates outside the index calendar {sorted(extra)}")
        d["symbol"], d["code"], d["type"], d["sector"] = s["symbol"], s["code"], s["type"], s["sector"]
        d["was_corrected"] = d["was_corrected"].astype("boolean").fillna(False).astype(bool)
        d["adj_factor"] = d["adj_factor"].fillna(1.0)
        traded = d["close_adj"].notna() & ~d["market_closed"]
        if s["type"] == "stock":
            d["traded"] = traded
            d["suspended"] = ~d["market_closed"] & d["close_adj"].isna()
            # halt length = consecutive open-market days without a trade before this day
            open_d = d[~d["market_closed"]]
            run, halt = 0, []
            for t in open_d["traded"]:
                halt.append(run if t else 0)
                run = 0 if t else run + 1
            d["halt_days_before"] = 0
            d.loc[open_d.index, "halt_days_before"] = halt
            d["first_trade_after_halt"] = d["traded"] & (d["halt_days_before"] > 0)
            d["adjustment_event"] = d["adj_factor"] != 1.0
        else:
            d["traded"] = ~d["market_closed"]
            d["suspended"] = False
            d["halt_days_before"] = 0
            d["first_trade_after_halt"] = False
            d["adjustment_event"] = False
        frames.append(d)
    daily = pd.concat(frames, ignore_index=True)
    cols = ["date_jalali", "date_greg", "symbol", "code", "type", "sector", "close_adj",
            "close_unadj", "volume", "value", "traded", "market_closed", "suspended",
            "first_trade_after_halt", "halt_days_before", "adjustment_event", "adj_factor",
            "was_corrected"]
    daily = daily[cols].sort_values(["type", "code", "date_jalali"]).reset_index(drop=True)
    daily["halt_days_before"] = daily["halt_days_before"].astype(int)
    return daily


# --------------------------------------------------------------------------- #
# Monthly panel
# --------------------------------------------------------------------------- #
def build_monthly(daily: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    last = cfg["cpi"]["last_month"]
    d = daily.assign(month_jalali=daily["date_jalali"].str[:7])
    d = d[(d["month_jalali"] >= BASE_MONTH) & (d["month_jalali"] <= last)]
    long_days = cfg["processing"]["long_suspension_days"]

    rows = []
    for (code, month), g in d.groupby(["code", "month_jalali"], sort=True):
        px = g[g["close_adj"].notna()]
        rows.append({
            "month_jalali": month, "symbol": g["symbol"].iloc[0], "code": code,
            "type": g["type"].iloc[0], "sector": g["sector"].iloc[0],
            "close_adj_eom": px["close_adj"].iloc[-1] if len(px) else np.nan,
            "close_date_jalali": px["date_jalali"].iloc[-1] if len(px) else None,
            "open_market_days": int((~g["market_closed"]).sum()),
            "trading_days": int(g["traded"].sum()),
            "market_closed_days": int(g["market_closed"].sum()),
            "suspended_days": int(g["suspended"].sum()),
            "adjustment_event_in_month": bool(g["adjustment_event"].any()),
            "corrected_value_in_month": bool(g["was_corrected"].any()),
        })
    m = pd.DataFrame(rows)
    # carry the last available close into months without any trade
    m = m.sort_values(["code", "month_jalali"]).reset_index(drop=True)
    m["close_carried_forward"] = m["close_adj_eom"].isna()
    m["close_date_jalali"] = m.groupby("code")["close_date_jalali"].ffill()
    m["close_adj_eom"] = m.groupby("code")["close_adj_eom"].ffill()
    m["market_closure_in_month"] = m["market_closed_days"] > 0
    m["long_suspension"] = m["suspended_days"] >= long_days
    m["no_trade_in_month"] = m["trading_days"] == 0
    m["return_nominal"] = m.groupby("code")["close_adj_eom"].pct_change(fill_method=None)

    cpi = dq.cpi_frame()[["jalali_month", "cpi_index"]].rename(columns={"jalali_month": "month_jalali"})
    cpi = cpi.sort_values("month_jalali").reset_index(drop=True)
    cpi["inflation_monthly"] = cpi["cpi_index"] / cpi["cpi_index"].shift(1) - 1
    cpi_base = float(cpi.loc[cpi["month_jalali"] == BASE_MONTH, "cpi_index"].iloc[0])
    m = m.merge(cpi, on="month_jalali", how="left")
    m["return_real"] = real_return(m["return_nominal"], m["inflation_monthly"])
    base = m[m["month_jalali"] == BASE_MONTH].set_index("code")["close_adj_eom"]
    m["growth_nominal"] = 100 * m["close_adj_eom"] / m["code"].map(base)
    m["growth_real"] = m["growth_nominal"] / (m["cpi_index"] / cpi_base)

    # CPI itself as a series
    c = cpi.copy()
    c = c.assign(symbol="CPI", code="cpi", type="cpi", sector=None,
                 close_adj_eom=c["cpi_index"], close_date_jalali=None,
                 open_market_days=np.nan, trading_days=np.nan, market_closed_days=np.nan,
                 suspended_days=np.nan, adjustment_event_in_month=False,
                 corrected_value_in_month=False, close_carried_forward=False,
                 market_closure_in_month=False, long_suspension=False,
                 no_trade_in_month=False, return_nominal=c["inflation_monthly"],
                 return_real=np.where(c["inflation_monthly"].notna(), 0.0, np.nan),
                 growth_nominal=100 * c["cpi_index"] / cpi_base, growth_real=100.0)
    m = pd.concat([m, c[m.columns]], ignore_index=True)

    m["is_base_month"] = m["month_jalali"] == BASE_MONTH
    m["data_flag"] = (m["market_closure_in_month"] | m["long_suspension"]
                      | m["no_trade_in_month"])
    cols = ["month_jalali", "symbol", "code", "type", "sector", "is_base_month",
            "close_adj_eom", "close_date_jalali", "close_carried_forward", "return_nominal",
            "cpi_index", "inflation_monthly", "return_real", "growth_nominal", "growth_real",
            "open_market_days", "trading_days", "market_closed_days", "suspended_days",
            "market_closure_in_month", "long_suspension", "no_trade_in_month", "data_flag",
            "adjustment_event_in_month", "corrected_value_in_month"]
    order = {"stock": 0, "market_index": 1, "sector_index": 2, "cpi": 3}
    m = m[cols].sort_values(["type", "code", "month_jalali"],
                            key=lambda s: s.map(order) if s.name == "type" else s)
    return m.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def write_corrections(corr_log: list[dict], cfg: dict, meta: dict) -> None:
    lines = ["# Corrections log\n",
             "Written by `src/process_data.py`. `data/raw` is never modified; corrections "
             "are applied in memory and only the processed panels contain corrected values "
             "(column `was_corrected` = true).\n",
             "## Values corrected\n"]
    if corr_log:
        t = pd.DataFrame(corr_log)
        t["original"] = t["original"].map(lambda x: f"{x:,.0f}")
        t["corrected"] = t["corrected"].map(lambda x: f"{x:,.0f}")
        t["surrounding_median"] = t["surrounding_median"].map(lambda x: f"{x:,.0f}")
        t = t.rename(columns={"date_jalali": "date (Jalali)",
                              "surrounding_median": "median of surrounding days"})
        lines.append(dq.md_table(t))
    else:
        lines.append("_none_\n")
    lines.append("\n## Known issues left uncorrected\n")
    lines.append("These cells are wrong in the source but sit in columns the analysis does not "
                 "use (only closing prices are used), so they are logged, not changed.\n")
    corrected_files = {c["file"] for c in cfg["processing"].get("corrections", [])}
    rows = []
    for k in cfg["quality"].get("known_issues", []):
        if k["file"] in corrected_files:
            continue
        df = dq.read_raw(k["file"])
        for dte in k["dates"]:
            r = df[df["J-Date"] == dte].iloc[0]
            vals = ", ".join(f"{c}={r[c]:,.0f}" for c in ("Open", "High", "Low", "Close")
                             if c in df.columns)
            rows.append({"file": k["file"], "date (Jalali)": dte, "column": k["column"],
                         "row values": vals, "issue": k["issue"],
                         "action": "none (column not used)"})
    lines.append(dq.md_table(pd.DataFrame(rows)))
    (REPORTS / "corrections.md").write_text("\n".join(lines), encoding="utf-8")


DAILY_DOC = {
    "date_jalali": ("text YYYY-MM-DD", "Trading-calendar date (Jalali). The calendar is every day on which TSETMC published شاخص کل, including market-closed days."),
    "date_greg": ("date", "Same date in the Gregorian calendar."),
    "symbol": ("text", "Series name: stock ticker, sector label as in config, or market index name."),
    "code": ("text", "ASCII identifier of the series (stable key for joins and file names)."),
    "type": ("stock / sector_index / market_index", "Kind of series."),
    "sector": ("text", "Sector label from config/settings.yaml (for stocks and sector indices); empty for market indices."),
    "close_adj": ("rial (stocks) / index points", "Stocks: official closing price (قیمت پایانی, TSETMC `Final`) back-adjusted for capital increases and dividends by algotik-tse, anchored at 1405-06-31 and truncated to integer rial. Indices: closing index value (corrected where `was_corrected`). Empty when the stock did not trade."),
    "close_unadj": ("rial / index points", "Stocks: unadjusted official closing price. Indices: same as close_adj."),
    "volume": ("shares", "Stocks: shares traded (unadjusted). شاخص کل: whole-market volume. Empty for other indices."),
    "value": ("rial", "Stocks: traded value. Empty for indices."),
    "traded": ("bool", "Stocks: a trade row exists and the market was open. Indices: market open."),
    "market_closed": ("bool", "One of the 61 days on which شاخص کل has zero volume and a flat value (market closed). No stock traded on these days."),
    "suspended": ("bool", "Stock had no trade although the market was open (symbol-specific halt)."),
    "first_trade_after_halt": ("bool", "Stock trades today after at least one open-market day without trading. Market-closed days do not count as a halt."),
    "halt_days_before": ("days", "Number of consecutive open-market days without a trade immediately before this trade (0 otherwise)."),
    "adjustment_event": ("bool", "Ex-date of a corporate action: adjusted/unadjusted ratio changes by at least processing.min_adjustment_event (1%)."),
    "adj_factor": ("ratio", "Factor applied to all earlier prices at this ex-date (e.g. 0.74 for a capital increase); 1 otherwise."),
    "was_corrected": ("bool", "A value on this row was changed by a correction listed in reports/corrections.md."),
}

MONTHLY_DOC = {
    "month_jalali": ("text YYYY-MM", "Jalali month. 1402-06 is the base month (no return); returns run 1402-07 to 1405-06."),
    "symbol": ("text", "Series name (as in the daily panel); `CPI` for the consumer price index."),
    "code": ("text", "ASCII identifier of the series."),
    "type": ("stock / market_index / sector_index / cpi", "Kind of series."),
    "sector": ("text", "Sector label (stocks and sector indices)."),
    "is_base_month": ("bool", "True for 1402-06."),
    "close_adj_eom": ("rial / index points / CPI points", "Last available adjusted close up to the end of the month (official closing price for stocks). If the series did not trade in the month, the previous month's value is carried forward. For CPI: the CPI value."),
    "close_date_jalali": ("text YYYY-MM-DD", "Date of the price used in close_adj_eom."),
    "close_carried_forward": ("bool", "No price in this month; close_adj_eom carried forward from an earlier month."),
    "return_nominal": ("fraction", "close_adj_eom_t / close_adj_eom_(t-1) - 1. Includes dividends and capital increases through the back-adjustment. For CPI: monthly inflation."),
    "cpi_index": ("index, 1400=100", "SCI CPI, all households, whole country, for this month."),
    "inflation_monthly": ("fraction", "CPI_t / CPI_(t-1) - 1."),
    "return_real": ("fraction", "(1 + return_nominal) / (1 + inflation_monthly) - 1. For CPI: 0."),
    "growth_nominal": ("index, 1402-06 = 100", "100 x close_adj_eom_t / close_adj_eom_1402-06. For CPI: 100 x CPI_t / CPI_1402-06."),
    "growth_real": ("index, 1402-06 = 100", "growth_nominal / (CPI_t / CPI_1402-06), i.e. purchasing power of 100 invested at the end of 1402-06. Equals 100 x cumulative product of (1 + return_real). Above 100 = beat inflation since 1402-06."),
    "open_market_days": ("days", "Days in the month on which the market was open."),
    "trading_days": ("days", "Stocks: days with a trade. Indices: open-market days."),
    "market_closed_days": ("days", "Market-closed days in the month."),
    "suspended_days": ("days", "Open-market days on which the stock did not trade."),
    "market_closure_in_month": ("bool", "The month contains at least one market-closed day."),
    "long_suspension": ("bool", "suspended_days >= processing.long_suspension_days (5)."),
    "no_trade_in_month": ("bool", "The series has no trade in the month (price carried forward, return 0 that month, the move lands in the month trading resumes)."),
    "data_flag": ("bool", "market_closure_in_month OR long_suspension OR no_trade_in_month. Treat monthly returns with this flag with care."),
    "adjustment_event_in_month": ("bool", "A corporate-action ex-date falls in the month."),
    "corrected_value_in_month": ("bool", "A corrected daily value falls in the month."),
}


def write_dictionary(daily: pd.DataFrame, monthly: pd.DataFrame) -> None:
    for name, df, doc in (("daily", daily, DAILY_DOC), ("monthly", monthly, MONTHLY_DOC)):
        undocumented = set(df.columns) - set(doc)
        if undocumented:
            raise ValueError(f"{name} panel has undocumented columns: {undocumented}")

    def table(df, doc):
        rows = [{"column": c, "dtype": str(df[c].dtype), "unit": doc[c][0], "definition": doc[c][1]}
                for c in df.columns]
        return dq.md_table(pd.DataFrame(rows))

    text = [
        "# Data dictionary\n",
        "Generated by `src/process_data.py`.\n",
        "## Conventions\n",
        "- Dates are Jalali (`YYYY-MM-DD`, months `YYYY-MM`). Gregorian dates are in `date_greg`.",
        "- Prices are in rial. Index values are in index points. Returns are fractions (0.05 = 5%).",
        "- Stock prices use TSETMC's official closing price (قیمت پایانی), not the last trade.",
        "- Adjusted prices come from algotik-tse 1.8.0, which back-adjusts every earlier price "
        "by (next day's reference price / closing price) at each ex-date. Returns on adjusted "
        "prices therefore include cash dividends and capital increases. Rights issues paid in "
        "cash are treated like bonus shares, which slightly overstates returns around them.",
        "- CPI is the Statistical Centre of Iran's index for all households of the whole country, "
        "base 1400 = 100. SCI collects prices from the 1st to the 28th of each month, so a "
        "month's CPI is an average over the month while stock returns are end-of-month to "
        "end-of-month.",
        "- Market-closed days: 61 days on which TSETMC published a flat, zero-volume index row. "
        "They are kept and flagged, never counted as stock suspensions.\n",
        f"## prices_daily.parquet\n\n{len(daily):,} rows: {daily['code'].nunique()} series x "
        f"{daily['date_jalali'].nunique()} calendar days ({daily['date_jalali'].min()} to "
        f"{daily['date_jalali'].max()}). Key: (code, date_jalali).\n",
        table(daily, DAILY_DOC),
        f"\n## prices_monthly.parquet\n\n{len(monthly):,} rows: {monthly['code'].nunique()} "
        f"series x {monthly['month_jalali'].nunique()} months ({monthly['month_jalali'].min()} "
        f"to {monthly['month_jalali'].max()}). Key: (code, month_jalali).\n",
        table(monthly, MONTHLY_DOC),
    ]
    (REPORTS / "data_dictionary.md").write_text("\n".join(text), encoding="utf-8")


# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cfg, meta = dq.load_settings(), dq.load_metadata()
    PROC.mkdir(parents=True, exist_ok=True)
    corr_log: list[dict] = []
    series = load_series(meta, cfg, corr_log)
    daily = build_daily(meta, cfg, series)
    monthly = build_monthly(daily, cfg)
    daily.to_parquet(DAILY, index=False)
    monthly.to_parquet(MONTHLY, index=False)
    write_corrections(corr_log, cfg, meta)
    write_dictionary(daily, monthly)
    print(f"daily:   {DAILY.relative_to(ROOT)}  {daily.shape}")
    print(f"monthly: {MONTHLY.relative_to(ROOT)}  {monthly.shape}")
    print(f"corrections applied: {len(corr_log)} values")
    return 0


if __name__ == "__main__":
    sys.exit(main())

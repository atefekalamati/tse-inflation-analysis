"""Data-quality checks on the raw downloads. Writes reports/data_quality.md.

Nothing here modifies data. Checks per file:
  * date range, trading days, duplicate dates, Jalali/Gregorian consistency
  * missing dates vs the overall-index calendar (= days the symbol did not trade),
    split into market-wide closures and symbol-specific suspensions
  * days with |adjusted daily return| > threshold (TSE daily price limits make these suspicious)
  * dates where adjusted and unadjusted prices diverge (capital increases / dividends),
    with the adjustment ratio, cross-checked against TSETMC's price-adjustment table
  * zero / non-positive prices and prices outside the day's Low-High range
  * CPI: missing months, consecutive months, known-value check, monthly-rate consistency

Usage:  python src/data_quality.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from persiantools.jdatetime import JalaliDate

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
EXT = ROOT / "data" / "external"
REPORT = ROOT / "reports" / "data_quality.md"
CONFIG = ROOT / "config" / "settings.yaml"

PRICE_COLS = ("Open", "High", "Low", "Close", "Final", "Adj Close")


# --------------------------------------------------------------------------- #
# Loading helpers (also used by tests/test_data.py)
# --------------------------------------------------------------------------- #
def load_settings() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def load_metadata() -> dict:
    return json.loads((RAW / "metadata.json").read_text(encoding="utf-8"))


def read_raw(rel_path: str) -> pd.DataFrame:
    df = pd.read_csv(ROOT / rel_path, encoding="utf-8")
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
    return df


def total_index_file(meta: dict) -> str:
    return next(f for f, i in meta["files"].items()
                if i.get("kind") == "index" and i.get("index_name") == "شاخص کل")


def index_calendar(meta: dict) -> pd.Series:
    """All J-Dates on which شاخص کل has a row (includes market-closed days)."""
    return read_raw(total_index_file(meta))["J-Date"].drop_duplicates().sort_values() \
        .reset_index(drop=True)


def market_closed_days(meta: dict) -> list[str]:
    """Index rows with zero market volume: TSETMC publishes a flat index row on
    days the market did not trade (holidays declared at short notice, closures)."""
    idx = read_raw(total_index_file(meta))
    return sorted(idx.loc[idx["Volume"] <= 0, "J-Date"])


def stock_pairs(meta: dict) -> dict[str, dict]:
    """symbol -> {'adjusted': path, 'unadjusted': path, 'adjustments': path}"""
    out: dict[str, dict] = {}
    for f, i in meta["files"].items():
        if i.get("symbol"):
            key = {"stock_adjusted": "adjusted", "stock_unadjusted": "unadjusted",
                   "price_adjustments": "adjustments"}[i["kind"]]
            out.setdefault(i["symbol"], {})[key] = f
    return out


def daily_returns(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col] / df[col].shift(1) - 1


def adjustment_events(adj: pd.DataFrame, unadj: pd.DataFrame, base_tol: float) -> pd.DataFrame:
    """Dates where the adjusted/unadjusted price ratio changes.

    ratio_t = adjusted Final_t / unadjusted Final_t. The library back-adjusts, so
    the ratio steps up at each event: factor = ratio_t / ratio_next < 1 means prices
    before `ex_date` were multiplied by `factor`. Adjusted prices are truncated to
    int, which adds noise up to ~2/price to the ratio; the tolerance scales with it.
    """
    m = adj[["Date", "J-Date", "Final"]].merge(
        unadj[["Date", "Final"]], on="Date", suffixes=("_adj", "_raw"))
    m["ratio"] = m["Final_adj"] / m["Final_raw"]
    nxt = m.shift(-1)
    m["factor"] = m["ratio"] / nxt["ratio"]
    tol = np.maximum(base_tol, 2.5 / np.minimum(m["Final_adj"], nxt["Final_adj"]))
    hit = (m["factor"] - 1).abs() > tol
    return pd.DataFrame({
        "last_date_before": m.loc[hit, "J-Date"],
        "ex_date": nxt.loc[hit, "J-Date"],
        "raw_final_before": m.loc[hit, "Final_raw"],
        "raw_final_ex_date": nxt.loc[hit, "Final_raw"],
        "factor": m.loc[hit, "factor"],
    }).reset_index(drop=True)


def runs_of(days: list[str], calendar: pd.Series) -> list[tuple[str, str, int]]:
    """Group days into runs of consecutive calendar entries."""
    pos = {d: i for i, d in enumerate(calendar)}
    runs: list[list[str]] = []
    for d in sorted(days, key=pos.get):
        if runs and pos[d] == pos[runs[-1][-1]] + 1:
            runs[-1].append(d)
        else:
            runs.append([d])
    return [(r[0], r[-1], len(r)) for r in runs]


def jalali_gregorian_mismatches(df: pd.DataFrame) -> int:
    if "J-Date" not in df.columns or "Date" not in df.columns:
        return 0
    conv = df["Date"].dt.date.map(lambda d: JalaliDate(d).isoformat())
    return int((conv != df["J-Date"]).sum())


def decimal_shift_rows(df: pd.DataFrame, cols=("Open", "High", "Low", "Close"),
                       window: int = 11, tol: float = 0.15) -> dict[str, list[tuple[str, str]]]:
    """Values that are ~10x or ~1/10 of the centred rolling median (decimal-place errors).

    Returns {column: [(J-Date, 'x10' | 'x0.1'), ...]}.
    """
    out: dict[str, list[tuple[str, str]]] = {}
    for c in cols:
        if c not in df.columns:
            continue
        v = df[c].where(df[c] > 0)
        med = v.rolling(window, center=True, min_periods=3).median()
        r = v / med
        hits = []
        for j, x in zip(df["J-Date"], r):
            if pd.notna(x) and abs(x / 10 - 1) < tol:
                hits.append((j, "x10"))
            elif pd.notna(x) and abs(x * 10 - 1) < tol:
                hits.append((j, "x0.1"))
        if hits:
            out[c] = hits
    return out


def cpi_frame() -> pd.DataFrame:
    return pd.read_csv(EXT / "cpi_iran_sci.csv", encoding="utf-8", dtype={"jalali_month": str})


def next_month(jm: str) -> str:
    y, m = map(int, jm.split("-"))
    return f"{y + (m == 12)}-{1 if m == 12 else m + 1:02d}"


# --------------------------------------------------------------------------- #
# Report helpers
# --------------------------------------------------------------------------- #
def fmt_pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def md_table(df: pd.DataFrame, indent: str = "") -> str:
    if df.empty:
        return indent + "_none_\n"
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |")
    return "\n".join(indent + l for l in lines) + "\n"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cfg = load_settings()
    meta = load_metadata()
    q = cfg["quality"]
    p_start, p_end = cfg["period"]["start"], cfg["period"]["end"]
    f_start = cfg["period"]["fetch_start"]
    cal_all = index_calendar(meta)
    cal = cal_all[(cal_all >= f_start) & (cal_all <= p_end)].reset_index(drop=True)
    closed = [d for d in market_closed_days(meta) if f_start <= d <= p_end]
    closed_set = set(closed)
    open_days = cal[~cal.isin(closed_set)].reset_index(drop=True)
    cal_period = cal[cal >= p_start]
    open_period = open_days[open_days >= p_start]
    pos = {d: i for i, d in enumerate(cal)}
    pos_open = {d: i for i, d in enumerate(open_days)}

    out: list[str] = []
    flags: list[str] = []
    info_notes: list[str] = []
    summary_rows = []

    out.append("# Data quality report (raw data, step 1)\n")
    out.append(f"Generated {dt.datetime.now().astimezone().isoformat(timespec='seconds')} by "
               "`src/data_quality.py`. Raw data downloaded "
               f"{meta['download_started_tehran']} (Tehran time) with {meta['library']['name']} "
               f"{meta['library']['version']}. Nothing in data/raw was modified.\n")
    out.append(f"Analysis period {p_start} to {p_end} (Jalali). Prices were fetched from "
               f"{f_start} so the base price at the end of 1402-06 exists.\n")
    out.append("Index calendar = days on which شاخص کل has a row: "
               f"{len(cal)} days in the fetch window, {len(cal_period)} in the analysis period. "
               f"Of these, {len(closed)} rows have zero market volume and a flat index "
               "(market closed). Days the market was open: "
               f"{len(open_days)} in the fetch window, {len(open_period)} in the analysis period.\n")
    out.append("Price conventions: `Close` = last trade, `Final` = official closing price "
               "(قیمت پایانی). Returns below use adjusted `Final` (and `Close` where noted). "
               "Adjusted series are back-adjusted by the library within the download window "
               "and truncated to integers.\n")

    # -------------------- generic per-file checks --------------------
    details: dict[str, dict] = {}
    for f, info in meta["files"].items():
        if info["kind"] == "price_adjustments":
            continue
        df = read_raw(f)
        jd = df["J-Date"]
        is_index = info["kind"] in ("index", "sector_index")
        d = {
            "rows": len(df), "first": jd.min(), "last": jd.max(),
            "days_in_period": int(((jd >= p_start) & (jd <= p_end)).sum()),
            "dup": int(df["Date"].duplicated().sum()),
            "dup_j": int(jd.duplicated().sum()),
            "jg_mismatch": jalali_gregorian_mismatches(df),
            "nan": {c: int(v) for c, v in df.isna().sum().items() if v},
            "not_in_calendar": sorted(set(jd) - set(cal_all)),
        }
        pcols = [c for c in PRICE_COLS if c in df.columns]
        nonpos = {c: df.loc[df[c] <= 0, "J-Date"].tolist() for c in pcols if (df[c] <= 0).any()}
        d["nonpositive"] = nonpos
        # Open/Close outside [Low, High]; small relative tolerance for index rounding
        tol = 0.005 if is_index else 0.0  # index High/Low are rounded / sampled
        lo, hi = df["Low"] * (1 - tol), df["High"] * (1 + tol)
        open_rows = df["Open"] > 0 if "Open" in df.columns else pd.Series(True, index=df.index)
        bad = {}
        for c in ("Open", "Close"):
            if c in df.columns:
                m = ((df[c] < lo) | (df[c] > hi)) & open_rows
                if m.any():
                    bad[c] = df.loc[m, "J-Date"].tolist()
        d["range_bad"] = bad
        if "Final" in df.columns:
            d["final_outside"] = int(((df["Final"] < df["Low"]) | (df["Final"] > df["High"])).sum())
        if "Volume" in df.columns:
            d["zero_volume"] = int((df["Volume"] <= 0).sum())
        span = cal[(cal >= max(f_start, d["first"])) & (cal <= p_end)]
        d["missing"] = sorted(set(span) - set(jd))
        d["missing_in_period"] = [x for x in d["missing"] if x >= p_start]
        d["suspended"] = [x for x in d["missing"] if x not in closed_set]
        d["suspended_in_period"] = [x for x in d["suspended"] if x >= p_start]
        details[f] = d

        if d["dup"] or d["dup_j"]:
            flags.append(f"`{f}` has duplicate dates ({d['dup']} Gregorian, {d['dup_j']} Jalali).")
        if d["jg_mismatch"]:
            flags.append(f"`{f}`: {d['jg_mismatch']} rows where J-Date does not match Date.")
        for c, days in nonpos.items():
            if is_index and c in ("Open", "High", "Low") and set(days) <= closed_set:
                info_notes.append(f"`{f}`: `{c}` = 0 on {len(days)} day(s), all of them "
                                  "market-closed days. Expected, because nothing traded; "
                                  "`Close` is the carried-forward value.")
            else:
                flags.append(f"`{f}`: `{c}` <= 0 on {len(days)} day(s): {', '.join(days[:12])}"
                             + (" ..." if len(days) > 12 else ""))
        for c, days in bad.items():
            flags.append(f"`{f}`: `{c}` outside the day's Low-High range on {len(days)} day(s): "
                         f"{', '.join(days[:8])}" + (" ..." if len(days) > 8 else ""))
        if d.get("final_outside"):
            info_notes.append(f"`{f}`: `Final` outside the day's Low-High on "
                              f"{d['final_outside']} day(s). TSETMC's closing price is a "
                              "volume-weighted figure and can sit outside the traded range; "
                              "not treated as an error.")
        if d["not_in_calendar"]:
            flags.append(f"`{f}`: {len(d['not_in_calendar'])} dates not in the index calendar: "
                         f"{d['not_in_calendar'][:10]}")
        if d["nan"]:
            flags.append(f"`{f}`: missing values {d['nan']}.")

    # -------------------- stocks --------------------
    stock_sections = []
    for sym, paths in stock_pairs(meta).items():
        a = read_raw(paths["adjusted"])
        u = read_raw(paths["unadjusted"])
        tse = read_raw(paths["adjustments"]) if "adjustments" in paths else pd.DataFrame()
        da = details[paths["adjusted"]]
        sec = [f"### {sym}\n",
               f"Files: `{paths['adjusted']}`, `{paths['unadjusted']}`"
               + (f", `{paths['adjustments']}`" if "adjustments" in paths else "") + "\n"]
        sec.append(f"- Range {da['first']} to {da['last']}. {da['rows']} rows in the fetch "
                   f"window, {da['days_in_period']} trading days in the analysis period "
                   f"(market open on {len(open_period)} days).")
        same = a["Date"].equals(u["Date"])
        sec.append(f"- Adjusted and unadjusted files have identical dates: {'yes' if same else 'NO'}. "
                   f"Duplicate dates: {da['dup']}. Zero-volume rows: {da.get('zero_volume', 0)}.")
        if not same:
            flags.append(f"{sym}: adjusted and unadjusted files cover different dates.")
        last_ratio = a["Final"].iloc[-1] / u["Final"].iloc[-1]
        sec.append(f"- Adjusted/unadjusted Final on the last day: {last_ratio:.4f} "
                   "(1 expected: the adjustment is anchored at the last date).")
        sec.append(f"- Index days without a trade: {len(da['missing'])} "
                   f"({len(da['missing_in_period'])} in the analysis period). Of these, "
                   f"{len(da['missing']) - len(da['suspended'])} are market-wide closures and "
                   f"**{len(da['suspended'])} are symbol-specific suspensions** "
                   f"({len(da['suspended_in_period'])} in the analysis period).")
        runs = runs_of(da["suspended"], open_days)
        if runs:
            rt = pd.DataFrame(runs, columns=["suspended from", "to", "open-market days"])
            sec.append("\n  Suspension runs (market-closure days excluded):\n")
            sec.append(md_table(rt, "  "))

        # adjustment events
        ev = adjustment_events(a, u, q["adjustment_ratio_tolerance"])
        tse_rows = []
        if not tse.empty:
            tse = tse.assign(JalaliDate=tse["JalaliDate"].astype(str),
                             ratio=tse["AdjustedClosingPrice"] / tse["UnadjustedClosingPrice"])
            tse_rows = list(tse[["JalaliDate", "ratio"]].itertuples(index=False))
        matched = set()
        ev_rows = []
        n_unlisted = 0
        for _, e in ev.iterrows():
            hits = [(dj, r) for dj, r in tse_rows if e["last_date_before"] < dj <= e["ex_date"]]
            matched.update(dj for dj, _ in hits)
            tse_ratio = float(np.prod([r for _, r in hits])) if hits else None
            if abs(e["factor"] - 1) < 0.01:
                note = "minor (rounding / price correction)"
            elif tse_ratio is None:
                note = "not in TSETMC table (likely capital increase)"
                n_unlisted += 1
            elif abs(e["factor"] / tse_ratio - 1) > 0.01:
                note = (f"TSETMC table explains {fmt_pct(tse_ratio - 1)}; remaining "
                        f"{fmt_pct(e['factor'] / tse_ratio - 1)} unlisted (likely capital increase)")
                n_unlisted += 1
            else:
                note = "matches TSETMC table (dividend)"
            ev_rows.append({
                "last trade before": e["last_date_before"], "ex-date": e["ex_date"],
                "factor": f"{e['factor']:.4f}",
                "equiv. gap": fmt_pct(e["factor"] - 1),
                "raw Final before / on ex-date": f"{e['raw_final_before']:.0f} / {e['raw_final_ex_date']:.0f}",
                "TSETMC table date (ratio)": ", ".join(f"{dj} ({r:.4f})" for dj, r in hits) or "",
                "note": note,
            })
        sec.append(f"\n- Adjustment events, where adjusted and unadjusted Final diverge: {len(ev)}. "
                   "`factor` multiplies all prices before the ex-date.\n")
        sec.append(md_table(pd.DataFrame(ev_rows)))
        unmatched = [dj for dj, _ in tse_rows if dj not in matched]
        if unmatched:
            flags.append(f"{sym}: TSETMC adjustment(s) {unmatched} not visible in the price data.")
        if n_unlisted:
            info_notes.append(f"{sym}: {n_unlisted} adjustment event(s) are absent or only partly "
                              "present in TSETMC's price-adjustment table. The library's adjusted "
                              "prices still include them, because it derives factors from the "
                              "previous-day price TSETMC publishes.")

        # big adjusted daily returns
        a = a.copy()
        a["ret_final"] = daily_returns(a, "Final")
        a["ret_close"] = daily_returns(a, "Close")
        a["prev"] = a["J-Date"].shift(1)
        big = a[(a["ret_final"].abs() > q["suspicious_daily_return"])
                | (a["ret_close"].abs() > q["suspicious_daily_return"])]
        rows = []
        ev_dates = set(ev["ex_date"])
        for _, r in big.iterrows():
            gap = pos_open.get(r["J-Date"], 0) - pos_open.get(r["prev"], 0) - 1
            notes = []
            if gap > 0:
                notes.append(f"first trade after {gap} open-market days without trading")
            if r["J-Date"] in ev_dates:
                notes.append("ex-date of an adjustment event")
            rows.append({"date": r["J-Date"], "prev. trade": r["prev"],
                         "ret Final": fmt_pct(r["ret_final"]), "ret Close": fmt_pct(r["ret_close"]),
                         "context": "; ".join(notes) or "none"})
        sec.append(f"\n- Days with |adjusted daily return| > {q['suspicious_daily_return']:.0%} "
                   f"(Final or Close): {len(rows)}\n")
        sec.append(md_table(pd.DataFrame(rows)))
        maxj = a["ret_final"].abs().max()
        if maxj > q["max_unexplained_jump"]:
            flags.append(f"{sym}: adjusted Final has a one-day move of {maxj:.1%}.")
        if rows:
            flags.append(f"{sym}: {len(rows)} day(s) with |adjusted return| > "
                         f"{q['suspicious_daily_return']:.0%}: "
                         + "; ".join(f"{r['date']} {r['ret Final']} ({r['context']})" for r in rows))
        stock_sections.append("\n".join(sec) + "\n")
        summary_rows.append({
            "series": sym, "first": da["first"], "last": da["last"], "rows": da["rows"],
            "days in period": da["days_in_period"], "dup": da["dup"],
            "suspended (period)": len(da["suspended_in_period"]),
            "|ret|>10%": len(rows),
            "adj. events": int(sum(1 for r in ev_rows if not r["note"].startswith("minor"))),
        })

    # -------------------- indices --------------------
    idx_sections = []
    for f, info in meta["files"].items():
        if info["kind"] not in ("index", "sector_index"):
            continue
        df = read_raw(f)
        d = details[f]
        r = daily_returns(df, "Close")
        bigm = r.abs() > q["suspicious_daily_return"]
        big = [f"{j} {fmt_pct(x)}" for j, x in zip(df.loc[bigm, "J-Date"], r[bigm])]
        shifts = decimal_shift_rows(df)
        shifted_txt = "; ".join(f"`{c}` {', '.join(f'{j} ({k})' for j, k in hits)}"
                                for c, hits in shifts.items())
        label, used = info.get("index_name"), info.get("used_name")
        name_note = "" if used == label else f" (fetched as `{used}`)"
        idx_sections.append(
            f"- **{label}**{name_note}. File `{f}`, InsCode {info.get('ins_code')}. "
            f"{d['first']} to {d['last']}, {d['rows']} rows, {d['days_in_period']} in the period. "
            f"Duplicates {d['dup']}. Missing vs calendar {len(d['missing'])}. "
            f"Columns: {', '.join(c for c in df.columns if c not in ('Date', 'J-Date', 'Weekday', 'Weekday_fa', 'Ticker'))}. "
            f"Daily |return| > {q['suspicious_daily_return']:.0%}: {len(big)}"
            + (f" ({', '.join(big)})" if big else "") + "."
            + (f" **Decimal-shift errors (value 10x or 1/10 of the surrounding days): "
               f"{shifted_txt}.**" if shifts else ""))
        if shifts:
            close_hit = "Close" in shifts
            flags.append(f"{label} (`{f}`): decimal-shift errors in the source data: {shifted_txt}."
                         + (" The `Close` errors cause the -90% / +900% daily returns and must "
                            "be repaired or masked before analysis." if close_hit else
                            " `Close` is not affected."))
        if big and not ("Close" in shifts):
            flags.append(f"{label}: {len(big)} daily move(s) > {q['suspicious_daily_return']:.0%}: "
                         f"{', '.join(big)}.")
        summary_rows.append({
            "series": label, "first": d["first"], "last": d["last"], "rows": d["rows"],
            "days in period": d["days_in_period"], "dup": d["dup"],
            "suspended (period)": len(d["suspended_in_period"]), "|ret|>10%": len(big),
            "adj. events": "",
        })
        if d["missing"]:
            flags.append(f"{label}: {len(d['missing'])} calendar days missing.")
    ew = next((i for i in meta["files"].values() if i.get("index_name") == "شاخص کل (هم وزن)"), None)
    if ew:
        v_total = read_raw(total_index_file(meta))["Volume"]
        v_ew = read_raw(ew["file"])["Volume"]
        if len(v_total) == len(v_ew) and (v_total.values == v_ew.values).all():
            info_notes.append("The equal-weight index file carries the same `Volume` column as "
                              "شاخص کل (whole-market volume), not a volume of its own.")

    # -------------------- market closures --------------------
    closed_runs = runs_of(closed, cal)
    idx = read_raw(total_index_file(meta)).set_index("J-Date")
    closed_tbl = pd.DataFrame([{
        "from": s, "to": e, "index rows": n,
        "index Close moved?": "yes" if idx.loc[s:e, "Close"].nunique() > 1 or
        abs(idx.loc[s, "Close"] / idx["Close"].shift(1).loc[s] - 1) > 1e-4 else "no (flat)",
    } for s, e, n in closed_runs])

    # -------------------- CPI --------------------
    cpi = cpi_frame()
    cpi_lines = []
    missing_m = cpi.loc[cpi["cpi_index"].isna(), "jalali_month"].tolist()
    consecutive = all(next_month(x) == y for x, y in
                      zip(cpi["jalali_month"], cpi["jalali_month"].iloc[1:]))
    cpi_lines.append(f"- File `data/external/cpi_iran_sci.csv`: {len(cpi)} months, "
                     f"{cpi['jalali_month'].iloc[0]} to {cpi['jalali_month'].iloc[-1]}. "
                     f"Consecutive: {'yes' if consecutive else 'NO'}. Missing months: "
                     f"{', '.join(missing_m) if missing_m else 'none'}.")
    src = cpi["source_url"].dropna().unique().tolist()
    pub = cpi["published_date"].dropna().unique().tolist()
    cpi_lines.append("- Series: SCI, CPI of all households of the whole country (شاخص کل), "
                     "base 1400=100. Source workbook: " + (", ".join(src) or "n/a")
                     + f". Upload date in the file name (Jalali): {', '.join(map(str, pub)) or 'n/a'}.")
    kv = []
    for jm, val in cfg["cpi"]["known_values"].items():
        got = cpi.loc[cpi["jalali_month"] == jm, "cpi_index"]
        g = float(got.iloc[0]) if len(got) and pd.notna(got.iloc[0]) else None
        ok = g is not None and abs(round(g, 1) - val) < 0.051
        kv.append({"month": jm, "expected": val, "fetched": "" if g is None else f"{g:.4f}",
                   "result": "OK" if ok else "MISMATCH"})
        if not ok:
            flags.append(f"CPI {jm}: expected {val}, got {g}.")
    cpi_lines.append("\nKnown-value check:\n\n" + md_table(pd.DataFrame(kv)))
    implied = (cpi["cpi_index"] / cpi["cpi_index"].shift(1) - 1) * 100
    diff = (implied - cpi["monthly_inflation_pct"]).abs()
    cpi_lines.append(f"- SCI's monthly inflation vs the rate recomputed from the index: max "
                     f"absolute difference {np.nanmax(diff):.4f} percentage points.")
    if missing_m:
        flags.append(f"CPI months missing: {missing_m}.")
    if not consecutive:
        flags.append("CPI months are not consecutive.")

    # -------------------- name resolution --------------------
    res_lines = []
    for name, rep in {**meta["symbol_resolution"], **meta["index_resolution"]}.items():
        if rep.get("resolution") != "exact":
            res_lines.append(f"- `{name}` had no exact match. Library search found "
                             f"{[c['name'] for c in rep.get('search_candidates', [])][:4]}. Used "
                             f"`{rep.get('used_name')}` (InsCode {rep.get('ins_code')}, "
                             f"`{rep.get('tsetmc_name')}`).")
    res_lines.append("- `مخابرات` matched exactly the industry index with InsCode "
                     "41867092385281437, which TSETMC's industry list labels `رادیویی` "
                     "(English: Telecommunications).")

    # -------------------- assemble --------------------
    out.append("## Summary\n")
    out.append("`suspended (period)` counts open-market days in the analysis period on which the "
               "symbol did not trade. Market-wide closures are excluded.\n")
    out.append(md_table(pd.DataFrame(summary_rows)))
    out.append("\n## Flags to review\n")
    out.append("\n".join(f"- {x}" for x in flags) + "\n" if flags else "_none_\n")
    out.append("\n## Informational notes\n")
    out.append("\n".join(f"- {x}" for x in info_notes) + "\n" if info_notes else "_none_\n")
    out.append("\n## Market-wide closures\n")
    traded_on_closed = sorted({d for p in stock_pairs(meta).values()
                               for d in read_raw(p["adjusted"])["J-Date"] if d in closed_set})
    out.append(f"Index rows with zero market volume ({len(closed)} days). Stock rows on these "
               f"days across all {len(stock_pairs(meta))} symbols: {len(traded_on_closed)}"
               + (f" ({', '.join(traded_on_closed)})" if traded_on_closed else "")
               + ". The rows stay in the raw index files and are excluded when counting "
               "suspensions.\n")
    out.append(md_table(closed_tbl))
    out.append("\n## Name resolution\n")
    out.append("\n".join(res_lines) + "\n")
    out.append("\n## Stocks\n")
    out.extend(stock_sections)
    out.append("\n## Indices\n")
    out.append("\n".join(idx_sections) + "\n")
    out.append("\n## CPI (Statistical Centre of Iran)\n")
    out.append("\n".join(cpi_lines) + "\n")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {REPORT} ({len(flags)} flags, {len(info_notes)} notes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

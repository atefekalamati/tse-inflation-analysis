"""Return, risk and inflation analysis on the monthly panel (36 months, 1402-07..1405-06).

Rules this module follows:
  * Conclusions about "the market" use only شاخص کل (overall index) and the
    equal-weight index. The 8 stocks illustrate dispersion across sectors.
  * Stocks are never compared with sector indices: it is unknown whether TSETMC sector
    indices include dividends. Sector indices appear only as labelled trend lines in the
    Power BI export.

Usage:
    import analysis as an
    res = an.run_all()            # computes every table, writes figures and Power BI CSVs
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_quality as dq  # noqa: E402
import process_data as pdx  # noqa: E402

ROOT = dq.ROOT
FIG = ROOT / "reports" / "figures"
PBI = ROOT / "data" / "processed" / "powerbi"
BASE = pdx.BASE_MONTH
CLOSURE = ("1404-12-09", "1405-02-28")
BLOCKS = [("1402-07", "1403-06"), ("1403-07", "1404-06"), ("1404-07", "1405-06")]

STOCK_CODES = ["foolad", "fameli", "shepna", "khodro", "vbmellat", "akhaber", "shasta", "tipico"]
MARKET_CODES = ["index_total", "index_equal_weight"]
PORTFOLIO_CODE = "ew_portfolio_8"
LABELS = {
    "foolad": "Foolad", "fameli": "Fameli", "shepna": "Shepna", "khodro": "Khodro",
    "vbmellat": "Vbmellat", "akhaber": "Akhaber", "shasta": "Shasta", "tipico": "Tipico",
    "index_total": "Overall index (TEDPIX)", "index_equal_weight": "Equal-weight index",
    "cpi": "CPI", PORTFOLIO_CODE: "8-stock EW portfolio (hindsight)",
}


# --------------------------------------------------------------------------- #
# Pure math (tested in tests/test_analysis.py)
# --------------------------------------------------------------------------- #
def cagr(start_value: float, end_value: float, months: int) -> float:
    """Compound annual growth rate over `months` months."""
    return (end_value / start_value) ** (12.0 / months) - 1


def cagr_from_returns(returns) -> float:
    r = pd.Series(returns, dtype=float)
    return float((1 + r).prod() ** (12.0 / len(r)) - 1)


def compound(returns) -> float:
    """Total return of a sequence of periodic returns."""
    return float((1 + pd.Series(returns, dtype=float)).prod() - 1)


def max_drawdown(levels: pd.Series) -> dict:
    """Maximum drawdown of a level series (index = period labels).

    Returns {'max_drawdown': negative fraction or 0, 'peak': label, 'trough': label,
             'recovery': label or None (first period back at/above the peak)}.
    """
    lv = pd.Series(levels, dtype=float)
    running_max = lv.cummax()
    dd = lv / running_max - 1
    trough_pos = int(np.argmin(dd.values))
    mdd = float(dd.iloc[trough_pos])
    if mdd == 0:
        return {"max_drawdown": 0.0, "peak": None, "trough": None, "recovery": None}
    peak_pos = int(np.argmax(lv.values[: trough_pos + 1]))
    peak_level = lv.iloc[peak_pos]
    after = lv.iloc[trough_pos + 1:]
    rec = after[after >= peak_level]
    return {"max_drawdown": mdd, "peak": lv.index[peak_pos], "trough": lv.index[trough_pos],
            "recovery": rec.index[0] if len(rec) else None}


def drawdown_series(levels: pd.Series) -> pd.Series:
    lv = pd.Series(levels, dtype=float)
    return lv / lv.cummax() - 1


def block_returns(returns: pd.Series, blocks=BLOCKS) -> pd.Series:
    """Compound return within each (first_month, last_month) block. Index = 'first..last'.
    Raises if a block is incomplete (missing months)."""
    out = {}
    for a, b in blocks:
        r = returns[(returns.index >= a) & (returns.index <= b)]
        expected = month_range(a, b)
        if list(r.index) != expected or r.isna().any():
            raise ValueError(f"block {a}..{b} incomplete: have {len(r.dropna())} of {len(expected)}")
        out[f"{a}..{b}"] = compound(r)
    return pd.Series(out)


def rolling_compound(returns: pd.Series, window: int = 12) -> pd.Series:
    return (1 + returns).rolling(window).apply(np.prod, raw=True) - 1


def month_range(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    out = []
    while f"{y}-{m:02d}" <= last:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def ew_rebalanced_returns(nominal_wide: pd.DataFrame) -> pd.Series:
    """Equal-weight, monthly rebalanced portfolio return = mean of member returns."""
    if nominal_wide.isna().any().any():
        raise ValueError("member returns contain NaN")
    return nominal_wide.mean(axis=1)


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_monthly() -> pd.DataFrame:
    m = pd.read_parquet(pdx.MONTHLY)
    m["label"] = m["code"].map(LABELS).fillna(m["symbol"])
    return m


def load_daily() -> pd.DataFrame:
    return pd.read_parquet(pdx.DAILY)


def wide(m: pd.DataFrame, col: str, codes: list[str], with_base=False) -> pd.DataFrame:
    sub = m[m["code"].isin(codes)]
    if not with_base:
        sub = sub[sub["month_jalali"] > BASE]
    return sub.pivot(index="month_jalali", columns="code", values=col)[codes]


def portfolio_frame(m: pd.DataFrame) -> pd.DataFrame:
    """Monthly rows for the hindsight 8-stock equal-weight portfolio, same columns as m."""
    nom = ew_rebalanced_returns(wide(m, "return_nominal", STOCK_CODES))
    cpi = m[m["code"] == "cpi"].set_index("month_jalali")
    months = [BASE] + list(nom.index)
    p = pd.DataFrame({"month_jalali": months})
    p["return_nominal"] = [np.nan] + list(nom.values)
    p["inflation_monthly"] = p["month_jalali"].map(cpi["inflation_monthly"])
    p["cpi_index"] = p["month_jalali"].map(cpi["cpi_index"])
    p["return_real"] = pdx.real_return(p["return_nominal"], p["inflation_monthly"])
    p["growth_nominal"] = 100 * (1 + p["return_nominal"].fillna(0)).cumprod()
    p["growth_real"] = 100 * (1 + p["return_real"].fillna(0)).cumprod()
    flags = m[m["code"].isin(STOCK_CODES)].groupby("month_jalali")
    p["data_flag"] = p["month_jalali"].map(flags["data_flag"].any()).fillna(False).astype(bool)
    p["market_closure_in_month"] = p["month_jalali"].map(flags["market_closure_in_month"].any())
    p["long_suspension"] = p["month_jalali"].map(flags["long_suspension"].any())
    p["no_trade_in_month"] = p["month_jalali"].map(flags["no_trade_in_month"].any())
    p = p.assign(code=PORTFOLIO_CODE, symbol=LABELS[PORTFOLIO_CODE], label=LABELS[PORTFOLIO_CODE],
                 type="portfolio_hindsight", sector=None, is_base_month=p["month_jalali"] == BASE)
    return p


# --------------------------------------------------------------------------- #
# 1. Return and risk table
# --------------------------------------------------------------------------- #
def series_metrics(s: pd.DataFrame) -> dict:
    s = s.sort_values("month_jalali")
    r = s[s["month_jalali"] > BASE]
    n = len(r)
    g_nom, g_real = s["growth_nominal"].iloc[-1], s["growth_real"].iloc[-1]
    vol = float(r["return_real"].std(ddof=1) * np.sqrt(12))
    real_cagr = cagr(100, g_real, n)
    dd = max_drawdown(s.set_index("month_jalali")["growth_real"])
    is_cpi = s["code"].iloc[0] == "cpi"
    worst, best = r.loc[r["return_real"].idxmin()], r.loc[r["return_real"].idxmax()]
    return {
        "code": s["code"].iloc[0], "series": s["label"].iloc[0], "type": s["type"].iloc[0],
        "months": n,
        "nominal_cum_3y": g_nom / 100 - 1, "real_cum_3y": g_real / 100 - 1,
        "nominal_cagr": cagr(100, g_nom, n), "real_cagr": real_cagr,
        "real_vol_per_year": vol,
        "real_max_drawdown_peak_to_trough": dd["max_drawdown"], "dd_peak": dd["peak"], "dd_trough": dd["trough"],
        "dd_recovery": dd["recovery"],
        "pct_months_beat_inflation": np.nan if is_cpi else float((r["return_real"] > 0).mean()),
        "real_worst_month_per_month": np.nan if is_cpi else float(worst["return_real"]),
        "worst_month": None if is_cpi else worst["month_jalali"],
        "real_best_month_per_month": np.nan if is_cpi else float(best["return_real"]),
        "best_month": None if is_cpi else best["month_jalali"],
        "real_cagr_per_unit_vol": np.nan if is_cpi or vol == 0 else real_cagr / vol,
        "flagged_months": int(r["data_flag"].sum()),
    }


def risk_table(m: pd.DataFrame, port: pd.DataFrame) -> pd.DataFrame:
    rows = [series_metrics(m[m["code"] == c]) for c in STOCK_CODES + MARKET_CODES + ["cpi"]]
    rows.append(series_metrics(port))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 2. Period breakdown
# --------------------------------------------------------------------------- #
def yearly_table(m: pd.DataFrame, port: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (long table, stock rank table). Long: code, series, type, block,
    real_return, nominal_return, inflation, rank_among_stocks."""
    allm = pd.concat([m, port], ignore_index=True)
    rows = []
    for c in STOCK_CODES + MARKET_CODES + ["cpi", PORTFOLIO_CODE]:
        s = allm[allm["code"] == c].set_index("month_jalali").sort_index()
        real = block_returns(s["return_real"])
        nom = block_returns(s["return_nominal"])
        infl = block_returns(s["inflation_monthly"])
        for b in real.index:
            rows.append({"code": c, "series": s["label"].iloc[0], "type": s["type"].iloc[0],
                         "block": b, "real_return_per_year": real[b], "nominal_return_per_year": nom[b],
                         "inflation_per_year": infl[b]})
    y = pd.DataFrame(rows)
    st = y[y["code"].isin(STOCK_CODES)].copy()
    st["rank_among_stocks"] = st.groupby("block")["real_return_per_year"].rank(ascending=False).astype(int)
    y = y.merge(st[["code", "block", "rank_among_stocks"]], on=["code", "block"], how="left")
    y["rank_among_stocks"] = y["rank_among_stocks"].astype("Int64")
    ranks = st.pivot(index="series", columns="block", values="rank_among_stocks")
    return y, ranks


def rank_stability(ranks: pd.DataFrame) -> pd.DataFrame:
    """Spearman correlation of stock ranks between consecutive blocks."""
    cols = list(ranks.columns)
    out = []
    for a, b in zip(cols, cols[1:]):
        out.append({"from": a, "to": b, "spearman_rank_corr": ranks[a].rank().corr(ranks[b].rank())})
    out.append({"from": cols[0], "to": cols[-1],
                "spearman_rank_corr": ranks[cols[0]].rank().corr(ranks[cols[-1]].rank())})
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- #
# 3. Market closure
# --------------------------------------------------------------------------- #
def jalali_days_in_month(month: str) -> int:
    from persiantools.jdatetime import JalaliDate
    y, mo = map(int, month.split("-"))
    for day in (31, 30, 29):
        try:
            JalaliDate(y, mo, day)
            return day
        except ValueError:
            continue
    raise ValueError(month)


def prev_month(month: str) -> str:
    y, mo = map(int, month.split("-"))
    return f"{y - 1}-12" if mo == 1 else f"{y}-{mo - 1:02d}"


def cpi_at_date(date_jalali: str, cpi: pd.Series) -> float:
    """CPI level on a calendar day, by geometric interpolation within the month.

    Convention (same as the monthly panel, where CPI_t is paired with the month-end
    close): the monthly CPI value is the level at the END of that month. On day d of
    month M with D days:  CPI(d) = CPI(M-1) * (CPI(M) / CPI(M-1)) ** (d / D).
    `cpi` is indexed by 'YYYY-MM'.
    """
    month, day = date_jalali[:7], int(date_jalali[8:10])
    D = jalali_days_in_month(month)
    if not 1 <= day <= D:
        raise ValueError(f"invalid date {date_jalali}")
    lo, hi = float(cpi[prev_month(month)]), float(cpi[month])
    return lo * (hi / lo) ** (day / D)


def closure_analysis(d: pd.DataFrame, m: pd.DataFrame) -> dict:
    """Real change across the closure.

    Primary: CPI pro-rated to the exact dates (cpi_at_date). Sensitivity: whole months,
    CPI from end of 1404-11 to end of the month of the later date (at least 1405-02).
    All changes are cumulative over the window, not annualized.
    """
    a, b = CLOSURE
    cal = d.drop_duplicates("date_jalali")[["date_jalali", "market_closed"]].sort_values("date_jalali")
    closed = cal[(cal["date_jalali"] >= a) & (cal["date_jalali"] <= b)]
    open_before = cal[(cal["date_jalali"] < a) & ~cal["market_closed"]]["date_jalali"].iloc[-1]
    open_after = cal[(cal["date_jalali"] > b) & ~cal["market_closed"]]["date_jalali"]
    reopen = open_after.iloc[0]
    cpi = m[m["code"] == "cpi"].set_index("month_jalali")["cpi_index"]
    cpi_from, cpi_to = "1404-11", "1405-02"   # whole CPI months bracketing the closure

    def cpi_monthly(day: str) -> float:
        return float(cpi[max(day[:7], cpi_to)] / cpi[cpi_from] - 1)

    def cpi_prorated(day0: str, day1: str) -> float:
        return cpi_at_date(day1, cpi) / cpi_at_date(day0, cpi) - 1

    rows = []
    for c in MARKET_CODES + STOCK_CODES:
        s = d[(d["code"] == c) & d["close_adj"].notna() & ~d["market_closed"]].set_index("date_jalali")["close_adj"]
        before_day = s[s.index < a].index[-1]
        after = s[s.index > b]
        day1 = after.index[0]
        d20 = after.index[min(19, len(after) - 1)]   # 20th trading day after the closure
        chg1 = after.iloc[0] / s[before_day] - 1
        chg20 = after.loc[d20] / s[before_day] - 1
        comparable = before_day == open_before and day1 == reopen
        p1, p20 = cpi_prorated(before_day, day1), cpi_prorated(before_day, d20)
        m1, m20 = cpi_monthly(day1), cpi_monthly(d20)
        rr = (lambda n, i: pdx.real_return(n, i) if comparable else np.nan)
        rows.append({
            "code": c, "series": LABELS[c], "type": "market_index" if c in MARKET_CODES else "stock",
            "last_close_before": before_day, "first_close_after": day1, "comparable": comparable,
            "nominal_change_reopen": chg1,
            "cpi_change_reopen_prorated": p1, "real_change_reopen_prorated": rr(chg1, p1),
            "cpi_change_reopen_monthly": m1, "real_change_reopen_monthly": rr(chg1, m1),
            "close_after_20_trading_days": d20,
            "nominal_change_20d": chg20,
            "cpi_change_20d_prorated": p20, "real_change_20d_prorated": rr(chg20, p20),
            "cpi_change_20d_monthly": m20, "real_change_20d_monthly": rr(chg20, m20),
            "note": "" if comparable else
            f"symbol not trading at the closure edges ({before_day} / {day1}); not comparable",
        })
    return {"closed_days": len(closed), "first_closed": closed["date_jalali"].iloc[0],
            "last_closed": closed["date_jalali"].iloc[-1],
            "last_open_before": open_before, "reopen": reopen,
            "cpi_change_prorated": cpi_prorated(open_before, reopen),
            "cpi_from": cpi_from, "cpi_to": cpi_to, "cpi_change_monthly": cpi_monthly(reopen),
            "table": pd.DataFrame(rows)}


# --------------------------------------------------------------------------- #
# 5-6. Correlation and rolling
# --------------------------------------------------------------------------- #
def correlation(m: pd.DataFrame) -> pd.DataFrame:
    w = wide(m, "return_real", STOCK_CODES + ["index_total"])
    c = w.corr()
    c.index = c.columns = [LABELS[x] for x in c.columns]
    return c


def rolling_real(m: pd.DataFrame, window=12) -> pd.DataFrame:
    w = wide(m, "return_real", MARKET_CODES)
    return w.apply(rolling_compound, window=window).dropna()


# --------------------------------------------------------------------------- #
# 7. Risk-free context
# --------------------------------------------------------------------------- #
def risk_free_context(m: pd.DataFrame, recent_days: int = 30) -> dict | None:
    files = sorted((ROOT / "data" / "external").glob("ifb_debt_yields_*.csv"))
    if not files:
        return None
    f = files[-1]
    y = pd.read_csv(f, encoding="utf-8")
    fetched = pd.Timestamp(y["fetched_at"].iloc[0])
    y["LastTradeDate"] = pd.to_datetime(y["LastTradeDate"])
    gov = y[(y["DebtType"] == "erad") & y["ReferenceYTM"].notna()]
    recent = gov[gov["LastTradeDate"] >= (fetched.tz_localize(None) - pd.Timedelta(days=recent_days))]
    cpi = m[m["code"] == "cpi"].set_index("month_jalali")["cpi_index"]
    last = cpi.index.max()
    months = list(cpi.index)
    i = months.index(last)
    p2p = cpi[last] / cpi[months[i - 12]] - 1
    avg12 = cpi.iloc[i - 11:i + 1].mean() / cpi.iloc[i - 23:i - 11].mean() - 1
    ytm = float(recent["ReferenceYTM"].median())
    return {
        "file": f.relative_to(ROOT).as_posix(), "source": y["reference_url"].iloc[0],
        "fetched_at": str(fetched),
        "snapshot_jalali": f.stem.rsplit("_", 1)[-1][:4] + "-" + f.stem.rsplit("_", 1)[-1][4:6] + "-" + f.stem.rsplit("_", 1)[-1][6:],
        "instrument": "government Murabaha bonds (اراد)",
        "n_bonds": int(len(recent)), "ytm_median": ytm,
        "ytm_min": float(recent["ReferenceYTM"].min()), "ytm_max": float(recent["ReferenceYTM"].max()),
        "cpi_month": last, "inflation_point_to_point": float(p2p),
        "inflation_12m_average": float(avg12),
        "real_ytm_vs_p2p": float(pdx.real_return(ytm, p2p)),
        "real_ytm_vs_avg12": float(pdx.real_return(ytm, avg12)),
    }


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
# Reference palette (dataviz skill): categorical slots in fixed order, chart chrome inks.
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
C_INDEX, C_EW, C_PORT = "#2a78d6", "#eb6834", "#1baf7a"   # slots 1, 2, 3
C_STOCK = "#a9a79f"                                        # thin context lines (identity via labels)
C_NOMINAL, C_REAL = "#86b6ef", "#1c5cab"                   # blue ramp steps 250 / 550
DIV_NEG, DIV_MID, DIV_POS = "#e34948", "#f0efec", "#2a78d6"


def _style():
    import matplotlib as mpl
    mpl.use("Agg")
    mpl.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"], "font.size": 10,
        "text.color": INK, "axes.labelcolor": INK2, "axes.edgecolor": AXIS,
        "xtick.color": INK2, "ytick.color": INK2, "axes.titlesize": 13,
        "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 24,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "lines.linewidth": 2, "legend.frameon": False, "figure.dpi": 150,
    })


def _subtitle(ax, text):
    ax.text(0, 1.02, text, transform=ax.transAxes, color=INK2, fontsize=9.5, va="bottom")


def _month_axis(ax, months, every=3, right_pad=4):
    pos = list(range(len(months)))
    ax.set_xticks(pos[::every])
    ax.set_xticklabels(months[::every], rotation=0, fontsize=8.5)
    ax.set_xlim(-0.5, len(months) - 0.5 + right_pad)


def _maybe_log(ax, values) -> bool:
    import matplotlib.ticker as mt
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v) & (v > 0)]
    if v.max() / v.min() > 5:
        ax.set_yscale("log")
        cands = [10, 15, 20, 25, 35, 50, 70, 100, 150, 200, 300, 500, 700, 1000]
        lo, hi = v.min() * 0.9, v.max() * 1.1
        ax.yaxis.set_major_locator(mt.FixedLocator([c for c in cands if lo <= c <= hi]))
        ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda x, _: f"{x:g}"))
        ax.yaxis.set_minor_formatter(mt.NullFormatter())
        return True
    return False


def _pct(ax, axis="y"):
    import matplotlib.ticker as mt
    f = mt.PercentFormatter(1.0, decimals=0)
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(f)


def _end_labels(ax, items, x, min_gap_frac=0.035, log=False):
    """Direct labels at line ends, nudged apart vertically. items: [(y, text, color)]."""
    if not items:
        return
    tr = (lambda y: np.log10(y)) if log else (lambda y: y)
    inv = (lambda t: 10 ** t) if log else (lambda t: t)
    lo, hi = ax.get_ylim()
    gap = (tr(hi) - tr(lo)) * min_gap_frac
    pts = sorted([(tr(y), t, c) for y, t, c in items])
    placed = []
    for y, t, c in pts:
        if placed and y - placed[-1][0] < gap:
            y = placed[-1][0] + gap
        placed.append([y, t, c])
    # second pass from the top: keep labels inside the axes
    top = tr(hi) - gap / 2
    for k in range(len(placed) - 1, -1, -1):
        limit = top if k == len(placed) - 1 else placed[k + 1][0] - gap
        if placed[k][0] > limit:
            placed[k][0] = limit
    for y, t, c in placed:
        ax.text(x, inv(y), t, color=c if c != C_STOCK else INK2, fontsize=8.5, va="center",
                bbox=dict(facecolor=SURFACE, edgecolor="none", pad=0.5), zorder=5)


def _plot_growth_lines(ax, m, col="growth_real"):
    labels, vals = [], []
    for c in STOCK_CODES:
        s = m[m["code"] == c].sort_values("month_jalali")
        ax.plot(range(len(s)), s[col], color=C_STOCK, lw=1, zorder=1)
        vals += list(s[col])
        labels.append((s[col].iloc[-1], LABELS[c], INK2))
    for c, colr in (("index_total", C_INDEX), ("index_equal_weight", C_EW)):
        s = m[m["code"] == c].sort_values("month_jalali")
        ax.plot(range(len(s)), s[col], color=colr, lw=2.6, zorder=3)
        vals += list(s[col])
        labels.append((s[col].iloc[-1], LABELS[c], colr))
    return labels, vals


def fig_cumulative_real(m, path):
    import matplotlib.pyplot as plt
    months = sorted(m["month_jalali"].unique())
    fig, ax = plt.subplots(figsize=(11, 6.2))
    labels, vals = _plot_growth_lines(ax, m)
    ax.axhline(100, color=INK2, lw=1.2, ls="--", zorder=2)
    log = _maybe_log(ax, vals + [100])
    _month_axis(ax, months)
    ax.text(0.2, 103, " CPI = 100: kept pace with inflation", color=INK2, fontsize=8.5,
            va="bottom", bbox=dict(facecolor=SURFACE, edgecolor="none", pad=1))
    _end_labels(ax, labels, len(months) - 0.3, log=log)
    ax.set_ylabel("Real growth index (1402-06 = 100" + (", log scale)" if log else ")"))
    ax.set_title("Real (inflation-adjusted) growth of 100 invested at the end of 1402-06")
    _subtitle(ax, "Adjusted month-end closes deflated by SCI CPI. Coloured = market indices; "
                  "thin grey = 8 individual stocks (dispersion, not the market).")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_real_vs_nominal(rt, path):
    import matplotlib.pyplot as plt
    t = rt.sort_values("real_cagr").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 6.6))
    y = np.arange(len(t))
    h = 0.38
    ax.barh(y + h / 2 + 0.01, t["nominal_cagr"], height=h, color=C_NOMINAL, label="Nominal CAGR")
    ax.barh(y - h / 2 - 0.01, t["real_cagr"], height=h, color=C_REAL, label="Real CAGR (after inflation)")
    for i, r in t.iterrows():
        v = r["real_cagr"]
        ax.text(v + (0.015 if v >= 0 else -0.015), i - h / 2, f"{v:+.1%}", va="center",
                ha="left" if v >= 0 else "right", fontsize=8, color=INK2)
    ax.axvline(0, color=AXIS, lw=1)
    ax.set_xlim(min(t["real_cagr"].min(), 0) - 0.12, t["nominal_cagr"].max() * 1.05)
    ax.set_yticks(y)
    ax.set_yticklabels(t["series"])
    ax.grid(axis="y", visible=False)
    _pct(ax, "x")
    ax.legend(loc="lower right")
    cpi_n = rt.loc[rt.code == "cpi", "nominal_cagr"].iloc[0]
    ax.set_title("Annualized return, nominal vs real (1402-07 to 1405-06)")
    _subtitle(ax, f"CAGR over 36 months. Real = after SCI CPI inflation ({cpi_n:.1%} a year). "
                  "The 8-stock portfolio is hindsight-selected.")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# label offsets (points) for the scatter, to keep labels clear of neighbours
LABEL_OFFSETS = {PORTFOLIO_CODE: (-8, 7, "right"), "index_total": (-9, -12, "right"),
                 "vbmellat": (6, -12, "left"), "tipico": (7, 5, "left")}


def fig_risk_return(rt, path):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9.5, 6.4))
    cash_real = cagr(100, 100 / (1 + rt.loc[rt.code == "cpi", "nominal_cum_3y"].iloc[0]), 36)
    for _, r in rt.iterrows():
        if r["code"] == "cpi":
            continue
        colr = {"index_total": C_INDEX, "index_equal_weight": C_EW, PORTFOLIO_CODE: C_PORT}.get(r["code"], C_STOCK)
        big = r["code"] in (MARKET_CODES + [PORTFOLIO_CODE])
        ax.scatter(r["real_vol_per_year"], r["real_cagr"], s=90 if big else 60, color=colr,
                   edgecolor=SURFACE, linewidth=2, zorder=3)
        dx, dy, ha = LABEL_OFFSETS.get(r["code"], (7, 4, "left"))
        ax.annotate(r["series"], (r["real_vol_per_year"], r["real_cagr"]), xytext=(dx, dy),
                    textcoords="offset points", fontsize=8.5, ha=ha, color=INK if big else INK2)
    ax.scatter(0, cash_real, s=60, color=INK2, marker="s", zorder=3)
    ax.annotate(f"Rial cash at 0% interest ({cash_real:.0%} a year)", (0, cash_real),
                xytext=(7, 4), textcoords="offset points", fontsize=8.5, color=INK2)
    ax.axhline(0, color=INK2, lw=1.2, ls="--")
    ax.text(0.005, 0.008, "kept pace with inflation", color=INK2, fontsize=8, va="bottom")
    ax.set_xlim(-0.02, rt["real_vol_per_year"].max() * 1.25)
    _pct(ax, "y")
    _pct(ax, "x")
    ax.set_xlabel("Volatility of monthly real returns (annualized)")
    ax.set_ylabel("Real CAGR")
    ax.set_title("Risk vs real return, 1402-07 to 1405-06")
    _subtitle(ax, "Blue / orange = market indices; grey = individual stocks; green = "
                  "hindsight portfolio.")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_drawdowns(m, path):
    import matplotlib.pyplot as plt
    months = sorted(m["month_jalali"].unique())
    fig, ax = plt.subplots(figsize=(11, 5.8))
    labels = []
    for c in STOCK_CODES:
        s = m[m["code"] == c].sort_values("month_jalali")
        dd = drawdown_series(s["growth_real"])
        ax.plot(range(len(s)), dd, color=C_STOCK, lw=1, zorder=1)
        labels.append((dd.iloc[-1], LABELS[c], INK2))
    for c, colr in (("index_total", C_INDEX), ("index_equal_weight", C_EW)):
        s = m[m["code"] == c].sort_values("month_jalali")
        dd = drawdown_series(s["growth_real"])
        ax.plot(range(len(s)), dd, color=colr, lw=2.6, zorder=3)
        labels.append((dd.iloc[-1], LABELS[c], colr))
    _month_axis(ax, months)
    _pct(ax)
    ax.set_ylim(top=0.03)
    _end_labels(ax, labels, len(months) - 0.3)
    ax.set_ylabel("Drawdown from previous real peak")
    ax.set_title("Drawdowns of the REAL (inflation-adjusted) growth index")
    _subtitle(ax, "0% = at a new inflation-adjusted high. Coloured = market indices; thin grey = "
                  "individual stocks.")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _diverging_cmap():
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list("div", [DIV_NEG, DIV_MID, DIV_POS])


def fig_yearly_heatmap(yearly, path):
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mt
    from matplotlib.colors import TwoSlopeNorm
    order = STOCK_CODES + MARKET_CODES + [PORTFOLIO_CODE]
    t = yearly[yearly["code"].isin(order)].pivot(index="code", columns="block",
                                                  values="real_return_per_year").loc[order]
    fig, ax = plt.subplots(figsize=(8.5, 6.6))
    lim = 1.0
    im = ax.imshow(t.values.clip(-lim, lim), cmap=_diverging_cmap(),
                   norm=TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim), aspect="auto")
    for i in range(t.shape[0]):
        for j in range(t.shape[1]):
            v = t.values[i, j]
            ax.text(j, i, f"{v:+.0%}", ha="center", va="center", fontsize=9,
                    color="white" if abs(v) > 0.55 else INK)
    ax.set_xticks(range(t.shape[1]))
    ax.set_xticklabels([b.replace("..", " to ") for b in t.columns])
    ax.set_yticks(range(t.shape[0]))
    ax.set_yticklabels([LABELS[c] for c in t.index])
    ax.axhline(len(STOCK_CODES) - 0.5, color=SURFACE, lw=4)
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cb.ax.yaxis.set_major_formatter(mt.PercentFormatter(1.0))
    cb.outline.set_visible(False)
    ax.set_title("REAL return per 12-month block")
    _subtitle(ax, "Compounded monthly real returns. Colour capped at ±100%; labels show "
                  "actual values.")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_correlation(corr, path):
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("seq", ["#cde2fb", "#3987e5", "#0d366b"])
    fig, ax = plt.subplots(figsize=(8.6, 7.4))
    im = ax.imshow(corr.values, cmap=cmap, vmin=0, vmax=1)
    n = len(corr)
    for i in range(n):
        for j in range(n):
            v = corr.values[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8.5,
                    color="white" if v > 0.6 else INK)
    ax.set_xticks(range(n))
    ax.set_xticklabels([c.replace(" (TEDPIX)", "") for c in corr.columns], rotation=35, ha="right")
    ax.set_yticks(range(n))
    ax.set_yticklabels(corr.index)
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cb.outline.set_visible(False)
    ax.set_title("Correlation of monthly REAL returns")
    _subtitle(ax, "Pearson correlation, 36 months (1402-07 to 1405-06).")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_rolling(roll, path):
    import matplotlib.pyplot as plt
    months = list(roll.index)
    fig, ax = plt.subplots(figsize=(11, 5.4))
    labels = []
    for c, colr in (("index_total", C_INDEX), ("index_equal_weight", C_EW)):
        ax.plot(range(len(months)), roll[c], color=colr, lw=2.4)
        labels.append((roll[c].iloc[-1], LABELS[c], colr))
    ax.axhline(0, color=INK2, lw=1.2, ls="--")
    _month_axis(ax, months, every=2, right_pad=5)
    _pct(ax)
    _end_labels(ax, labels, len(months) - 0.3)
    ax.set_ylabel("Real return over the trailing 12 months")
    ax.set_title("Rolling 12-month REAL return of the market indices")
    _subtitle(ax, "Each point: compounded real return over the 12 months ending that month. "
                  "Below 0 = lost to inflation.")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_closure(d, m, clo, path):
    import matplotlib.pyplot as plt
    a, b = CLOSURE
    lo, hi = "1404-11-01", "1405-03-31"
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 5.8), gridspec_kw={"width_ratios": [2.2, 1]})
    cal = d[(d["code"] == "index_total") & (d["date_jalali"] >= lo) & (d["date_jalali"] <= hi)]
    days = list(cal["date_jalali"])
    pos = {x: i for i, x in enumerate(days)}
    closed_pos = [pos[x] for x in days if a <= x <= b]
    ax1.axvspan(min(closed_pos) - 0.5, max(closed_pos) + 0.5, color="#ecebe6", zorder=0)
    ax1.text((min(closed_pos) + max(closed_pos)) / 2, 0.97,
             f"market closed\n{a} to {b}\n({clo['closed_days']} index days)",
             transform=ax1.get_xaxis_transform(), ha="center", va="top", fontsize=8.5, color=INK2)
    for c, colr in (("index_total", C_INDEX), ("index_equal_weight", C_EW)):
        s = d[(d["code"] == c)].set_index("date_jalali")["close_adj"]
        base = s[clo["last_open_before"]]
        s = s.loc[lo:hi] / base * 100
        ax1.plot([pos[x] for x in s.index], s.values, color=colr, lw=2.2,
                 label=LABELS[c] + " (nominal)")
    cpi = m[m["code"] == "cpi"].set_index("month_jalali")["cpi_index"]
    base_cpi = cpi_at_date(clo["last_open_before"], cpi)
    ax1.plot(range(len(days)), [cpi_at_date(x, cpi) / base_cpi * 100 for x in days], color=INK2,
             lw=1.4, ls="--", label="CPI, interpolated daily (pro-rated)")
    ticks = [i for i, x in enumerate(days) if x[:7] != days[i - 1][:7] or i == 0]
    ax1.set_xticks(ticks)
    ax1.set_xticklabels([days[i] for i in ticks], fontsize=8.5)
    ax1.set_ylabel(f"Level, last close before closure ({clo['last_open_before']}) = 100")
    ax1.legend(loc="upper left", fontsize=8.5)
    ax1.set_title("Market closure: prices frozen, CPI kept rising")
    _subtitle(ax1, "Daily index levels (nominal) vs CPI interpolated by calendar day.")

    t = clo["table"].set_index("code").loc[MARKET_CODES]
    groups = ["Index change\non reopening", "CPI change\n(pro-rated to dates)",
              "REAL change\non reopening"]
    w = 0.38
    for k, (c, colr) in enumerate((("index_total", C_INDEX), ("index_equal_weight", C_EW))):
        vals = [t.loc[c, "nominal_change_reopen"], t.loc[c, "cpi_change_reopen_prorated"],
                t.loc[c, "real_change_reopen_prorated"]]
        xx = np.arange(3) + (k - 0.5) * (w + 0.02)
        ax2.bar(xx, vals, width=w, color=colr, label=LABELS[c])
        for x_, v in zip(xx, vals):
            ax2.text(x_, v + (0.01 if v >= 0 else -0.01), f"{v:+.1%}", ha="center",
                     va="bottom" if v >= 0 else "top", fontsize=8, color=INK2)
    ax2.axhline(0, color=AXIS, lw=1)
    ax2.set_xticks(range(3))
    ax2.set_xticklabels(groups, fontsize=8.5)
    ax2.grid(axis="x", visible=False)
    _pct(ax2)
    ax2.set_ylim(-0.3, 0.3)
    ax2.legend(loc="lower left", fontsize=8)
    ax2.set_title("Real loss while trading was impossible")
    _subtitle(ax2, f"Cumulative, {clo['last_open_before']} to {clo['reopen']}. "
                   "CPI interpolated to the exact dates.")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_portfolio(m, port, path):
    import matplotlib.pyplot as plt
    months = sorted(m["month_jalali"].unique())
    fig, ax = plt.subplots(figsize=(11, 5.8))
    labels = []
    for c, colr, s in (("index_total", C_INDEX, m[m["code"] == "index_total"]),
                       ("index_equal_weight", C_EW, m[m["code"] == "index_equal_weight"]),
                       (PORTFOLIO_CODE, C_PORT, port)):
        s = s.sort_values("month_jalali")
        ax.plot(range(len(s)), s["growth_real"], color=colr, lw=2.4,
                ls="-" if c != PORTFOLIO_CODE else (0, (5, 2)))
        labels.append((s["growth_real"].iloc[-1], LABELS[c], colr))
    ax.axhline(100, color=INK2, lw=1.2, ls="--")
    ax.text(0.2, 100, " CPI = 100", color=INK2, fontsize=8.5, va="bottom")
    _month_axis(ax, months, right_pad=7)
    _end_labels(ax, labels, len(months) - 0.3)
    ax.set_ylabel("Real growth index (1402-06 = 100)")
    ax.set_title("HINDSIGHT-SELECTED 8-stock portfolio vs the market, real terms")
    _subtitle(ax, "Equal weights, rebalanced monthly. The 8 stocks were picked after the fact, "
                  "so this is not a test of an investable strategy.")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Power BI exports
# --------------------------------------------------------------------------- #
def month_end_gregorian(month: str) -> str:
    from persiantools.jdatetime import JalaliDate
    y, mo = map(int, month.split("-"))
    for day in (31, 30, 29):
        try:
            return JalaliDate(y, mo, day).to_gregorian().isoformat()
        except ValueError:
            continue
    raise ValueError(month)


FA_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
             "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
SERIES_FA = {"index_total": "شاخص کل", "index_equal_weight": "شاخص کل (هم‌وزن)",
             "cpi": "شاخص قیمت مصرف‌کننده (تورم)",
             PORTFOLIO_CODE: "سبد هم‌وزن ۸ سهم با نگاه به گذشته"}
TYPE_DIM = {"stock": "stock", "market_index": "market_index", "sector_index": "sector_index",
            "portfolio_hindsight": "portfolio", "cpi": "cpi"}
USAGE_NOTE = {
    "stock": "individual stock: dispersion, not the market",
    "market_index": "the market: conclusions about the market use only these two indices",
    "sector_index": "trend only: unknown whether dividends are included; do not compare with stocks",
    "portfolio": "hindsight-selected portfolio, not an investable strategy",
    "cpi": "inflation benchmark (SCI CPI, 1400=100)",
}
TYPE_ORDER = {"market_index": 0, "cpi": 1, "portfolio": 2, "stock": 3, "sector_index": 4}


def month_label_fa(month: str) -> str:
    y, mo = month.split("-")
    return f"{FA_MONTHS[int(mo) - 1]} {y.translate(FA_DIGITS)}"


def rolling_real_12m_long(allm: pd.DataFrame) -> pd.Series:
    """Real return over the 12 months ending in each month; NaN for the base month and
    the first 11 return months. Aligned to allm's index."""
    out = pd.Series(np.nan, index=allm.index)
    for _, g in allm.groupby("code"):
        g = g.sort_values("month_jalali")
        r = g["return_real"].where(g["month_jalali"] > BASE)
        out.loc[g.index] = rolling_compound(r.dropna(), 12).reindex(g.index).values
    return out


def dim_series_frame(allm: pd.DataFrame) -> pd.DataFrame:
    stock_order = {c: i for i, c in enumerate(STOCK_CODES)}
    d = allm.drop_duplicates("code")[["code", "label", "symbol", "type", "sector"]].copy()
    d["type"] = d["type"].map(TYPE_DIM)
    d["series_fa"] = [SERIES_FA.get(c, f"شاخص صنعت {sym}" if t == "sector_index" else sym)
                      for c, sym, t in zip(d["code"], d["symbol"], d["type"])]
    d["series"] = [lab if t != "sector_index" else
                   c.replace("sector_", "").replace("_", " ").title() + " (sector index)"
                   for c, lab, t in zip(d["code"], d["label"], d["type"])]
    d["usage_note"] = d["type"].map(USAGE_NOTE)
    d["_k1"] = d["type"].map(TYPE_ORDER)
    d["_k2"] = [stock_order.get(c, 0) if t == "stock" else
                (MARKET_CODES.index(c) if t == "market_index" else 0)
                for c, t in zip(d["code"], d["type"])]
    d = d.sort_values(["_k1", "_k2", "code"]).reset_index(drop=True)
    d["sort_order"] = np.arange(1, len(d) + 1)
    return d.rename(columns={"code": "series_code"})[
        ["series_code", "series", "series_fa", "type", "sector", "usage_note", "sort_order"]]


def dim_month_frame(months: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "month": months,
        "month_label_fa": [month_label_fa(x) for x in months],
        "month_end_gregorian": [month_end_gregorian(x) for x in months],
        "jalali_year": [int(x[:4]) for x in months],
        "sort_key": [int(x[:4]) * 100 + int(x[5:7]) for x in months],
    })


def closure_summary_frame(clo: dict, fa: dict) -> pd.DataFrame:
    rows = []
    for _, r in clo["table"].iterrows():
        for window, sfx, end in (("on_reopening", "reopen", r["first_close_after"]),
                                 ("after_20_days", "20d", r["close_after_20_trading_days"])):
            rows.append({
                "series_code": r["code"], "series": r["series"], "series_fa": fa[r["code"]],
                "window": window, "window_start": r["last_close_before"], "window_end": end,
                "nominal": r[f"nominal_change_{sfx}"],
                "cpi_prorated": r[f"cpi_change_{sfx}_prorated"],
                "real_prorated": r[f"real_change_{sfx}_prorated"],
                "cpi_whole_months": r[f"cpi_change_{sfx}_monthly"],
                "real_whole_months": r[f"real_change_{sfx}_monthly"],
                "comparable": bool(r["comparable"]),
            })
    return pd.DataFrame(rows)


def context_frame(rf: dict | None) -> pd.DataFrame:
    cols = ["bond_ytm", "inflation_12m_avg", "inflation_point_to_point", "real_yield_avg",
            "real_yield_p2p", "snapshot_date", "source_url", "instrument", "n_bonds"]
    if not rf:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([{
        "bond_ytm": rf["ytm_median"], "inflation_12m_avg": rf["inflation_12m_average"],
        "inflation_point_to_point": rf["inflation_point_to_point"],
        "real_yield_avg": rf["real_ytm_vs_avg12"], "real_yield_p2p": rf["real_ytm_vs_p2p"],
        "snapshot_date": rf["snapshot_jalali"], "source_url": rf["source"],
        "instrument": "اوراق مرابحه دولت (اراد)", "n_bonds": rf["n_bonds"],
    }])[cols]


def export_powerbi(res: dict) -> dict[str, str]:
    """Write the Power BI CSVs (UTF-8) to data/processed/powerbi/."""
    m, port, rt, yearly, corr = res["monthly"], res["portfolio"], res["risk"], res["yearly"], res["corr"]
    PBI.mkdir(parents=True, exist_ok=True)
    allm = pd.concat([m, port], ignore_index=True)
    dim_series = dim_series_frame(allm)
    fa = dict(zip(dim_series["series_code"], dim_series["series_fa"]))
    ml = pd.DataFrame({
        "month": allm["month_jalali"],
        "month_end_gregorian": allm["month_jalali"].map(month_end_gregorian),
        "series": allm["label"], "series_fa": allm["code"].map(fa), "series_code": allm["code"],
        "type": allm["type"], "sector": allm["sector"],
        "usage_note": allm["type"].map(TYPE_DIM).map(USAGE_NOTE),
        "nominal_return_per_month": allm["return_nominal"],
        "real_return_per_month": allm["return_real"],
        "inflation_per_month": allm["inflation_monthly"],
        "real_return_rolling_12m": rolling_real_12m_long(allm),
        "nominal_index_1402_06_eq_100": allm["growth_nominal"],
        "real_index_1402_06_eq_100": allm["growth_real"],
        "nominal_cum_since_1402_06": allm["growth_nominal"] / 100 - 1,
        "real_cum_since_1402_06": allm["growth_real"] / 100 - 1,
        "is_base_month": allm["is_base_month"],
        "flag_any": allm["data_flag"].astype(bool),
        "flag_market_closure": allm["market_closure_in_month"].astype(bool),
        "flag_long_suspension": allm["long_suspension"].astype(bool),
        "flag_no_trade": allm["no_trade_in_month"].astype(bool),
    }).sort_values(["series_code", "month"]).reset_index(drop=True)
    # 10 x 10: the 8 stocks and both market indices (the notebook's 9 x 9 matrix plus the
    # equal-weight index; same method: Pearson on monthly real returns, 36 months)
    codes10 = STOCK_CODES + MARKET_CODES
    corr10 = wide(m, "return_real", codes10).corr().rename_axis(index="a", columns="b")
    order = dict(zip(dim_series["series_code"], dim_series["sort_order"]))
    cl = corr10.stack().rename("corr_real_return_per_month").reset_index()
    cl.columns = ["series_a_code", "series_b_code", "corr_real_return_per_month"]
    cl = pd.DataFrame({
        "series_a": cl["series_a_code"].map(LABELS), "series_a_code": cl["series_a_code"],
        "series_a_fa": cl["series_a_code"].map(fa), "series_a_order": cl["series_a_code"].map(order),
        "series_b": cl["series_b_code"].map(LABELS), "series_b_code": cl["series_b_code"],
        "series_b_fa": cl["series_b_code"].map(fa), "series_b_order": cl["series_b_code"].map(order),
        "corr_real_return_per_month": cl["corr_real_return_per_month"]})
    frames = {
        "monthly_long": ml, "risk_summary": rt, "yearly_real": yearly, "correlation_long": cl,
        "closure_summary": closure_summary_frame(res["closure"], fa),
        "dim_series": dim_series,
        "dim_month": dim_month_frame(sorted(allm["month_jalali"].unique())),
        "context": context_frame(res["risk_free"]),
    }
    out = {}
    for name, df in frames.items():
        p = PBI / f"{name}.csv"
        df.to_csv(p, index=False, encoding="utf-8")
        out[name] = p.relative_to(ROOT).as_posix()
    return out


# --------------------------------------------------------------------------- #
# Key findings (every number comes from the computed results)
# --------------------------------------------------------------------------- #
def key_findings(res: dict) -> list[str]:
    """Five findings. Every return states its unit: per year, or cumulative over 3 years
    (or, for the closure, cumulative over the stated window)."""
    rt = res["risk"].set_index("code")
    yr = res["yearly"]
    clo, rf = res["closure"], res["risk_free"]
    cpi_cum = rt.loc["cpi", "nominal_cum_3y"]
    cash_loss = 1 / (1 + cpi_cum) - 1
    tot, ew, pf = rt.loc["index_total"], rt.loc["index_equal_weight"], rt.loc[PORTFOLIO_CODE]
    st = rt.loc[STOCK_CODES]
    winners = st[st["real_cum_3y"] > 0].sort_values("real_cum_3y", ascending=False)
    winners_txt = ", ".join(f"{LABELS[c]} {winners.loc[c, 'real_cum_3y']:+.0%}" for c in winners.index)
    b = yr[yr["code"] == "index_total"].set_index("block")["real_return_per_year"]
    rs = res["rank_stability"]["spearman_rank_corr"]
    ct = clo["table"].set_index("code").loc["index_total"]
    f = [
        f"**1. The market did not beat inflation, but it beat cash by a wide margin.** CPI rose "
        f"{cpi_cum:.0%} cumulative over 3 years ({rt.loc['cpi', 'nominal_cagr']:.1%} per year). "
        f"In real terms the overall index lost {-tot['real_cum_3y']:.1%} cumulative over 3 years "
        f"({tot['real_cagr']:+.1%} per year) and the equal-weight index lost "
        f"{-ew['real_cum_3y']:.1%} cumulative over 3 years ({ew['real_cagr']:+.1%} per year). "
        f"Rial cash at 0% lost {-cash_loss:.0%} of its purchasing power, cumulative over 3 years. "
        f"*Implication:* idle rial cash was by far the costliest place to hold money; a broad "
        f"index nearly preserved value, at the price of {tot['real_vol_per_year']:.0%} real "
        f"volatility per year.",

        f"**2. Single stocks are bets, not inflation hedges.** {len(winners)} of the 8 stocks beat "
        f"inflation ({winners_txt} real, cumulative over 3 years). Real CAGRs ranged from "
        f"{st['real_cagr'].min():+.1%} per year ({LABELS[st['real_cagr'].idxmin()]}) to "
        f"{st['real_cagr'].max():+.1%} per year ({LABELS[st['real_cagr'].idxmax()]}). Even this "
        f"hindsight-selected set, held in equal weights and rebalanced monthly, made only "
        f"{pf['real_cum_3y']:+.1%} real cumulative over 3 years, which is {pf['real_cagr']:+.1%} "
        f"per year. *Implication:* the spread between stocks dwarfs the gap between the market and "
        f"inflation; protection against inflation needs diversification, not a favourite ticker.",

        f"**3. All of the real gain came in the last 12 months, and leadership kept changing.** "
        f"The overall index returned {b.iloc[0]:+.1%}, {b.iloc[1]:+.1%} and {b.iloc[2]:+.1%} "
        f"real per year in the three 12-month blocks. The rank correlation of the 8 stocks "
        f"between consecutive years was only {rs.iloc[0]:.2f} and {rs.iloc[1]:.2f}. "
        f"*Implication:* beating inflation with equities needed a multi-year horizon and the "
        f"stomach for two losing years; last year's winner was a weak guide to next year's.",

        f"**4. Liquidity risk is real: the {clo['closed_days']}-trading-day market closure cost "
        f"{-ct['real_change_reopen_prorated']:.1%} in real terms by reopening.** From the last close "
        f"({clo['last_open_before']}) to the first close after the closure ({clo['reopen']}) the "
        f"overall index changed {ct['nominal_change_reopen']:+.1%} nominal while CPI, pro-rated "
        f"to those dates, rose {ct['cpi_change_reopen_prorated']:.1%}; all three figures are "
        f"cumulative over the closure. Using whole CPI months ({clo['cpi_from']} to "
        f"{clo['cpi_to']}) instead gives {ct['real_change_reopen_monthly']:+.1%}. Twenty trading "
        f"days after reopening the index was {ct['nominal_change_20d']:+.1%} nominal and "
        f"{ct['real_change_20d_prorated']:+.1%} real, cumulative from the last close before the "
        f"closure ({ct['real_change_20d_monthly']:+.1%} with whole CPI months). *Implication:* "
        f"listed equities can be locked for months; a treasury must keep its operating runway "
        f"in instruments it can actually withdraw.",
    ]
    if rf:
        f.append(
            f"**5. The 'safe' asset is negative in real terms too.** If inflation stays at last "
            f"year's level, today's government bond yield implies a real return of about "
            f"{rf['real_ytm_vs_avg12']:.0%} per year ({rf['real_ytm_vs_p2p']:.0%} per year against "
            f"point-to-point inflation). The median yield to maturity of government Murabaha bonds "
            f"(اراد, {rf['n_bonds']} issues traded in the 30 days before the snapshot) was "
            f"{rf['ytm_median']:.1%} per year (IFB snapshot {rf['snapshot_jalali']}, {rf['source']}); "
            f"this yield is forward-looking. Last year's inflation is trailing: "
            f"{rf['inflation_12m_average']:.1%} per year as a 12-month average and "
            f"{rf['inflation_point_to_point']:.1%} point-to-point (12 months to {rf['cpi_month']}). "
            f"*Implication:* fixed rial income only slows the loss; size rial holdings to near-term "
            f"rial costs and treat the rest as capital to protect, not to park.")
    return f


# --------------------------------------------------------------------------- #
def run_all(write: bool = True) -> dict:
    m, d = load_monthly(), load_daily()
    port = portfolio_frame(m)
    res = {"monthly": m, "portfolio": port}
    res["risk"] = risk_table(m, port)
    res["yearly"], res["ranks"] = yearly_table(m, port)
    res["rank_stability"] = rank_stability(res["ranks"])
    res["closure"] = closure_analysis(d, m)
    res["corr"] = correlation(m)
    res["rolling"] = rolling_real(m)
    res["risk_free"] = risk_free_context(m)
    res["findings"] = key_findings(res)
    if write:
        _style()
        FIG.mkdir(parents=True, exist_ok=True)
        fig_cumulative_real(m, FIG / "01_cumulative_real_growth.png")
        fig_real_vs_nominal(res["risk"], FIG / "02_real_vs_nominal_bar.png")
        fig_risk_return(res["risk"], FIG / "03_risk_return_scatter.png")
        fig_drawdowns(m, FIG / "04_drawdowns.png")
        fig_yearly_heatmap(res["yearly"], FIG / "05_yearly_real_returns_heatmap.png")
        fig_correlation(res["corr"], FIG / "06_correlation_heatmap.png")
        fig_rolling(res["rolling"], FIG / "07_rolling_12m_real.png")
        fig_closure(d, m, res["closure"], FIG / "08_closure_period.png")
        fig_portfolio(m, port, FIG / "09_hindsight_portfolio.png")
        res["powerbi"] = export_powerbi(res)
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    r = run_all()
    print("\n\n".join(r["findings"]))

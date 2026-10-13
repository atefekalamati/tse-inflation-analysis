"""Generate and execute notebooks/01_analysis.ipynb (all logic lives in src/analysis.py).

Usage:  python src/build_notebook.py
"""
from __future__ import annotations

from pathlib import Path

import nbformat as nbf
from nbconvert.preprocessors import ExecutePreprocessor

ROOT = Path(__file__).resolve().parents[1]
NB = ROOT / "notebooks" / "01_analysis.ipynb"

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell

cells = [
    md("""# Did Tehran Stock Exchange stocks beat inflation? (Mehr 1402 to Shahrivar 1405)

**Data:** monthly panel `data/processed/prices_monthly.parquet`. It has 36 monthly returns from
1402-07 to 1405-06, base month 1402-06. Prices are adjusted official closing prices from
TSETMC via algotik-tse. Inflation is the CPI of the Statistical Centre of Iran (all households,
whole country, 1400 = 100). *Real* always means deflated by that CPI:
real return = (1 + nominal) / (1 + inflation) - 1.

**How to read this notebook**

* **Conclusions about "the market" come only from شاخص کل (overall index, TEDPIX) and the
  equal-weight index.**
* The 8 stocks (one per sector) **illustrate dispersion across sectors; they are not the
  market.** They were picked after the fact, so any average of them is hindsight-selected.
* Stocks are **not compared with sector indices**. It is unknown whether TSETMC sector indices
  include dividends, while the adjusted stock prices do. Sector indices appear only as trend
  lines in the Power BI export, labelled "trend only".
* All code lives in `src/analysis.py`; this notebook only calls it. Tests: `tests/test_analysis.py`."""),
    code("""import sys
from pathlib import Path
ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
from IPython.display import Image, Markdown, display
import analysis as an

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)
res = an.run_all()          # computes all tables, writes figures and Power BI CSVs
FIG = an.FIG

def pct(df, cols, digits=1):
    out = df.copy()
    for c in cols:
        out[c] = out[c].map(lambda v: "" if pd.isna(v) else f"{v:+.{digits}%}")
    return out"""),

    md("""## 1. Return and risk

Annualized figures are CAGR over the 36 months. Volatility is the standard deviation of
monthly **real** returns times √12. Maximum drawdown is measured on the **real** cumulative
index. "Real return per unit of risk" is real CAGR divided by real volatility. It is *not* a
Sharpe ratio, because there is no risk-free rate in it.

`flagged months` counts months with a market closure, a long suspension (5 or more
open-market days) or no trade. Returns in those months are less reliable."""),
    code("""rt = res["risk"]
show = rt[["series", "type", "cagr_nominal", "cagr_real", "cum_real_growth", "vol_real_annual",
           "max_drawdown_real", "dd_peak", "dd_trough", "dd_recovery",
           "pct_months_beat_inflation", "worst_real_month", "worst_month", "best_real_month",
           "best_month", "real_return_per_unit_risk", "flagged_months"]]
show = pct(show, ["cagr_nominal", "cagr_real", "cum_real_growth", "max_drawdown_real",
                  "worst_real_month", "best_real_month"])
show["vol_real_annual"] = rt["vol_real_annual"].map(lambda v: f"{v:.1%}")
show["pct_months_beat_inflation"] = rt["pct_months_beat_inflation"].map(
    lambda v: "" if pd.isna(v) else f"{v:.0%}")
show["real_return_per_unit_risk"] = rt["real_return_per_unit_risk"].map(
    lambda v: "" if pd.isna(v) else f"{v:+.2f}")
show.fillna("")"""),
    code("""display(Image(FIG / "02_real_vs_nominal_bar.png"))
display(Image(FIG / "03_risk_return_scatter.png"))
display(Image(FIG / "04_drawdowns.png"))"""),
    md("""**Reading:** the overall index lost a little to inflation and the equal-weight index lost more,
so the average listed company did worse than the large caps. Rial cash at 0% sits far below
everything. The individual stocks spread out widely in both risk and return."""),

    md("""## 2. Period breakdown: real return per 12-month block"""),
    code("""y = res["yearly"]
blocks = y.pivot(index="series", columns="block", values="real_return")
order = [an.LABELS[c] for c in an.STOCK_CODES + an.MARKET_CODES + [an.PORTFOLIO_CODE, "cpi"]]
blocks = blocks.loc[order]
display(blocks.map(lambda v: f"{v:+.1%}"))
print("Rank among the 8 stocks (1 = best real return in the block):")
display(res["ranks"])
print("Rank stability (Spearman correlation of stock ranks):")
display(res["rank_stability"].round(2))"""),
    code("""display(Image(FIG / "05_yearly_real_returns_heatmap.png"))"""),
    md("""**Did the ranking change?** Yes. Rank correlations between consecutive years are low,
and only Fameli stayed near the top in every block. Every series lost to inflation in the first
block, and all but Vbmellat lost again in the second. The whole real gain of the market came in
1404-07 to 1405-06."""),

    md("""## 3. Market closure (1404-12-09 to 1405-02-28)

The overall index was flat and at zero volume on 50 index days. Nothing could be bought or
sold. CPI is monthly, so closure-period inflation is measured from CPI 1404-11 to CPI 1405-02,
the three months the closure spans. The 20-trading-day comparison uses CPI through the month in
which that window ends (1405-03)."""),
    code("""c = res["closure"]
print(f"Closed index days: {c['closed_days']}  ({c['first_closed']} to {c['last_closed']})")
print(f"Last close before: {c['last_open_before']}   first close after: {c['reopen']}")
print(f"CPI growth {c['cpi_from']} -> {c['cpi_to']}: {c['cpi_growth']:.1%}")
t = c["table"][["series", "type", "last_close_before", "first_close_after",
                "nominal_change_first_day", "real_change_first_day",
                "close_after_20_trading_days", "nominal_change_20d", "cpi_growth_20d",
                "real_change_20d", "note"]]
pct(t, ["nominal_change_first_day", "real_change_first_day", "nominal_change_20d",
        "cpi_growth_20d", "real_change_20d"]).fillna("")"""),
    code("""display(Image(FIG / "08_closure_period.png"))"""),
    md("""**Reading:** on reopening, both market indices were where they had been 50 trading days
earlier, while prices in the economy had risen about a fifth. That is the real loss investors
carried while they could not trade. The market then caught up over the following weeks. That
gradual pace is consistent with TSE daily price limits, although this data cannot prove the cause. Foolad stayed suspended until 1405-05-17, so its row is
not comparable."""),

    md("""## 4. Equal-weight portfolio of the 8 stocks (HINDSIGHT-SELECTED)

Equal weights, rebalanced monthly: each month's return is the average of the 8 stocks' returns.
**The 8 stocks were chosen after the period, so this is not an investable strategy and not
evidence about the market.** It only shows what diversifying across these sectors would have
done."""),
    code("""p = res["risk"].set_index("code").loc[[an.PORTFOLIO_CODE, "index_total", "index_equal_weight"]]
pct(p[["series", "cagr_nominal", "cagr_real", "cum_real_growth", "max_drawdown_real"]],
    ["cagr_nominal", "cagr_real", "cum_real_growth", "max_drawdown_real"])"""),
    code("""display(Image(FIG / "09_hindsight_portfolio.png"))
display(Image(FIG / "01_cumulative_real_growth.png"))"""),

    md("""## 5. Correlation of monthly real returns"""),
    code("""display(res["corr"].round(2))
display(Image(FIG / "06_correlation_heatmap.png"))"""),
    md("""**Reading:** all stocks move strongly with the market. The correlation with the overall
index is 0.70 to 0.95, which limits how much diversifying across these 8 names reduces risk.
Foolad and Tipico are the least correlated pair."""),

    md("""## 6. Rolling 12-month real return of the market indices"""),
    code("""display(res["rolling"].map(lambda v: f"{v:+.1%}").T)
display(Image(FIG / "07_rolling_12m_real.png"))"""),

    md("""## 7. Risk-free context

TSETMC treasury bills (اخزا) are **not listed** on the IFB YTM page that algotik-tse reads.
The closest government instrument there is **government Murabaha bonds (اراد)**, so those are
used instead. The yield is a snapshot taken when the data was fetched (early 1405-07). It is
compared with SCI inflation for the 12 months to 1405-06."""),
    code("""rf = res["risk_free"]
if rf is None:
    print("No IFB snapshot found: item skipped.")
else:
    display(pd.Series(rf))"""),

    md("""## Data caveats

* Adjusted prices treat rights issues paid in cash like bonus shares, which slightly overstates
  returns around those events.
* In a month with no trade, the previous price is carried forward. The move then lands in the
  month trading resumes. Such months are flagged (`flagged_months`).
* CPI is a monthly average of prices collected from the 1st to the 28th. Stock returns are
  end-of-month to end-of-month, so single-month real returns contain some timing noise. Over
  36 months this noise largely cancels.
* Five days of the petroleum sector index were corrected (decimal shift). That index is not
  used in any finding. See `reports/corrections.md`."""),

    md("## Key findings"),
    code("""display(Markdown("\\n\\n".join(res["findings"])))"""),
]

nb = nbf.v4.new_notebook()
nb["cells"] = cells
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
ExecutePreprocessor(timeout=600, kernel_name="python3").preprocess(nb, {"metadata": {"path": str(NB.parent)}})
nbf.write(nb, NB)
print(f"wrote {NB.relative_to(ROOT)}")

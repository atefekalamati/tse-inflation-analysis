"""Tests for src/analysis.py: hand examples for the math, consistency checks on results."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import analysis as an  # noqa: E402


# ------------------------------ CAGR ------------------------------------- #
def test_cagr_hand_examples():
    # 100 -> 121 over 24 months = 10% a year
    assert an.cagr(100, 121, 24) == pytest.approx(0.10)
    # 100 -> 800 over 36 months = doubling every year
    assert an.cagr(100, 800, 36) == pytest.approx(1.0)
    # 100 -> 50 over 12 months = -50%
    assert an.cagr(100, 50, 12) == pytest.approx(-0.5)
    # 6 months: 100 -> 110.25 annualizes to 21.55%
    assert an.cagr(100, 110.25, 6) == pytest.approx(1.1025 ** 2 - 1)


def test_cagr_from_returns_matches_levels():
    r = [0.10, -0.05, 0.02, 0.0, 0.07, -0.01, 0.03, 0.04, -0.02, 0.05, 0.01, 0.0]
    level = 100 * np.prod([1 + x for x in r])
    assert an.cagr_from_returns(r) == pytest.approx(an.cagr(100, level, 12))
    assert an.cagr_from_returns(r) == pytest.approx(level / 100 - 1)   # 12 months = 1 year


# ----------------------------- drawdown ---------------------------------- #
def test_max_drawdown_hand_example():
    lv = pd.Series([100, 120, 90, 60, 80, 130, 110], index=list("abcdefg"))
    dd = an.max_drawdown(lv)
    assert dd["max_drawdown"] == pytest.approx(60 / 120 - 1)   # -50%
    assert dd["peak"] == "b" and dd["trough"] == "d"
    assert dd["recovery"] == "f"                                # first value >= 120


def test_max_drawdown_not_recovered_and_monotone():
    dd = an.max_drawdown(pd.Series([100, 90, 95, 80, 85], index=range(5)))
    assert dd["max_drawdown"] == pytest.approx(-0.20)
    assert (dd["peak"], dd["trough"], dd["recovery"]) == (0, 3, None)
    up = an.max_drawdown(pd.Series([100, 101, 105, 110]))
    assert up["max_drawdown"] == 0 and up["peak"] is None


def test_drawdown_uses_earlier_peak_not_later_one():
    # the deepest fall is from 200 to 100 (-50%), not from the later peak 150
    lv = pd.Series([100, 200, 100, 150, 90], index=range(5))
    dd = an.max_drawdown(lv)
    assert dd["max_drawdown"] == pytest.approx(90 / 200 - 1)
    assert dd["peak"] == 1 and dd["trough"] == 4


# --------------------------- 12-month blocks ----------------------------- #
def test_block_returns_hand_example():
    months = an.month_range("1402-07", "1405-06")
    assert len(months) == 36 and months[5] == "1402-12" and months[6] == "1403-01"
    # +1% every month in block 1, -1% in block 2, 0% in block 3
    r = pd.Series([0.01] * 12 + [-0.01] * 12 + [0.0] * 12, index=months)
    b = an.block_returns(r)
    assert list(b.index) == ["1402-07..1403-06", "1403-07..1404-06", "1404-07..1405-06"]
    assert b.iloc[0] == pytest.approx(1.01 ** 12 - 1)
    assert b.iloc[1] == pytest.approx(0.99 ** 12 - 1)
    assert b.iloc[2] == pytest.approx(0.0)
    # blocks chain to the whole-period return
    assert np.prod(1 + b.values) == pytest.approx(np.prod(1 + r.values))


def test_block_returns_rejects_incomplete_block():
    months = an.month_range("1402-07", "1405-06")
    r = pd.Series(0.01, index=months).drop("1403-02")
    with pytest.raises(ValueError):
        an.block_returns(r)


def test_rolling_compound_hand_example():
    r = pd.Series([0.1, 0.1, -0.5, 0.2])
    out = an.rolling_compound(r, window=2)
    assert np.isnan(out.iloc[0])
    assert out.iloc[1] == pytest.approx(1.1 * 1.1 - 1)
    assert out.iloc[3] == pytest.approx(0.5 * 1.2 - 1)


def test_ew_rebalanced_is_mean_of_returns():
    w = pd.DataFrame({"a": [0.10, -0.20], "b": [0.30, 0.00]})
    assert list(an.ew_rebalanced_returns(w)) == pytest.approx([0.20, -0.10])


# ---------------------- consistency on the real data --------------------- #
@pytest.fixture(scope="module")
def res():
    return an.run_all(write=False)


def test_risk_table_series_and_definitions(res):
    rt = res["risk"].set_index("code")
    assert set(an.STOCK_CODES + an.MARKET_CODES + ["cpi"]) <= set(rt.index)
    assert (rt["months"] == 36).all()
    m = res["monthly"]
    for c in an.STOCK_CODES + an.MARKET_CODES:
        s = m[(m["code"] == c) & (m["month_jalali"] > an.BASE)]
        assert rt.loc[c, "cagr_real"] == pytest.approx(an.cagr_from_returns(s["return_real"]))
        assert rt.loc[c, "vol_real_annual"] == pytest.approx(s["return_real"].std() * np.sqrt(12))
        assert rt.loc[c, "pct_months_beat_inflation"] == pytest.approx(
            (s["return_nominal"] > s["inflation_monthly"]).mean())
        assert rt.loc[c, "real_return_per_unit_risk"] == pytest.approx(
            rt.loc[c, "cagr_real"] / rt.loc[c, "vol_real_annual"])
    assert rt.loc["cpi", "cagr_real"] == pytest.approx(0, abs=1e-12)
    assert rt.loc["cpi", "cum_nominal_growth"] == pytest.approx(729.8394 / 201.7326 - 1, rel=1e-6)


def test_yearly_blocks_chain_to_total(res):
    y = res["yearly"]
    rt = res["risk"].set_index("code")
    for c, g in y.groupby("code"):
        assert len(g) == 3
        assert np.prod(1 + g["real_return"]) - 1 == pytest.approx(rt.loc[c, "cum_real_growth"], rel=1e-9)


def test_portfolio_is_hindsight_labeled_and_consistent(res):
    p = res["portfolio"]
    assert (p["type"] == "portfolio_hindsight").all()
    assert "hindsight" in an.LABELS[an.PORTFOLIO_CODE]
    m = res["monthly"]
    w = an.wide(m, "return_nominal", an.STOCK_CODES)
    pr = p.set_index("month_jalali")["return_nominal"].dropna()
    assert np.allclose(pr.values, w.mean(axis=1).values)


def test_closure_uses_market_days(res):
    c = res["closure"]
    assert c["closed_days"] == 50
    assert (c["last_open_before"], c["reopen"]) == ("1404-12-06", "1405-02-29")
    t = c["table"].set_index("code")
    expect = (1 + t.loc["index_total", "nominal_change_first_day"]) / (1 + c["cpi_growth"]) - 1
    assert t.loc["index_total", "real_change_first_day"] == pytest.approx(expect)


def test_findings_have_numbers(res):
    f = res["findings"]
    assert len(f) == 5
    assert all(any(ch.isdigit() for ch in x) and "Implication" in x for x in f)

"""Tests on the processed panels (step 2). Run:  pytest -q"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import data_quality as dq  # noqa: E402
import process_data as pdx  # noqa: E402

DAILY = pd.read_parquet(pdx.DAILY)
MONTHLY = pd.read_parquet(pdx.MONTHLY)
CFG = dq.load_settings()
RETURN_MONTHS = [m for m in dq.cpi_frame()["jalali_month"] if m > pdx.BASE_MONTH]


def test_return_months_are_1402_07_to_1405_06():
    assert RETURN_MONTHS[0] == "1402-07" and RETURN_MONTHS[-1] == "1405-06"
    assert len(RETURN_MONTHS) == 36


# ----------------------------- corrections ------------------------------- #
def test_corrected_sector_index_has_no_jump_over_50pct():
    s = DAILY[DAILY["symbol"] == "فرآورده‌های نفتی"].sort_values("date_jalali")
    assert len(s) and s["was_corrected"].sum() == 5
    r = s["close_adj"].pct_change(fill_method=None)
    big = s.loc[r.abs() > 0.5, "date_jalali"].tolist()
    assert not big, f"|daily return| > 50% on {big}"


def test_no_series_has_daily_jump_over_50pct():
    for code, s in DAILY.groupby("code"):
        r = s.sort_values("date_jalali")["close_adj"].dropna().pct_change().dropna()
        assert (r.abs() <= 0.5).all(), f"{code}: max |daily return| {r.abs().max():.1%}"


def test_raw_file_is_not_modified_by_processing():
    raw = dq.read_raw("data/raw/sector_of_shepna.csv").set_index("J-Date")
    assert raw.loc["1404-03-19", "Close"] == 1301800.0  # still the original wrong value


# ------------------------------ daily panel ------------------------------ #
def test_daily_panel_key_unique_and_complete():
    assert not DAILY.duplicated(["code", "date_jalali"]).any()
    n_days = DAILY["date_jalali"].nunique()
    assert (DAILY.groupby("code").size() == n_days).all()


def test_daily_flags_consistent():
    assert DAILY.loc[DAILY["market_closed"], "date_jalali"].nunique() == 61
    st = DAILY[DAILY["type"] == "stock"]
    assert not (st["market_closed"] & st["close_adj"].notna()).any(), "stock trade on closed day"
    assert not (st["suspended"] & st["market_closed"]).any()
    assert (st["suspended"] == (~st["market_closed"] & st["close_adj"].isna())).all()
    assert not DAILY.loc[DAILY["type"] != "stock", "suspended"].any()
    assert (st.loc[st["first_trade_after_halt"], "halt_days_before"] > 0).all()
    assert (st.loc[st["traded"], "close_adj"] > 0).all()


# ----------------------------- monthly panel ----------------------------- #
@pytest.mark.parametrize("code", sorted(MONTHLY["code"].unique()))
def test_monthly_has_36_return_months_per_series(code):
    s = MONTHLY[MONTHLY["code"] == code]
    got = s.loc[s["return_nominal"].notna(), "month_jalali"].tolist()
    assert got == RETURN_MONTHS, f"{code}: return months {got[:3]}...{got[-3:]} ({len(got)})"
    assert s.loc[s["return_real"].notna(), "month_jalali"].tolist() == RETURN_MONTHS
    base = s[s["month_jalali"] == pdx.BASE_MONTH]
    assert len(base) == 1 and base["growth_nominal"].iloc[0] == pytest.approx(100)


def test_expected_series_present():
    m = MONTHLY.drop_duplicates("code")
    assert (m["type"] == "stock").sum() == 8
    assert set(m.loc[m["type"] == "market_index", "symbol"]) == {"شاخص کل", "شاخص کل (هم وزن)"}
    assert (m["type"] == "sector_index").sum() == 7
    assert (m["type"] == "cpi").sum() == 1


def test_real_return_formula_hand_example():
    # nominal +10%, inflation +4%  ->  1.10 / 1.04 - 1 = 0.057692...
    assert pdx.real_return(0.10, 0.04) == pytest.approx(0.0576923077, abs=1e-10)
    # nominal -5%, inflation +3%  ->  0.95 / 1.03 - 1 = -0.077669...
    assert pdx.real_return(-0.05, 0.03) == pytest.approx(-0.0776699029, abs=1e-10)
    # matching nominal and inflation -> zero real return
    assert pdx.real_return(0.042434, 0.042434) == pytest.approx(0.0)


def test_real_return_formula_in_panel():
    m = MONTHLY.dropna(subset=["return_real"])
    expect = (1 + m["return_nominal"]) / (1 + m["inflation_monthly"]) - 1
    assert np.allclose(m["return_real"], expect, atol=1e-12)


def test_inflation_is_cpi_ratio():
    c = MONTHLY[MONTHLY["code"] == "cpi"].set_index("month_jalali")
    assert c.loc["1405-06", "inflation_monthly"] == pytest.approx(729.8394 / 700.1304 - 1, abs=1e-6)


def test_cpi_cumulative_growth_matches_raw_cpi():
    cpi = dq.cpi_frame().set_index("jalali_month")["cpi_index"]
    expected = 729.8394 / cpi.loc["1402-06"]
    c = MONTHLY[MONTHLY["code"] == "cpi"].set_index("month_jalali")
    assert c.loc["1405-06", "growth_nominal"] / 100 == pytest.approx(expected, rel=1e-9)
    # the same via the product of monthly inflation
    prod = (1 + c.loc["1402-07":"1405-06", "inflation_monthly"]).prod()
    assert prod == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("code", sorted(MONTHLY["code"].unique()))
def test_growth_indices_consistent_with_returns(code):
    s = MONTHLY[MONTHLY["code"] == code].sort_values("month_jalali")
    r = s[s["month_jalali"] > pdx.BASE_MONTH]
    assert s["growth_nominal"].iloc[-1] == pytest.approx(100 * (1 + r["return_nominal"]).prod(), rel=1e-9)
    assert s["growth_real"].iloc[-1] == pytest.approx(100 * (1 + r["return_real"]).prod(), rel=1e-9)


def test_month_end_close_matches_daily():
    """close_adj_eom is the last available daily close up to that month end."""
    d = DAILY.dropna(subset=["close_adj"]).assign(m=lambda x: x["date_jalali"].str[:7])
    for code, s in MONTHLY[MONTHLY["type"] != "cpi"].groupby("code"):
        dd = d[d["code"] == code]
        for _, row in s.iterrows():
            last = dd[dd["m"] <= row["month_jalali"]].iloc[-1]
            assert row["close_adj_eom"] == last["close_adj"], (code, row["month_jalali"])
            assert row["close_date_jalali"] == last["date_jalali"]

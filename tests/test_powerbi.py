"""Tests for the Power BI CSV exports (data/processed/powerbi/)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import analysis as an  # noqa: E402

PBI = ROOT / "data" / "processed" / "powerbi"
FACTS = ["monthly_long", "risk_summary", "yearly_real", "closure_summary"]


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(PBI / f"{name}.csv", encoding="utf-8")


def code_col(df: pd.DataFrame) -> str:
    return "series_code" if "series_code" in df.columns else "code"


@pytest.fixture(scope="module")
def res():
    return an.run_all(write=False)


# ------------------------------ dimensions ------------------------------- #
def test_dim_series_keys_and_types():
    d = load("dim_series")
    assert d["series_code"].is_unique and d["series_fa"].is_unique
    assert set(d["type"]) == {"stock", "market_index", "sector_index", "portfolio", "cpi"}
    assert (d["type"] == "stock").sum() == 8 and (d["type"] == "sector_index").sum() == 7
    assert list(d["sort_order"]) == list(range(1, len(d) + 1))
    assert d.loc[d["type"] == "sector_index", "series_fa"].str.startswith("شاخص صنعت").all()


@pytest.mark.parametrize("fact", FACTS)
def test_every_fact_key_is_in_dim_series(fact):
    f = load(fact)
    missing = set(f[code_col(f)]) - set(load("dim_series")["series_code"])
    assert not missing, f"{fact}: codes not in dim_series: {missing}"


def test_dim_month_complete_and_sortable():
    d = load("dim_month")
    assert list(d["month"]) == an.month_range("1402-06", "1405-06")
    assert d["sort_key"].is_monotonic_increasing and d["sort_key"].is_unique
    assert d["month_label_fa"].is_unique
    assert d.loc[d["month"] == "1402-07", "month_label_fa"].iloc[0] == "مهر ۱۴۰۲"
    dates = pd.to_datetime(d["month_end_gregorian"])
    assert dates.is_monotonic_increasing
    assert d.loc[d["month"] == "1405-06", "month_end_gregorian"].iloc[0] == "2026-09-22"  # 31 Shahrivar 1405
    assert set(load("monthly_long")["month"]) <= set(d["month"])


# ------------------------- rolling 12-month column ------------------------ #
def test_rolling_12m_blank_for_first_11_months():
    m = load("monthly_long")
    for code, g in m.groupby("series_code"):
        g = g.sort_values("month")
        blank = g.loc[g["real_return_rolling_12m"].isna(), "month"].tolist()
        assert blank == an.month_range("1402-06", "1403-05"), code   # base month + 11 months
        assert g["real_return_rolling_12m"].notna().sum() == 25, code


def test_rolling_12m_matches_analysis_and_hand_product(res):
    m = load("monthly_long").set_index(["series_code", "month"])
    roll = res["rolling"]
    for code in an.MARKET_CODES:
        got = m.loc[code, "real_return_rolling_12m"].dropna()
        assert np.allclose(got.values, roll[code].reindex(got.index).values)
    g = m.loc["fameli"].sort_index()
    window = g.loc["1404-07":"1405-06", "real_return_per_month"]
    assert len(window) == 12
    assert g.loc["1405-06", "real_return_rolling_12m"] == pytest.approx((1 + window).prod() - 1)


# ---------------------------- closure summary ---------------------------- #
def test_closure_summary_matches_analysis(res):
    c = load("closure_summary").set_index(["series_code", "window"])
    t = res["closure"]["table"].set_index("code")
    assert set(c.index.get_level_values("window")) == {"on_reopening", "after_20_days"}
    assert len(c) == 2 * len(t)
    for code, r in t.iterrows():
        for w, sfx in (("on_reopening", "reopen"), ("after_20_days", "20d")):
            row = c.loc[(code, w)]
            assert row["nominal"] == pytest.approx(r[f"nominal_change_{sfx}"])
            assert row["cpi_prorated"] == pytest.approx(r[f"cpi_change_{sfx}_prorated"])
            assert row["cpi_whole_months"] == pytest.approx(r[f"cpi_change_{sfx}_monthly"])
            if r["comparable"]:
                assert row["real_prorated"] == pytest.approx(
                    (1 + row["nominal"]) / (1 + row["cpi_prorated"]) - 1)
            else:
                assert pd.isna(row["real_prorated"]) and not row["comparable"]
    assert c.loc[("index_total", "on_reopening"), "real_prorated"] == pytest.approx(-0.1564, abs=5e-5)


# -------------------------------- context -------------------------------- #
def test_context_single_row_matches_analysis(res):
    c = load("context")
    rf = res["risk_free"]
    assert len(c) == 1
    r = c.iloc[0]
    assert r["bond_ytm"] == pytest.approx(rf["ytm_median"])
    assert r["real_yield_avg"] == pytest.approx((1 + r["bond_ytm"]) / (1 + r["inflation_12m_avg"]) - 1)
    assert r["real_yield_p2p"] == pytest.approx((1 + r["bond_ytm"]) / (1 + r["inflation_point_to_point"]) - 1)
    assert r["snapshot_date"] == "1405-07-22" and r["source_url"].startswith("https://ifb.ir")


def test_numbers_unchanged_by_export(res):
    """The exported risk table is the analysis table, unchanged."""
    rs = load("risk_summary").set_index("code")
    rt = res["risk"].set_index("code")
    for col in ["real_cagr", "nominal_cagr", "real_cum_3y", "real_vol_per_year"]:
        assert np.allclose(rs.loc[rt.index, col], rt[col])
    assert rs.loc["index_total", "real_cum_3y"] == pytest.approx(-0.066, abs=5e-4)


def test_correlation_long_ten_series_matches_analysis(res):
    c = load("correlation_long")
    assert len(c) == 100
    assert set(c["series_a_code"]) == set(an.STOCK_CODES + an.MARKET_CODES)
    assert c["series_a_fa"].notna().all() and c["series_a_order"].notna().all()
    piv = c.pivot(index="series_a", columns="series_b", values="corr_real_return_per_month")
    nine = res["corr"]                       # the notebook's 9 x 9 matrix
    assert np.allclose(piv.loc[nine.index, nine.columns].values, nine.values)
    assert np.allclose(np.diag(piv.values), 1.0)

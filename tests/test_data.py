"""Tests on the raw data (step 1). Run:  pytest -q

Known source-data errors are listed in config/settings.yaml (quality.known_issues).
A test only tolerates exactly those documented cells; anything new fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import data_quality as dq  # noqa: E402

META = dq.load_metadata()
CFG = dq.load_settings()
Q = CFG["quality"]
KNOWN = Q.get("known_issues", [])
CLOSED = set(dq.market_closed_days(META))

PRICE_FILES = {f: i for f, i in META["files"].items() if i["kind"] != "price_adjustments"}
STOCK_ADJ = {f: i for f, i in META["files"].items() if i["kind"] == "stock_adjusted"}
INDEX_FILES = {f: i for f, i in META["files"].items() if i["kind"] in ("index", "sector_index")}


def known_dates(file: str, column: str | None = None) -> set[str]:
    return {d for k in KNOWN if k["file"] == file and (column is None or k["column"] == column)
            for d in k["dates"]}


@pytest.fixture(scope="module", params=sorted(PRICE_FILES), ids=lambda f: Path(f).stem)
def price_file(request):
    return request.param, dq.read_raw(request.param)


# --------------------------------------------------------------------------- #
def test_metadata_matches_files():
    for f, info in META["files"].items():
        assert (ROOT / f).exists(), f
        assert len(pd.read_csv(ROOT / f)) == info["rows"], f
    req = [b["name"] for b in CFG["benchmarks"] if b.get("required", True)]
    failed = {x["item"] for x in META["failures"]}
    assert not set(req) & failed, f"required benchmark failed: {set(req) & failed}"


def test_no_duplicate_dates(price_file):
    f, df = price_file
    assert not df["Date"].duplicated().any(), f"{f}: duplicate Gregorian dates"
    assert not df["J-Date"].duplicated().any(), f"{f}: duplicate Jalali dates"
    assert df["Date"].is_monotonic_increasing, f"{f}: dates not sorted"


def test_jalali_matches_gregorian(price_file):
    f, df = price_file
    assert dq.jalali_gregorian_mismatches(df) == 0, f


def test_prices_positive(price_file):
    """Close/Final must be > 0 everywhere. Open/High/Low must be > 0 except
    (a) on market-closed days in index files (nothing traded, TSETMC stores 0) and
    (b) cells documented in quality.known_issues."""
    f, df = price_file
    is_index = PRICE_FILES[f]["kind"] in ("index", "sector_index")
    for c in ("Close", "Final", "Adj Close"):
        if c in df.columns:
            bad = df.loc[df[c] <= 0, "J-Date"].tolist()
            assert not bad, f"{f}: {c} <= 0 on {bad}"
    for c in ("Open", "High", "Low"):
        if c not in df.columns:
            continue
        bad = set(df.loc[df[c] <= 0, "J-Date"])
        allowed = known_dates(f, c) | (CLOSED if is_index else set())
        assert bad <= allowed, f"{f}: {c} <= 0 on undocumented dates {sorted(bad - allowed)}"


def _jumps(df: pd.DataFrame, col: str, limit: float) -> pd.DataFrame:
    r = df[col] / df[col].shift(1) - 1
    return pd.DataFrame({"date": df["J-Date"], "prev": df["J-Date"].shift(1), "ret": r})[r.abs() > limit]


@pytest.mark.parametrize("f", sorted(STOCK_ADJ), ids=lambda f: Path(f).stem)
@pytest.mark.parametrize("col", ["Close", "Final"])
def test_adjusted_stock_no_unexplained_jump(f, col):
    """No one-day move > max_unexplained_jump (50%) in adjusted prices.
    Corporate actions are already removed by the adjustment, so any such jump is
    a data problem unless documented in quality.known_issues."""
    df = dq.read_raw(f)
    j = _jumps(df, col, Q["max_unexplained_jump"])
    doc = known_dates(f)
    j = j[~(j["date"].isin(doc) | j["prev"].isin(doc))]
    assert j.empty, f"{f} {col}: unexplained jumps\n{j.to_string()}"


@pytest.mark.parametrize("f", sorted(INDEX_FILES), ids=lambda f: Path(f).stem)
def test_index_no_unexplained_jump(f):
    df = dq.read_raw(f)
    j = _jumps(df, "Close", Q["max_unexplained_jump"])
    doc = known_dates(f, "Close")
    j = j[~(j["date"].isin(doc) | j["prev"].isin(doc))]
    assert j.empty, f"{f}: unexplained jumps\n{j.to_string()}"


@pytest.mark.parametrize("sym", sorted(dq.stock_pairs(META)))
def test_adjusted_and_unadjusted_align(sym):
    p = dq.stock_pairs(META)[sym]
    a, u = dq.read_raw(p["adjusted"]), dq.read_raw(p["unadjusted"])
    assert a["Date"].equals(u["Date"]), sym
    # adjustment is anchored at the last date: ratio there must be 1
    assert abs(a["Final"].iloc[-1] / u["Final"].iloc[-1] - 1) < 1e-3, sym
    # unadjusted file's own 'Adj Close' equals the adjusted file's Close
    assert (a["Close"] - u["Adj Close"]).abs().max() <= 1, sym


def test_price_window_covers_period():
    start, end = CFG["period"]["start"], CFG["period"]["end"]
    for f, i in PRICE_FILES.items():
        assert i["first_date_jalali"] < start, f"{f}: no base price before {start}"
        assert i["last_date_jalali"] <= end, f
    idx_last = max(i["last_date_jalali"] for i in INDEX_FILES.values())
    assert idx_last >= end[:7], "index data does not reach the last month of the period"


# ------------------------------- CPI ------------------------------------- #
def test_cpi_months_consecutive():
    cpi = dq.cpi_frame()
    months = cpi["jalali_month"].tolist()
    assert months[0] == CFG["cpi"]["first_month"] and months[-1] == CFG["cpi"]["last_month"]
    for a, b in zip(months, months[1:]):
        assert dq.next_month(a) == b, f"CPI gap or disorder between {a} and {b}"
    assert len(set(months)) == len(months), "duplicate CPI months"


def test_cpi_complete_and_sci_only():
    cpi = dq.cpi_frame()
    missing = cpi.loc[cpi["cpi_index"].isna(), "jalali_month"].tolist()
    assert not missing, f"CPI months to fill by hand: {missing}"
    assert cpi["source_url"].str.contains("amar.org.ir").all(), "non-SCI source in CPI file"


@pytest.mark.parametrize("month,value", sorted(CFG["cpi"]["known_values"].items()))
def test_cpi_known_values(month, value):
    cpi = dq.cpi_frame().set_index("jalali_month")
    assert round(float(cpi.loc[month, "cpi_index"]), 1) == pytest.approx(value, abs=0.051)

"""Snapshot of Iranian debt-security yields from the IFB YTM page (via algotik-tse).

Used only as risk-free *context* in the analysis. Treasury bills (اخزا) do not appear on
the IFB YTM page, so the closest available government instrument is used: government
Murabaha bonds (اراد, DebtType 'erad').

Output: data/external/ifb_debt_yields_<Jalali date>.csv (the full table, unchanged)
Usage:  python src/fetch_bond_yields.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import algotik_tse as att

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "data" / "external"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    y = att.get_debt_yields()
    if y is None or y.empty:
        print("no data returned")
        return 1
    fetched = y.attrs.get("fetched_at")
    from persiantools.jdatetime import JalaliDate
    jd = JalaliDate(fetched.date()).strftime("%Y%m%d") if fetched is not None else "unknown"
    y = y.assign(fetched_at=str(fetched), reference_url=y.attrs.get("reference_url"))
    out = EXT / f"ifb_debt_yields_{jd}.csv"
    y.to_csv(out, index=False, encoding="utf-8")
    print(f"wrote {out} ({len(y)} rows), source {y.attrs.get('reference_url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Fetch Iran's monthly CPI (whole country, all households, base 1400=100)
from the Statistical Centre of Iran (SCI, amar.org.ir).

Source: the SCI "prices" page (https://amar.org.ir/prices) publishes the time-series
workbook "شاخص قیمت مصرف کننده کل خانوارهای کشور" (ts_national_YYMMDD-<upload stamp>.xlsx).
  * sheet "جدول 1": CPI by month and main group, base 1400=100
  * sheet "جدول 2": monthly % change of CPI by month and main group
Only the overall row "شاخص کل" is used. No Central Bank (CBI) figures are used.

Output: data/external/cpi_iran_sci.csv with columns
  jalali_month, cpi_index, monthly_inflation_pct, source_url, published_date, status, note
Months that cannot be read are kept as rows with empty values and status=MISSING
so they can be filled by hand. The downloaded workbook is kept in
data/external/source/ for provenance.

Usage:  python src/fetch_cpi.py
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path

import openpyxl
import pandas as pd
import requests
import yaml

# amar.org.ir does not send its intermediate certificate; the OS trust store
# (which can fetch it) verifies the chain where certifi alone cannot.
# TLS verification stays ON.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "data" / "external"
SRC_DIR = EXT / "source"
CONFIG = ROOT / "config" / "settings.yaml"
PRICES_PAGE = "https://amar.org.ir/prices"
BASE = "https://amar.org.ir"
UA = {"User-Agent": "Mozilla/5.0 (research; tse-inflation-analysis)"}

MONTHS_FA = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
             "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]

log = logging.getLogger("cpi")


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s).replace("ي", "ی").replace("ك", "ک")
                  .replace("‌", " ")).strip()


def get(url: str, retries: int = 5, backoff: float = 2.0, timeout: int = 120) -> requests.Response:
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=UA, timeout=timeout)
            log.info("GET %s -> %s (%d bytes)", url, r.status_code, len(r.content))
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            log.warning("GET %s failed (attempt %d/%d): %s", url, attempt, retries, exc)
            if attempt == retries:
                raise
            time.sleep(backoff * 2 ** (attempt - 1))
    raise RuntimeError("unreachable")


def find_workbook_url() -> tuple[str, str | None]:
    """Return (workbook URL, upload date 'YYYY-MM-DD' Jalali or None)."""
    html = get(PRICES_PAGE).text
    links = sorted(set(re.findall(r'href="(/Portals/0/Statistics/ts_national_[^"]+\.xlsx)"', html)))
    if not links:
        raise RuntimeError("no ts_national_*.xlsx link found on " + PRICES_PAGE)
    # ts_national_140506-14050719122615.xlsx -> data through 1405-06, uploaded 1405-07-19
    def key(link):
        m = re.search(r"ts_national_(\d{6})", link)
        return m.group(1) if m else ""
    link = max(links, key=key)
    m = re.search(r"-(\d{4})(\d{2})(\d{2})\d{6}\.xlsx$", link)
    uploaded = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
    log.info("national CPI workbook links found: %s; using %s", links, link)
    return BASE + link, uploaded


def read_monthly_table(ws) -> dict[str, float]:
    """Parse a month x group sheet. Returns {'YYYY-MM': value} for the 'شاخص کل' row."""
    rows = list(ws.iter_rows(values_only=True))
    year_row = month_row = total_row = None
    for i, row in enumerate(rows[:10]):
        if any(isinstance(v, (int, float)) and 1380 < v < 1500 for v in row[1:]):
            year_row = i
            month_row = i + 1
            break
    for row in rows:
        if row and row[0] is not None and _norm(row[0]) == "شاخص کل":
            total_row = row
            break
    if year_row is None or total_row is None:
        raise RuntimeError(f"could not find year header or 'شاخص کل' row in sheet {ws.title}")
    years, months = rows[year_row], rows[month_row]
    out: dict[str, float] = {}
    year = None
    for col in range(1, len(total_row)):
        if col < len(years) and isinstance(years[col], (int, float)):
            year = int(years[col])
        mname = _norm(months[col]) if col < len(months) and months[col] else None
        if year is None or mname not in MONTHS_FA:
            continue
        val = total_row[col]
        if isinstance(val, (int, float)):
            out[f"{year}-{MONTHS_FA.index(mname) + 1:02d}"] = float(val)
    return out


def month_range(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    ly, lm = map(int, last.split("-"))
    out = []
    while (y, m) <= (ly, lm):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    EXT.mkdir(parents=True, exist_ok=True)
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(EXT / "fetch_cpi.log", "w", encoding="utf-8")])
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["cpi"]
    months = month_range(cfg["first_month"], cfg["last_month"])

    cpi: dict[str, float] = {}
    mom: dict[str, float] = {}
    url = published = None
    error = None
    try:
        url, published = find_workbook_url()
        content = get(url).content
        local = SRC_DIR / url.rsplit("/", 1)[-1]
        local.write_bytes(content)
        wb = openpyxl.load_workbook(local, read_only=True, data_only=True)
        cpi = read_monthly_table(wb["جدول 1"])
        mom = read_monthly_table(wb["جدول 2"])
        log.info("parsed %d CPI months (%s .. %s)", len(cpi), min(cpi), max(cpi))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log.error("could not fetch/parse SCI workbook: %s", error)

    rows = []
    for jm in months:
        if jm in cpi:
            rows.append({"jalali_month": jm, "cpi_index": round(cpi[jm], 4),
                         "monthly_inflation_pct": round(mom[jm], 4) if jm in mom else None,
                         "source_url": url, "published_date": published, "status": "OK",
                         "note": "SCI ts_national workbook, sheet جدول 1 / جدول 2, row شاخص کل"})
        else:
            rows.append({"jalali_month": jm, "cpi_index": None, "monthly_inflation_pct": None,
                         "source_url": None, "published_date": None, "status": "MISSING",
                         "note": "fill by hand from amar.org.ir" + (f" ({error})" if error else "")})
    df = pd.DataFrame(rows)
    df.to_csv(EXT / "cpi_iran_sci.csv", index=False, encoding="utf-8")
    log.info("wrote %s: %d rows, %d missing", EXT / "cpi_iran_sci.csv", len(df),
             (df["status"] == "MISSING").sum())

    for jm, known in cfg["known_values"].items():
        got = cpi.get(jm)
        ok = got is not None and abs(round(got, 1) - known) < 0.051
        log.info("check %s: known %.1f, fetched %s -> %s", jm, known,
                 "n/a" if got is None else f"{got:.4f}", "OK" if ok else "MISMATCH")
    return 0 if error is None else 1


if __name__ == "__main__":
    sys.exit(main())

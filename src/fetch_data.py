"""Download raw daily price data for the TSE-vs-inflation project.

STEP 1 only: fetch and store raw data. No cleaning, no analysis.

For every symbol in config/settings.yaml:
  * daily history with auto_adjust=True and with auto_adjust=False
  * TSETMC's own price-adjustment event table (used later to explain jumps)
For the overall index, the equal-weight index and every sector index:
  * daily history

Every DataFrame returned by algotik-tse is saved unchanged (the Date index is
written as a column) to data/raw/ as UTF-8 CSV. data/raw/metadata.json records
what was downloaded, when, how, and what failed. Every HTTP request is logged
to data/raw/fetch.log.

Usage:  python src/fetch_data.py
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import platform
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import yaml

import algotik_tse as att

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CONFIG = ROOT / "config" / "settings.yaml"
LOG_FILE = RAW / "fetch.log"

log = logging.getLogger("fetch")


# --------------------------------------------------------------------------- #
# Logging, including one line per HTTP request made by the library
# --------------------------------------------------------------------------- #
def setup_logging() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    root.addHandler(sh)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    http_log = logging.getLogger("http")
    original_send = requests.Session.send

    def logged_send(self, request, **kwargs):
        t0 = time.perf_counter()
        try:
            resp = original_send(self, request, **kwargs)
        except Exception as exc:
            http_log.warning("%s %s -> EXCEPTION %s: %s", request.method,
                             request.url, type(exc).__name__, exc)
            raise
        http_log.info("%s %s -> %s (%d bytes, %.2fs)", request.method, request.url,
                      resp.status_code, len(resp.content or b""),
                      time.perf_counter() - t0)
        return resp

    requests.Session.send = logged_send


# --------------------------------------------------------------------------- #
# Retry with exponential backoff
# --------------------------------------------------------------------------- #
class EmptyResult(RuntimeError):
    pass


NON_TRANSIENT = (att.StockNotFoundError, att.AmbiguousSymbolError, att.InvalidParameterError)


def with_retry(fn, call_repr: str, max_retries: int, backoff: float, allow_empty=False):
    """Call fn(); retry on exceptions and on None/empty results.

    algotik-tse catches network errors internally and returns None, so an
    empty result is treated as a retryable failure unless allow_empty.
    """
    last_exc = None
    for attempt in range(1, max_retries + 1):
        log.info("CALL attempt %d/%d: %s", attempt, max_retries, call_repr)
        try:
            out = fn()
            if out is None or (isinstance(out, pd.DataFrame) and out.empty and not allow_empty):
                raise EmptyResult("empty result (library returned None or no rows)")
            return out
        except NON_TRANSIENT:
            raise  # a wrong name will not fix itself by retrying
        except Exception as exc:
            last_exc = exc
            wait = backoff * 2 ** (attempt - 1)
            log.warning("  failed (%s: %s)", type(exc).__name__, exc)
            if attempt < max_retries:
                log.warning("  retrying in %.0fs", wait)
                time.sleep(wait)
    raise RuntimeError(f"giving up after {max_retries} attempts: {call_repr}") from last_exc


# --------------------------------------------------------------------------- #
# Name resolution with search fallback
# --------------------------------------------------------------------------- #
def _norm(text: str) -> str:
    text = str(text).replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
    text = re.sub(r"[()\-_،,]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> set[str]:
    """Word set; plural suffixes written apart ('بانک ها') are re-attached."""
    out: list[str] = []
    for t in _norm(text).split():
        if t in ("ها", "های") and out:
            out[-1] += t
        elif t != "و":
            out.append(t)
    return set(out)


def _compact(text: str) -> str:
    return _norm(text).replace(" ", "")


def search_candidates(name: str, kind: str) -> list[dict]:
    """Search the library's registries for names similar to `name`.

    kind 'industry': att.list_industry_indices() plus the library's alias table.
    kind 'index':    att.list_indices().
    kind 'stock':    att.get_symbols().
    Returns up to 8 candidates, best first, with the exact library name,
    TSETMC InsCode and a similarity score in [0, 1].
    """
    rows: list[tuple[str, str]] = []
    if kind == "industry":
        tbl = att.list_industry_indices(progress=False)
        rows += [(str(r.IndustryName), str(r.IndexInsCode)) for r in tbl.itertuples()]
        try:
            from algotik_tse.core.search import _INDUSTRY_RAW
            rows += [(a, c) for c, aliases in _INDUSTRY_RAW.items() for a in aliases]
        except Exception:
            pass
    elif kind == "index":
        tbl = att.list_indices(progress=False)
        rows += [(str(r.Name), str(r.InsCode)) for r in tbl.itertuples()]
    else:
        tbl = att.get_symbols()
        names = tbl["Ticker"] if "Ticker" in tbl.columns else tbl.index
        rows += [(str(x), "") for x in names]

    want_t, want_c = _tokens(name), _compact(name)
    scored: dict[str, dict] = {}
    for exact, code in rows:
        t = _tokens(exact)
        if _compact(exact) == want_c:
            score = 1.0
        elif t and want_t:
            # mean of Jaccard similarity and the share of the candidate's
            # words that appear in the requested name
            common = len(t & want_t)
            score = 0.5 * (common / len(t | want_t) + common / len(t))
        else:
            score = 0.0
        if score > 0 and (exact not in scored or scored[exact]["score"] < score):
            scored[exact] = {"name": exact, "ins_code": code, "score": round(score, 3)}
    return sorted(scored.values(), key=lambda d: -d["score"])[:8]


def resolve(name: str, kind: str, report: dict) -> tuple[str | None, str | None]:
    """Return (name_to_use, ins_code), or (None, None). Records details in report."""
    asset_type = "industry" if kind == "industry" else "auto"
    report["requested_name"] = name
    try:
        ref = att.resolve_instrument(name, asset_type=asset_type)
        report.update(used_name=name, ins_code=ref.ins_code, tsetmc_name=ref.name,
                      resolution="exact")
        return name, ref.ins_code
    except Exception as exc:
        log.warning("Name %r (%s) did not resolve: %s: %s", name, kind, type(exc).__name__, exc)
        report["resolution_error"] = f"{type(exc).__name__}: {exc}"

    try:
        cands = search_candidates(name, kind)
    except Exception as exc:
        log.error("Search for %r failed: %s", name, exc)
        cands = []
    report["search_candidates"] = cands
    log.warning("Search candidates for %r: %s", name,
                [(c["name"], c["ins_code"], c["score"]) for c in cands])

    # Accept only a clear winner: every top-scoring candidate points to one InsCode.
    if cands:
        best = cands[0]["score"]
        top = [c for c in cands if c["score"] == best]
        if best >= 0.5 and len({c["ins_code"] for c in top}) == 1:
            # Try the candidate names first, then the InsCode, and keep the first
            # selector that resolves back to the same InsCode.
            selectors = [c["name"] for c in top] + [top[0]["ins_code"]]
            for sel in selectors:
                if not sel:
                    continue
                try:
                    ref = att.resolve_instrument(sel, asset_type=asset_type)
                except Exception as exc:
                    log.info("  candidate %r did not resolve: %s", sel, exc)
                    continue
                if top[0]["ins_code"] and ref.ins_code != top[0]["ins_code"]:
                    continue
                used = sel if not sel.isdigit() else ref.symbol
                try:  # the name we pass to get_history must resolve on its own
                    att.resolve_instrument(used, asset_type=asset_type)
                except Exception:
                    used = sel
                report.update(used_name=used, ins_code=ref.ins_code, tsetmc_name=ref.name,
                              tsetmc_symbol=ref.symbol, resolution="search_fallback")
                log.warning("Using search result %r (InsCode %s) for %r",
                            used, ref.ins_code, name)
                return used, ref.ins_code
    report["resolution"] = "failed"
    return None, None


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #
def save_raw(df: pd.DataFrame, path: Path) -> dict:
    out = df.reset_index()  # the library's Gregorian Date index becomes a column
    out.to_csv(path, index=False, encoding="utf-8")
    info = {"file": path.relative_to(ROOT).as_posix(), "rows": int(len(out)),
            "columns": [str(c) for c in out.columns]}
    if len(out):
        if "J-Date" in out.columns:
            info["first_date_jalali"] = str(out["J-Date"].iloc[0])
            info["last_date_jalali"] = str(out["J-Date"].iloc[-1])
        if "Date" in out.columns:
            info["first_date_gregorian"] = str(pd.Timestamp(out["Date"].iloc[0]).date())
            info["last_date_gregorian"] = str(pd.Timestamp(out["Date"].iloc[-1]).date())
    log.info("saved %s (%d rows)", info["file"], info["rows"])
    return info


def history_call(name: str, start: str, end: str, auto_adjust: bool):
    kwargs = dict(start=start, end=end, auto_adjust=auto_adjust, output_type="full",
                  date_format="both", progress=False)
    rep = "algotik_tse.get_history({!r}, {})".format(
        name, ", ".join(f"{k}={v!r}" for k, v in kwargs.items()))
    return (lambda: att.get_history(name, **kwargs)), rep


# --------------------------------------------------------------------------- #
def main() -> int:
    setup_logging()
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    fcfg = cfg["fetch"]
    att.settings.timeout = fcfg["timeout_seconds"]
    att.settings.rate_limit_delay = fcfg["rate_limit_delay_seconds"]
    retries, backoff = fcfg["max_retries"], fcfg["backoff_base_seconds"]
    start, end = cfg["period"]["fetch_start"], cfg["period"]["end"]

    started = dt.datetime.now(dt.timezone.utc)
    tehran = dt.timezone(dt.timedelta(hours=3, minutes=30))
    meta: dict = {
        "download_started_utc": started.isoformat(timespec="seconds"),
        "download_started_tehran": started.astimezone(tehran).isoformat(timespec="seconds"),
        "library": {"name": "algotik-tse", "import_name": "algotik_tse",
                    "version": getattr(att, "__version__", "unknown")},
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "period": cfg["period"],
        "symbols": [s["symbol"] for s in cfg["symbols"]],
        "notes": [
            "CSV files are the DataFrames returned by algotik-tse, unchanged; the "
            "Gregorian 'Date' index is written as the first column.",
            "Close = last trade price (<LAST>); Final = official closing price "
            "(<CLOSE>, qeymat-e payani); mapping per algotik_tse/core/stock.py.",
            "auto_adjust=True back-adjusts OHLC/Close/Final by the cumulative product "
            "of (next day's yesterday-price / today's Final), computed only from "
            "events inside the requested window, and truncates prices to int.",
            "Prices are fetched from period.fetch_start, one month before the "
            "analysis start, so the base price at the end of 1402-06 is available.",
        ],
        "symbol_resolution": {},
        "index_resolution": {},
        "files": {},
        "failures": [],
    }

    # ---------------- stocks ----------------
    for s in cfg["symbols"]:
        sym, code = s["symbol"], s["code"]
        rep: dict = {}
        used, ins = resolve(sym, "stock", rep)
        meta["symbol_resolution"][sym] = rep
        if used is None:
            meta["failures"].append({"item": sym, "kind": "stock", "error": "name not resolved",
                                     "candidates": rep.get("search_candidates")})
            continue
        for adj, tag in ((True, "adjusted"), (False, "unadjusted")):
            fn, call = history_call(used, start, end, adj)
            try:
                df = with_retry(fn, call, retries, backoff)
                info = save_raw(df, RAW / f"stock_{code}_{tag}.csv")
                info.update(call=call, symbol=sym, ins_code=ins, kind=f"stock_{tag}")
                meta["files"][info["file"]] = info
            except Exception as exc:
                log.error("FAILED %s: %s", call, exc)
                meta["failures"].append({"item": sym, "kind": f"stock_{tag}", "call": call,
                                         "error": f"{type(exc).__name__}: {exc}"})
        # TSETMC's own price-adjustment events (capital increases / dividend gaps)
        call = (f"algotik_tse.get_price_adjustments({used!r}, start={start!r}, "
                f"end={end!r}, progress=False)")
        try:
            df = with_retry(lambda: att.get_price_adjustments(used, start=start, end=end,
                                                              progress=False),
                            call, retries, backoff, allow_empty=True)
            info = save_raw(df, RAW / f"adjustments_{code}.csv")
            info.update(call=call, symbol=sym, ins_code=ins, kind="price_adjustments")
            meta["files"][info["file"]] = info
        except Exception as exc:
            log.error("FAILED %s: %s", call, exc)
            meta["failures"].append({"item": sym, "kind": "price_adjustments", "call": call,
                                     "error": f"{type(exc).__name__}: {exc}"})

    # ---------------- indices ----------------
    jobs = [(b["name"], b["code"], "index", b.get("required", True)) for b in cfg["benchmarks"]]
    seen: set[str] = set()
    for s in cfg["symbols"]:
        name = s.get("sector_index_tse") or s["sector_index"]
        if name not in seen:
            seen.add(name)
            jobs.append((name, f"sector_of_{s['code']}", "industry", True))

    index_files: dict[str, str] = {}
    for name, code, kind, required in jobs:
        rep = {}
        used, ins = resolve(name, kind, rep)
        meta["index_resolution"][name] = rep
        if used is None:
            meta["failures"].append({"item": name, "kind": kind, "required": required,
                                     "error": "name not resolved",
                                     "candidates": rep.get("search_candidates")})
            continue
        fn, call = history_call(used, start, end, True)
        try:
            df = with_retry(fn, call, retries, backoff)
            info = save_raw(df, RAW / f"{code}.csv")
            info.update(call=call, index_name=name, used_name=used, ins_code=ins,
                        kind="index" if kind == "index" else "sector_index")
            meta["files"][info["file"]] = info
            index_files[name] = info["file"]
        except Exception as exc:
            log.error("FAILED %s: %s", call, exc)
            meta["failures"].append({"item": name, "kind": kind, "call": call,
                                     "error": f"{type(exc).__name__}: {exc}"})

    meta["symbol_to_sector_index_file"] = {
        s["symbol"]: index_files.get(s.get("sector_index_tse") or s["sector_index"])
        for s in cfg["symbols"]}
    meta["download_finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    (RAW / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    log.info("metadata written: %d files, %d failures", len(meta["files"]), len(meta["failures"]))
    return 0 if not meta["failures"] else 1


if __name__ == "__main__":
    sys.exit(main())

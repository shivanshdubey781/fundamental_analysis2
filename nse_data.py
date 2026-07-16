"""
nse_data.py — NSE Bhavcopy (Delivery %) + F&O OI data fetcher.

Delivery % approach:
  1. Try NSE deliveryData API (requires cookie session — fast but can fail)
  2. Fallback: Download the public CM Bhavcopy ZIP from NSE archives
     (no login required, always works after 6:30 PM on trading days)

F&O OI: Uses NSE option-chain API with cookie session.
"""

from __future__ import annotations

import io
import logging
import time
import zipfile
from datetime import date, timedelta
from typing import Optional

import requests

log = logging.getLogger(__name__)

_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         "https://www.nseindia.com/",
    "Connection":      "keep-alive",
}

_SESSION_CACHE: Optional[requests.Session] = None
_SESSION_TS: float = 0.0
_SESSION_TTL: float = 300.0   # refresh session every 5 min

# In-memory bhavcopy cache  {date_str: {SYMBOL: delivery_pct}}
_BHAVCOPY_CACHE: dict[str, dict[str, float]] = {}


# ── Session management ────────────────────────────────────────────────────────

def _get_session() -> requests.Session:
    global _SESSION_CACHE, _SESSION_TS
    now = time.time()
    if _SESSION_CACHE is None or (now - _SESSION_TS) > _SESSION_TTL:
        s = requests.Session()
        s.headers.update(_NSE_HEADERS)
        try:
            # Two-step warm-up: homepage → then set cookies
            s.get("https://www.nseindia.com/", timeout=10)
            time.sleep(0.3)
            s.get("https://www.nseindia.com/market-data/live-equity-market", timeout=10)
            time.sleep(0.2)
        except Exception as exc:
            log.warning("NSE session warm-up failed: %s", exc)
        _SESSION_CACHE = s
        _SESSION_TS = now
    return _SESSION_CACHE


# ── Date helpers ──────────────────────────────────────────────────────────────

def _last_trading_day() -> date:
    """Return last weekday as a date object."""
    d = date.today()
    if d.weekday() == 0:    # Monday → Friday
        d -= timedelta(days=3)
    elif d.weekday() == 6:  # Sunday → Friday
        d -= timedelta(days=2)
    else:
        d -= timedelta(days=1)
    return d


def _date_to_nse_str(d: date) -> str:
    """DD-Mon-YYYY in uppercase e.g. 12-MAY-2026"""
    return d.strftime("%d-%b-%Y").upper()


# ── Bhavcopy CSV fallback ─────────────────────────────────────────────────────

def _fetch_bhavcopy_csv(trade_date: date) -> dict[str, float]:
    """
    Download NSE CM delivery data for a given date and return
    { SYMBOL: delivery_pct }.  Cached in _BHAVCOPY_CACHE per date.

    Tries two NSE archive URLs:
      1. MTO_DDMMYYYY.DAT  (delivery-specific file, primary)
      2. sec_bhavdata_full_DDMMYYYY.csv  (full bhavcopy with delivery col)
    """
    date_key = trade_date.strftime("%Y-%m-%d")
    if date_key in _BHAVCOPY_CACHE:
        return _BHAVCOPY_CACHE[date_key]

    dd   = trade_date.strftime("%d")
    mm   = trade_date.strftime("%m")
    yyyy = trade_date.strftime("%Y")

    result: dict[str, float] = {}

    # ── URL 1: MTO file (DDMMYYYY format) ────────────────────────────────────
    mto_url = (
        f"https://archives.nseindia.com/archives/equities/mto/"
        f"MTO_{dd}{mm}{yyyy}.DAT"
    )
    try:
        resp = requests.get(mto_url, headers=_NSE_HEADERS, timeout=20)
        if resp.status_code == 200:
            # Actual format: RecType, SrNo, Symbol, Series, TradedQty, DeliverableQty, DelivPct%
            # Index:            [0]    [1]    [2]      [3]      [4]           [5]           [6]
            for line in resp.text.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 7 or parts[0] != "20":
                    continue
                symbol = parts[2].strip().upper()
                series = parts[3].strip().upper()
                if series not in ("EQ", "BE", "BZ", "SM", "ST"):
                    continue   # skip debt/bond instruments
                try:
                    result[symbol] = float(parts[6])   # index 6 = delivery %
                except (ValueError, IndexError):
                    pass
            if result:
                _BHAVCOPY_CACHE[date_key] = result
                log.info("MTO loaded %d EQ symbols for %s", len(result), date_key)
                return result
        log.debug("MTO HTTP %s for %s", resp.status_code, mto_url)
    except Exception as exc:
        log.debug("MTO fetch error: %s", exc)

    # ── URL 2: sec_bhavdata_full CSV ─────────────────────────────────────────
    bhav_url = (
        f"https://archives.nseindia.com/products/content/"
        f"sec_bhavdata_full_{dd}{mm}{yyyy}.csv"
    )
    try:
        resp = requests.get(bhav_url, headers=_NSE_HEADERS, timeout=25)
        if resp.status_code == 200:
            import csv as _csv
            reader = _csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                symbol  = (row.get("SYMBOL") or "").strip().upper()
                series  = (row.get("SERIES") or "").strip().upper()
                if series != "EQ" or not symbol:
                    continue
                del_pct_raw = row.get("DELIV_PER") or row.get("% Dly Qt to Traded Qty")
                if del_pct_raw:
                    try:
                        result[symbol] = float(del_pct_raw)
                    except ValueError:
                        pass
            if result:
                _BHAVCOPY_CACHE[date_key] = result
                log.info("sec_bhavdata loaded %d symbols for %s", len(result), date_key)
                return result
        log.debug("sec_bhavdata HTTP %s for %s", resp.status_code, bhav_url)
    except Exception as exc:
        log.debug("sec_bhavdata fetch error: %s", exc)

    _BHAVCOPY_CACHE[date_key] = result   # cache even if empty to avoid repeated failures
    return result


# ── Bhavcopy — Delivery % ─────────────────────────────────────────────────────

def fetch_nse_delivery(ticker: str, trade_date: Optional[str] = None) -> dict:
    """
    Return delivery % data for a ticker.

    Strategy:
      1. Try NSE deliveryData JSON API (fast, requires cookie session)
      2. Fallback: NSE MTO archive CSV (public, no login)

    Args:
        ticker:     NSE symbol (e.g. 'RELIANCE')
        trade_date: 'DD-Mon-YYYY' format; defaults to last trading day

    Returns dict with keys: symbol, delivery_pct, trade_date
    """
    ticker = ticker.strip().upper()
    ltd = _last_trading_day()
    dt_str = trade_date or _date_to_nse_str(ltd)

    # ── Strategy 1: JSON API ─────────────────────────────────────────────────
    try:
        url  = f"https://www.nseindia.com/api/deliveryData?symbol={ticker}&series=EQ&date={dt_str}"
        resp = _get_session().get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, dict):
                entry    = data if "symbol" in data else (data.get("data") or [{}])[0]
                del_pct  = entry.get("deliveryToTradedQty") or entry.get("DELIV_PER")
                if del_pct is None:
                    deliverable = entry.get("deliverableQty") or entry.get("DELIV_QTY")
                    traded      = entry.get("tradedQuantity")  or entry.get("TTL_TRD_QNTY")
                    if deliverable and traded:
                        try:
                            del_pct = round(float(deliverable) / float(traded) * 100, 2)
                        except (TypeError, ZeroDivisionError):
                            del_pct = None
                if del_pct is not None:
                    return {"symbol": ticker, "trade_date": dt_str, "delivery_pct": float(del_pct)}
    except Exception as exc:
        log.debug("NSE delivery API failed for %s: %s", ticker, exc)

    # ── Strategy 2: MTO Archive CSV ──────────────────────────────────────────
    try:
        bhavcopy = _fetch_bhavcopy_csv(ltd)
        if ticker in bhavcopy:
            return {
                "symbol":       ticker,
                "trade_date":   dt_str,
                "delivery_pct": bhavcopy[ticker],
                "source":       "mto_archive",
            }
    except Exception as exc:
        log.debug("Bhavcopy fallback failed for %s: %s", ticker, exc)

    return {"symbol": ticker, "trade_date": dt_str, "delivery_pct": None,
            "error": "Delivery data unavailable"}


# ── F&O OI buildup ────────────────────────────────────────────────────────────

def fetch_nse_oi(ticker: str) -> dict:
    """
    Return a summary of F&O OI buildup for a ticker.

    Uses NSE option-chain API and returns:
      total_call_oi, total_put_oi, pcr (put-call ratio),
      max_call_oi_strike, max_put_oi_strike, oi_signal.
    """
    ticker = ticker.strip().upper()
    url = f"https://www.nseindia.com/api/option-chain-equities?symbol={ticker}"
    try:
        resp = _get_session().get(url, timeout=12)
        resp.raise_for_status()
        payload = resp.json()
        records = payload.get("records", {}).get("data", [])
        if not records:
            return {"error": f"No OI data for {ticker}"}

        call_oi: dict[float, int] = {}
        put_oi:  dict[float, int] = {}

        for rec in records:
            strike = rec.get("strikePrice", 0)
            if "CE" in rec:
                call_oi[strike] = call_oi.get(strike, 0) + (rec["CE"].get("openInterest") or 0)
            if "PE" in rec:
                put_oi[strike]  = put_oi.get(strike, 0)  + (rec["PE"].get("openInterest") or 0)

        total_call = sum(call_oi.values())
        total_put  = sum(put_oi.values())
        pcr = round(total_put / total_call, 3) if total_call else None

        max_call_strike = max(call_oi, key=call_oi.get) if call_oi else None
        max_put_strike  = max(put_oi,  key=put_oi.get)  if put_oi  else None

        if pcr is not None:
            oi_signal = "BULLISH" if pcr >= 1.3 else ("NEUTRAL" if pcr >= 0.8 else "BEARISH")
        else:
            oi_signal = "UNKNOWN"

        return {
            "symbol":             ticker,
            "total_call_oi":      total_call,
            "total_put_oi":       total_put,
            "pcr":                pcr,
            "max_call_oi_strike": max_call_strike,
            "max_put_oi_strike":  max_put_strike,
            "oi_signal":          oi_signal,
        }
    except Exception as exc:
        log.error("NSE OI fetch failed for %s: %s", ticker, exc)
        return {"error": str(exc)}

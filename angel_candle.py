"""
angel_candle.py — Angel One SmartAPI · Historical OHLCV provider
=================================================================

Replaces yfinance as the source for daily OHLCV used in technical
indicator calculations (RSI, EMA, BB, ATR, ADX, Volume).

Architecture
------------
1. On first use, downloads the Angel One NSE instrument master and builds
   a full symbol → token map (~2 000+ NSE equities).  The map is cached
   to data/angel_token_map.json and auto-refreshed every 24 hours so
   symbol failures stay near zero.

2. `get_ohlcv(ticker, days)` fetches daily candles via getCandleData and
   returns a DataFrame identical in schema to scoring_engine.fetch_price_data()
   (columns: open, high, low, close, adjusted_close, volume).

3. `fetch_price_data_angel()` is the drop-in replacement used by
   scoring_engine.  It tries Angel One first; if the token is missing or
   the API call fails, it signals the caller to fall back to yfinance.

Rate limits (Angel One SmartAPI)
---------------------------------
Historical data : 3 req / sec
LTP             : 1 req / sec
We enforce a 0.35 s gap between candle requests (well under 3/sec).

Fundamentals
------------
Angel One has NO fundamentals endpoint.  ROE, ROCE, EPS, D/E continue to
come from yfinance — this module does NOT replace that path.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
_CACHE_DIR            = Path(__file__).parent / "data"
_TOKEN_MAP_PATH       = _CACHE_DIR / "angel_token_map.json"
_TOKEN_MAP_TTL_HOURS  = 24          # refresh instrument master once a day
_CANDLE_INTERVAL      = "ONE_DAY"
_INSTRUMENT_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

# In-memory token-map cache
_token_map: Optional[dict[str, str]] = None
_token_map_ts: float = 0.0

# Rate-limit compliance — Angel One historical: 3 req/sec → wait 0.4 s between calls
_RATE_LIMIT_SLEEP = 0.40

# NSE symbol → Angel One instrument master symbol
# When the NSE ticker differs from the Angel One scrip name, add a mapping here.
# This is the Angel One equivalent of the yfinance YF_ALIAS_MAP.
ANGEL_ALIAS_MAP: dict[str, str] = {
    # ── NSE symbol renamed / corporate-action in Angel One master ──
    "AARTI":        "AARTIIND",      # Aarti Industries
    "AMARARAJA":    "ARE&M",         # Amara Raja Energy & Mobility
    "HAPPYMINDS":   "HAPPSTMNDS",    # HappyMind Technologies
    "GMRINFRA":     "GMRP&UI",       # GMR Power and Urban Infra
    "RAMKRISHNA":   "RKFORGE",       # Ramkrishna Forgings
    "LTIM":         "LTTS",          # LTIMindtree — Angel One uses LTTS token
    # Note: TATAMOTORS is not present in Angel One master as of May 2025
    # CCL Products: CCL.NS is the yfinance sym; Angel One master uses CCL (token 11452)
}

# Credentials imported lazily from angel_ltp to avoid circular imports
_CREDS_MODULE = "angel_ltp"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_session():
    """Reuse the authenticated SmartConnect session from angel_ltp."""
    try:
        import angel_ltp
        return angel_ltp._get_session()
    except Exception as exc:
        log.error("angel_candle: could not get Angel One session — %s", exc)
        return None


def _load_token_map() -> dict[str, str]:
    """Return the NSE symbol → token dict (cache-first, then disk, then download)."""
    global _token_map, _token_map_ts

    now = time.time()
    if _token_map and (now - _token_map_ts) < _TOKEN_MAP_TTL_HOURS * 3600:
        return _token_map

    # Try disk cache
    if _TOKEN_MAP_PATH.exists():
        age_h = (now - _TOKEN_MAP_PATH.stat().st_mtime) / 3600
        if age_h < _TOKEN_MAP_TTL_HOURS:
            try:
                with open(_TOKEN_MAP_PATH, encoding="utf-8") as fh:
                    _token_map = json.load(fh)
                _token_map_ts = now
                log.info("Angel One token map loaded from cache — %d symbols", len(_token_map))
                return _token_map
            except Exception as exc:
                log.warning("Token map cache read failed: %s", exc)

    return _refresh_token_map()


def _refresh_token_map() -> dict[str, str]:
    """Download instrument master and build symbol → token map for NSE equities."""
    global _token_map, _token_map_ts

    log.info("Downloading Angel One instrument master …")
    try:
        resp = requests.get(_INSTRUMENT_MASTER_URL, timeout=40)
        resp.raise_for_status()
        instruments = resp.json()
    except Exception as exc:
        log.error("Instrument master download failed: %s", exc)
        return _token_map or {}

    token_map: dict[str, str] = {}
    for inst in instruments:
        # Keep only NSE plain equities (instrumenttype == "" means EQ spot)
        if inst.get("exch_seg") != "NSE":
            continue
        if inst.get("instrumenttype") not in ("", "EQ"):
            continue

        raw_sym = str(inst.get("symbol", "")).strip().upper()
        token   = str(inst.get("token", "")).strip()
        if not raw_sym or not token:
            continue

        # Strip exchange suffix variants: RELIANCE-EQ → RELIANCE
        clean = raw_sym.replace("-EQ", "").replace("-BE", "").replace("-BL", "").strip()
        # Keep only first mapping if duplicate
        if clean and clean not in token_map:
            token_map[clean] = token

    log.info("Token map built — %d NSE equity symbols", len(token_map))

    _CACHE_DIR.mkdir(exist_ok=True)
    try:
        with open(_TOKEN_MAP_PATH, "w", encoding="utf-8") as fh:
            json.dump(token_map, fh, indent=2)
    except Exception as exc:
        log.warning("Could not save token map: %s", exc)

    _token_map    = token_map
    _token_map_ts = time.time()
    return token_map


def get_token(ticker: str) -> Optional[str]:
    """Return the Angel One instrument token for an NSE symbol, or None."""
    sym = ticker.strip().upper()
    tm  = _load_token_map()

    # 1. Direct match
    if sym in tm:
        return tm[sym]

    # 2. Angel One alias (corporate actions / renaming)
    alias = ANGEL_ALIAS_MAP.get(sym)
    if alias and alias in tm:
        return tm[alias]

    # 3. Try common suffix variants used in master
    for suffix in ("-EQ", "-BE", "-BL"):
        if sym + suffix in tm:
            return tm[sym + suffix]

    return None


# ── Public OHLCV API ──────────────────────────────────────────────────────────

def get_ohlcv(ticker: str, days: int = 180) -> Optional[pd.DataFrame]:
    """
    Fetch `days` of daily OHLCV from Angel One for `ticker`.

    Returns a DataFrame with columns:
        open, high, low, close, adjusted_close, volume
    indexed by date (DatetimeIndex, tz-naive).

    Returns None on any failure so the caller can fall back to yfinance.
    """
    token = get_token(ticker)
    if token is None:
        log.debug("angel_candle: no token for %s — will use yfinance", ticker)
        return None

    obj = _get_session()
    if obj is None:
        log.debug("angel_candle: no session — will use yfinance")
        return None

    # Angel One date format: "YYYY-MM-DD HH:MM"
    to_dt   = datetime.now()
    from_dt = to_dt - timedelta(days=days + 10)   # +10 for buffer / holidays
    from_str = from_dt.strftime("%Y-%m-%d 09:15")
    to_str   = to_dt.strftime("%Y-%m-%d 15:30")

    historic_param = {
        "exchange":    "NSE",
        "symboltoken": token,
        "interval":    _CANDLE_INTERVAL,
        "fromdate":    from_str,
        "todate":      to_str,
    }

    time.sleep(_RATE_LIMIT_SLEEP)   # respect 3 req/sec rate limit

    try:
        resp = obj.getCandleData(historic_param)
    except Exception as exc:
        log.error("angel_candle getCandleData(%s) raised: %s", ticker, exc)
        return None

    if not resp or not resp.get("status"):
        log.warning("angel_candle: bad response for %s — %s", ticker, resp)
        return None

    raw = resp.get("data") or []
    if not raw:
        log.warning("angel_candle: empty data for %s", ticker)
        return None

    # Each row: [timestamp_str, open, high, low, close, volume]
    records = []
    for row in raw:
        try:
            ts    = pd.to_datetime(row[0]).tz_localize(None)
            records.append({
                "date":           ts,
                "open":           float(row[1]),
                "high":           float(row[2]),
                "low":            float(row[3]),
                "close":          float(row[4]),
                "adjusted_close": float(row[4]),   # no adj-close from Angel One; use close
                "volume":         int(row[5]),
            })
        except Exception:
            continue

    if not records:
        return None

    df = pd.DataFrame(records).set_index("date").sort_index()

    # ── Strip today's partial bar (same logic as yfinance fix) ────────────────
    today_str = str(date.today())
    if len(df) > 1:
        last_date = str(df.index[-1].date())
        if last_date == today_str:
            df = df.iloc[:-1]

    # ── Drop zero-volume rows (exchange holidays / bad ticks) ─────────────────
    df = df[df["volume"] > 0]

    if df.empty:
        return None

    log.debug("angel_candle: %s — %d bars fetched via Angel One", ticker, len(df))
    return df


def is_available() -> bool:
    """Return True if Angel One session is active and token map is loaded."""
    try:
        import angel_ltp
        return angel_ltp.is_configured() and _get_session() is not None
    except Exception:
        return False

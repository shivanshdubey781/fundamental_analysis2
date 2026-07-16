"""
angel_ltp.py - Angel One SmartAPI real-time LTP provider
========================================================

Fetches live Last Traded Price (LTP) from Angel One SmartAPI during
market hours as a higher-quality replacement for delayed yfinance data.
Fundamentals and historical OHLCV continue to come from yfinance.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

import config

ANGEL_API_KEY = config.ANGEL_API_KEY
ANGEL_CLIENT_ID = config.ANGEL_CLIENT_ID
ANGEL_PASSWORD = config.ANGEL_PASSWORD
ANGEL_TOTP_KEY = config.ANGEL_TOTP_KEY


# Fallback token map for core symbols.
NSE_TOKEN_MAP: dict[str, str] = {
    "RELIANCE": "2885",
    "TCS": "11536",
    "HDFCBANK": "1333",
    "INFY": "1594",
    "ICICIBANK": "4963",
    "HINDUNILVR": "356",
    "ITC": "1660",
    "SBIN": "3045",
    "BHARTIARTL": "10604",
    "KOTAKBANK": "1922",
    "LT": "11483",
    "HCLTECH": "7229",
    "AXISBANK": "5900",
    "BAJFINANCE": "317",
    "WIPRO": "3787",
    "MARUTI": "10999",
    "SUNPHARMA": "3351",
    "TITAN": "3506",
    "ULTRACEMCO": "11532",
    "ASIANPAINT": "236",
    "NESTLEIND": "17963",
    "POWERGRID": "14977",
    "NTPC": "11630",
    "ONGC": "2475",
    "JSWSTEEL": "11723",
    "TATAMOTORS": "3456",
    "M&M": "2031",
    "TECHM": "13538",
    "INDUSINDBK": "5258",
    "ADANIENT": "25",
    "BAJAJFINSV": "16675",
    "GRASIM": "1232",
    "ADANIPORTS": "15083",
    "COALINDIA": "20374",
    "BPCL": "526",
    "CIPLA": "694",
    "DRREDDY": "881",
    "EICHERMOT": "910",
    "HEROMOTOCO": "1348",
    "HINDALCO": "1363",
    "TATASTEEL": "3499",
    "SBILIFE": "21808",
    "HDFCLIFE": "119",
    "BRITANNIA": "547",
    "DIVISLAB": "10940",
    "APOLLOHOSP": "157",
    "TATACONSUM": "3432",
    "BAJAJ-AUTO": "16669",
    "UPL": "11287",
    "SHREECEM": "3103",
}


_obj = None
_auth_ts: float = 0.0
_SESSION_TTL: float = 6 * 3600
_LOGIN_COOLDOWN: float = 15.0
_LTP_MIN_INTERVAL: float = 1.05
_LTP_CACHE_TTL: float = 15.0
_last_login_attempt_ts: float = 0.0
_last_ltp_call_ts: float = 0.0
_ltp_cache: dict[str, tuple[float, float]] = {}
_session_lock = threading.Lock()
_ltp_lock = threading.Lock()

_SESSION_EXPIRY_HINTS = {
    "invalid token",
    "session expired",
    "jwt",
    "unauthorized",
    "token expired",
    "access token",
    "not logged in",
}
_RATE_LIMIT_HINTS = {
    "access rate",
    "rate limit",
    "too many requests",
    "throttle",
}


def is_configured() -> bool:
    """Return True only when all four credentials have been filled in."""
    placeholders = {
        "YOUR_API_KEY_HERE",
        "YOUR_CLIENT_ID_HERE",
        "YOUR_MPIN_HERE",
        "YOUR_TOTP_SECRET_HERE",
    }
    return not bool(
        {ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_KEY}
        & placeholders
    )


def _is_session_expiry(resp: dict) -> bool:
    msg = str(resp.get("message", "") or "").lower()
    return any(hint in msg for hint in _SESSION_EXPIRY_HINTS)


def _is_rate_limited_message(message: object) -> bool:
    msg = str(message or "").lower()
    return any(hint in msg for hint in _RATE_LIMIT_HINTS)


def _get_cached_ltp(ticker: str, max_age: float = _LTP_CACHE_TTL) -> Optional[float]:
    cached = _ltp_cache.get(ticker)
    if not cached:
        return None
    ts, value = cached
    if (time.time() - ts) <= max_age:
        return value
    return None


def _store_cached_ltp(ticker: str, ltp: float) -> None:
    _ltp_cache[ticker] = (time.time(), ltp)


def _wait_for_ltp_slot() -> None:
    global _last_ltp_call_ts
    with _ltp_lock:
        now = time.time()
        sleep_for = _LTP_MIN_INTERVAL - (now - _last_ltp_call_ts)
        if sleep_for > 0:
            time.sleep(sleep_for)
        _last_ltp_call_ts = time.time()


def force_relogin() -> bool:
    """Explicitly invalidate the cached session and create a fresh one."""
    global _obj, _auth_ts
    with _session_lock:
        _obj = None
        _auth_ts = 0.0
    log.info("Angel One: forcing relogin ...")
    return _get_session(force=True) is not None


def _get_session(force: bool = False):
    """Return an authenticated SmartConnect session."""
    global _obj, _auth_ts, _last_login_attempt_ts
    if not is_configured():
        return None

    with _session_lock:
        now = time.time()
        if _obj and (now - _auth_ts) < _SESSION_TTL and not force:
            return _obj

        if not force and _last_login_attempt_ts and (now - _last_login_attempt_ts) < _LOGIN_COOLDOWN:
            log.warning("Angel One login cooldown active; skipping relogin burst.")
            return _obj

        _last_login_attempt_ts = now

        try:
            import pyotp
            from SmartApi import SmartConnect

            obj = SmartConnect(api_key=ANGEL_API_KEY)
            totp = pyotp.TOTP(ANGEL_TOTP_KEY).now()
            data = obj.generateSession(ANGEL_CLIENT_ID, ANGEL_PASSWORD, totp)

            if data.get("status"):
                _obj = obj
                _auth_ts = now
                log.info("Angel One: session OK for %s", ANGEL_CLIENT_ID)
                return _obj

            message = data.get("message")
            if _is_rate_limited_message(message):
                log.warning("Angel One login rate-limited: %s", message)
            else:
                log.error("Angel One login failed: %s", message)
            _obj = None
            return None
        except ImportError:
            log.error(
                "Angel One: smartapi-python or pyotp not installed. "
                "Run: pip install smartapi-python pyotp"
            )
            return None
        except Exception as exc:
            if _is_rate_limited_message(exc):
                log.warning("Angel One session rate-limited: %s", exc)
            else:
                log.error("Angel One session error: %s", exc)
            _obj = None
            return None


def session_age_seconds() -> Optional[float]:
    """Seconds since last successful login (None if never logged in)."""
    return (time.time() - _auth_ts) if _auth_ts else None


def get_ltp(ticker: str, _retry: bool = True) -> Optional[float]:
    """
    Fetch real-time LTP for an NSE stock from Angel One.

    Returns:
        float when available, otherwise None.
    """
    if not is_configured():
        return None

    ticker = ticker.strip().upper()
    cached_ltp = _get_cached_ltp(ticker)
    if cached_ltp is not None:
        return cached_ltp

    token = None
    try:
        import angel_candle
        token = angel_candle.get_token(ticker)
    except Exception:
        pass

    if not token:
        token = NSE_TOKEN_MAP.get(ticker)

    if not token:
        log.debug("Angel One: no token mapped for %s", ticker)
        return None

    obj = _get_session()
    if obj is None:
        log.error("Angel One SmartConnect session could not be established.")
        return _get_cached_ltp(ticker, max_age=300.0)

    _wait_for_ltp_slot()

    try:
        resp = obj.ltpData("NSE", ticker, token)
    except Exception as exc:
        if _is_rate_limited_message(exc):
            log.warning("Angel One LTP rate-limited for %s: %s", ticker, exc)
            return _get_cached_ltp(ticker, max_age=300.0)

        err = str(exc).lower()
        if _retry and any(hint in err for hint in _SESSION_EXPIRY_HINTS):
            log.warning("Angel One session expired while fetching %s. Relogging once...", ticker)
            if force_relogin():
                return get_ltp(ticker, _retry=False)
        log.error("Angel One LTP fetch failed for %s: %s", ticker, exc)
        return _get_cached_ltp(ticker, max_age=300.0)

    if resp and resp.get("status") and resp.get("data"):
        ltp = resp["data"].get("ltp")
        if ltp is None:
            return None
        value = float(ltp)
        _store_cached_ltp(ticker, value)
        return value

    if resp and _is_session_expiry(resp) and _retry:
        log.warning(
            "Angel One: session expiry detected (%s) - relogging in ...",
            resp.get("message"),
        )
        if force_relogin():
            return get_ltp(ticker, _retry=False)
        return _get_cached_ltp(ticker, max_age=300.0)

    if resp and _is_rate_limited_message(resp.get("message")):
        log.warning("Angel One ltpData rate-limited for %s: %s", ticker, resp.get("message"))
        return _get_cached_ltp(ticker, max_age=300.0)

    log.warning("Angel One ltpData empty for %s: %s", ticker, resp)
    return _get_cached_ltp(ticker, max_age=300.0)


def get_ltp_batch(tickers: list[str]) -> dict[str, Optional[float]]:
    """Fetch LTP for multiple tickers. Returns {TICKER: ltp_or_None}."""
    return {t: get_ltp(t) for t in tickers}

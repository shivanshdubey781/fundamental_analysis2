"""
mastertrust_trade.py — MasterTrust Broker · Nifty 50 MIS Intraday Trade Engine
================================================================================

PURPOSE
-------
This module places MIS (Margin Intraday Square-off) LIMIT orders on Nifty 50
Futures via the MasterTrust broker REST API.

WORKFLOW
--------
1.  Reads trading credentials from MongoDB (collection: mastertrust_credentials)
2.  Uses a WebSocket connection to the MasterTrust feed server to fetch the
    real-time LTP (Last Traded Price) of the Nifty 50 current-month futures
3.  Places a LIMIT BUY / SELL order at that LTP via the REST API
4.  Logs all activity to console + a rotating log file

SETUP
-----
1.  Ensure MongoDB is running and has a document like:
        {
            "user_id":       "MT123456",
            "client_id":     "your_client_id",
            "client_secret": "your_client_secret",
            "access_token":  "Ot5RFp...",     (pre-obtained OAuth2 token)
            "active": true
        }
    Collection  : mastertrust_credentials
    Database    : trading_db     (change MONGO_DB below if different)

2.  Nifty 50 futures token — edit NIFTY_FUT_TOKEN (and NIFTY_FUT_SYMBOL)
    to match the current month's contract token from MasterTrust instrument
    master.  The token stays the same for the entire contract month.

3.  Set TRANSACTION_TYPE = "BUY" or "SELL" and NIFTY_LOT_QTY as required.

DEPENDENCIES
------------
    pip install pymongo requests websocket-client

DISCLAIMER
----------
This software is provided for educational/reference purposes only.
Trading in derivatives involves significant financial risk.
Always paper-trade and test thoroughly before going live.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import ssl
import struct
import threading
import time
from typing import Optional

import requests

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — CONFIGURATION  (edit these before running)
# ─────────────────────────────────────────────────────────────────────────────

# ── MongoDB ───────────────────────────────────────────────────────────────────
MONGO_URI        = "mongodb://localhost:27017/"   # Change if MongoDB is remote
MONGO_DB         = "trading_db"                   # Database name
MONGO_COLLECTION = "mastertrust_credentials"      # Collection name

# ── MasterTrust REST API ──────────────────────────────────────────────────────
MT_API_BASE = "https://masterswift-beta.mastertrust.co.in"   # REST base URL

# ── MasterTrust WebSocket Feed ────────────────────────────────────────────────
MT_WS_HOST   = "agnik-mobile.mastertrust.co.in"
MT_WS_ORIGIN = f"https://{MT_WS_HOST}"

# ── Nifty 50 Futures — update these every month when contract rolls ───────────
# Exchange segment for NFO (NSE Futures & Options) in MasterTrust WS feed = 4
# Get the correct token from MasterTrust instrument master for the current
# expiry contract (e.g., NIFTY26JUNFUT → token 35001 etc.)
NIFTY_WS_SEGMENT   = 4           # NFO segment in MasterTrust WebSocket
NIFTY_FUT_TOKEN    = 35001        # ◄── REPLACE with current month futures token
NIFTY_FUT_SYMBOL   = "NIFTY26JUNFUT"  # ◄── REPLACE with current expiry symbol
NIFTY_EXCHANGE     = "NFO"        # Exchange for order placement

# ── Order Parameters ──────────────────────────────────────────────────────────
TRANSACTION_TYPE = "BUY"    # "BUY" or "SELL"
NIFTY_LOT_QTY    = 25       # 1 lot = 25 (verify current lot size with broker)
NUM_LOTS         = 1        # Number of lots to trade
ORDER_TYPE       = "LIMIT"
PRODUCT_TYPE     = "MIS"    # Margin Intraday Square-off
VALIDITY         = "DAY"

# ── LTP Fetch Timeout ─────────────────────────────────────────────────────────
LTP_WAIT_TIMEOUT_SEC = 20   # Max seconds to wait for a tick from WebSocket

# ── Heartbeat Interval ────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL = 9

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — LOGGING SETUP
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR    = os.path.join(SCRIPT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_log_filename = os.path.join(
    LOG_DIR,
    f"mastertrust_trade_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(_log_filename, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logging.getLogger("websocket").setLevel(logging.WARNING)

log = logging.getLogger("MT_TRADE")
log.info("Log file: %s", _log_filename)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — MONGODB CREDENTIAL FETCH
# ─────────────────────────────────────────────────────────────────────────────

def fetch_credentials_from_mongo() -> Optional[dict]:
    """
    Fetch the active MasterTrust trading credentials from MongoDB.

    Expected document schema in collection mastertrust_credentials:
    {
        "user_id":       "MT123456",        (MasterTrust client/user ID)
        "client_id":     "abc123",          (OAuth2 client_id)
        "client_secret": "xyz789",          (OAuth2 client_secret)
        "access_token":  "Ot5RFp...",       (current valid Bearer token)
        "active":        true               (only one doc should be active=true)
    }

    Returns:
        dict with credential fields, or None if not found / error.
    """
    try:
        import pymongo
    except ImportError:
        log.error(
            "pymongo not installed. Run: pip install pymongo\n"
            "Falling back to hardcoded credentials (if any)."
        )
        return None

    try:
        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Ping to verify connection
        client.admin.command("ping")
        db   = client[MONGO_DB]
        coll = db[MONGO_COLLECTION]

        # Prefer the document explicitly marked active; fall back to first doc
        doc = coll.find_one({"active": True}) or coll.find_one()

        if doc is None:
            log.error(
                "No credentials found in MongoDB collection '%s'. "
                "Please insert a credentials document.",
                MONGO_COLLECTION,
            )
            return None

        required = {"user_id", "client_id", "client_secret", "access_token"}
        missing  = required - set(doc.keys())
        if missing:
            log.error("MongoDB document is missing required fields: %s", missing)
            return None

        log.info(
            "Credentials loaded from MongoDB for user_id=%s", doc.get("user_id")
        )
        return doc

    except Exception as exc:
        log.error("MongoDB connection/fetch error: %s", exc)
        return None

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — MASTERTRUST REST API HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _auth_headers(access_token: str) -> dict:
    """Build the Authorization header for MasterTrust REST API calls."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def get_ltp_via_rest(access_token: str, symbol: str = NIFTY_FUT_SYMBOL) -> Optional[float]:
    """
    (OPTIONAL FALLBACK) Fetch LTP via MasterTrust REST API.

    Prefer the WebSocket-based LTP fetcher (get_nifty_ltp_via_websocket)
    for real-time accuracy. Use this only if the WebSocket fails.

    Args:
        access_token: Valid Bearer token.
        symbol:       Trading symbol (e.g., "NIFTY26JUNFUT").

    Returns:
        float LTP or None on failure.
    """
    url    = f"{MT_API_BASE}/api/v1/market_data/ltp"
    params = {"exchange": NIFTY_EXCHANGE, "tradingsymbol": symbol}

    try:
        resp = requests.get(
            url,
            headers=_auth_headers(access_token),
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        # MasterTrust typically returns {"data": {"ltp": 23456.75, ...}, "status": "success"}
        ltp = (
            data.get("data", {}).get("ltp")
            or data.get("ltp")
            or data.get("last_price")
        )
        if ltp is not None:
            log.info("REST LTP for %s: %.2f", symbol, float(ltp))
            return float(ltp)

        log.warning("REST LTP response had no ltp field: %s", data)
        return None

    except Exception as exc:
        log.warning("REST LTP fetch failed: %s", exc)
        return None


def place_order(
    access_token:     str,
    transaction_type: str = TRANSACTION_TYPE,
    price:            float = 0.0,
    quantity:         int   = NIFTY_LOT_QTY * NUM_LOTS,
    symbol:           str   = NIFTY_FUT_SYMBOL,
    exchange:         str   = NIFTY_EXCHANGE,
    order_type:       str   = ORDER_TYPE,
    product_type:     str   = PRODUCT_TYPE,
    validity:         str   = VALIDITY,
) -> Optional[dict]:
    """
    Place a LIMIT order for Nifty 50 futures (MIS Intraday) via REST API.

    ─────────────────────────────────────────────────
    CRITICAL — NIFTY 50 ONLY GUARD
    ─────────────────────────────────────────────────
    This function will REFUSE to place an order if 'symbol' does not
    start with "NIFTY".  This is a safety check to ensure only Nifty 50
    contracts are traded from this module.

    Args:
        access_token:     Bearer token (from MongoDB credentials).
        transaction_type: "BUY" or "SELL".
        price:            Limit price (should be the current LTP).
        quantity:         Total units (lots × lot_size).
        symbol:           Trading symbol, must start with "NIFTY".
        exchange:         "NFO" for futures.
        order_type:       "LIMIT" (always limit orders per design).
        product_type:     "MIS" for intraday.
        validity:         "DAY".

    Returns:
        API response dict on success, or None on failure.
    """
    # ── NIFTY 50 ONLY GUARD ───────────────────────────────────────────────────
    if not symbol.upper().startswith("NIFTY"):
        log.error(
            "ORDER BLOCKED — symbol '%s' is not a Nifty 50 contract. "
            "This module is restricted to NIFTY* symbols only.",
            symbol,
        )
        return None

    if exchange.upper() != "NFO":
        log.error(
            "ORDER BLOCKED — exchange '%s' is not NFO. "
            "Nifty 50 futures must be traded on NFO.",
            exchange,
        )
        return None

    if product_type.upper() != "MIS":
        log.error(
            "ORDER BLOCKED — product_type '%s' is not MIS. "
            "Only MIS (intraday) orders are allowed from this module.",
            product_type,
        )
        return None

    if order_type.upper() != "LIMIT":
        log.error(
            "ORDER BLOCKED — order_type '%s' is not LIMIT. "
            "Only LIMIT orders are allowed from this module.",
            order_type,
        )
        return None

    if price <= 0:
        log.error("ORDER BLOCKED — invalid price: %.2f. Must be > 0.", price)
        return None

    if quantity <= 0 or quantity % NIFTY_LOT_QTY != 0:
        log.error(
            "ORDER BLOCKED — quantity %d is invalid. "
            "Must be a positive multiple of lot size %d.",
            quantity,
            NIFTY_LOT_QTY,
        )
        return None

    # ── Build payload ─────────────────────────────────────────────────────────
    payload = {
        "exchange":         exchange.upper(),
        "tradingsymbol":    symbol.upper(),
        "transaction_type": transaction_type.upper(),   # "BUY" / "SELL"
        "quantity":         str(quantity),
        "price":            str(round(price, 2)),
        "product":          product_type.upper(),        # "MIS"
        "order_type":       order_type.upper(),          # "LIMIT"
        "validity":         validity.upper(),            # "DAY"
        "trigger_price":    "0",                        # Not required for LIMIT
        "disclosed_quantity": "0",
        "is_amo":           "false",                    # Not After Market Order
    }

    url = f"{MT_API_BASE}/api/v1/orders"

    log.info(
        "Placing order — Symbol: %s | Side: %s | Qty: %d | Price: %.2f | "
        "Product: %s | Type: %s",
        symbol,
        transaction_type,
        quantity,
        price,
        product_type,
        order_type,
    )
    log.debug("Order payload: %s", json.dumps(payload, indent=2))

    try:
        resp = requests.post(
            url,
            headers=_auth_headers(access_token),
            json=payload,
            timeout=15,
        )

        log.info("Order API HTTP status: %d", resp.status_code)

        try:
            result = resp.json()
        except Exception:
            result = {"raw_text": resp.text}

        if resp.status_code == 200:
            order_id = (
                result.get("data", {}).get("orderid")
                or result.get("orderid")
                or result.get("order_id")
                or "UNKNOWN"
            )
            log.info(
                "ORDER PLACED SUCCESSFULLY — order_id=%s | Response: %s",
                order_id,
                result,
            )
            return result
        else:
            log.error(
                "Order placement FAILED — HTTP %d | Response: %s",
                resp.status_code,
                result,
            )
            return None

    except requests.exceptions.ConnectionError:
        log.error("Cannot reach MasterTrust API server at %s", MT_API_BASE)
        return None
    except requests.exceptions.Timeout:
        log.error("MasterTrust API request timed out after 15 seconds")
        return None
    except Exception as exc:
        log.error("Unexpected error during order placement: %s", exc)
        return None

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — WEBSOCKET-BASED REAL-TIME LTP FETCHER
# ─────────────────────────────────────────────────────────────────────────────

class NiftyLTPFetcher:
    """
    Connects to the MasterTrust WebSocket feed, subscribes to the Nifty 50
    futures token, and captures the first LTP tick.

    Usage:
        fetcher = NiftyLTPFetcher(access_token="Ot5RFp...")
        ltp = fetcher.fetch(timeout=20)   # returns float or None
    """

    def __init__(self, access_token: str):
        self.access_token = access_token
        self._ltp: Optional[float] = None
        self._event = threading.Event()
        self._ws    = None

    # ── WebSocket URL ─────────────────────────────────────────────────────────
    def _ws_url(self) -> str:
        return f"wss://{MT_WS_HOST}/ws/v1/feeds?token={self.access_token}"

    # ── Packet decoder (mirrors MasterTrust binary feed format) ───────────────
    @staticmethod
    def _decode_packet(message: bytes) -> Optional[dict]:
        """
        Decode a MasterTrust binary tick packet.
        Bytes 2-5  → token  (4 bytes big-endian uint32)
        Bytes 6-9  → LTP    (4 bytes big-endian uint32, divide by 100)
        """
        try:
            if len(message) < 10:
                return None
            token   = struct.unpack(">I", message[2:6])[0]
            raw_ltp = struct.unpack(">I", message[6:10])[0]
            ltp     = raw_ltp / 100.0
            return {"token": token, "ltp": ltp}
        except Exception as exc:
            log.debug("Packet decode error: %s", exc)
            return None

    # ── WebSocket callbacks ───────────────────────────────────────────────────
    def _on_open(self, ws):
        log.info("WebSocket connected — subscribing to Nifty 50 futures token %d", NIFTY_FUT_TOKEN)
        subscribe_msg = json.dumps({
            "a": "subscribe",
            "v": [[NIFTY_WS_SEGMENT, NIFTY_FUT_TOKEN]],
            "m": "marketdata",
        })
        ws.send(subscribe_msg)

        # Start heartbeat thread
        threading.Thread(
            target=self._heartbeat,
            args=(ws,),
            daemon=True,
            name="MT-Heartbeat",
        ).start()

    def _on_message(self, ws, message):
        if isinstance(message, bytes):
            decoded = self._decode_packet(message)
            if decoded and decoded["token"] == NIFTY_FUT_TOKEN:
                self._ltp = decoded["ltp"]
                log.info(
                    "Nifty 50 LTP received — token=%d | ltp=%.2f",
                    decoded["token"],
                    decoded["ltp"],
                )
                self._event.set()   # Signal the main thread
                ws.close()          # We have what we need; close cleanly

    def _on_error(self, ws, error):
        err = str(error)
        if "opcode=8" in err:
            return   # Normal server-side close
        log.warning("WebSocket error: %s", err)
        self._event.set()   # Unblock the main thread on error

    def _on_close(self, ws, code, msg):
        log.info("WebSocket closed — code=%s msg=%s", code, msg)
        self._event.set()   # Unblock in case of unexpected close

    def _heartbeat(self, ws):
        hb = json.dumps({"a": "h", "v": [], "m": ""})
        while not self._event.is_set():
            try:
                ws.send(hb)
                log.debug("Heartbeat sent")
            except Exception:
                break
            for _ in range(HEARTBEAT_INTERVAL):
                if self._event.is_set():
                    return
                time.sleep(1)

    # ── Public method ─────────────────────────────────────────────────────────
    def fetch(self, timeout: int = LTP_WAIT_TIMEOUT_SEC) -> Optional[float]:
        """
        Spin up a WebSocket, wait for the first LTP tick, then return it.

        Args:
            timeout: Maximum seconds to wait before giving up.

        Returns:
            float LTP, or None if timed out / error.
        """
        import websocket as _ws_lib

        ws_headers = [
            "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Cache-Control: no-cache",
            "Pragma: no-cache",
        ]

        ws = _ws_lib.WebSocketApp(
            self._ws_url(),
            header=ws_headers,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._ws = ws

        ws_thread = threading.Thread(
            target=ws.run_forever,
            kwargs={
                "sslopt":        {"cert_reqs": ssl.CERT_NONE},
                "host":          MT_WS_HOST,
                "origin":        MT_WS_ORIGIN,
                "ping_interval": 0,
            },
            daemon=True,
            name="MT-WSFeed",
        )
        ws_thread.start()

        got_tick = self._event.wait(timeout=timeout)

        if not got_tick:
            log.warning(
                "LTP fetch timed out after %d seconds — no tick received for token %d",
                timeout,
                NIFTY_FUT_TOKEN,
            )
            ws.close()

        ws_thread.join(timeout=5)
        return self._ltp


def get_nifty_ltp_via_websocket(access_token: str) -> Optional[float]:
    """
    Convenience wrapper — fetch the Nifty 50 futures LTP via WebSocket.

    Returns float LTP or None.
    """
    fetcher = NiftyLTPFetcher(access_token=access_token)
    return fetcher.fetch(timeout=LTP_WAIT_TIMEOUT_SEC)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — MARKET HOURS GUARD
# ─────────────────────────────────────────────────────────────────────────────

def is_market_open() -> bool:
    """
    Returns True if the current time (IST) is within NSE trading hours
    Monday–Friday, 09:15–15:30.
    """
    try:
        import pytz
        IST = pytz.timezone("Asia/Kolkata")
        now = datetime.datetime.now(IST)
    except ImportError:
        # pytz not available; use UTC+5:30 offset as fallback
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)

    if now.weekday() >= 5:   # Saturday=5, Sunday=6
        return False

    market_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7 — MAIN TRADE EXECUTION ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def run_trade(
    transaction_type: str = TRANSACTION_TYPE,
    num_lots:         int  = NUM_LOTS,
    force_outside_hours: bool = False,
) -> Optional[dict]:
    """
    End-to-end trade execution:
      1. Load credentials from MongoDB
      2. Guard: only Nifty 50 MIS intraday during market hours
      3. Fetch Nifty 50 LTP via MasterTrust WebSocket
      4. Place LIMIT order at LTP via MasterTrust REST API

    Args:
        transaction_type:     "BUY" or "SELL".
        num_lots:             Number of Nifty lots to trade (default = NUM_LOTS).
        force_outside_hours:  Set True to bypass the market-hours guard
                              (use ONLY for testing).

    Returns:
        API response dict from MasterTrust if order succeeds, else None.
    """
    log.info("=" * 70)
    log.info("MasterTrust Trade Engine — STARTING")
    log.info("Symbol    : %s | Exchange: %s", NIFTY_FUT_SYMBOL, NIFTY_EXCHANGE)
    log.info("Side      : %s | Lots: %d | Qty: %d", transaction_type, num_lots, num_lots * NIFTY_LOT_QTY)
    log.info("Product   : %s | Order Type: %s | Validity: %s", PRODUCT_TYPE, ORDER_TYPE, VALIDITY)
    log.info("=" * 70)

    # ── Step 1: Load credentials from MongoDB ─────────────────────────────────
    creds = fetch_credentials_from_mongo()
    if creds is None:
        log.error("Cannot proceed — no credentials available.")
        return None

    access_token = creds["access_token"]
    user_id      = creds.get("user_id", "UNKNOWN")
    log.info("Trading as user_id=%s", user_id)

    # ── Step 2: Market hours guard ────────────────────────────────────────────
    if not force_outside_hours and not is_market_open():
        log.warning(
            "Market is CLOSED right now. "
            "Trade will not be placed. Use force_outside_hours=True to override (testing only)."
        )
        return None

    # ── Step 3: Fetch real-time LTP for Nifty 50 futures (WebSocket) ─────────
    log.info(
        "Fetching real-time LTP for %s (token=%d) via MasterTrust WebSocket ...",
        NIFTY_FUT_SYMBOL,
        NIFTY_FUT_TOKEN,
    )
    ltp = get_nifty_ltp_via_websocket(access_token)

    if ltp is None:
        log.warning("WebSocket LTP unavailable — trying REST API fallback ...")
        ltp = get_ltp_via_rest(access_token, symbol=NIFTY_FUT_SYMBOL)

    if ltp is None or ltp <= 0:
        log.error(
            "Could not fetch a valid LTP for %s. Order NOT placed.",
            NIFTY_FUT_SYMBOL,
        )
        return None

    log.info("Current LTP for %s: %.2f", NIFTY_FUT_SYMBOL, ltp)

    # ── Step 4: Place LIMIT order at LTP ─────────────────────────────────────
    result = place_order(
        access_token     = access_token,
        transaction_type = transaction_type,
        price            = ltp,
        quantity         = num_lots * NIFTY_LOT_QTY,
        symbol           = NIFTY_FUT_SYMBOL,
        exchange         = NIFTY_EXCHANGE,
        order_type       = ORDER_TYPE,
        product_type     = PRODUCT_TYPE,
        validity         = VALIDITY,
    )

    if result is not None:
        log.info("Trade execution COMPLETE for user_id=%s", user_id)
    else:
        log.error("Trade execution FAILED for user_id=%s", user_id)

    log.info("=" * 70)
    return result

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8 — STANDALONE EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Run this file directly to execute a single trade:
        python mastertrust_trade.py

    Edit TRANSACTION_TYPE = "BUY" or "SELL" in SECTION 1 before running.

    For testing outside market hours:
        result = run_trade(force_outside_hours=True)
    """
    import sys

    # Optional: accept CLI argument for BUY / SELL
    side = TRANSACTION_TYPE
    if len(sys.argv) > 1 and sys.argv[1].upper() in {"BUY", "SELL"}:
        side = sys.argv[1].upper()
        log.info("CLI override — transaction_type=%s", side)

    # Check required package: websocket-client
    try:
        import websocket  # noqa: F401
    except ImportError:
        log.error(
            "websocket-client not installed. Run: pip install websocket-client"
        )
        sys.exit(1)

    # Check required package: pymongo
    try:
        import pymongo  # noqa: F401
    except ImportError:
        log.error("pymongo not installed. Run: pip install pymongo")
        sys.exit(1)

    # Execute the trade
    order_result = run_trade(transaction_type=side)

    if order_result:
        print("\n✅ Order placed successfully:")
        print(json.dumps(order_result, indent=2, default=str))
        sys.exit(0)
    else:
        print("\n❌ Order placement failed — check the log for details.")
        print(f"   Log file: {_log_filename}")
        sys.exit(1)

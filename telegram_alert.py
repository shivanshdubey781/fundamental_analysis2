import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional, Set
import requests

log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8789482456:AAGi2-EJ_89yUjGFOG9Ihsl5f_gQxZ-2u-A")
TELEGRAM_OWNER_ID = os.getenv("TELEGRAM_OWNER_ID", "1390865188")

_SUBS_FILE = Path(__file__).parent / "subscribers.json"
_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
_TIMEOUT = 8

_subscribers: dict[str, dict] = {}
_subs_lock = threading.Lock()
_poll_offset = 0

def _load_subscribers() -> None:
    global _subscribers
    with _subs_lock:
        loaded_subs = {}
        if _SUBS_FILE.exists():
            try:
                data = json.loads(_SUBS_FILE.read_text(encoding="utf-8"))
                if "chat_ids" in data:
                    for cid in data["chat_ids"]:
                        scid = str(cid)
                        loaded_subs[scid] = {
                            "chat_id": scid,
                            "first_name": "Trader"
                        }
                elif "subscribers" in data:
                    for sub in data["subscribers"]:
                        scid = str(sub.get("chat_id", ""))
                        if scid:
                            loaded_subs[scid] = sub
            except Exception as exc:
                log.warning("Telegram: could not read subscribers.json — %s", exc)

        # Make sure the Owner is always included
        if TELEGRAM_OWNER_ID not in loaded_subs:
            loaded_subs[TELEGRAM_OWNER_ID] = {
                "chat_id": TELEGRAM_OWNER_ID,
                "first_name": "Owner"
            }

        _subscribers = loaded_subs
        log.info("Telegram: loaded %d subscriber(s)", len(_subscribers))

def _save_subscribers() -> None:
    global _subscribers
    with _subs_lock:
        subs_list = list(_subscribers.values())
    try:
        _SUBS_FILE.write_text(
            json.dumps({"subscribers": subs_list}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        log.warning("Telegram: could not save subscribers.json — %s", exc)

def _add_subscriber(chat_id: str, first_name: str = "", last_name: str = "", username: str = "") -> bool:
    global _subscribers
    chat_id = str(chat_id)
    with _subs_lock:
        is_new = chat_id not in _subscribers
        sub = _subscribers.get(chat_id, {})
        sub["chat_id"] = chat_id
        if first_name:
            sub["first_name"] = first_name
        if last_name:
            sub["last_name"] = last_name
        if username:
            sub["username"] = username
        if "first_name" not in sub or not sub["first_name"]:
            sub["first_name"] = "Trader"
        _subscribers[chat_id] = sub
    _save_subscribers()
    if is_new:
        log.info("Telegram: new subscriber added — chat_id=%s name=%s", chat_id, first_name)
    return is_new

def _add_phone_number(chat_id: str, phone_number: str) -> None:
    global _subscribers
    chat_id = str(chat_id)
    with _subs_lock:
        if chat_id in _subscribers:
            _subscribers[chat_id]["phone_number"] = phone_number
    _save_subscribers()
    log.info("Telegram: updated phone number for chat_id=%s — %s", chat_id, phone_number)

def get_subscriber_count() -> int:
    with _subs_lock:
        return len(_subscribers)

def get_subscribers() -> list[str]:
    with _subs_lock:
        return list(_subscribers.keys())

def is_configured() -> bool:
    return TELEGRAM_BOT_TOKEN not in ("", "YOUR_BOT_TOKEN_HERE")

def send_alert(message: str, parse_mode: str = "HTML") -> bool:
    """
    Broadcast a message to ALL subscribers.
    Returns True if successfully sent to at least one subscriber/recipient.
    """
    import config
    if not getattr(config, "TELEGRAM_SEND_ENABLED", True):
        log.info("Telegram sending is suppressed by configuration.")
        return False

    if not is_configured():
        log.debug("Telegram not configured — skipping alert")
        return False

    recipients = get_subscribers()
    if not recipients:
        recipients = [TELEGRAM_OWNER_ID]

    success = 0
    for chat_id in recipients:
        try:
            resp = requests.post(
                f"{_API_BASE}/sendMessage",
                json={
                    "chat_id":    chat_id,
                    "text":       message,
                    "parse_mode": parse_mode,
                },
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                success += 1
            else:
                data = resp.json() if resp.content else {}
                err  = data.get("description", resp.text[:120])
                if resp.status_code == 403:
                    log.warning("Telegram: chat_id %s blocked the bot — removing subscriber", chat_id)
                    with _subs_lock:
                        if chat_id in _subscribers:
                            del _subscribers[chat_id]
                    _save_subscribers()
                else:
                    log.warning("Telegram error %s for chat_id %s: %s", resp.status_code, chat_id, err)
        except Exception as exc:
            log.error("Telegram send failed for chat_id %s: %s", chat_id, exc)

    if success:
        log.info("Telegram alert broadcast to %d / %d subscriber(s)", success, len(recipients))
    return success > 0

def _send_welcome(chat_id: str, first_name: str = "") -> None:
    name = first_name or "Trader"
    msg = (
        f"👋 <b>Welcome, {name}!</b>\n\n"
        f"You are now subscribed to <b>NSE Composite Screener</b> alerts.\n\n"
        f"📲 <b>Please share your phone number</b> using the button below to link your verified contact card to your subscription!\n\n"
        f"You will receive notifications every time the screener finds:\n"
        f"  📈 Grade A+ / A stocks\n"
        f"  🚀 BB Breakouts\n"
        f"  ⭐ Squeeze setups\n\n"
        f"<i>Send /stop at any time to unsubscribe.</i>"
    )
    reply_markup = {
        "keyboard": [[{"text": "📱 Share Phone Number / Register", "request_contact": True}]],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }
    try:
        requests.post(
            f"{_API_BASE}/sendMessage",
            json={
                "chat_id":    chat_id,
                "text":       msg,
                "parse_mode": "HTML",
                "reply_markup": reply_markup
            },
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        log.error("Telegram: welcome message send failed — %s", exc)

def _send_unsubscribe_confirm(chat_id: str) -> None:
    msg = (
        "✅ You have been <b>unsubscribed</b> from NSE Screener alerts.\n\n"
        "Send /start at any time to re-subscribe."
    )
    try:
        requests.post(
            f"{_API_BASE}/sendMessage",
            json={
                "chat_id":    chat_id,
                "text":       msg,
                "parse_mode": "HTML",
                "reply_markup": {"remove_keyboard": True}
            },
            timeout=_TIMEOUT,
        )
    except Exception:
        pass

def _poll_updates() -> None:
    global _poll_offset
    log.info("Telegram subscriber listener started (polling every 10 s)")
    while True:
        try:
            resp = requests.get(
                f"{_API_BASE}/getUpdates",
                params={"offset": _poll_offset, "timeout": 5, "allowed_updates": ["message"]},
                timeout=15,
            )
            if resp.status_code != 200:
                time.sleep(10)
                continue
            updates = resp.json().get("result", [])
            for upd in updates:
                _poll_offset = upd["update_id"] + 1
                msg = upd.get("message", {})
                text = (msg.get("text") or "").strip()
                chat = msg.get("chat", {})
                chat_id = str(chat.get("id", ""))
                from_user = msg.get("from", {})
                first_name = from_user.get("first_name", "") or chat.get("first_name", "")
                last_name = from_user.get("last_name", "") or chat.get("last_name", "")
                username = from_user.get("username", "") or chat.get("username", "")

                contact = msg.get("contact", {})
                if contact:
                    phone_number = contact.get("phone_number", "")
                    _add_phone_number(chat_id, phone_number)
                    try:
                        requests.post(
                            f"{_API_BASE}/sendMessage",
                            json={
                                "chat_id": chat_id,
                                "text": "✅ <b>Phone number registered!</b> Thank you for completing your subscription.",
                                "parse_mode": "HTML",
                                "reply_markup": {"remove_keyboard": True}
                            },
                            timeout=_TIMEOUT
                        )
                    except Exception:
                        pass
                    continue

                if text.lower() == "/start":
                    _add_subscriber(chat_id, first_name, last_name, username)
                    _send_welcome(chat_id, first_name)
                elif text.lower() == "/stop":
                    with _subs_lock:
                        if chat_id in _subscribers:
                            del _subscribers[chat_id]
                    _save_subscribers()
                    _send_unsubscribe_confirm(chat_id)
        except Exception as exc:
            log.warning("Telegram poll error: %s", exc)
        time.sleep(10)

def _backfill_subscriber_details() -> None:
    pass

def start_subscriber_listener() -> None:
    _load_subscribers()
    t = threading.Thread(target=_poll_updates, daemon=True, name="tg-subscriber-poll")
    t.start()

def send_top_picks(df) -> None:
    pass


# ── Active alert formatting and send functions ──────────────────────────────

def format_new_running_trade(entry_row: dict) -> str:
    """Format alert HTML for a new running trade."""
    ticker = entry_row.get("ticker", "—")
    entry_price = entry_row.get("entry_price")
    target_price = entry_row.get("target_price")
    sl_price = entry_row.get("sl_price")
    current_trail_sl = entry_row.get("current_trail_sl")
    entry_at = entry_row.get("entry_at", "—")
    
    from datetime import datetime
    formatted_date = entry_at
    try:
        clean_at = entry_at.split("+")[0].split("Z")[0]
        dt = datetime.fromisoformat(clean_at)
        formatted_date = dt.strftime("%d %b %H:%M") + " IST"
    except Exception:
        pass

    ep = f"₹{entry_price:.2f}" if entry_price is not None else "—"
    tp = f"₹{target_price:.2f}" if target_price is not None else "—"
    sl = f"₹{sl_price:.2f}" if sl_price is not None else "—"
    tsl = f"₹{current_trail_sl:.2f}" if current_trail_sl is not None else "—"

    return (
        f"📈 <b>New Running Position Added</b>\n\n"
        f"<b>Ticker</b>: {ticker}\n"
        f"<b>Entry Price</b>: {ep}\n"
        f"<b>Entry Date</b>: {formatted_date}\n"
        f"<b>Target (15%)</b>: {tp}\n"
        f"<b>Stop Loss (5%)</b>: {sl}\n"
        f"<b>Trailing SL (8%)</b>: {tsl}"
    )

def format_booked_trade(entry_row: dict) -> str:
    """Format alert HTML for a booked trade."""
    ticker = entry_row.get("ticker", "—")
    exit_reason = entry_row.get("exit_reason", "—")
    exit_type = entry_row.get("status", "—")
    entry_price = entry_row.get("entry_price")
    exit_price = entry_row.get("exit_price")
    
    pnl_pct = entry_row.get("realized_pnl_pct")
    if pnl_pct is None and entry_row.get("pnl_pct") is not None:
        pnl_pct = entry_row.get("pnl_pct")
        
    pnl_amount = entry_row.get("realized_amount")
    if pnl_amount is None and entry_row.get("running_amount") is not None:
        pnl_amount = entry_row.get("running_amount")

    from datetime import datetime
    entry_date = entry_row.get("entry_at", "—")
    try:
        clean_at = entry_date.split("+")[0].split("Z")[0]
        dt = datetime.fromisoformat(clean_at)
        entry_date = dt.strftime("%d %b %Y")
    except Exception:
        pass

    exit_date = entry_row.get("exit_at", "—")
    try:
        clean_at = exit_date.split("+")[0].split("Z")[0]
        dt = datetime.fromisoformat(clean_at)
        exit_date = dt.strftime("%d %b %H:%M") + " IST"
    except Exception:
        pass

    ep = f"₹{entry_price:.2f}" if entry_price is not None else "—"
    xp = f"₹{exit_price:.2f}" if exit_price is not None else "—"
    
    pnl_str = "—"
    if pnl_pct is not None:
        sign = "+" if pnl_pct >= 0 else ""
        amt_str = f" ({sign}₹{pnl_amount:.2f})" if pnl_amount is not None else ""
        pnl_str = f"{sign}{pnl_pct:.2f}%{amt_str}"

    return (
        f"🔒 <b>Position Booked / Closed</b>\n\n"
        f"<b>Ticker</b>: {ticker}\n"
        f"<b>Exit Reason</b>: {exit_reason} (Type: {exit_type})\n"
        f"<b>Trade Taken</b>: {entry_date}\n"
        f"<b>Exit Date</b>: {exit_date}\n"
        f"<b>Entry Price</b>: {ep}\n"
        f"<b>Exit Price</b>: {xp}\n"
        f"<b>PnL</b>: {pnl_str}"
    )

def format_eod_links(base_url: str, date_str: str) -> str:
    """Format alert HTML for EOD report links."""
    return (
        f"📊 <b>NSE Screener — End of Day Reports</b>\n"
        f"<i>Date: {date_str}</i>\n\n"
        f"📁 <b>Running Positions CSV</b>:\n"
        f"{base_url}/api/reports/running.csv\n\n"
        f"📁 <b>Booked Positions CSV</b>:\n"
        f"{base_url}/api/reports/booked.csv\n\n"
        f"📁 <b>Today\'s Screener Report CSV</b>:\n"
        f"{base_url}/reports/today_clean.csv"
    )

def send_new_running_trade_alert(entry_row: dict) -> bool:
    """Format and send alert for new running trade. Returns True on success."""
    import config
    if not config.TELEGRAM_ENABLE_NEW_RUNNING_ALERTS:
        log.debug("Telegram running alerts disabled — skipping")
        return False
    msg = format_new_running_trade(entry_row)
    return send_alert(msg)

def send_booked_trade_alert(entry_row: dict) -> bool:
    """Format and send alert for booked trade. Returns True on success."""
    import config
    if not config.TELEGRAM_ENABLE_BOOKED_ALERTS:
        log.debug("Telegram booked alerts disabled — skipping")
        return False
    msg = format_booked_trade(entry_row)
    return send_alert(msg)

def send_eod_links_alert(base_url: str, date_str: str) -> bool:
    """Format and send alert for EOD report links. Returns True on success."""
    import config
    if not config.TELEGRAM_ENABLE_EOD_LINKS:
        log.debug("Telegram EOD links alerts disabled — skipping")
        return False
    msg = format_eod_links(base_url, date_str)
    return send_alert(msg)

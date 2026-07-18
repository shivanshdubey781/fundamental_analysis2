"""
NSE Fundamental Screener — Production Flask Server
Run: python main.py
"""

import csv
import json
import logging
import math
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, jsonify, render_template, request, send_file

from nse_data import fetch_nse_delivery, fetch_nse_oi
from angel_ltp import (
    get_ltp as angel_get_ltp,
    is_configured as angel_is_configured,
    force_relogin as angel_force_relogin,
    session_age_seconds as angel_session_age,
)
from scoring_engine import (
    build_composite_score,
    fetch_fundamentals_result,
    fetch_nifty_data,
    fetch_price_data,
    run_batch_screener,
)
import config
import tracker_store

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

app = Flask(__name__)

# ── Sectoral Analysis Blueprint (pure-additive, zero risk) ───────────────────
from sectoral_analysis import sector_bp, set_bg_ref  # noqa: E402
app.register_blueprint(sector_bp)


# ── NaN-safe JSON provider ────────────────────────────────────────────────────
# Python's float NaN is NOT valid JSON (only null is).  pandas returns NaN for
# missing metric fields, which would produce "roe_pct":NaN breaking the browser.
from flask.json.provider import DefaultJSONProvider

class SafeJSONProvider(DefaultJSONProvider):
    """Replace float NaN / Inf with JSON null recursively on every response."""

    @staticmethod
    def _clean(obj):
        if isinstance(obj, dict):
            return {k: SafeJSONProvider._clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return type(obj)(SafeJSONProvider._clean(v) for v in obj)
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return obj

    def dumps(self, obj, **kwargs):
        return super().dumps(self._clean(obj), **kwargs)


app.json_provider_class = SafeJSONProvider
app.json = SafeJSONProvider(app)


ROOT    = Path(__file__).resolve().parent
IST     = pytz.timezone("Asia/Kolkata")
REPORTS_DIR    = ROOT / "reports"
FIRST_SEEN_FILE = ROOT / "data" / "first_seen.json"

# ── First-seen tracker ────────────────────────────────────────────────────────
# Persists {TICKER: "YYYY-MM-DD"} so the UI can show how long each stock
# has been qualifying in the screener.

def _load_first_seen() -> dict:
    """Load the first-seen date map from disk. Returns {} on missing/error."""
    try:
        if FIRST_SEEN_FILE.exists():
            return json.loads(FIRST_SEEN_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("[first-seen] Could not load %s: %s", FIRST_SEEN_FILE, exc)
    return {}


def _save_first_seen(data: dict) -> None:
    """Persist the first-seen map to disk."""
    try:
        FIRST_SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        FIRST_SEEN_FILE.write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )
    except Exception as exc:
        log.warning("[first-seen] Could not save %s: %s", FIRST_SEEN_FILE, exc)


def _update_first_seen(tickers: list[str]) -> dict:
    """
    For every ticker in `tickers`, record today's IST date as first_seen
    if it is not already present.  Returns the full up-to-date map.
    """
    today = datetime.now(IST).strftime("%Y-%m-%d")
    data  = _load_first_seen()
    changed = False
    for t in tickers:
        if t not in data:
            data[t] = today
            changed  = True
    if changed:
        _save_first_seen(data)
    return data


def _annotate_first_seen(df):
    """Add first-seen metadata to screener rows."""
    if df.empty:
        return df

    qualifying_tickers = df["ticker"].tolist()
    first_seen_map = _update_first_seen(qualifying_tickers)
    today = datetime.now(IST).date()

    def _days_since(ticker: str) -> int:
        try:
            d = datetime.strptime(first_seen_map.get(ticker, str(today)), "%Y-%m-%d").date()
            return (today - d).days
        except Exception:
            return 0

    def _format_first_seen(ticker: str) -> str:
        try:
            d_str = first_seen_map.get(ticker, str(today))
            d = datetime.strptime(d_str, "%Y-%m-%d")
            return d.strftime("%d/%m/%Y")
        except Exception:
            return datetime.now(IST).strftime("%d/%m/%Y")

    df["first_seen"] = df["ticker"].map(_format_first_seen)
    df["days_in_screener"] = df["ticker"].map(_days_since)
    df["scan_date"] = datetime.now(IST).strftime("%d/%m/%Y")
    return df

# ── Stock universes (P1-B) ────────────────────────────────────────────────────
# ── Stock universes (P1-B) ────────────────────────────────────────────────────
import universe_store

INDEX_MAP = universe_store.get_index_map()
NIFTY50_TICKERS = universe_store.get_universe("nifty50")
NIFTY500_TICKERS = universe_store.get_universe("nifty500_custom")

SECTORAL_FALLBACK_TICKERS = [
    # Hotel
    "INDHOTEL", "EIHOTEL", "IRCTC", "EASEMYTRIP", "INDIGO",
    # Entertainment
    "PVRINOX", "SAREGAMA", "ZEEL",
    # Realty
    "OBEROIRLTY", "DLF", "GODREJPROP", "PRESTIGE", "PHOENIXLTD"
]

def _default_scan_tickers() -> list[str]:
    """Returns the complete broad scan ticker list."""
    core_keys = ["nifty500_custom"]
    unique_tickers, _ = universe_store.build_unique_universe(core_keys)
    return unique_tickers


# ── Scheduled-scan universe ───────────────────────────────────────────────────
# All scheduled scans (nightly + auto-telegram) use this deduped list.
# It combines all core index universes plus sectoral fallbacks.
SCHEDULED_SCAN_TICKERS: list[str] = _default_scan_tickers()




# ── Helpers ───────────────────────────────────────────────────────────────────

import threading

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")


# ── Background screener state ─────────────────────────────────────────────────
_bg: dict = {
    "running":     False,
    "progress":    0,
    "total":       0,
    "started_at":  None,
    "finished_at": None,
    "index":       "nifty50",
    "error":       None,
    "results":     [],   # last run results cached in memory
}
_bg_lock = threading.Lock()

_in_app_notifications = []
_in_app_notifications_lock = threading.Lock()

def add_in_app_notification(notif_type: str, ticker: str, message: str):
    with _in_app_notifications_lock:
        notif_id = len(_in_app_notifications) + 1
        _in_app_notifications.append({
            "id": notif_id,
            "type": notif_type,
            "ticker": ticker,
            "message": message,
            "timestamp": datetime.now(IST).isoformat()
        })
        if len(_in_app_notifications) > 100:
            _in_app_notifications.pop(0)

def _trigger_in_app_notification(notif_type: str, ticker: str, message: str):
    log.info("[in-app-notification] Triggering %s alert for %s: %s", notif_type, ticker, message)
    add_in_app_notification(notif_type, ticker, message)

# ── Wire _bg reference into sectoral_analysis (fixes circular-import issue) ──
set_bg_ref(_bg)


def _cleanup_report_csvs(max_age_hours: int = None) -> None:
    """Delete generated CSV reports older than the configured retention window."""
    if max_age_hours is None:
        max_age_hours = config.REPORT_RETENTION_HOURS
    if not REPORTS_DIR.exists():
        return

    cutoff = datetime.now(IST) - timedelta(hours=max_age_hours)
    deleted = 0

    for csv_file in REPORTS_DIR.glob("*.csv"):
        try:
            modified_at = datetime.fromtimestamp(csv_file.stat().st_mtime, tz=IST)
            if modified_at <= cutoff:
                csv_file.unlink()
                deleted += 1
        except Exception as exc:
            log.warning("[reports-cleanup] Could not delete %s: %s", csv_file, exc)

    if deleted:
        log.info("[reports-cleanup] Deleted %d CSV report(s) older than %d hours", deleted, max_age_hours)


def _latest_report_for_day(day: datetime | None = None) -> Path | None:
    day = day or datetime.now(IST)
    if not REPORTS_DIR.exists():
        return None

    prefix = f"screener_{day.strftime('%Y%m%d')}"
    matches = [path for path in REPORTS_DIR.glob(f"{prefix}*.csv") if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def _latest_screener_report() -> Path | None:
    if not REPORTS_DIR.exists():
        return None
    # Matches both manual run outputs (screener_YYYYMMDD_HHMMSS.csv) and auto scans (screener_autoscan_YYYYMMDD_HHMMSS.csv)
    matches = list(REPORTS_DIR.glob("screener_*.csv"))
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def _get_latest_screener_scores() -> dict[str, float]:
    """Returns a mapping of normalized ticker -> latest total_score."""
    scores = {}

    # 1. Check in-memory cache first
    results = _bg.get("results", [])
    if results:
        for r in results:
            t = r.get("ticker")
            s = r.get("total_score")
            if t and s is not None:
                scores[universe_store.normalize_ticker(t)] = float(s)
        return scores

    # 2. Fallback to reading the latest CSV report on disk
    try:
        import pandas as pd
        latest_report = _latest_screener_report()
        if latest_report and latest_report.exists():
            df = pd.read_csv(latest_report)
            if not df.empty and "ticker" in df.columns and "total_score" in df.columns:
                for _, row in df.iterrows():
                    t = row["ticker"]
                    s = row["total_score"]
                    if pd.notna(t) and pd.notna(s):
                        scores[universe_store.normalize_ticker(str(t))] = float(s)
    except Exception as e:
        log.warning("[scores] Failed to read latest scores from CSV: %s", e)

    return scores


def resolve_tracking_price(ticker: str, row: dict) -> tuple[float | None, str]:
    """
    Returns (price, source).
    Source should be one of:
    - "angel_ltp"
    - "close"
    - "missing"
    """
    price = None
    source = "missing"
    
    if angel_is_configured():
        try:
            price = angel_get_ltp(ticker)
            if price is not None:
                source = "angel_ltp"
        except Exception as e:
            log.warning("resolve_tracking_price: Angel LTP failed for %s: %s", ticker, e)
            
    # If LTP failed, and session age suggests it is stale or missing, attempt relogin once
    if price is None and angel_is_configured():
        age = angel_session_age()
        if age is None or age >= 3600:
            log.info("resolve_tracking_price: LTP failed and session stale (%s). Attempting relogin...", age)
            if angel_force_relogin():
                try:
                    price = angel_get_ltp(ticker, _retry=False)
                    if price is not None:
                        source = "angel_ltp"
                except Exception as e:
                    log.warning("resolve_tracking_price: Angel LTP retry failed for %s: %s", ticker, e)
            
    # Fallback to close price from row
    if price is None:
        close_val = row.get("close")
        if close_val is not None:
            try:
                val = float(close_val)
                if not math.isnan(val) and not math.isinf(val):
                    price = round(val, 2)
                    source = "close"
            except (ValueError, TypeError):
                pass
                
    if price is not None:
        log.info("resolve_tracking_price: Resolved %s to %s via %s", ticker, price, source)
    else:
        log.warning("resolve_tracking_price: Could not resolve price for %s", ticker)
            
    return price, source


def _scheduled_scan_tickers() -> list[str]:
    """Universe used by scheduled scans, including fallback sectoral symbols."""
    return _default_scan_tickers()


def _parse_timestamp(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = IST.localize(dt)
        return dt
    except Exception:
        return None

def _should_enter_running(row: dict) -> bool:
    ticker = row.get("ticker")
    if not ticker:
        return False
    score = float(row.get("total_score", 0.0))
    return score >= config.TRADE_ENTRY_MIN_SCORE

def _defend_running_entry_creation(row: dict, active_entries: dict, all_entries: dict) -> bool:
    ticker = row.get("ticker")
    if not ticker:
        return False
        
    # Check if already active
    if ticker in active_entries:
        return False
        
    # Re-entry guard: check if last exit was recent
    previous = all_entries.get(ticker)
    if previous is not None and previous["status"] != "active":
        exit_at_str = previous.get("exit_at")
        if exit_at_str:
            exit_at = _parse_timestamp(exit_at_str)
            if exit_at:
                # If exit was less than 1 hour ago, block re-entry
                if datetime.now(IST) - exit_at < timedelta(hours=1):
                    log.info("[tracking] Blocking immediate re-entry for %s (exit was less than 1 hour ago)", ticker)
                    return False
                    
    return _should_enter_running(row)


def apply_trade_tracking(df, index_name: str, report_name: str):
    """
    For each qualifying screener row:
    - resolve latest price
    - create or update active entry
    - append snapshot
    - merge tracking state into dataframe
    Returns enriched dataframe.
    """
    import pandas as pd
    import config
    import tracker_store

    if df.empty:
        return df

    tickers = df["ticker"].tolist()
    active_entries = tracker_store.get_tracking_rows_for_tickers(tickers)
    # Also load any closed entries so we can suppress re-entries for already-booked stocks
    all_entries = tracker_store.get_all_entries_for_tickers(tickers)
    
    enriched_rows = []
    
    for _, row_series in df.iterrows():
        row = row_series.to_dict()
        ticker = row["ticker"]
        
        # Determine trade eligibility based on score
        score = float(row.get("total_score", 0.0))
        trade_eligible = (score >= config.TRADE_ENTRY_MIN_SCORE)
        row["trade_eligible"] = trade_eligible
        
        # 1. Resolve latest price
        price, source = resolve_tracking_price(ticker, row)
        if price is None:
            log.warning("[tracking] Skip tracking for %s: latest price not available", ticker)
            for col in [
                "entry_at", "entry_price", "entry_source", "target_pct", "target_price",
                "sl_pct", "sl_price", "trail_sl_pct", "highest_price", "current_trail_sl",
                "last_price", "last_seen_at", "status", "exit_at", "exit_price", "exit_reason",
                "pnl_pct", "max_gain_pct", "drawdown_from_high_pct"
            ]:
                row[col] = None
            row["trade_active"] = False
            enriched_rows.append(row)
            continue
            
        now_str = datetime.now(IST).isoformat()
        
        # 2. Check if active entry exists
        entry = active_entries.get(ticker)
        
        if entry is None:
            if _defend_running_entry_creation(row, active_entries, all_entries):
                # Create a new active entry
                entry_id = tracker_store.create_entry(
                    ticker=ticker,
                    index_name=index_name,
                    entry_at=now_str,
                    entry_price=price,
                    entry_source=source,
                    target_pct=config.TARGET_PCT,
                    sl_pct=config.SL_PCT,
                    trail_sl_pct=config.TRAIL_SL_PCT,
                    report_name=report_name
                )
                # Retrieve the created entry details
                entry = tracker_store.get_active_entry(ticker)
                if entry is None:
                    log.error("[tracking] Created entry for %s but failed to retrieve it", ticker)
                    row["trade_active"] = False
                    enriched_rows.append(row)
                    continue
                    
                # Append initial active snapshot
                tracker_store.append_snapshot(
                    entry_id=entry_id,
                    snapshot_at=now_str,
                    price=price,
                    highest_price=price,
                    current_trail_sl=entry["current_trail_sl"],
                    status="active",
                    report_name=report_name
                )
                _maybe_send_new_running_alert(entry, entry_id)
                _trigger_in_app_notification("sim_entry", ticker, f"SIM ENTRY: {ticker} entered simulation at ₹{price:.2f}")
            else:
                for col in [
                    "entry_at", "entry_price", "entry_source", "target_pct", "target_price",
                    "sl_pct", "sl_price", "trail_sl_pct", "highest_price", "current_trail_sl",
                    "last_price", "last_seen_at", "status", "exit_at", "exit_price", "exit_reason",
                    "pnl_pct", "max_gain_pct", "drawdown_from_high_pct"
                ]:
                    row[col] = None
                row["trade_active"] = False
                enriched_rows.append(row)
                continue

        else:
            # Update existing active entry
            entry_id = entry["id"]
            entry_price = entry["entry_price"]
            
            # Evaluate state using shared helper
            eval_res = _evaluate_exit(entry, price, now_str)
            status = eval_res["status"]
            exit_at = eval_res["exit_at"]
            exit_price = eval_res["exit_price"]
            exit_reason = eval_res["exit_reason"]
            highest_price = eval_res["highest_price"]
            current_trail_sl = eval_res["current_trail_sl"]
            new_breach_count = eval_res["sl_breach_count"]
            new_breach_since = eval_res["sl_breach_since"]
            
            if status != "active":
                # Close the entry in database
                tracker_store.close_entry(
                    entry_id=entry_id,
                    status=status,
                    exit_at=exit_at,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    report_name=report_name
                )
                # Send booked alert
                entry_copy = dict(entry)
                entry_copy["status"] = status
                entry_copy["exit_at"] = exit_at
                entry_copy["exit_price"] = exit_price
                entry_copy["exit_reason"] = exit_reason
                ep_val = entry_copy.get("entry_price") or 0.0
                if ep_val > 0:
                    entry_copy["realized_pnl_pct"] = ((exit_price - ep_val) / ep_val) * 100
                else:
                    entry_copy["realized_pnl_pct"] = 0.0
                entry_copy["realized_amount"] = exit_price - ep_val
                _maybe_send_booked_alert(entry_copy, entry_id)
                _trigger_in_app_notification("booked", ticker, f"BOOKED: {ticker} hit {exit_reason} (Type: {status}) at ₹{price:.2f}")
            else:
                # Update normal state
                tracker_store.update_entry_state(
                    entry_id=entry_id,
                    last_price=price,
                    last_seen_at=now_str,
                    highest_price=highest_price,
                    current_trail_sl=current_trail_sl,
                    report_name=report_name,
                    sl_breach_count=new_breach_count,
                    sl_breach_since=new_breach_since
                )
                
            # Append snapshot (taken at scan time, not on every 3-minute refresh)
            tracker_store.append_snapshot(
                entry_id=entry_id,
                snapshot_at=now_str,
                price=price,
                highest_price=highest_price,
                current_trail_sl=current_trail_sl,
                status=status,
                report_name=report_name
            )
            
            # Update local entry dict for merging
            entry["last_price"] = price
            entry["last_seen_at"] = now_str
            entry["highest_price"] = highest_price
            entry["current_trail_sl"] = current_trail_sl
            entry["status"] = status
            entry["exit_at"] = exit_at
            entry["exit_price"] = exit_price
            entry["exit_reason"] = exit_reason
            
        # 3. Calculate performance metrics
        entry_price = entry["entry_price"]
        highest_price = entry["highest_price"]
        last_price = entry["last_price"]
        
        pnl_pct = ((last_price - entry_price) / entry_price) * 100
        max_gain_pct = ((highest_price - entry_price) / entry_price) * 100
        drawdown_from_high_pct = ((last_price - highest_price) / highest_price) * 100
        
        # 4. Merge tracking fields into the row dict
        row["entry_at"] = entry["entry_at"]
        row["entry_price"] = round(entry_price, 2)
        row["entry_source"] = entry["entry_source"]
        row["target_pct"] = round(entry["target_pct"], 4)
        row["target_price"] = round(entry["target_price"], 2)
        row["sl_pct"] = round(entry["sl_pct"], 4)
        row["sl_price"] = round(entry["sl_price"], 2)
        row["trail_sl_pct"] = round(entry["trail_sl_pct"], 4)
        row["highest_price"] = round(highest_price, 2)
        row["current_trail_sl"] = round(entry["current_trail_sl"], 2)
        row["last_price"] = round(last_price, 2)
        row["last_seen_at"] = entry["last_seen_at"]
        row["status"] = entry["status"]
        row["exit_at"] = entry["exit_at"]
        row["exit_price"] = round(entry["exit_price"], 2) if entry["exit_price"] is not None else None
        row["exit_reason"] = entry["exit_reason"]
        row["pnl_pct"] = round(pnl_pct, 2)
        row["max_gain_pct"] = round(max_gain_pct, 2)
        row["drawdown_from_high_pct"] = round(drawdown_from_high_pct, 2)
        row["trade_active"] = True
        
        enriched_rows.append(row)
        
    return pd.DataFrame(enriched_rows)


def _run_scan_pipeline(
    tickers: list[str],
    index_name: str,
    report_name: str,
    save_csv: bool = True,
    update_bg_cache: bool = False,
) -> "pd.DataFrame":
    """
    Shared scan pipeline used by all scan entry-points (manual thread,
    nightly scheduler, auto-telegram scheduler).

    Steps:
      1. run_batch_screener(tickers, min_score=0)
      2. _annotate_first_seen(df)          — updates first_seen.json
      3. apply_trade_tracking(df, …)       — persists new Running entries
      4. optionally save CSV to reports/
      5. optionally refresh _bg["results"] cache

    The trade-entry gate (total_score >= TRADE_ENTRY_MIN_SCORE) is enforced
    inside apply_trade_tracking() and is unchanged.

    Returns the enriched DataFrame (may be empty).
    """
    df = run_batch_screener(tickers, min_score=0)
    if not df.empty:
        df = _annotate_first_seen(df)
        df = apply_trade_tracking(df, index_name, report_name)

        # Feature 1: Compute LTP delta relative to previous scan run today
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        if "ltp" not in df.columns:
            df["ltp"] = df["last_price"].fillna(df["close"]).fillna(0.0).round(2)

        prev_ltps = {t: tracker_store.get_prev_scan_ltp(t, today_str) for t in df["ticker"]}
        
        def calc_change(r):
            ticker_val = r["ticker"]
            prev_ltp = prev_ltps.get(ticker_val)
            if prev_ltp is not None:
                return round(r["ltp"] - prev_ltp, 2)
            return None

        df["ltp_change_since_scan"] = df.apply(calc_change, axis=1)

        # Upsert current ltp to database scan history
        for _, r in df.iterrows():
            try:
                tracker_store.upsert_scan_ltp(r["ticker"], r["ltp"], today_str)
            except Exception as e:
                log.warning("[scan-pipeline] Failed to upsert scan ltp for %s: %s", r["ticker"], e)

        # Attach source metadata (P2-D)
        try:
            all_indices = list(universe_store.get_index_map().keys())
            clean_indices = [idx for idx in all_indices if idx not in ("all", "nifty500")]
            _, source_map = universe_store.build_unique_universe(clean_indices)
            source_indices_list = []
            source_count_list = []
            for t in df["ticker"]:
                norm = universe_store.normalize_ticker(t)
                indices = source_map.get(norm, [])
                source_indices_list.append(",".join(indices))
                source_count_list.append(len(indices))
            df["source_indices"] = source_indices_list
            df["source_count"] = source_count_list
        except Exception as e:
            log.warning("[scan-pipeline] Failed to attach source metadata: %s", e)
    if save_csv and not df.empty:
        REPORTS_DIR.mkdir(exist_ok=True)
        _cleanup_report_csvs()
        (REPORTS_DIR / report_name).parent.mkdir(exist_ok=True)
        df.to_csv(REPORTS_DIR / report_name, index=False)
        log.info("[scan-pipeline] Saved %d rows → %s", len(df), report_name)
    if update_bg_cache:
        _bg["results"]     = df.to_dict(orient="records") if not df.empty else []
        _bg["finished_at"] = datetime.now(IST).isoformat()
        _bg["error"]       = None
    return df


def _public_csv_url(path: str) -> str:
    """Builds a public URL for a given report/CSV path using APP_PUBLIC_BASE_URL."""
    base = config.APP_PUBLIC_BASE_URL.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def _maybe_send_new_running_alert(entry: dict, entry_id: int) -> None:
    """Checks duplicate status and config, then sends running alert, recording if sent successfully.
    Only allows alerts for entries created today (IST) to prevent legacy alert noise.
    """
    if not config.TELEGRAM_ENABLE_NEW_RUNNING_ALERTS:
        return

    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    if not entry.get("entry_at", "").startswith(today_str):
        log.info("[telegram] Skip new running alert for %s: entry date %s is not today (%s)",
                 entry.get("ticker"), entry.get("entry_at"), today_str)
        return

    event_key = f"new_running:{entry_id}"
    if tracker_store.telegram_event_sent(event_key):
        return

    from telegram_alert import send_new_running_trade_alert
    # Call sender
    if send_new_running_trade_alert(entry):
        tracker_store.record_telegram_event(
            event_key=event_key,
            event_type="new_running",
            entry_id=entry_id,
            ticker=entry.get("ticker")
        )


def _maybe_send_booked_alert(entry: dict, entry_id: int) -> None:
    """Checks duplicate status and config, then sends booked alert, recording if sent successfully.
    Only allows alerts for entries created today (IST) to prevent legacy alert noise.
    """
    if not config.TELEGRAM_ENABLE_BOOKED_ALERTS:
        return

    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    if not entry.get("entry_at", "").startswith(today_str):
        log.info("[telegram] Skip booked alert for %s: entry date %s is not today (%s)",
                 entry.get("ticker"), entry.get("entry_at"), today_str)
        return

    event_key = f"booked:{entry_id}"
    if tracker_store.telegram_event_sent(event_key):
        return

    from telegram_alert import send_booked_trade_alert
    # Call sender
    if send_booked_trade_alert(entry):
        tracker_store.record_telegram_event(
            event_key=event_key,
            event_type="booked",
            entry_id=entry_id,
            ticker=entry.get("ticker")
        )


def _maybe_send_eod_links_alert() -> None:
    """Checks duplicate status and config, then sends daily EOD links summary, recording if sent successfully."""
    if not config.TELEGRAM_ENABLE_EOD_LINKS:
        return

    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    event_key = f"eod_links:{today_str}"
    
    if tracker_store.telegram_event_sent(event_key):
        return

    from telegram_alert import send_eod_links_alert
    base_url = config.APP_PUBLIC_BASE_URL.rstrip("/")
    if send_eod_links_alert(base_url, today_str):
        tracker_store.record_telegram_event(
            event_key=event_key,
            event_type="eod_links",
            entry_id=None,
            ticker=None
        )



def _run_screener_async(tickers: list, min_score: float, index_name: str) -> None:
    """Background thread: runs the screener and caches results."""
    global _bg

    def _progress(done: int, total: int) -> None:
        _bg["progress"] = done

    try:
        import pandas as pd
        df = run_batch_screener(tickers, min_score=min_score, progress_callback=_progress)

        report_ts   = datetime.now(IST).strftime('%Y%m%d_%H%M%S')
        report_name = f"screener_{report_ts}.csv"

        if not df.empty:
            df = _annotate_first_seen(df)
            df = apply_trade_tracking(df, index_name, report_name)

        _bg["results"]     = df.to_dict(orient="records") if not df.empty else []
        _bg["finished_at"] = datetime.now(IST).isoformat()
        _bg["error"]       = None

        # Save CSV report
        REPORTS_DIR.mkdir(exist_ok=True)
        _cleanup_report_csvs()
        fname = REPORTS_DIR / report_name
        if not df.empty:
            df.to_csv(fname, index=False)
        log.info("[bg-screener] Done — %d results saved to %s", len(_bg["results"]), fname)
    except Exception as exc:
        _bg["error"] = str(exc)
        log.error("[bg-screener] Failed: %s", exc)
    finally:
        _bg["running"]  = False
        _bg["progress"] = _bg["total"]


def _normalize_ticker(raw: str) -> str:
    ticker = (raw or "").strip().upper()
    return ticker.replace(".NSE", "").replace(".NS", "")


# ── Nightly batch screener job ────────────────────────────────────────────────

def _nightly_screener() -> None:
    """
    Nightly batch scan at 18:15 IST (Mon–Fri).
    Uses the full SCHEDULED_SCAN_TICKERS universe, applies first-seen
    annotation and trade tracking, and saves a dated CSV report.
    Does NOT overwrite _bg["results"] — that cache belongs to manual runs.
    No Telegram alert is sent — outside market hours.
    """
    now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    tickers = _scheduled_scan_tickers()
    log.info("[nightly] Starting nightly scan at %s (%d tickers)",
             now_ist, len(tickers))
    try:
        report_name = f"screener_{datetime.now(IST).strftime('%Y%m%d')}.csv"
        df = _run_scan_pipeline(
            tickers,
            index_name="nifty500_custom",
            report_name=report_name,
            save_csv=True,
            update_bg_cache=False,   # <— does NOT overwrite manual screener cache
        )
        log.info("[nightly] Done — %d qualifying rows saved.", len(df))
    except Exception as exc:
        log.error("[nightly] Batch screener failed: %s", exc)


# ── Auto-scan for Telegram alerts (market hours only, ALL indices) ──────────

def _auto_telegram_scan() -> None:
    """
    Scheduled auto-scan during NSE market hours (Mon–Fri).
    Runs the full pipeline (first-seen + trade-tracking) on SCHEDULED_SCAN_TICKERS,
    then sends a Telegram alert for the top-scoring picks.
    """
    now_ist = datetime.now(IST)
    market_open  = now_ist.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)

    if not (market_open <= now_ist <= market_close):
        log.info("[auto-scan] Skipped — outside market hours (%s IST)",
             now_ist.strftime("%H:%M"))
        return

    tickers = _scheduled_scan_tickers()
    log.info("[auto-scan] Starting intraday scan at %s IST (%d tickers)",
             now_ist.strftime("%H:%M"), len(tickers))
    try:
        report_name = f"screener_autoscan_{now_ist.strftime('%Y%m%d_%H%M%S')}.csv"
        # ── Step 1: Run the shared pipeline (persists tracker entries) ──────
        df = _run_scan_pipeline(
            tickers,
            index_name="nifty500_custom",
            report_name=report_name,
            save_csv=True,
            update_bg_cache=False,   # <— does NOT overwrite manual screener cache
        )

        if df.empty:
            log.warning("[auto-scan] Screener returned empty DataFrame.")
            return

        # ── Step 2: Send Telegram alert for top picks (best-effort) ─────────
        top = df[df["total_score"] >= 70].head(5)
        if top.empty:
            log.info("[auto-scan] No stocks scored >= 70 this run — no alert sent.")
            return

        # Enrich top picks with live LTP from Angel One (best-effort)
        top = top.copy()
        top["ltp"] = [None] * len(top)
        if angel_is_configured():
            ltps = []
            for t in top["ticker"].tolist():
                try:
                    ltps.append(angel_get_ltp(t))
                except Exception:
                    ltps.append(None)
            top["ltp"] = ltps

        try:
            from telegram_alert import send_top_picks
            send_top_picks(top)
            log.info("[auto-scan] Telegram alert sent for %d top picks.", len(top))
        except Exception as tg_exc:
            log.warning("[auto-scan] Telegram send skipped: %s", tg_exc)

    except Exception as exc:
        log.error("[auto-scan] Failed: %s", exc)


def _auto_full_scan() -> None:
    """
    Rolling 30-minute auto-scan during market hours (Mon–Fri).
    Unlike _auto_telegram_scan, this DOES update the in-memory UI cache
    (_bg["results"]) so the frontend reflects the new scan without a manual trigger.
    """
    # Concurrency Guard: Check if a scan is already in flight (manual or scheduled)
    if _bg.get("running", False):
        log.warning("[auto-scan-30min] Skipped — another scan is currently in progress.")
        return

    now_ist = datetime.now(IST)
    market_open  = now_ist.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    if not (market_open <= now_ist <= market_close):
        log.info("[auto-scan-30min] Skipped — outside market hours (%s IST)", now_ist.strftime("%H:%M"))
        return

    tickers = _scheduled_scan_tickers()
    report_name = f"screener_autoscan30_{now_ist.strftime('%Y%m%d_%H%M%S')}.csv"
    try:
        # Mark running to prevent concurrency and let UI know
        _bg["running"] = True
        _bg["progress"] = 0
        df = _run_scan_pipeline(
            tickers,
            index_name="nifty500_custom",
            report_name=report_name,
            save_csv=True,
            update_bg_cache=True,
        )
        log.info("[auto-scan-30min] Completed at %s IST — %d rows.", now_ist.strftime("%H:%M"), len(df))
    except Exception as exc:
        log.warning("[auto-scan-30min] Failed: %s", exc)
        _bg["error"] = str(exc)
    finally:
        _bg["running"] = False



# ── Shared Exit Evaluation Helper ─────────────────────────────────────────────

def _evaluate_exit(entry: dict, price: float, now_str: str) -> dict:
    """
    Pure business logic helper to evaluate target and stop-loss breach status.
    Returns a dict containing the updated status, breach counting state, and exit details.
    Does NOT write to the database, append snapshots, or send alerts.
    """
    sl_price = entry["sl_price"]
    target_price = entry["target_price"]
    current_trail_sl = entry["current_trail_sl"]
    highest_price = entry["highest_price"]
    trail_sl_pct = entry["trail_sl_pct"]

    # Update highest price and trailing SL if new high
    if price > highest_price:
        highest_price = price
        current_trail_sl = round(highest_price * (1 - trail_sl_pct), 2)

    status = "active"
    exit_at = None
    exit_price = None
    exit_reason = None

    CONFIRM_BREACHES_REQUIRED = 2
    old_breach_count = entry.get("sl_breach_count") or 0
    new_breach_count = old_breach_count
    new_breach_since = entry.get("sl_breach_since")

    if price <= sl_price or price <= current_trail_sl:
        new_breach_count += 1
        if old_breach_count == 0:
            new_breach_since = now_str
        if new_breach_count >= CONFIRM_BREACHES_REQUIRED:
            status = "sl_hit" if price <= sl_price else "trail_sl_hit"
            exit_at = now_str
            exit_price = price
            exit_reason = ("Fixed Stop Loss hit (confirmed)" if status == "sl_hit"
                           else "Trailing Stop Loss hit (confirmed)")
    elif price >= target_price:
        status = "target_hit"
        exit_at = now_str
        exit_price = price
        exit_reason = "Target price hit"
    else:
        new_breach_count = 0
        new_breach_since = None

    return {
        "status": status,
        "exit_at": exit_at,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "highest_price": highest_price,
        "current_trail_sl": current_trail_sl,
        "sl_breach_count": new_breach_count,
        "sl_breach_since": new_breach_since
    }


# ── Live tracker price refresh ────────────────────────────────────────────────

def _refresh_tracker_prices() -> None:
    """
    Background job: fetch live LTP for all active gated tracker entries and
    update their state (last_price, highest_price, current_trail_sl, status).

    Runs every 3 minutes during market hours (9:15–15:30 IST Mon–Fri).
    This keeps the Running mode PnL live even when no screener run is triggered.
    """
    now_ist = datetime.now(IST)
    market_open  = now_ist.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)

    if not (market_open <= now_ist <= market_close):
        return  # Silent skip outside market hours

    if not angel_is_configured():
        log.debug("[tracker-refresh] Angel One not configured — skip.")
        return

    active_rows = tracker_store.get_running_entries()
    if not active_rows:
        return

    log.info("[tracker-refresh] Refreshing LTP for %d active entries …", len(active_rows))
    now_str = now_ist.isoformat()
    updated = 0
    exited  = 0
    failed = 0
    relogin_attempted = False

    for entry in active_rows:
        ticker     = entry["ticker"]
        entry_id   = entry["id"]
        entry_price    = entry["entry_price"]
        highest_price  = entry["highest_price"]
        current_trail_sl = entry["current_trail_sl"]
        sl_price       = entry["sl_price"]
        target_price   = entry["target_price"]
        trail_sl_pct   = entry["trail_sl_pct"]

        price = None
        try:
            price = angel_get_ltp(ticker)
        except Exception as exc:
            log.warning("[tracker-refresh] LTP failed for %s: %s", ticker, exc)

        if price is None and not relogin_attempted:
            age = angel_session_age()
            if age is None or age >= 3600:
                log.info("[tracker-refresh] LTP failed and session stale (%s). Forcing relogin once for loop recovery...", age)
                relogin_attempted = True
                if angel_force_relogin():
                    try:
                        price = angel_get_ltp(ticker, _retry=False)
                    except Exception as exc:
                        log.warning("[tracker-refresh] LTP failed on retry for %s: %s", ticker, exc)

        if price is None:
            failed += 1
            continue

        # Evaluate state using shared helper
        eval_res = _evaluate_exit(entry, price, now_str)
        status = eval_res["status"]
        exit_at = eval_res["exit_at"]
        exit_price = eval_res["exit_price"]
        exit_reason = eval_res["exit_reason"]
        highest_price = eval_res["highest_price"]
        current_trail_sl = eval_res["current_trail_sl"]
        new_breach_count = eval_res["sl_breach_count"]
        new_breach_since = eval_res["sl_breach_since"]

        if status != "active":
            tracker_store.close_entry(
                entry_id=entry_id,
                status=status,
                exit_at=exit_at,
                exit_price=exit_price,
                exit_reason=exit_reason,
                report_name="ltp_refresh",
            )
            # Send booked alert
            entry_copy = dict(entry)
            entry_copy["status"] = status
            entry_copy["exit_at"] = exit_at
            entry_copy["exit_price"] = exit_price
            entry_copy["exit_reason"] = exit_reason
            if entry_price > 0:
                entry_copy["realized_pnl_pct"] = ((exit_price - entry_price) / entry_price) * 100
            else:
                entry_copy["realized_pnl_pct"] = 0.0
            entry_copy["realized_amount"] = exit_price - entry_price
            _maybe_send_booked_alert(entry_copy, entry_id)
            _trigger_in_app_notification("booked", ticker, f"BOOKED: {ticker} hit {exit_reason} (Type: {status}) at ₹{price:.2f}")

            log.info("[tracker-refresh] %s → %s @ ₹%.2f", ticker, status, price)
            exited += 1
        else:
            tracker_store.update_entry_state(
                entry_id=entry_id,
                last_price=price,
                last_seen_at=now_str,
                highest_price=highest_price,
                current_trail_sl=current_trail_sl,
                report_name="ltp_refresh",
                sl_breach_count=new_breach_count,
                sl_breach_since=new_breach_since
            )
            updated += 1

    log.info(
        "[tracker-refresh] Done — %d updated, %d exited, %d failed (total %d entries)",
        updated, exited, failed, len(active_rows),
    )


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.after_request
def add_header(response):
    """Add headers to disable browser caching on localhost."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/api/notifications")
def api_notifications():
    since_id = request.args.get("since_id", type=int)
    with _in_app_notifications_lock:
        if since_id is not None:
            filtered = [n for n in _in_app_notifications if n["id"] > since_id]
        else:
            filtered = _in_app_notifications[-10:]
        return jsonify({"notifications": filtered})


@app.route("/")
def index():
    return render_template("index.html")


# ── Sector lookup for Quick Load dropdown ─────────────────────────────────────
# Maps ticker → sector label shown in the sidebar list
_SECTOR: dict[str, str] = config.STOCK_SECTOR


@app.route("/api/universe")
def api_universe():
    """
    Return ticker+sector lists for one or more index groups.
    ?index=nifty50           → {nifty50: [{ticker, sector}, ...]}
    ?index=nifty50,next50    → {nifty50: [...], next50: [...]}
    ?index=all               → returns all available groups
    Also returns a 'combined' deduplicated flat list.
    """
    raw = request.args.get("index", "").strip().lower()
    if not raw or raw == "all":
        parts = ["all"]
    else:
        parts = [p.strip() for p in raw.split(",")]

    payload: dict[str, list] = {}
    seen: set[str] = set()
    combined: list[dict] = []

    for part in parts:
        if part == "all":
            tickers = _default_scan_tickers()
        else:
            tickers = INDEX_MAP.get(part)
            
        if tickers is None:
            continue
        group_list = []
        for t in tickers:
            entry = {"ticker": t, "sector": _SECTOR.get(t, "Other"), "index": part}
            group_list.append(entry)
            if t not in seen:
                seen.add(t)
                combined.append(entry)
        payload[part] = group_list

    counts = {}
    universes = universe_store.load_universes()
    for k, tickers_list in universes.items():
        counts[k] = len(tickers_list)
    counts["all"] = len(combined)

    return jsonify({"groups": payload, "combined": combined, "total": len(combined), "counts": counts})



@app.route("/api/health")
def health():
    return jsonify({
        "ok":            True,
        "configured":    True,
        "provider":      "yfinance",
        "angel_one_ltp": angel_is_configured(),
    })


@app.route("/api/status")
def api_status():
    """Lightweight status endpoint polled by the UI every few seconds."""
    age = angel_session_age()
    return jsonify({
        "ok":              True,
        "angel_configured": angel_is_configured(),
        "angel_session":   "active" if (age is not None and age < 21600) else "none",
        "angel_session_age_s": round(age, 0) if age else None,
    })


@app.route("/api/angel/relogin", methods=["POST", "GET"])
def api_angel_relogin():
    """Force a fresh Angel One login. Call from UI or curl when LTP breaks."""
    if not angel_is_configured():
        return jsonify({"ok": False, "error": "Credentials not configured in angel_ltp.py"}), 503
    success = angel_force_relogin()
    if success:
        return jsonify({"ok": True, "message": "Angel One relogin successful"})
    return jsonify({"ok": False, "error": "Relogin failed — check logs"}), 502


@app.route("/api/fundamentals")
def api_fundamentals():
    ticker = _normalize_ticker(request.args.get("ticker", ""))
    if not ticker:
        return jsonify({"error": "Missing ticker"}), 400
    data, error = fetch_fundamentals_result(ticker)
    if data is None:
        return jsonify({"error": error or f"Unable to fetch fundamentals for {ticker}"}), 502
    return jsonify({"ticker": ticker, "fundamentals": data})


@app.route("/api/stock")
def api_stock():
    ticker = _normalize_ticker(request.args.get("ticker", ""))
    if not ticker:
        return jsonify({"error": "Missing ticker"}), 400

    fund_data, error = fetch_fundamentals_result(ticker)
    if fund_data is None:
        return jsonify({"error": error or f"Unable to fetch fundamentals for {ticker}"}), 502

    price_df     = fetch_price_data(ticker, period=200)
    nifty_series = fetch_nifty_data(period=200)
    composite    = build_composite_score(ticker, fund_data, price_df=price_df, nifty_data=nifty_series)

    price_rows = []
    if price_df is not None:
        for _, row in price_df.reset_index().iterrows():
            price_rows.append({
                "date":           row["date"].strftime("%Y-%m-%d"),
                "open":           float(row["open"]),
                "high":           float(row["high"]),
                "low":            float(row["low"]),
                "close":          float(row["close"]),
                "adjusted_close": (
                    float(row["adjusted_close"])
                    if "adjusted_close" in row and row["adjusted_close"] == row["adjusted_close"]
                    else float(row["close"])
                ),
                "volume":         float(row["volume"]),
            })

    # ── Angel One LTP override ───────────────────────────────────────────────────
    angel_ltp = angel_get_ltp(ticker)

    # ── P2-B: NSE Delivery % + OI enrichment (best-effort, non-blocking) ─────
    delivery_info = {}
    oi_info       = {}
    try:
        delivery_info = fetch_nse_delivery(ticker)
    except Exception:
        pass
    try:
        oi_info = fetch_nse_oi(ticker)
    except Exception:
        pass

    # Wire delivery_pct + OI into composite technical sub-score
    d_pct = delivery_info.get("delivery_pct")
    if d_pct is not None:
        composite.technical.delivery_pct = float(d_pct)
        if float(d_pct) >= 65:
            composite.technical.delivery_score = 5
        elif float(d_pct) >= 50:
            composite.technical.delivery_score = 3
        composite.total = round(min(100, composite.total + composite.technical.delivery_score), 1)

    pcr = oi_info.get("pcr")
    if pcr is not None:
        composite.technical.pcr      = float(pcr)
        composite.technical.oi_signal = oi_info.get("oi_signal", "")
        if float(pcr) >= 1.3:
            composite.technical.oi_score = 3
        elif float(pcr) >= 0.8:
            composite.technical.oi_score = 1
        composite.total = round(min(100, composite.total + composite.technical.oi_score), 1)

    return jsonify({
        "ticker":       ticker,
        "fundamentals": fund_data,
        "price_data":   price_rows,
        "composite":    composite.to_dict(),
        "ltp": {
            "value":  angel_ltp,
            "source": "angel_one" if angel_ltp else "yfinance",
        },
        "delivery":     delivery_info,
        "oi":           oi_info,
    })


@app.route("/api/batch")
def api_batch():
    """Legacy synchronous batch (kept for backward compat — prefer /api/screener/run)."""
    min_score   = float(request.args.get("min_score", 0))
    index_group = request.args.get("index", "nifty50").lower()
    tickers     = INDEX_MAP.get(index_group, NIFTY50_TICKERS)
    try:
        df = run_batch_screener(tickers, min_score=min_score)
        return jsonify({"count": len(df), "index": index_group, "results": df.to_dict(orient="records")})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Background screener endpoints ─────────────────────────────────────────────

@app.route("/api/screener/run", methods=["POST", "GET"])
def api_screener_run():
    """Start a non-blocking background screener run. Returns immediately."""
    global _bg
    if _bg["running"]:
        return jsonify({"ok": False, "error": "Screener already running", "progress": _bg["progress"], "total": _bg["total"]}), 409

    raw_index = request.args.get("index", "").strip().lower()
    min_score = float(request.args.get("min_score", 0))
    
    if not raw_index or raw_index == "all":
        tickers = _default_scan_tickers()
        raw_index_for_bg = "all"
    else:
        parts = [p.strip() for p in raw_index.split(",")]
        collapsed = universe_store._collapse_overlapping_indices(parts)
        tickers, _ = universe_store.build_unique_universe(collapsed)
        if not tickers:
            tickers = _default_scan_tickers()
            raw_index_for_bg = "all"
        else:
            collapsed_in_order = []
            for p in parts:
                if p in collapsed and p not in collapsed_in_order:
                    collapsed_in_order.append(p)
            raw_index_for_bg = ",".join(collapsed_in_order)

    with _bg_lock:
        _bg.update({
            "running":     True,
            "progress":    0,
            "total":       len(tickers),
            "started_at":  datetime.now(IST).isoformat(),
            "finished_at": None,
            "index":       raw_index_for_bg,
            "error":       None,
        })

    # Force min_score=0.0 in the background run. The backend will screen all stocks,
    # populating the sector overview and saving a complete CSV. The frontend UI
    # is already doing client-side real-time filtering with its own min_score slider.
    t = threading.Thread(target=_run_screener_async, args=(tickers, 0.0, raw_index_for_bg), daemon=True)
    t.start()
    return jsonify({"ok": True, "total": len(tickers), "index": raw_index_for_bg})



@app.route("/api/screener/status")
def api_screener_status():
    """Poll this every 2 s to track background run progress."""
    pct = round((_bg["progress"] / _bg["total"]) * 100, 1) if _bg["total"] else 0
    return jsonify({
        "running":     _bg["running"],
        "progress":    _bg["progress"],
        "total":       _bg["total"],
        "pct":         pct,
        "started_at":  _bg["started_at"],
        "finished_at": _bg["finished_at"],
        "index":       _bg["index"],
        "error":       _bg["error"],
    })


@app.route("/api/screener/latest")
def api_screener_latest():
    """Return the most recent cached screener results (populated after a run)."""
    results = _bg.get("results", [])
    return jsonify({
        "running":     _bg["running"],
        "finished_at": _bg["finished_at"],
        "count":       len(results),
        "results":     results,
    })


@app.route("/api/reports/today")
def api_reports_today():
    report = _latest_report_for_day()
    if report is None:
        return jsonify({"ok": False, "error": "No report generated for today yet."}), 404

    stat = report.stat()
    return jsonify({
        "ok": True,
        "name": report.name,
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=IST).isoformat(),
        "download_url": _public_csv_url("/reports/today.csv"),
    })


@app.route("/reports/today.csv")
def download_today_report():
    report = _latest_report_for_day()
    if report is None:
        return jsonify({"ok": False, "error": "No report generated for today yet."}), 404
    return send_file(report, as_attachment=True, download_name=report.name, mimetype="text/csv")


@app.route("/reports/today_clean.csv")
def download_today_clean_report():
    report = _latest_report_for_day()
    if report is None:
        return jsonify({"ok": False, "error": "No report generated for today yet."}), 404

    try:
        import pandas as pd
        import io
        from flask import Response

        df = pd.read_csv(report)
        if df.empty:
            cols = ["ticker", "since", "score", "grd", "signal", "close", "ltp", "ltp_change_since_scan", "stop", "rsi", "atr", "filter"]
            return Response(",".join(cols) + "\r\n", mimetype="text/csv",
                            headers={"Content-Disposition": f"attachment; filename={report.stem}_clean.csv"})

        # Filter to total_score >= 70
        df = df[df["total_score"] >= 70]

        # Build curated columns
        clean_df = pd.DataFrame()
        clean_df["ticker"] = df["ticker"]
        clean_df["since"] = df["first_seen"]
        clean_df["score"] = df["total_score"]
        clean_df["grd"] = df["grade"]
        clean_df["signal"] = df["signal"]
        clean_df["close"] = df["close"].fillna(0.0).round(2)
        clean_df["ltp"] = df["last_price"].fillna(df["close"]).fillna(0.0).round(2)
        
        # Add ltp_change_since_scan
        if "ltp_change_since_scan" in df.columns:
            clean_df["ltp_change_since_scan"] = df["ltp_change_since_scan"]
        else:
            clean_df["ltp_change_since_scan"] = None

        clean_df["stop"] = df["stop_loss"].fillna(0.0).round(2)
        clean_df["rsi"] = df["rsi"].fillna(0.0).round(1)
        clean_df["atr"] = df["atr"].fillna(0.0).round(2)
        clean_df["filter"] = df["passes_filter"].map(lambda x: "PASS" if x is True else "FAIL")

        # Convert to CSV string
        csv_buffer = io.StringIO()
        clean_df.to_csv(csv_buffer, index=False)
        csv_content = csv_buffer.getvalue()

        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={report.stem}_clean.csv"}
        )
    except Exception as e:
        log.error("Failed to build clean EOD report CSV: %s", e)
        return jsonify({"ok": False, "error": f"Failed to build clean report: {str(e)}"}), 500


def _build_new_rows(today_only: bool = False) -> list[dict]:
    results = _bg.get("results", [])
    if today_only:
        return [r for r in results if r.get("days_in_screener") == 0]
    return results


def _build_running_rows() -> list[dict]:
    """Full running-entry row shape used by the JSON API.

    Returns ALL active positions from tracker_store, regardless of
    their current re-scan score. The score gate applies only at entry time —
    once a trade is active it must remain visible until it exits via
    target/SL/trailing-SL.
    """
    rows = tracker_store.get_running_entries()
    return tracker_store.enrich_tracker_rows(rows)


def _build_booked_rows() -> list[dict]:
    rows = tracker_store.get_booked_entries()
    return tracker_store.enrich_tracker_rows(rows)


BOOKED_CSV_COLUMNS = [
    "ticker", "entry_date", "exit_date", "entry_price", "exit_price",
    "target", "sl", "trail_sl", "highest",
    "pnl_pct", "pnl_amount", "days", "exit_type"
]


def _build_booked_csv_rows() -> list[dict]:
    """
    Returns booked entries shaped for CSV export — exactly 13 columns
    in the order defined by BOOKED_CSV_COLUMNS.
    """
    enriched = _build_booked_rows()   # full-detail rows (JSON API shape)
    csv_rows = []
    for r in enriched:
        entry_date = "—"
        try:
            raw_at = (r.get("entry_at") or "").split("+")[0].split("Z")[0]
            entry_date = datetime.fromisoformat(raw_at).strftime("%#d %b")
        except Exception:
            pass

        exit_date = "—"
        try:
            raw_at = (r.get("exit_at") or "").split("+")[0].split("Z")[0]
            exit_date = datetime.fromisoformat(raw_at).strftime("%#d %b")
        except Exception:
            pass

        # Trailing stop column behavior:
        # - if status == "trail_sl_hit" -> show the trail SL value
        # - if status == "sl_hit" or status == "target_hit" -> leave the trail SL field blank/None
        status = r.get("status")
        trail_sl = r.get("current_trail_sl") if status == "trail_sl_hit" else None

        csv_rows.append({
            "ticker":      r.get("ticker"),
            "entry_date":  entry_date,
            "exit_date":   exit_date,
            "entry_price": r.get("entry_price"),
            "exit_price":  r.get("exit_price"),
            "target":      r.get("target_price"),
            "sl":          r.get("sl_price"),
            "trail_sl":    trail_sl,
            "highest":     r.get("highest_price"),
            "pnl_pct":     r.get("realized_pnl_pct"),
            "pnl_amount":  r.get("realized_amount"),
            "days":        r.get("days_held"),
            "exit_type":   status,
        })
    return csv_rows


# ── Running CSV export — 11-column shape ─────────────────────────────────────
# Exact column order mandated by the spec:
RUNNING_CSV_COLUMNS = [
    "ticker", "entry_date", "entry_price", "current_price",
    "target", "sl", "trail_sl", "highest",
    "pnl_pct", "pnl_amount", "days",
]


def _build_running_csv_rows() -> list[dict]:
    """
    Returns running entries shaped for CSV export — exactly 11 columns
    in the order defined by RUNNING_CSV_COLUMNS.

    When there are no active running positions, returns an empty list.
    The _rows_to_csv_response helper will emit the correct 11-column header
    even in that case because it uses RUNNING_CSV_COLUMNS explicitly.

    Field mapping (CSV ← internal):
        ticker        ← ticker
        entry_date    ← entry_at   (formatted "10 Jul")
        entry_price   ← entry_price
        current_price ← last_price
        target        ← target_price
        sl            ← sl_price
        trail_sl      ← current_trail_sl
        highest       ← highest_price
        pnl_pct       ← pnl_pct
        pnl_amount    ← running_amount
        days          ← days_running
    """
    enriched = _build_running_rows()   # full-detail rows (JSON API shape)
    csv_rows = []
    for r in enriched:
        # Format entry_at as "10 Jul" (Windows-safe: %#d avoids leading zero)
        entry_date = "—"
        try:
            raw_at = (r.get("entry_at") or "").split("+")[0].split("Z")[0]
            entry_date = datetime.fromisoformat(raw_at).strftime("%#d %b")
        except Exception:
            pass

        csv_rows.append({
            "ticker":        r.get("ticker"),
            "entry_date":    entry_date,
            "entry_price":   r.get("entry_price"),
            "current_price": r.get("last_price"),
            "target":        r.get("target_price"),
            "sl":            r.get("sl_price"),
            "trail_sl":      r.get("current_trail_sl"),
            "highest":       r.get("highest_price"),
            "pnl_pct":       r.get("pnl_pct"),
            "pnl_amount":    r.get("running_amount"),
            "days":          r.get("days_running"),
        })
    return csv_rows

def _rows_to_csv_response(rows: list[dict], filename: str, columns: list[str] | None = None):
    """
    Serialize `rows` to a streaming CSV download response.
    If `columns` is provided, the CSV will use exactly those columns in order
    (emitting the correct header even when rows is empty).
    """
    import io
    import pandas as pd
    if columns is not None:
        # Always emit the requested column header, even with zero rows
        df = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)
    elif not rows:
        df = pd.DataFrame()
    else:
        df = pd.DataFrame(rows)

    output = io.BytesIO()
    df.to_csv(output, index=False)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="text/csv"
    )

@app.route("/api/screener/new")
def api_screener_new():
    today_only = request.args.get("today_only", "0") in ("1", "true", "yes")
    rows = _build_new_rows(today_only=today_only)
    return jsonify({
        "mode": "new",
        "count": len(rows),
        "results": rows
    })

@app.route("/api/screener/running")
def api_screener_running():
    rows = _build_running_rows()
    return jsonify({
        "mode": "running",
        "count": len(rows),
        "results": rows
    })

@app.route("/api/screener/booked")
def api_screener_booked():
    rows = _build_booked_rows()
    return jsonify({
        "mode": "booked",
        "count": len(rows),
        "results": rows
    })


@app.route("/api/tracker/refresh", methods=["POST"])
def api_tracker_refresh():
    """Manually trigger a live LTP refresh for all active tracker entries."""
    if not angel_is_configured():
        return jsonify({"ok": False, "error": "Angel One not configured"}), 503
    try:
        _refresh_tracker_prices()
        return jsonify({"ok": True, "message": "Tracker prices refreshed"})
    except Exception as exc:
        log.error("[api/tracker/refresh] %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

NEW_CSV_COLUMNS = [
    "ticker", "since", "score", "grd", "signal", "close", "ltp", "ltp_change_since_scan", "stop", "rsi", "atr", "filter"
]


def _build_new_csv_rows(today_only: bool = False) -> list[dict]:
    """
    Returns clean new screener rows shaped for CSV export — exactly 12 columns
    in the order defined by NEW_CSV_COLUMNS.
    Only includes rows where total_score >= 70.
    """
    results = _bg.get("results", [])
    if today_only:
        results = [r for r in results if r.get("days_in_screener") == 0]

    csv_rows = []
    for r in results:
        score = r.get("total_score")
        if score is None or score < 70.0:
            continue

        # Extract and format fields matching download_today_clean_report
        ticker = r.get("ticker", "")
        since = r.get("scan_date", r.get("first_seen", ""))
        grd = r.get("grade", "")
        signal = r.get("signal", "")
        close = round(float(r.get("close") or 0.0), 2)
        ltp = round(float(r.get("last_price") or r.get("close") or 0.0), 2)
        
        # Feature 1: extract ltp_change_since_scan from memory cache
        ltp_change = r.get("ltp_change_since_scan")
        ltp_change_val = round(float(ltp_change), 2) if ltp_change is not None else None

        stop = round(float(r.get("stop_loss") or 0.0), 2)
        rsi = round(float(r.get("rsi") or 0.0), 1)
        atr = round(float(r.get("atr") or 0.0), 2)

        passes_filter = r.get("passes_filter")
        flt = "PASS" if passes_filter is True else "FAIL"

        csv_rows.append({
            "ticker": ticker,
            "since": since,
            "score": score,
            "grd": grd,
            "signal": signal,
            "close": close,
            "ltp": ltp,
            "ltp_change_since_scan": ltp_change_val,
            "stop": stop,
            "rsi": rsi,
            "atr": atr,
            "filter": flt
        })
    return csv_rows


@app.route("/api/reports/new.csv")
def download_new_csv():
    today_only = request.args.get("today_only", "0") in ("1", "true", "yes")
    rows = _build_new_csv_rows(today_only=today_only)
    return _rows_to_csv_response(rows, "screener_new.csv", columns=NEW_CSV_COLUMNS)

@app.route("/api/reports/running.csv")
def download_running_csv():
    """Download running positions as a clean 11-column CSV.
    Always emits the correct header even when there are zero active positions.
    """
    rows = _build_running_csv_rows()
    return _rows_to_csv_response(rows, "screener_running.csv", columns=RUNNING_CSV_COLUMNS)

@app.route("/api/reports/booked.csv")
def download_booked_csv():
    rows = _build_booked_csv_rows()
    return _rows_to_csv_response(rows, "screener_booked.csv", columns=BOOKED_CSV_COLUMNS)


@app.route("/api/screener/tracking/all")
def api_screener_tracking_all():
    """
    Returns a CSV file containing the complete active and historical lifecycle entries.
    """
    import io
    import pandas as pd
    entries = tracker_store.export_all_entries()
    if not entries:
        return jsonify({"ok": True, "message": "No tracking entries found in database"}), 200
        
    df = pd.DataFrame(entries)
    
    # Calculate performance fields
    def add_pnl_fields(row):
        entry_price = row["entry_price"]
        highest_price = row["highest_price"]
        last_price = row["last_price"]
        
        pnl = ((last_price - entry_price) / entry_price) * 100 if entry_price else 0.0
        max_gain = ((highest_price - entry_price) / entry_price) * 100 if entry_price else 0.0
        drawdown = ((last_price - highest_price) / highest_price) * 100 if highest_price else 0.0
        
        row["pnl_pct"] = round(pnl, 2)
        row["max_gain_pct"] = round(max_gain, 2)
        row["drawdown_from_high_pct"] = round(drawdown, 2)
        return row
        
    df = df.apply(add_pnl_fields, axis=1)
    
    # Re-order columns nicely
    cols_order = [
        "id", "ticker", "index_name", "entry_at", "entry_price", "entry_source",
        "target_pct", "target_price", "sl_pct", "sl_price", "trail_sl_pct",
        "highest_price", "current_trail_sl", "last_price", "last_seen_at",
        "status", "exit_at", "exit_price", "exit_reason", "pnl_pct", "max_gain_pct",
        "drawdown_from_high_pct", "first_report_name", "last_report_name"
    ]
    cols_order = [c for c in cols_order if c in df.columns]
    df = df[cols_order]
    
    output = io.BytesIO()
    df.to_csv(output, index=False)
    output.seek(0)
    
    return send_file(
        output,
        as_attachment=True,
        download_name="screener_lifecycle_tracker.csv",
        mimetype="text/csv"
    )


@app.route("/api/ltp")
def api_ltp():
    """Quick real-time LTP for a single ticker via Angel One."""
    ticker = _normalize_ticker(request.args.get("ticker", ""))
    if not ticker:
        return jsonify({"error": "Missing ticker"}), 400
    if not angel_is_configured():
        return jsonify({"error": "Angel One credentials not configured", "hint": "Fill ANGEL_* constants in angel_ltp.py"}), 503
    ltp = angel_get_ltp(ticker)
    if ltp is None:
        return jsonify({"ticker": ticker, "ltp": None, "source": "angel_one", "note": "Market may be closed or token not mapped"})
    return jsonify({"ticker": ticker, "ltp": ltp, "source": "angel_one"})


@app.route("/api/ltp/batch")
def api_ltp_batch():
    """
    Fetch LTP for multiple tickers in one request.
    Query param: tickers=RELIANCE,TCS,INFY,...  (comma-separated)
    Returns: { "ltps": { "RELIANCE": 1291.0, "TCS": null, ... }, "source": "angel_one" }
    Calls are paced inside angel_ltp.get_ltp(), so this endpoint can stay simple
    while still respecting Angel One rate limits.
    """
    raw = request.args.get("tickers", "")
    if not raw:
        return jsonify({"error": "Missing tickers param"}), 400
    tickers = [_normalize_ticker(t) for t in raw.split(",") if t.strip()]
    if not tickers:
        return jsonify({"error": "No valid tickers provided"}), 400
    if not angel_is_configured():
        return jsonify({"error": "Angel One credentials not configured"}), 503

    results: dict = {}
    for i, ticker in enumerate(tickers):
        try:
            results[ticker] = angel_get_ltp(ticker)
        except Exception as exc:
            log.warning("Batch LTP failed for %s: %s", ticker, exc)
            results[ticker] = None

    return jsonify({"ltps": results, "source": "angel_one"})


@app.route("/api/nse/delivery")
def api_delivery():
    ticker = _normalize_ticker(request.args.get("ticker", ""))
    if not ticker:
        return jsonify({"error": "Missing ticker"}), 400
    return jsonify(fetch_nse_delivery(ticker))


@app.route("/api/nse/oi")
def api_oi():
    ticker = _normalize_ticker(request.args.get("ticker", ""))
    if not ticker:
        return jsonify({"error": "Missing ticker"}), 400
    return jsonify(fetch_nse_oi(ticker))


# ── Entry Point ───────────────────────────────────────────────────────────────

def _extract_report_scan_date(report_path: Path) -> str:
    name = report_path.name
    parts = name.split("_")
    for p in parts:
        if len(p) == 8 and p.isdigit():
            try:
                dt = datetime.strptime(p, "%Y%m%d")
                return dt.strftime("%d/%m/%Y")
            except Exception:
                pass
        if len(p) >= 8 and p[:8].isdigit() and p[8:] in (".csv", ""):
            try:
                dt = datetime.strptime(p[:8], "%Y%m%d")
                return dt.strftime("%d/%m/%Y")
            except Exception:
                pass
                
    mtime = report_path.stat().st_mtime
    dt = datetime.fromtimestamp(mtime, tz=IST)
    return dt.strftime("%d/%m/%Y")


def _pre_load_latest_report() -> None:
    """Pre-load the most recent CSV report from disk into memory cache at startup."""
    global _bg
    try:
        # Check today's latest report first
        report = _latest_report_for_day()
        if not report:
            # If no report for today, check for any latest report in REPORTS_DIR
            if REPORTS_DIR.exists():
                matches = [path for path in REPORTS_DIR.glob("*.csv") if path.is_file()]
                if matches:
                    report = max(matches, key=lambda path: path.stat().st_mtime)
        
        if report and report.exists():
            import pandas as pd
            df = pd.read_csv(report)
            if not df.empty:
                # Convert nan values to None so that the JSON encoder outputs null instead of NaN
                # which breaks the browser
                records = df.to_dict(orient="records")
                
                scan_date_val = _extract_report_scan_date(report)
                # Replace float NaN with None for safety
                for r in records:
                    r["scan_date"] = r.get("scan_date") or scan_date_val
                    for k, v in list(r.items()):
                        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                            r[k] = None
                            
                _bg["results"] = records
                _bg["finished_at"] = datetime.fromtimestamp(report.stat().st_mtime, tz=IST).isoformat()
                _bg["total"] = len(records)
                _bg["progress"] = len(records)
                log.info("[startup] Pre-loaded %d results from latest report: %s (scan_date: %s)", len(records), report.name, scan_date_val)
    except Exception as exc:
        log.warning("[startup] Failed to pre-load latest report: %s", exc)


def _start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=IST)

    # Hourly CSV cleanup
    scheduler.add_job(
        _cleanup_report_csvs,
        CronTrigger(minute=0, timezone=IST),
        id="reports_cleanup",
        replace_existing=True,
    )

    # Nightly data refresh (18:15 IST Mon–Fri) — no Telegram, just saves CSV
    scheduler.add_job(
        _nightly_screener,
        CronTrigger(day_of_week="mon-fri", hour=18, minute=15, timezone=IST),
        id="nightly_screener",
        replace_existing=True,
    )

    # ── Auto Telegram scan — ALL indices, 4 times per trading day ────────────
    # Fires at 09:30, 11:00, 13:00, 15:00 IST (Mon–Fri)
    for _hour, _minute in [(9, 30), (11, 0), (13, 0), (15, 0)]:
        scheduler.add_job(
            _auto_telegram_scan,
            CronTrigger(day_of_week="mon-fri", hour=_hour, minute=_minute, timezone=IST),
            id=f"auto_telegram_{_hour:02d}{_minute:02d}",
            replace_existing=True,
        )

    # ── Live tracker price refresh — every 3 min during market hours ─────────
    scheduler.add_job(
        _refresh_tracker_prices,
        CronTrigger(day_of_week="mon-fri", minute="*/3", timezone=IST),
        id="tracker_price_refresh",
        replace_existing=True,
    )

    # ── Rolling 30-minute auto-scan — Mon-Fri 9-15 (9:15-15:30 IST market hours) ──
    scheduler.add_job(
        _auto_full_scan,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/30", timezone=IST),
        id="auto_scan_30min",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # ── EOD CSV Links Alert (Mon-Fri at TELEGRAM_EOD_HOUR:TELEGRAM_EOD_MINUTE IST) ──
    scheduler.add_job(
        _maybe_send_eod_links_alert,
        CronTrigger(day_of_week="mon-fri", hour=config.TELEGRAM_EOD_HOUR, minute=config.TELEGRAM_EOD_MINUTE, timezone=IST),
        id="telegram_eod_links",
        replace_existing=True,
    )


    _cleanup_report_csvs()
    _pre_load_latest_report()  # Pre-load latest results into memory cache
    scheduler.start()
    log.info(
        "APScheduler started — nightly CSV at 18:15 IST | "
        "Telegram auto-scan at 09:30, 11:00, 13:00, 15:00 IST (Mon–Fri, all indices)"
    )
    return scheduler


if __name__ == "__main__":
    # Initialize SQLite database for tracking
    tracker_store.init_db()

    scheduler = _start_scheduler()

    # Start Telegram subscriber listener — auto-registers new users on /start
    try:
        from telegram_alert import start_subscriber_listener
        start_subscriber_listener()
    except Exception as _tg_exc:
        log.warning("Telegram subscriber listener could not start: %s", _tg_exc)

    print("NSE Composite Screener — http://127.0.0.1:8023")
    try:
        host = os.getenv("APP_HOST", "0.0.0.0")
        port = int(os.getenv("APP_PORT", "8023"))
        debug = os.getenv("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    finally:
        scheduler.shutdown()

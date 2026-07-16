import sqlite3
import os
import logging
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime

log = logging.getLogger(__name__)

DB_PATH = str(Path(__file__).resolve().parent / "data" / "tracker.db")

@contextmanager
def get_conn():
    """Context manager for SQLite connections. Safely handles transactions and threading."""
    # Ensure data directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db() -> None:
    """Initializes the database schema and indices."""
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS screen_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            index_name TEXT,
            entry_at TEXT NOT NULL,
            entry_price REAL NOT NULL,
            entry_source TEXT,
            target_pct REAL NOT NULL,
            target_price REAL NOT NULL,
            sl_pct REAL NOT NULL,
            sl_price REAL NOT NULL,
            trail_sl_pct REAL NOT NULL,
            highest_price REAL NOT NULL,
            current_trail_sl REAL NOT NULL,
            last_price REAL,
            last_seen_at TEXT,
            status TEXT NOT NULL,
            exit_at TEXT,
            exit_price REAL,
            exit_reason TEXT,
            gated_entry INTEGER NOT NULL DEFAULT 0,
            first_report_name TEXT,
            last_report_name TEXT
        );
        """)
        
        conn.execute("""
        CREATE TABLE IF NOT EXISTS screen_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            snapshot_at TEXT NOT NULL,
            price REAL,
            highest_price REAL,
            current_trail_sl REAL,
            status TEXT NOT NULL,
            report_name TEXT,
            FOREIGN KEY(entry_id) REFERENCES screen_entries(id)
        );
        """)
        
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_screen_entries_ticker_status
        ON screen_entries (ticker, status);
        """)
        
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_screen_snapshots_entry_id
        ON screen_snapshots (entry_id);
        """)

        # Lightweight migration for older local DBs created before gated-entry support.
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(screen_entries)").fetchall()
        }
        if "gated_entry" not in cols:
            conn.execute(
                "ALTER TABLE screen_entries ADD COLUMN gated_entry INTEGER NOT NULL DEFAULT 0"
            )


        # Create telegram_events table to suppress duplicate alerts
        conn.execute("""
        CREATE TABLE IF NOT EXISTS telegram_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            entry_id INTEGER,
            ticker TEXT,
            sent_at TEXT NOT NULL
        );
        """)

        
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_telegram_events_key ON telegram_events (event_key);
        """)
        
    log.info("tracker_store: Database initialized at %s", DB_PATH)


def telegram_event_sent(event_key: str) -> bool:
    """Returns True if the event has already been successfully sent/recorded."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM telegram_events WHERE event_key = ?",
            (event_key,)
        ).fetchone()
        return row is not None


def record_telegram_event(event_key: str, event_type: str, entry_id: int | None, ticker: str | None) -> None:
    """Records a Telegram alert event to prevent future duplicate sends.
    Generates sent_at internally in IST.
    """
    import pytz
    from datetime import datetime
    ist = pytz.timezone("Asia/Kolkata")
    sent_at = datetime.now(ist).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO telegram_events (event_key, event_type, entry_id, ticker, sent_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_key, event_type, entry_id, ticker, sent_at)
        )


def get_active_entry(ticker: str) -> dict | None:
    """Returns the single active entry for a ticker, or None."""
    ticker_upper = ticker.strip().upper()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM screen_entries WHERE ticker = ? AND status = 'active'",
            (ticker_upper,)
        ).fetchone()
        return dict(row) if row else None


def get_any_entry(ticker: str) -> dict | None:
    """Returns the most recent entry for a ticker regardless of status (active or closed).
    Used to detect if a ticker has EVER been entered, preventing erroneous re-entries
    after a position has been booked/SL-hit.
    """
    ticker_upper = ticker.strip().upper()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM screen_entries WHERE ticker = ? ORDER BY id DESC LIMIT 1",
            (ticker_upper,)
        ).fetchone()
        return dict(row) if row else None

def create_entry(
    ticker: str,
    index_name: str,
    entry_at: str,
    entry_price: float,
    entry_source: str,
    target_pct: float,
    sl_pct: float,
    trail_sl_pct: float,
    report_name: str,
    gated_entry: int = 1,
) -> int:
    """Creates a new active screen entry and returns its ID."""
    ticker_upper = ticker.strip().upper()
    
    # Calculate prices
    target_price = round(entry_price * (1 + target_pct), 2)
    sl_price = round(entry_price * (1 - sl_pct), 2)
    highest_price = entry_price
    current_trail_sl = round(entry_price * (1 - trail_sl_pct), 2)
    
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO screen_entries (
                ticker, index_name, entry_at, entry_price, entry_source,
                target_pct, target_price, sl_pct, sl_price, trail_sl_pct,
                highest_price, current_trail_sl, last_price, last_seen_at,
                status, gated_entry, first_report_name, last_report_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                ticker_upper, index_name, entry_at, entry_price, entry_source,
                target_pct, target_price, sl_pct, sl_price, trail_sl_pct,
                highest_price, current_trail_sl, entry_price, entry_at,
                int(gated_entry), report_name, report_name
            )
        )
        entry_id = cursor.lastrowid
        assert entry_id is not None
        return entry_id

def update_entry_state(
    entry_id: int,
    last_price: float,
    last_seen_at: str,
    highest_price: float,
    current_trail_sl: float,
    report_name: str,
) -> None:
    """Updates the runtime state metrics of an active tracker entry."""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE screen_entries
            SET last_price = ?,
                last_seen_at = ?,
                highest_price = ?,
                current_trail_sl = ?,
                last_report_name = ?
            WHERE id = ?
            """,
            (last_price, last_seen_at, highest_price, current_trail_sl, report_name, entry_id)
        )

def close_entry(
    entry_id: int,
    status: str,
    exit_at: str,
    exit_price: float,
    exit_reason: str,
    report_name: str,
) -> None:
    """Closes an active entry by setting its final exit details and status."""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE screen_entries
            SET status = ?,
                exit_at = ?,
                exit_price = ?,
                exit_reason = ?,
                last_report_name = ?
            WHERE id = ?
            """,
            (status, exit_at, exit_price, exit_reason, report_name, entry_id)
        )

def append_snapshot(
    entry_id: int,
    snapshot_at: str,
    price: float | None,
    highest_price: float | None,
    current_trail_sl: float | None,
    status: str,
    report_name: str,
) -> None:
    """Appends a snapshot metric point linked to a screen entry."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO screen_snapshots (
                entry_id, snapshot_at, price, highest_price, current_trail_sl, status, report_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (entry_id, snapshot_at, price, highest_price, current_trail_sl, status, report_name)
        )

def get_tracking_rows_for_tickers(tickers: list[str]) -> dict[str, dict]:
    """
    Returns active tracking states for specified tickers.
    Output mapping: { TICKER: dict_of_columns }
    """
    if not tickers:
        return {}
        
    placeholders = ",".join("?" for _ in tickers)
    tickers_upper = [t.strip().upper() for t in tickers]
    
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM screen_entries WHERE status = 'active' AND ticker IN ({placeholders})",
            tickers_upper
        ).fetchall()
        return {row["ticker"]: dict(row) for row in rows}


def get_all_entries_for_tickers(tickers: list[str]) -> dict[str, dict]:
    """
    Returns the most recent entry (active OR closed) for each ticker.
    Used to detect if a ticker has ever been entered so we don't re-enter
    booked/SL-hit positions on the next screener run.
    Output mapping: { TICKER: most_recent_dict }
    """
    if not tickers:
        return {}

    placeholders = ",".join("?" for _ in tickers)
    tickers_upper = [t.strip().upper() for t in tickers]

    with get_conn() as conn:
        # Get most recent entry per ticker (any status)
        rows = conn.execute(
            f"""
            SELECT * FROM screen_entries
            WHERE ticker IN ({placeholders})
            GROUP BY ticker
            HAVING id = MAX(id)
            """,
            tickers_upper
        ).fetchall()
        return {row["ticker"]: dict(row) for row in rows}

def export_all_entries() -> list[dict]:
    """Returns a list of all entries sorted by id."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM screen_entries ORDER BY id ASC").fetchall()
        return [dict(row) for row in rows]

def get_running_entries() -> list[dict]:
    """Returns active gated tracked entries from SQLite, ordered by last_seen_at DESC."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM screen_entries WHERE status = 'active' AND gated_entry = 1 ORDER BY last_seen_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

def get_booked_entries() -> list[dict]:
    """Returns closed gated tracked entries from SQLite, ordered by exit_at DESC."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM screen_entries WHERE gated_entry = 1 AND status IN ('target_hit', 'sl_hit', 'trail_sl_hit') ORDER BY exit_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

def get_entries_by_status(statuses: list[str]) -> list[dict]:
    """Returns tracked entries matching any of the specified statuses, ordered by id DESC."""
    if not statuses:
        return []
    placeholders = ",".join("?" for _ in statuses)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM screen_entries WHERE status IN ({placeholders}) ORDER BY id DESC",
            statuses
        ).fetchall()
        return [dict(row) for row in rows]

def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    from datetime import datetime
    dt = None
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        try:
            dt = datetime.fromisoformat(s.split('+')[0])
        except Exception:
            try:
                dt = datetime.strptime(s, "%Y-%m-%d")
            except Exception:
                return None
    if dt and dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt

def enrich_tracker_rows(rows: list[dict]) -> list[dict]:
    """Adds derived values like days_running, realized_pnl_pct, etc."""
    enriched = []
    for r in rows:
        row = dict(r)
        status = row.get("status")
        entry_price = row.get("entry_price") or 0.0
        highest_price = row.get("highest_price") or entry_price
        
        if status == "active":
            last_price = row.get("last_price") or 0.0
            pnl_pct = ((last_price - entry_price) / entry_price) * 100 if entry_price else 0.0
            row["pnl_pct"] = round(pnl_pct, 2)
            row["running_amount"] = round(last_price - entry_price, 2)
            
            max_gain_pct = ((highest_price - entry_price) / entry_price) * 100 if entry_price else 0.0
            row["max_gain_pct"] = round(max_gain_pct, 2)
            
            drawdown = ((last_price - highest_price) / highest_price) * 100 if highest_price else 0.0
            row["drawdown_from_high_pct"] = round(drawdown, 2)
            
            dt_entry = _parse_iso(row.get("entry_at"))
            dt_last = _parse_iso(row.get("last_seen_at"))
            row["days_running"] = max(0, (dt_last - dt_entry).days) if dt_entry and dt_last else 0
        else:
            exit_price = row.get("exit_price") or 0.0
            realized_pnl_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price else 0.0
            row["realized_pnl_pct"] = round(realized_pnl_pct, 2)
            row["realized_amount"] = round(exit_price - entry_price, 2)
            
            dt_entry = _parse_iso(row.get("entry_at"))
            dt_exit = _parse_iso(row.get("exit_at"))
            row["holding_days"] = max(0, (dt_exit - dt_entry).days) if dt_entry and dt_exit else 0
            
            max_gain_pct = ((highest_price - entry_price) / entry_price) * 100 if entry_price else 0.0
            row["max_gain_pct"] = round(max_gain_pct, 2)
            
            drawdown = ((exit_price - highest_price) / highest_price) * 100 if highest_price else 0.0
            row["drawdown_from_high_pct"] = round(drawdown, 2)
            
        enriched.append(row)
    return enriched

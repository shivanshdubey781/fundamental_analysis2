# Agent Handoff Spec

This document is the implementation handoff for extending the screener project.
It is written for an AI coding agent that needs to understand the current system,
the target behavior, and the safest patch order.

## 1. Project Overview

This project is a Flask-based NSE stock screener.

Current behavior:

1. The frontend selects one or more index groups.
2. The backend resolves those symbols from `INDEX_MAP` in `main.py`.
3. The backend runs `run_batch_screener()` from `scoring_engine.py`.
4. Results are stored in `_bg["results"]` in memory.
5. Results are exported to a CSV file in `reports/`.
6. The UI reads the latest results via `/api/screener/latest`.

Core files:

- `main.py`: Flask app, index lists, background screener, CSV export
- `scoring_engine.py`: scoring engine and output dataframe construction
- `angel_ltp.py`: Angel One LTP provider
- `templates/index.html`: index selection modal
- `static/js/app.js`: UI index logic and screener table rendering

## 2. Current Constraints And Known Issues

The implementing agent must understand these before making changes:

- `midcap100` in `main.py` is incomplete.
- `nifty500` in the app is not the official Nifty 500; it is a custom extended basket.
- Only `first_seen` is persisted today, via `data/first_seen.json`.
- Lifecycle trading data does not exist yet.
- CSV exports are snapshots, not lifecycle history.
- Old reports are auto-deleted after 24 hours.
- Angel credentials are hardcoded in `angel_ltp.py` and should be moved to env/config.

## 3. Scope Of Work

Implement these additions:

1. Add support for:
   - `smallcap250`
   - `midsmallcap400`
2. Add screener lifecycle tracking:
   - entry timestamp
   - entry price
   - target price
   - fixed SL price
   - trailing SL price
   - highest price since entry
   - latest price
   - status
   - exit timestamp and reason
3. Add enriched CSV export with performance fields.

## 4. Naming Rules

Use these index keys:

- `nifty50`
- `next50`
- `midcap100`
- `smallcap250`
- `midsmallcap400`
- `nifty500_custom`

Do not call `midsmallcap400` as `midcap400` in code unless a user-facing alias is intentionally added.

## 5. Required Architecture Change

Do not implement lifecycle tracking with only JSON and CSV.

Use:

- `data/index_universes.json` as the source of truth for universes
- `data/tracker.db` SQLite as the source of truth for lifecycle tracking

## 6. New Data Files

### 6.1 `data/index_universes.json`

Target shape:

```json
{
  "nifty50": [],
  "next50": [],
  "midcap100": [],
  "smallcap250": [],
  "midsmallcap400": [],
  "nifty500_custom": []
}
```

Notes:

- Symbol values must be normalized to the ticker format already used in the repo.
- `midsmallcap400` should be official-style broad market coverage.
- Keep custom baskets separate from official index groups.

### 6.2 `data/tracker.db`

SQLite database for active and historical lifecycle tracking.

## 7. Database Schema

The agent should create a new module named `tracker_store.py`.

### 7.1 Table: `screen_entries`

```sql
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
    first_report_name TEXT,
    last_report_name TEXT
);
```

### 7.2 Table: `screen_snapshots`

```sql
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
```

### 7.3 Optional Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_screen_entries_ticker_status
ON screen_entries (ticker, status);

CREATE INDEX IF NOT EXISTS idx_screen_snapshots_entry_id
ON screen_snapshots (entry_id);
```

## 8. Status Model

Allowed lifecycle statuses:

- `active`
- `target_hit`
- `sl_hit`
- `trail_sl_hit`
- `removed_from_scan`

For initial implementation, `removed_from_scan` may be deferred until the core path is stable.

## 9. Config Contract

Create a central config path or local helper for these tunables:

- `TARGET_PCT`
- `SL_PCT`
- `TRAIL_SL_PCT`
- `REPORT_RETENTION_HOURS`
- `ANGEL_API_KEY`
- `ANGEL_CLIENT_ID`
- `ANGEL_PASSWORD`
- `ANGEL_TOTP_KEY`

Recommended defaults:

- `TARGET_PCT = 0.10`
- `SL_PCT = 0.05`
- `TRAIL_SL_PCT = 0.07`
- `REPORT_RETENTION_HOURS = 24`

Use environment variables with defaults where safe.

## 10. New Helper Modules

### 10.1 `universe_store.py`

Purpose:

- load `data/index_universes.json`
- validate required keys
- normalize missing/malformed structures

Required functions:

```python
def load_universes() -> dict[str, list[str]]:
    ...

def get_index_map() -> dict[str, list[str]]:
    ...

def get_universe(index_key: str) -> list[str]:
    ...
```

Behavior rules:

- Return empty list for unknown keys.
- Do not crash app startup on malformed JSON; log and fall back to safe defaults.

### 10.2 `tracker_store.py`

Purpose:

- initialize SQLite
- create and update active entries
- append snapshots
- export entry state

Required functions:

```python
def init_db() -> None:
    ...

def get_active_entry(ticker: str) -> dict | None:
    ...

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
) -> int:
    ...

def update_entry_state(
    entry_id: int,
    last_price: float,
    last_seen_at: str,
    highest_price: float,
    current_trail_sl: float,
    report_name: str,
) -> None:
    ...

def close_entry(
    entry_id: int,
    status: str,
    exit_at: str,
    exit_price: float,
    exit_reason: str,
    report_name: str,
) -> None:
    ...

def append_snapshot(
    entry_id: int,
    snapshot_at: str,
    price: float | None,
    highest_price: float | None,
    current_trail_sl: float | None,
    status: str,
    report_name: str,
) -> None:
    ...

def get_tracking_rows_for_tickers(tickers: list[str]) -> dict[str, dict]:
    ...

def export_all_entries() -> list[dict]:
    ...
```

Behavior rules:

- There must be at most one `active` entry per ticker.
- Historical closed entries must never be overwritten.
- Multiple lifecycle rows for the same ticker over time are allowed.

## 11. Lifecycle Rules

Apply these exact rules.

### 11.1 Entry Creation

Create a new active entry when:

- a ticker appears in the screener result
- and there is no active entry for that ticker

### 11.2 Entry Timestamp

Use:

```python
datetime.now(IST).isoformat()
```

### 11.3 Entry Price

Preferred order:

1. Angel LTP if available
2. screener row `close`

If neither is available:

- skip entry creation for that ticker
- log the reason

### 11.4 Target

```python
target_price = round(entry_price * (1 + TARGET_PCT), 2)
```

### 11.5 Fixed SL

```python
sl_price = round(entry_price * (1 - SL_PCT), 2)
```

### 11.6 Trailing SL

At entry:

```python
highest_price = entry_price
current_trail_sl = round(highest_price * (1 - TRAIL_SL_PCT), 2)
```

On later scans:

- if new price > `highest_price`, update `highest_price`
- recalculate `current_trail_sl`

### 11.7 Exit Rules

The agent must use one fixed priority order and keep it documented.

Recommended order:

1. `sl_hit` if `last_price <= sl_price`
2. `trail_sl_hit` if `last_price <= current_trail_sl`
3. `target_hit` if `last_price >= target_price`

This order is intentionally conservative.

### 11.8 Removed From Scan

Initial implementation:

- do not auto-close on disappearance from one scan
- leave deferred unless user explicitly asks

## 12. CSV Contract

The latest screener CSV should include existing screener columns plus these tracking columns:

- `entry_at`
- `entry_price`
- `entry_source`
- `target_pct`
- `target_price`
- `sl_pct`
- `sl_price`
- `trail_sl_pct`
- `highest_price`
- `current_trail_sl`
- `last_price`
- `last_seen_at`
- `status`
- `exit_at`
- `exit_price`
- `exit_reason`
- `pnl_pct`
- `max_gain_pct`
- `drawdown_from_high_pct`

Formula contract:

```python
pnl_pct = ((last_price - entry_price) / entry_price) * 100
max_gain_pct = ((highest_price - entry_price) / entry_price) * 100
drawdown_from_high_pct = ((last_price - highest_price) / highest_price) * 100
```

Round display/export numeric fields to 2 decimals unless a field already follows another repo convention.

## 13. Integration Points

### 13.1 `main.py`

Primary backend patch points:

- replace hardcoded `INDEX_MAP` loading
- initialize tracker database at startup
- enrich `_run_screener_async()`
- extend CSV export

The main integration point for lifecycle tracking is:

```python
def _run_screener_async(tickers: list, min_score: float, index_name: str) -> None:
```

Current sequence:

1. `run_batch_screener(...)`
2. annotate `first_seen`
3. store `_bg["results"]`
4. write CSV

New desired sequence:

1. `run_batch_screener(...)`
2. annotate `first_seen`
3. enrich rows with actionable live/latest price
4. apply tracking updates
5. merge tracking fields into dataframe
6. store `_bg["results"]`
7. write enriched CSV

### 13.2 `scoring_engine.py`

Do not rewrite scoring logic unless required.

Only extend if needed for:

- carrying more metadata columns
- preserving clean dataframe output

### 13.3 `angel_ltp.py`

Required cleanup:

- move credentials to environment/config

Optional extension:

- strengthen batch LTP usage if too many single calls slow the run

### 13.4 `static/js/app.js`

Patch responsibilities:

- add labels for new index groups
- update modal counts
- update selected-index serialization

### 13.5 `templates/index.html`

Patch responsibilities:

- add new modal checkboxes
- rename misleading labels if needed

## 14. Exact Patch Sequence

The agent should follow this order.

### Patch 1

Create:

- `data/index_universes.json`
- `universe_store.py`

Then update `main.py` to read universes from JSON.

### Patch 2

Update UI index selection:

- `templates/index.html`
- `static/js/app.js`

Add:

- `smallcap250`
- `midsmallcap400`

### Patch 3

Create:

- `tracker_store.py`

Add SQLite schema and helper functions.

### Patch 4

Refactor `angel_ltp.py`:

- remove hardcoded credentials
- read env/config values

### Patch 5

Add lifecycle application logic to `main.py`.

Suggested helper:

```python
def apply_trade_tracking(df, index_name: str, report_name: str) -> pd.DataFrame:
    ...
```

Responsibilities:

- determine latest price
- create active entries
- update highs and trailing SL
- close entries if exit conditions are hit
- merge tracking fields into dataframe

### Patch 6

Extend CSV export paths:

- latest screener CSV
- optional full lifecycle CSV endpoint

### Patch 7

Add tests.

## 15. Suggested Helper Logic

The implementing agent may use these helper-level functions.

### 15.1 Latest Price Resolver

```python
def resolve_tracking_price(ticker: str, row: dict) -> tuple[float | None, str]:
    """
    Returns (price, source).
    Source should be one of:
    - "angel_ltp"
    - "close"
    - "missing"
    """
```

### 15.2 Tracking Application

```python
def apply_trade_tracking(df: pd.DataFrame, index_name: str, report_name: str) -> pd.DataFrame:
    """
    For each qualifying screener row:
    - resolve latest price
    - create or update active entry
    - append snapshot
    - merge tracking state into dataframe
    Returns enriched dataframe.
    """
```

### 15.3 Universe Fallback Rules

If `index_universes.json` is missing or malformed:

- app must still boot
- log a warning
- fall back to minimal existing basket behavior

## 16. Testing Contract

The agent should add tests for:

- universe loading
- DB initialization
- active entry creation
- repeated update on same ticker
- target hit close
- fixed SL close
- trailing SL move and close
- CSV enrichment fields present

Suggested test files:

- `test_tracker_store.py`
- `test_universe_store.py`
- `test_report_export.py`

## 17. Non-Goals

Do not do these in the first implementation unless explicitly requested:

- real-time UI lifecycle dashboards
- auto-close on a single missed scan
- intraday tick-by-tick persistence
- full multi-user account isolation
- replacing the scoring model

## 18. Definition Of Done

The work is complete when:

1. New index groups can be selected and scanned.
2. The backend persists screener-entry lifecycle state in SQLite.
3. Entry, target, SL, trailing SL, and exit data are tracked across runs.
4. Enriched CSV export includes lifecycle metrics.
5. The app still works for existing screener flows.
6. Tests cover the new persistence and export behavior.

## 19. Recommended Sources For Universe Maintenance

Use official NIFTY sources for universe updates:

- Nifty Smallcap 250 page:
  https://www.niftyindices.com/indices/equity/broad-based-indices/niftysmallcap250
- Nifty Smallcap 250 constituent CSV:
  https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv
- Nifty MidSmallcap 400 page:
  https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-midsmallcap-400
- Nifty MidSmallcap 400 factsheet:
  https://www.niftyindices.com/Factsheet/ind_Nifty_MidSmallcap_400.pdf
- Rebalancing schedule:
  https://www.niftyindices.com/resources/index-rebalancing-schedule

As of July 10, 2026:

- `Nifty Smallcap 250` is official.
- `Nifty MidSmallcap 400` is official.
- `Nifty Midcap 400` is not the official broad-market index name.

# screener-v2
# fundamental_analysis2 — NSE Stock Screener & Trade Tracker

A Flask-based screener for NSE-listed stocks that combines **fundamental** data (via EODHD/NSE sources) with **technical** indicators (BB squeeze, RSI, EMA, volume ratio, RS vs Nifty) into a single composite score (0–100), then automatically tracks simulated trades for any stock that qualifies.

---

## 1. What it actually does, end to end

1. You pick an index group in the UI (Nifty 50, Next 50, Midcap 100, custom Nifty 500, etc.).
2. The backend resolves that group to a list of ticker symbols.
3. Each ticker gets scored — fundamentals + technicals — producing a `total_score` out of 100.
4. Any stock scoring **≥ 70** (`config.TRADE_ENTRY_MIN_SCORE`) is eligible to become a tracked trade. If it doesn't already have an open position, a new entry is created with a target, a fixed stop-loss, and a trailing stop-loss.
5. Every few minutes during market hours, a background job re-fetches live prices from Angel One and checks each open trade against its target/SL/trailing-SL — closing it and recording the outcome ("booked") if one is hit.
6. Results are cached in memory, written to a CSV report, and (optionally) pushed to Telegram subscribers.
7. The frontend polls the backend for scan progress and renders three tabs: **New** (this run's scores), **Running** (open trades), **Booked** (closed trades).

---

## 2. Directory / file map

```
fundamental_analysis2/
├── main.py                  # Flask app — routes, background scan thread, trade-tracking glue
├── config.py                 # All tunables, credentials, sector maps
├── scoring_engine.py          # Composite fundamental + technical scoring
├── tracker_store.py           # SQLite-backed trade lifecycle (entries, exits, snapshots)
├── universe_store.py          # Loads index → ticker-list mappings
├── nse_data.py                 # Fundamental data fetch (EODHD/NSE)
├── sectoral_analysis.py         # Sector-level rollups, relative strength vs Nifty
├── angel_ltp.py                  # Angel One SmartAPI session + live LTP (last traded price)
├── angel_candle.py                # Angel One historical candle data + symbol-token lookup
├── astro_engine.py                 # Optional astrology-based sector scoring overlay
├── telegram_alert.py                # Telegram bot: new-pick alerts, booked alerts, EOD links
├── query_server.py                   # One-off CLI script to inspect the live tracker.db
├── mastertrust_trade.py               # Separate broker integration (Mastertrust), not wired into main flow
├── data/
│   ├── index_universes.json            # Nifty 50 / Next 50 / Midcap 100 ticker lists
│   └── tracker.db                        # SQLite DB — created at runtime by tracker_store.init_db()
├── NIFTY-500.csv / .xlsx                  # Base universe fallback data
├── reports/                                 # Auto-generated CSV screener snapshots (24h retention)
├── static/js/app.js                          # Frontend: run scans, poll status, render tabs
├── templates/index.html                       # Frontend page shell
├── subscribers.json                            # Telegram subscriber IDs
├── nse-screener.service                         # systemd unit for production deployment
├── requirements.txt                              # Python dependencies
├── test_*.py                                      # Pytest suite (scoring, tracker, universe, exports…)
└── AGENT_HANDOFF_SPEC.md / plan.md / task.md        # Design notes / in-progress specs
```

---

## 3. What each core file actually does

### `main.py` — the orchestrator
The Flask app itself. It doesn't compute scores or manage the database directly — it calls out to the specialist modules below and wires their output together. Responsibilities:
- Flask routes (`/api/screener/run`, `/api/screener/status`, `/api/screener/latest`, `/api/screener/running`, `/api/screener/booked`, CSV export endpoints).
- `_run_screener_async()` — runs a scan on a background thread so the HTTP request returns immediately; the frontend polls `/api/screener/status` for progress.
- `apply_trade_tracking()` — after scoring, decides which rows become tracked trades (gated by `TRADE_ENTRY_MIN_SCORE`) and calls into `tracker_store`.
- `_refresh_tracker_prices()` — APScheduler job (every ~3 min, market hours only) that re-fetches LTP for every open trade and closes any that hit target/SL/trailing-SL.
- `_build_running_rows()` / `_build_booked_rows()` — shape the tracker's raw rows for the API/UI.
- Scheduler setup: nightly CSV snapshot at 18:15 IST, Telegram auto-scan at 09:30/11:00/13:00/15:00 IST.

### `config.py` — single source of truth for tunables
`TARGET_PCT`, `SL_PCT`, `TRAIL_SL_PCT`, `TRADE_ENTRY_MIN_SCORE`, report retention, Telegram toggles, and the sector/planet mapping used by `astro_engine.py`. All values are overridable via environment variables (`os.getenv(...)`), with hardcoded fallback defaults.

> ⚠️ **Security note**: Angel One credentials and the Telegram bot token currently have hardcoded fallback values in this file (and `telegram_alert.py`) rather than being required from the environment. If this repo is ever made public, rotate those credentials and remove the hardcoded defaults — keep only `os.getenv("VAR_NAME")` with no fallback, so a missing `.env` fails loudly instead of silently using a real secret.

### `scoring_engine.py` — the scoring model
Takes a list of tickers and produces a `total_score` per stock by blending:
- Fundamental factors (from `nse_data.py`)
- Technical factors: Bollinger Band squeeze, RSI, EMA alignment, volume ratio, relative strength vs Nifty
`run_batch_screener(tickers, min_score, progress_callback)` is the main entry point — it's what drives the progress bar in the UI (`progress_callback` fires after each ticker is scored).

### `tracker_store.py` — trade lifecycle database
SQLite-backed (`data/tracker.db`). Two logical tables:
- **`screen_entries`** — one row per trade: entry price, target, fixed SL, trailing SL, current status (`active` / `target_hit` / `sl_hit` / `trail_sl_hit`), exit details.
- **`screen_snapshots`** — historical snapshots linked to an entry, for audit/history.

Key functions: `init_db()`, `create_entry()`, `get_running_entries()`, `get_booked_entries()`, `update_entry_state()`, `close_entry()`. Enforces one active entry per ticker.

### `universe_store.py` — index membership
Loads `data/index_universes.json` (Nifty 50, Next 50, Midcap 100, etc.), with hardcoded fallback lists baked into the file itself if the JSON is missing or malformed. Also owns `normalize_ticker()`, used everywhere to keep symbol formatting consistent (e.g. matching `M&M` vs `M&M`).

### `nse_data.py` / `sectoral_analysis.py` — fundamentals & sector context
`nse_data.py` fetches company fundamentals. `sectoral_analysis.py` rolls stocks up into sectors and computes sector-relative strength, feeding into the scoring model and the sector dashboard.

### `angel_ltp.py` / `angel_candle.py` — live market data
Wrap the Angel One **SmartAPI** SDK:
- `angel_ltp.py` — authenticated session management (`_get_session()`, TOTP-based login), live last-traded-price fetch (`get_ltp()`), with caching and a relogin-on-session-expiry path.
- `angel_candle.py` — historical OHLC candle data and ticker → instrument-token lookup (needed because Angel One's API takes tokens, not symbols).

### `astro_engine.py` — optional sector overlay
Parses planetary transit data and computes an "astro score" per sector/stock, blended in as an optional secondary signal alongside the fundamental/technical score.

### `telegram_alert.py` — notifications
Telegram bot integration: sends new-pick alerts (score ≥ 70), booked-trade alerts (target/SL/trailing-SL hit), and end-of-day report links. Manages its own subscriber list (`subscribers.json`) and long-polls Telegram for new `/start` commands to auto-register users.

### `query_server.py` — debug utility
A tiny standalone script (not part of the app) that connects directly to the production `tracker.db` and prints currently active gated entries — useful for a quick sanity check without spinning up the full Flask app.

### `mastertrust_trade.py` — separate integration
A Mastertrust broker OAuth/trading integration. Lives in the repo but isn't currently called from `main.py`'s main flow — a separate track of work.

### `static/js/app.js` — the frontend
Vanilla JS, no framework. Handles:
- Kicking off a scan (`POST /api/screener/run`) and polling `/api/screener/status` every 2s until it reports `running: false`.
- Rendering the progress bar (`_showProgress()`), the results table, and the New/Running/Booked tab switching.
- Live-refreshing the "Running" tab every 5 minutes and polling in-app notifications every 15s.

---

## 4. How a single scan flows through the files

```
User clicks "Run Scan"
        │
        ▼
static/js/app.js  →  POST /api/screener/run          (main.py route)
        │
        ▼
main.py: _run_screener_async()  runs on a background thread
        │
        ├─→ universe_store.py     resolve index name → ticker list
        │
        ├─→ scoring_engine.py     run_batch_screener(tickers, progress_callback)
        │        ├─→ nse_data.py           fundamentals
        │        ├─→ sectoral_analysis.py  sector context
        │        └─→ angel_candle.py       technical price history
        │        (progress_callback updates _bg["progress"] → drives the UI progress bar)
        │
        ├─→ main.py: apply_trade_tracking(df)
        │        ├─→ angel_ltp.py          resolve current LTP per qualifying row
        │        └─→ tracker_store.py      create_entry() for new score≥70 stocks,
        │                                  update_entry_state() for existing ones
        │
        ├─→ reports/*.csv          write snapshot
        └─→ telegram_alert.py      send new-pick alert (if enabled)
        │
        ▼
_bg["running"] = False
        │
        ▼
static/js/app.js polling loop sees running:false → hides progress bar,
        fetches /api/screener/latest, renders the table
```

Separately, **every ~3 minutes during market hours**, regardless of whether anyone runs a manual scan:

```
main.py: _refresh_tracker_prices()  (APScheduler job)
    │
    ├─→ tracker_store.get_running_entries()   all open trades
    ├─→ angel_ltp.get_ltp()  per ticker         live price
    ├─→ compare price vs target / SL / trailing-SL
    └─→ tracker_store.close_entry()  or  update_entry_state()
```

This is what keeps "Running" trade P&L live and books trades automatically even when no one is actively scanning.

---

## 5. Running it

### Local / development
```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```
Starts on `http://127.0.0.1:8023` by default (`APP_HOST` / `APP_PORT` env vars to override). This also initializes `data/tracker.db` (`tracker_store.init_db()`), starts the APScheduler jobs, and starts the Telegram subscriber listener.

### Production (as currently deployed)
Runs under systemd via `nse-screener.service`:
```ini
WorkingDirectory=/var/www/fundamental_analysis2
EnvironmentFile=/var/www/fundamental_analysis2/.env
ExecStart=/var/www/fundamental_analysis2/venv/bin/python main.py
Restart=always
```
Environment variables (Angel One creds, Telegram token, tunables) are loaded from a `.env` file that systemd reads via `EnvironmentFile=` — **not** committed to the repo. Deploy steps: `git pull` → `pip install -r requirements.txt` (if changed) → `sudo systemctl restart nse-screener`.

### Tests
```bash
pytest
```
Covers scoring (`test_scoring.py`), tracker lifecycle (`test_tracker_store.py`, `test_running_logic.py`), universe loading (`test_universe_store.py`), CSV exports (`test_report_export.py`, `test_running_csv.py`, `test_tracker_mode_exports.py`), and scheduled scans (`test_scheduled_scan.py`).

---

## 6. Known rough edges (as of last review)

- **Running-trade visibility bug**: `_build_running_rows()` in `main.py` hides open trades from the UI if their *current* re-scan score drops below 70, even though the trade is still open in the DB and still being managed by `_refresh_tracker_prices()`. Fix: don't filter active trades by current score — the ≥70 gate should apply at entry only.
- **Scanner can hang at 100%**: `angel_ltp.py`'s calls into the Angel One SmartAPI SDK (`obj.ltpData()`, `obj.generateSession()`) have no timeout. If Angel One's server stalls mid-request, the background scan thread blocks indefinitely *after* the progress bar has already reached 100% (scoring is done; it's stuck in the trade-tracking price-sync step). Fix: wrap those calls with a hard timeout (e.g. via `ThreadPoolExecutor.result(timeout=...)`).
- **Hardcoded secrets** in `config.py` / `telegram_alert.py` — see security note in section 3.
- `midcap100` universe is incomplete; the in-app `nifty500` group is a custom (non-official) basket — see `AGENT_HANDOFF_SPEC.md` for details.

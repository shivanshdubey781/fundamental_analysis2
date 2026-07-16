# Booked / Running / New Blueprint

This document is the implementation blueprint for adding three screener modes to the current project:

- `New`
- `Running`
- `Booked`

The goal is to keep the user inside the existing Screener tab while switching the data source, summary cards, table columns, and CSV download behavior based on the selected mode.

## 1. Feature Goal

Add three square toggle boxes near the Screener toolbar:

- `Booked`
- `Running`
- `New`

Behavior:

- `New` shows the latest screener result set, similar to the current UI
- `Running` shows active tracked stocks that are still open
- `Booked` shows realized tracked stocks where target, fixed SL, or trailing SL has already been hit

Each mode must also have its own CSV download.

## 2. Mapping To Existing Project

The current project already has the key backend foundations:

- latest screener rows are stored in `_bg["results"]` in `main.py`
- lifecycle tracking is computed in `apply_trade_tracking()` in `main.py`
- lifecycle data is persisted in `tracker_store.py`
- the current screener table is rendered in `static/js/app.js`
- the toolbar/cards/table region already exists in `templates/index.html`

This means the new feature should be implemented as an extension of the existing screener, not as a separate page or subsystem.

## 3. Business Definitions

### 3.1 New

Definition:

- latest screener output from the most recent background screener run

Recommended default behavior:

- show all rows from the latest screener run

Optional later filter:

- `today_only`: only rows where `days_in_screener == 0`

### 3.2 Running

Definition:

- tracker entries where `status = 'active'`

These represent live/open positions still being tracked.

### 3.3 Booked

Definition:

- tracker entries where `status IN ('target_hit', 'sl_hit', 'trail_sl_hit')`

These represent realized outcomes.

## 4. Trade Rule Settings

The requested target/SL model for this view is:

- target: `15% to 20%`
- fixed SL: `5%`
- trailing SL: `8%`

### Recommended phase-1 rule

Use one fixed target first:

- `TARGET_PCT = 0.15`
- `SL_PCT = 0.05`
- `TRAIL_SL_PCT = 0.08`

This keeps the implementation simpler and makes Booked logic easier to explain.

### Optional phase-2 rule

If needed later, support:

- `TARGET_PCT_PRIMARY = 0.15`
- `TARGET_PCT_SECONDARY = 0.20`

But this should not be the initial build unless explicitly requested.

## 5. Backend API Blueprint

Add three new JSON endpoints:

### 5.1 `/api/screener/new`

Purpose:

- return latest screener result rows from `_bg["results"]`

Suggested query params:

- `today_only=0|1`

Response shape:

```json
{
  "mode": "new",
  "count": 58,
  "results": [...]
}
```

### 5.2 `/api/screener/running`

Purpose:

- return active tracked entries from SQLite

Response shape:

```json
{
  "mode": "running",
  "count": 24,
  "results": [...]
}
```

### 5.3 `/api/screener/booked`

Purpose:

- return closed tracked entries from SQLite

Response shape:

```json
{
  "mode": "booked",
  "count": 37,
  "results": [...]
}
```

## 6. CSV Endpoint Blueprint

Add three CSV download endpoints:

### 6.1 `/api/reports/new.csv`

Source:

- latest screener result rows

### 6.2 `/api/reports/running.csv`

Source:

- tracker entries with `status = 'active'`

### 6.3 `/api/reports/booked.csv`

Source:

- tracker entries with `status IN ('target_hit', 'sl_hit', 'trail_sl_hit')`

Each CSV should have a filename matching its mode, for example:

- `screener_new.csv`
- `screener_running.csv`
- `screener_booked.csv`

## 7. Backend Data Contract

### 7.1 Fields for New

Expected row fields:

- `ticker`
- `sector`
- `total_score`
- `grade`
- `signal`
- `first_seen`
- `days_in_screener`
- `close`
- `entry_at`
- `entry_price`
- `target_price`
- `sl_price`
- `current_trail_sl`
- `status`
- `pnl_pct`

### 7.2 Fields for Running

Expected row fields:

- `ticker`
- `index_name`
- `entry_at`
- `entry_price`
- `last_price`
- `target_price`
- `sl_price`
- `current_trail_sl`
- `highest_price`
- `pnl_pct`
- `max_gain_pct`
- `drawdown_from_high_pct`
- `status`
- `days_running`
- `running_amount`

### 7.3 Fields for Booked

Expected row fields:

- `ticker`
- `index_name`
- `entry_at`
- `exit_at`
- `entry_price`
- `exit_price`
- `highest_price`
- `exit_reason`
- `status`
- `realized_pnl_pct`
- `realized_amount`
- `holding_days`

## 8. Derived Field Formulas

### 8.1 Running

```python
pnl_pct = ((last_price - entry_price) / entry_price) * 100
running_amount = last_price - entry_price
days_running = date_diff(last_seen_at, entry_at)
```

### 8.2 Booked

```python
realized_pnl_pct = ((exit_price - entry_price) / entry_price) * 100
realized_amount = exit_price - entry_price
holding_days = date_diff(exit_at, entry_at)
```

Round display values to 2 decimals unless the existing project already uses another convention for that metric.

## 9. Tracker Store Additions

Extend `tracker_store.py` with query helpers.

### Required new functions

```python
def get_running_entries() -> list[dict]:
    ...

def get_booked_entries() -> list[dict]:
    ...

def get_entries_by_status(statuses: list[str]) -> list[dict]:
    ...
```

### Optional helper

```python
def enrich_tracker_rows(rows: list[dict]) -> list[dict]:
    """
    Adds derived values like days_running, realized_pnl_pct, etc.
    """
```

## 10. Main Backend Changes

Main file to change:

- `main.py`

### Required additions

#### A. Add mode endpoints

Add:

- `/api/screener/new`
- `/api/screener/running`
- `/api/screener/booked`

#### B. Add CSV endpoints

Add:

- `/api/reports/new.csv`
- `/api/reports/running.csv`
- `/api/reports/booked.csv`

#### C. Add formatting helpers

Suggested helpers:

```python
def _build_new_rows(today_only: bool = False) -> list[dict]:
    ...

def _build_running_rows() -> list[dict]:
    ...

def _build_booked_rows() -> list[dict]:
    ...

def _rows_to_csv_response(rows: list[dict], filename: str):
    ...
```

#### D. Keep current tracking pipeline

Do not replace `apply_trade_tracking()`.

Instead:

- keep using it in `_run_screener_async()`
- keep writing enriched screener rows
- reuse the tracker DB for Running and Booked modes

## 11. Frontend State Blueprint

Main file to change:

- `static/js/app.js`

### Add a screener mode state

Suggested global:

```javascript
let _screenerMode = 'new'; // 'new' | 'running' | 'booked'
```

### Required frontend functions

```javascript
function setScreenerMode(mode) {
  ...
}

async function loadScreenerModeData() {
  ...
}

function renderModeSummary(rows) {
  ...
}

function renderModeTable(rows) {
  ...
}

function downloadModeCsv() {
  ...
}
```

### Mode endpoint mapping

```javascript
const MODE_API = {
  new: '/api/screener/new',
  running: '/api/screener/running',
  booked: '/api/screener/booked',
};

const MODE_CSV = {
  new: '/api/reports/new.csv',
  running: '/api/reports/running.csv',
  booked: '/api/reports/booked.csv',
};
```

## 12. Frontend UI Layout Blueprint

Main file to change:

- `templates/index.html`

### Insert a 3-box mode switcher near the current toolbar

Recommended placement:

- inside the existing toolbar row
- between filters and CSV/Run buttons

Suggested structure:

```html
<div class="screener-mode-switch">
  <button id="mode-new" class="mode-box active" onclick="setScreenerMode('new')">New</button>
  <button id="mode-running" class="mode-box" onclick="setScreenerMode('running')">Running</button>
  <button id="mode-booked" class="mode-box" onclick="setScreenerMode('booked')">Booked</button>
</div>
```

### CSV button behavior

Replace single-mode wording:

- from `TODAY CSV`

To dynamic wording:

- `NEW CSV`
- `RUNNING CSV`
- `BOOKED CSV`

Or keep one button and update the label dynamically in JS.

## 13. Summary Card Behavior

Main files:

- `templates/index.html`
- `static/js/app.js`

The current snapshot cards should become mode-aware.

### New mode summary

- `New Stocks`
- `Avg Score`
- `Breakouts`
- `Today Qualified`

### Running mode summary

- `Running Count`
- `Total Running PnL`
- `Winners`
- `Losers`

### Booked mode summary

- `Booked Count`
- `Total Realized PnL`
- `Target Hits`
- `SL / Trail SL Hits`

You can either:

- reuse the existing snapshot card grid and change labels dynamically

or

- add a second dedicated summary strip

Recommended:

- reuse the current grid to reduce markup churn

## 14. Table Layout Blueprint

### 14.1 New mode columns

- `Ticker`
- `Since`
- `Score`
- `Grade`
- `Signal`
- `Close`
- `Entry`
- `Target`
- `SL`
- `Trail SL`

### 14.2 Running mode columns

- `Ticker`
- `Entry Date`
- `Entry Price`
- `Current Price`
- `Target`
- `SL`
- `Trail SL`
- `Highest`
- `PnL %`
- `PnL ₹`
- `Days`

### 14.3 Booked mode columns

- `Ticker`
- `Entry Date`
- `Exit Date`
- `Entry Price`
- `Exit Price`
- `Booked %`
- `Booked ₹`
- `Exit Type`
- `Highest`
- `Days Held`

## 15. Styling Blueprint

Main file:

- `static/css/style.css`

### Add styles for mode boxes

Required classes:

- `.screener-mode-switch`
- `.mode-box`
- `.mode-box.active`

Visual direction:

- square/rectangular chips
- consistent with existing neon/dark visual language
- subtle active glow

### Optional color suggestions

- `New`: cyan/teal
- `Running`: amber/green
- `Booked`: blue or muted gold

## 16. Recommended Backend Query Rules

### New

Use `_bg["results"]` as source of truth.

### Running

Query:

```sql
SELECT * FROM screen_entries
WHERE status = 'active'
ORDER BY last_seen_at DESC
```

### Booked

Query:

```sql
SELECT * FROM screen_entries
WHERE status IN ('target_hit', 'sl_hit', 'trail_sl_hit')
ORDER BY exit_at DESC
```

## 17. Important UX Decisions

### New mode

Recommended default:

- show all latest screener results

Optional later:

- add a small toggle for `Today Only`

### Running mode

Recommended sort:

- sort by `pnl_pct` descending

### Booked mode

Recommended sort:

- sort by `exit_at` descending

## 18. Performance Notes

The current `resolve_tracking_price()` prefers Angel LTP first.

This is fine for ongoing tracking, but it can get slow when the selected universe is large.

Recommended behavior:

- keep current tracking logic for now
- for Running and Booked screens, do not refetch live Angel LTP for every row on every view switch
- use stored tracker values from SQLite as the primary source for those modes

## 19. Patch Order

### Patch 1

Update trade thresholds in `config.py`:

- target `0.15`
- fixed SL `0.05`
- trailing SL `0.08`

### Patch 2

Extend `tracker_store.py`:

- add running/booked query helpers
- add enrichment helpers for derived columns

### Patch 3

Extend `main.py`:

- add new/running/booked JSON endpoints
- add new/running/booked CSV endpoints
- add helper builders for row preparation

### Patch 4

Update `templates/index.html`:

- add 3 mode boxes
- make CSV button mode-aware

### Patch 5

Update `static/js/app.js`:

- add `_screenerMode`
- add mode switching
- add mode-based fetch
- add mode-based table rendering
- add mode-based summary rendering

### Patch 6

Update `static/css/style.css`:

- add mode switch styling

### Patch 7

Add tests:

- `test_screener_modes.py`
- `test_tracker_mode_exports.py`

## 20. Acceptance Criteria

The feature is complete when:

1. The Screener tab shows three clickable mode boxes:
   - `New`
   - `Running`
   - `Booked`
2. Clicking each mode changes the table on the screen.
3. Each mode has mode-appropriate summary cards.
4. Each mode has a dedicated CSV download.
5. Running rows come from active tracker entries.
6. Booked rows come from realized tracker entries.
7. New rows still preserve the current screener behavior.

## 21. Non-Goals For Phase 1

Do not include these unless explicitly requested:

- a separate page for Running/Booked
- multi-target scaling exits
- intraday tick-by-tick refresh
- live price streaming for all rows
- strategy simulation overlays inside this feature

## 22. Recommended Next Step

Implementation should begin with:

1. tracker query helpers
2. mode endpoints
3. toolbar mode switch
4. mode table rendering

This keeps the feature incremental and avoids breaking the current screener flow.

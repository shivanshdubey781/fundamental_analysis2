# Plan: Running Screener Logic Cleanup

## Goal

Align the `Running` tab with the intended meaning of "currently strong / currently qualified" stocks instead of simply showing every active tracked entry that has not yet hit target, SL, or trail SL.

Right now the large running count is expected because the system treats `Running` as a lifecycle tracker, not a live high-score screener view.

## Current Logic

### Where stocks enter Running

- `main.py`
- Function: `apply_trade_tracking(...)`

Behavior:
- A stock is added to tracking when it appears in scan results
- It must satisfy `TRADE_ENTRY_MIN_SCORE`
- If there is no existing active entry, a new active tracker row is created

### Entry threshold

- `config.py`
- Variable: `TRADE_ENTRY_MIN_SCORE`

This controls who can enter `Running`.

### What the Running API returns

- `tracker_store.py`
- Function: `get_running_entries()`

Behavior:
- Returns every tracker entry where:
  - `status = 'active'`
  - `gated_entry = 1`

Important:
- It does not check the current screener score
- It does not check whether the stock is still in today's qualified list
- It does not enforce `score >= 70`

### How the Running screen is built

- `main.py`
- Functions:
  - `_build_running_rows()`
  - `/api/screener/running`

Behavior:
- Reads active tracker rows from SQLite
- Enriches them for display
- Sends them to the frontend

### Where the frontend count comes from

- `static/js/app.js`

Behavior:
- Running count is based on `rows.length`
- So the UI is only showing how many entries the backend returned

## Root Cause of the Large Running Count

The high count is happening because:

1. Stocks enter tracking when they first qualify above the trade-entry threshold.
2. They remain in `Running` until they hit target, fixed SL, or trailing SL.
3. If their screener score later drops below 70, they still remain active.
4. Scheduled scans continue adding new active entries over multiple days.

So `Running` currently means:

- "active open tracked positions"

not:

- "stocks that currently score above 70"

## Decision Needed

Choose one of these definitions for `Running`.

### Option A: Keep lifecycle tracker behavior

Meaning:
- Show all active open tracked entries until they close

Result:
- Count stays large
- Best if `Running` is meant to behave like a trade book

Changes needed:
- No backend logic change
- Only update labels/text so users understand the meaning

### Option B: Running should mean current score >= 70

Meaning:
- Only show active entries whose latest score is still at least 70

Result:
- Count will drop
- Running becomes more like a live screener + tracker hybrid

Changes needed:
- Add a current-score filter in the Running row builder
- Possibly recompute or store the latest score before returning rows

### Option C: Running should mean still present in today's qualified scan

Meaning:
- Show only active entries that still appear in the latest scan result set

Result:
- Count will drop further
- Running becomes tied to the latest scan snapshot

Changes needed:
- Compare active tracker tickers against latest screener result tickers
- Filter out active entries not present in the current scan

## Recommended Direction

Recommended if you want the Running tab to feel cleaner:

- Keep the database lifecycle tracker as-is
- Change only the `Running` API/view logic
- Filter the displayed rows based on the latest score or latest qualification

This is safer than changing how tracker entries are stored and closed.

## Implementation Roadmap

### Phase 1: Confirm desired Running definition

Pick one:
- Option A: lifecycle active trades
- Option B: active trades with current score >= 70
- Option C: active trades still present in latest scan

### Phase 2: Inspect current threshold settings

Check:
- `config.py`
- `TRADE_ENTRY_MIN_SCORE`

Questions:
- Should entry remain `65` while Running display becomes `70`?
- Or should entry threshold also become `70`?

### Phase 3: Decide whether this is display-only or storage behavior

Recommended:
- Display-only change first

Why:
- Easier to reverse
- Lower risk
- Does not rewrite historical tracker logic

### Phase 4: Update backend Running builder

Primary file:
- `main.py`

Primary logic point:
- `_build_running_rows()`

Possible change paths:

#### If using Option B

- Fetch active tracker rows
- Attach or look up latest score
- Return only rows with `latest_score >= 70`

#### If using Option C

- Fetch active tracker rows
- Compare with latest screener cache / latest report / latest batch output
- Return only rows whose tickers still exist in the current qualified set

### Phase 5: Keep tracker storage unchanged

File:
- `tracker_store.py`

Recommendation:
- Do not change `get_running_entries()` first
- Keep storage semantics as "all active entries"
- Apply filtering in `main.py` view-building layer instead

This avoids breaking:
- booked transitions
- tracker refresh loop
- Telegram booked alerts
- running CSV export logic unexpectedly

### Phase 6: Update labels in frontend

File:
- `static/js/app.js`
- possibly `templates/index.html`

If using Option B or C:
- rename or clarify summary labels
- make count wording match filtered behavior

Examples:
- `Running Count`
- `Qualified Active Trades`
- `Active Trades >= 70`

### Phase 7: Decide CSV behavior

Important decision:
- Should `running.csv` export the filtered Running view?
- Or should it export all active lifecycle trades?

Recommendation:
- Match CSV to the visible Running tab to avoid confusion

Primary file:
- `main.py`
- `_build_running_csv_rows()`

### Phase 8: Test coverage

Add or update tests for:

1. Active trade with score >= 70 appears in Running
2. Active trade with score < 70 is hidden if using Option B
3. Active trade missing from latest scan is hidden if using Option C
4. Booked trades still move correctly to Booked
5. Running CSV matches the chosen Running definition
6. Frontend count equals filtered backend rows

Suggested test files:
- `test_tracker_mode_exports.py`
- `test_running_csv.py`
- new test file if needed: `test_running_logic.py`

## File Impact Summary

### Definitely inspect

- `config.py`
- `main.py`
- `tracker_store.py`
- `static/js/app.js`

### Likely test updates

- `test_running_csv.py`
- `test_tracker_mode_exports.py`

## Safe Change Order

1. Decide the new meaning of `Running`
2. Leave tracker storage untouched
3. Filter only in `_build_running_rows()`
4. Align `running.csv`
5. Update frontend labels
6. Add regression tests
7. Verify Running count after a fresh scan

## Success Criteria

The change is successful when:

- The Running count matches the intended definition
- Users no longer confuse active lifecycle trades with current high-score trades
- Booked logic remains unchanged
- CSV and UI stay consistent with each other

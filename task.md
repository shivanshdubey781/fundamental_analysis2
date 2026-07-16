# Task: Fix `112 vs 500` Universe Bug and Align Modal Counts

## Goal

Fix the broad-universe bug where the app is still scanning only `112` runtime symbols instead of the intended `500` corrected symbols from `NIFTY-500.csv`, and make the UI counts reflect the same backend truth.

This task must keep the code CSV-based and must not disturb:

- Running / Booked lifecycle logic
- tracker storage behavior
- current LTP recovery logic
- existing scan/report endpoints outside the universe-count fix

---

## Problem Summary

The current behavior is inconsistent:

- `Nifty 50` shows `50`
- `Nifty Next 50` shows `50`
- `Nifty 500 (CSV)` shows `500`
- `All` shows `112`
- the scan progress also behaves like only `112` symbols are actually being scanned

This means the app is mixing:

1. UI display counts
2. backend runtime universe counts
3. filtered CSV-backed scan universe counts

Right now, the real runtime universe appears to be `112`, not `500`.

---

## Desired End State

After this fix:

1. `NIFTY-500.csv` remains the runtime source of truth.
2. The row-wise loader reads the intended corrected `NIFTY 500` symbol column correctly.
3. The backend broad universe actually resolves to the intended `500` symbols, unless unsupported symbols are explicitly and intentionally filtered.
4. The modal counts for:
   - `Nifty 50`
   - `Nifty Next 50`
   - `Nifty 500 (CSV)`
   - `All`
   all come from backend truth.
5. The scan progress count matches the same runtime universe count.
6. There is no `500` vs `112` contradiction left in the UI.

---

## Root Cause Areas To Investigate

There are only a few likely causes for the `112` result:

1. The row-wise CSV loader is reading the wrong rows or column.
2. The corrected CSV file on disk does not actually contain the full intended 500 usable rows.
3. Angel compatibility filtering is removing too many symbols.
4. The deployed server CSV differs from the local CSV.
5. The UI is showing mixed hardcoded and backend-derived counts.

This task must verify which of these is actually causing the `112`.

---

## File-by-File Plan

## 1. CSV Source Validation

### File: `NIFTY-500.csv`

This remains the runtime source file.

### Required checks

- confirm the `NIFTY 500` column actually contains the intended corrected 500 symbols
- confirm the file is row-wise and not missing rows
- confirm blank rows are not truncating the loader path
- confirm the deployed server file matches the local file

### Required rule

The runtime scan universe must come from the `NIFTY 500` column only unless there is an explicit product decision to merge other columns.

---

## 2. Row-Wise Loader

### File: `universe_store.py`

### Function: `_load_nifty500_csv_symbols()`

This is the first critical function.

### Required behavior

- open `NIFTY-500.csv`
- read the header row
- locate the `NIFTY 500` column index dynamically
- iterate row by row
- read only that one column
- skip blanks
- skip header-like junk values
- preserve raw order

### Required verification

Add logging or validation to confirm:

- raw loaded row count from `NIFTY 500`
- count after blank/header skipping

If this function returns around `112`, the problem is here or in the CSV itself.

---

## 3. Dedupe Layer

### File: `universe_store.py`

### Function: `_dedupe_preserve_order()`

### Required behavior

- normalize symbols with `normalize_ticker()`
- remove duplicates only
- preserve first appearance order

### Required verification

Log or validate:

- raw CSV symbol count
- deduped count

If the raw count is near 500 but deduped falls to 112, the CSV has heavy repetition or the normalization is collapsing too aggressively.

---

## 4. Angel Compatibility Filter

### File: `universe_store.py`

### Function: `_filter_symbols_present_in_angel_master()`

### Required behavior

- reuse `angel_candle.get_token()`
- keep only symbols that resolve to Angel tokens

### Required verification

Log or validate:

- deduped count before Angel filtering
- final count after Angel filtering
- optionally list unresolved symbols for debugging

This is the most likely place where `500` can collapse down to `112`.

### Important decision

You must decide which rule is correct:

1. **Strict Angel-compatible scan universe**
   - only symbols resolvable in Angel are scanned
   - then `112` may actually be the current true runtime universe

2. **Full corrected 500-symbol scan universe**
   - scan all corrected symbols
   - Angel compatibility should only affect LTP/tracking, not whether the stock enters the scan universe

If your intent is truly “scan all 500 stocks,” then the current Angel filtering rule is too strict and must be relaxed or moved later in the flow.

---

## 5. Broad Universe Builder

### File: `universe_store.py`

### Function: `get_nifty500_custom()`

### Required behavior

- load row-wise CSV symbols
- dedupe correctly
- apply the intended filter policy
- cache the final runtime list

### Required update

Make this function reflect the final business rule:

- if the scanner should scan all corrected 500 stocks, do not let this function shrink to `112` just because Angel token resolution fails

### Recommended safe split

Separate:

- `scan_universe_symbols`
- `angel_ltp_compatible_symbols`

Do not force them to be the same unless that is explicitly desired.

---

## 6. Universe Exposure To The App

### File: `universe_store.py`

### Functions to verify

- `load_universes()`
- `_get_default_universe()`
- `get_universe()`
- `get_full_universe()`
- `build_unique_universe()`

### Required behavior

- `nifty500_custom` must resolve to the real corrected runtime universe
- aliases such as `all` and `nifty500` must stay consistent
- no older hardcoded fallback path should silently override the corrected CSV universe

---

## 7. Scan Entry Points

### File: `main.py`

### Functions to verify

- `_default_scan_tickers()`
- `_scheduled_scan_tickers()`
- `api_screener_run()`
- `_nightly_screener()`
- `_auto_telegram_scan()`

### Required behavior

- all broad/default scans must use the same runtime broad universe
- scan progress count must reflect the same runtime total

### Important review point

`_default_scan_tickers()` currently may merge sectoral fallback tickers after building the broad universe.

Decide clearly whether:

- `All` = corrected `NIFTY 500` only
or
- `All` = corrected `NIFTY 500` plus sectoral extras

That definition must be consistent in:

- backend universe
- modal counts
- scan progress

---

## 8. Backend Universe Count API

### File: `main.py`

### Endpoint: `/api/universe`

This must become the single truth source for UI counts.

### Required response behavior

Return:

- `groups`
- `combined`
- `total`
- explicit per-group counts if needed

Recommended additional structure:

- `counts.nifty50`
- `counts.next50`
- `counts.nifty500_custom`
- `counts.all`

### Required rule

Every modal count in the UI should come from this backend truth, not from hardcoded assumptions.

---

## 9. Modal Count Fix

### File: `static/js/app.js`

### Functions/variables to update

- `fetchBackendUniverseCounts()`
- `_IDX_SIZES`
- `updateModalCount()`
- `openIndexModal()`

### Current issue

The UI still partly relies on hardcoded default sizes like `500`, while `All` is already showing a backend-derived total such as `112`.

### Required behavior

- `Nifty 50` count must come from backend `nifty50`
- `Nifty Next 50` count must come from backend `next50`
- `Nifty 500 (CSV)` count must come from backend `nifty500_custom`
- `All` count must come from backend `all`

### Important note

`_IDX_SIZES` should no longer be treated as the source of truth for real counts.
It can remain only as a fallback placeholder or be removed from count logic entirely.

### Best fix

When selections change:

1. build `indexParam`
2. query `/api/universe?index=<selected>`
3. use returned `total` directly for the modal summary

This avoids fake overlap math and guarantees the modal count matches the backend.

---

## 10. Static Count Labels

### File: `templates/index.html`

### Required behavior

The visible count labels beside:

- `Nifty 50`
- `Nifty Next 50`
- `Nifty 500 (CSV)`
- `All`

should be placeholders only until JS fills them from backend truth.

### Required rule

Do not keep misleading hardcoded visible counts in the template.

---

## 11. Scan Progress Count

### Files

- `main.py`
- `static/js/app.js`

### Required behavior

The live progress text such as:

- `Scanning 2/112 stocks`

must come from the same runtime universe size used by the actual scan.

### Required verification

If the app is intended to scan all corrected 500 stocks, then progress should move toward `500` or the exact intended broad-universe total, not `112`.

If it still shows `112`, then the backend runtime universe is still being reduced before scan execution.

---

## 12. Date Fix Preservation

### Files

- `main.py`
- `static/js/app.js`

Keep the existing date fix intact:

- `first_seen` = historical first qualification date
- `scan_date` = current scan/report date

This task must not undo the `New` tab date correction while fixing the universe bug.

---

## 13. Deployment Consistency Check

### Required verification on Ubuntu server

Confirm the deployed versions of:

- `NIFTY-500.csv`
- `universe_store.py`
- `main.py`
- `static/js/app.js`
- `templates/index.html`

match the intended local versions.

Also verify:

- browser cache is not serving stale JS
- service restart actually picked up the new files

This is important because the screenshot may reflect a server file mismatch, not just a code bug.

---

## Tests To Add or Update

### `test_universe_store.py`

Add or extend tests for:

- row-wise loading from `NIFTY 500` column
- header skipping
- blank row handling
- deduped count behavior
- Angel-filter count behavior

### `test_full_universe_scan.py`

Add tests for:

- broad scan universe count
- relationship between `nifty500_custom` and `all`

### `test_scheduled_scan.py`

Add tests for:

- scheduled scans using the same broad-universe count as manual default scans

### API tests

Add tests for `/api/universe` response shape and counts:

- `groups`
- `combined`
- `total`
- `counts`

### Frontend/manual verification

Verify:

- `Nifty 500 (CSV)` does not falsely show `500` unless runtime universe is truly 500
- `All` shows a count consistent with backend meaning
- modal summary matches backend total
- scan progress matches runtime universe size

---

## Recommended Implementation Order

1. Verify the corrected `NIFTY-500.csv` contents
2. Verify `_load_nifty500_csv_symbols()` raw count
3. Verify `_dedupe_preserve_order()` count
4. Verify `_filter_symbols_present_in_angel_master()` count
5. Decide whether Angel filtering should reduce the scan universe
6. Fix `get_nifty500_custom()` to match that rule
7. Fix `/api/universe` to expose explicit backend counts
8. Fix `static/js/app.js` to use backend counts for every modal label and summary
9. Verify scan progress count uses the same runtime total
10. Deploy and hard-refresh the browser

---

## Success Criteria

This bug is fixed when:

1. the app scans the intended corrected broad universe, not just `112` unintended symbols
2. `Nifty 500 (CSV)` count matches the actual runtime broad universe
3. `All` count has one clear meaning and matches backend truth
4. modal summary count matches backend total
5. scan progress count matches the same runtime universe
6. there is no mixed hardcoded/dynamic count behavior left
7. the `New` tab date fix remains intact

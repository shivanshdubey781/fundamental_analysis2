import os
import io
import csv
import unittest
import pandas as pd
from pathlib import Path
from unittest.mock import patch

import tracker_store
import config

# ── Redirect to test database ─────────────────────────────────────────────────
TEST_DB_PATH = str(Path(__file__).resolve().parent / 'data' / 'test_running_csv.db')
tracker_store.DB_PATH = TEST_DB_PATH

# ── Disable Angel One network calls ───────────────────────────────────────────
import angel_ltp
angel_ltp.is_configured = lambda: False

EXPECTED_COLUMNS = [
    'ticker', 'entry_date', 'entry_price', 'current_price',
    'target', 'sl', 'trail_sl', 'highest',
    'pnl_pct', 'pnl_amount', 'days',
]


# =============================================================================
# Tests: CSV shape with at least one seeded Running entry
# =============================================================================

class TestRunningCsvShape(unittest.TestCase):
    DB_PATH = str(Path(__file__).resolve().parent / 'data' / 'test_running_csv_shape.db')

    def setUp(self):
        tracker_store.DB_PATH = self.DB_PATH
        import main
        main.tracker_store.DB_PATH = self.DB_PATH
        if os.path.exists(self.DB_PATH):
            try:
                os.remove(self.DB_PATH)
            except Exception:
                pass
        tracker_store.init_db()
        try:
            with tracker_store.get_conn() as conn:
                conn.execute("DELETE FROM screen_snapshots;")
                conn.execute("DELETE FROM screen_entries;")
        except Exception:
            pass
        self._seed_running_entry()

    def tearDown(self):
        try:
            with tracker_store.get_conn() as conn:
                conn.execute("DELETE FROM screen_snapshots;")
                conn.execute("DELETE FROM screen_entries;")
        except Exception:
            pass
        if os.path.exists(self.DB_PATH):
            try:
                os.remove(self.DB_PATH)
            except Exception:
                pass

    def _seed_running_entry(self):
        import main
        df = pd.DataFrame([
            {'ticker': 'CSVTEST', 'close': 500.0,
             'total_score': config.TRADE_ENTRY_MIN_SCORE + 10}
        ])
        df = main._annotate_first_seen(df)
        main.apply_trade_tracking(df, 'nifty500_custom', 'test_csv_shape.csv')

    def _get_csv_rows(self):
        import main
        return main._build_running_csv_rows()

    # ── 1. exact column order ─────────────────────────────────────────────────

    def test_exact_column_order(self):
        rows = self._get_csv_rows()
        self.assertTrue(len(rows) > 0, 'Expected at least one running row for CSV test')
        actual_keys = list(rows[0].keys())
        self.assertEqual(actual_keys, EXPECTED_COLUMNS,
                         f'Column order mismatch.\nExpected: {EXPECTED_COLUMNS}\nGot:      {actual_keys}')

    # ── 2. no extra internal columns ──────────────────────────────────────────

    def test_no_extra_internal_columns(self):
        rows = self._get_csv_rows()
        for row in rows:
            extras = set(row.keys()) - set(EXPECTED_COLUMNS)
            self.assertEqual(extras, set(),
                             f'Unexpected internal columns found in CSV row: {extras}')

    # ── 3. exactly 11 columns ────────────────────────────────────────────────

    def test_column_count_is_eleven(self):
        rows = self._get_csv_rows()
        for row in rows:
            self.assertEqual(len(row), 11,
                             f'CSV row should have exactly 11 keys, got {len(row)}: {list(row.keys())}')

    # ── 4. value mapping correct ──────────────────────────────────────────────

    def test_csv_values_map_correctly(self):
        rows = self._get_csv_rows()
        row = next((r for r in rows if r['ticker'] == 'CSVTEST'), None)
        self.assertIsNotNone(row, 'CSVTEST not found in CSV rows')

        self.assertIsNotNone(row['entry_price'], 'entry_price must not be None')
        self.assertIsNotNone(row['current_price'], 'current_price must not be None')
        self.assertIsNotNone(row['target'], 'target must not be None')
        self.assertIsNotNone(row['sl'], 'sl must not be None')
        self.assertIsNotNone(row['trail_sl'], 'trail_sl must not be None')

        self.assertAlmostEqual(row['entry_price'], 500.0, places=1)
        self.assertAlmostEqual(row['current_price'], 500.0, places=1)

    # ── 5. entry_date format ──────────────────────────────────────────────────

    def test_entry_date_format(self):
        import re
        rows = self._get_csv_rows()
        row = next((r for r in rows if r['ticker'] == 'CSVTEST'), None)
        self.assertIsNotNone(row)
        entry_date = row.get('entry_date', '')
        self.assertNotEqual(entry_date, '', 'entry_date must not be empty')
        self.assertRegex(entry_date, r'^\d{1,2} [A-Z][a-z]{2}$',
                         f'entry_date should look like "10 Jul", got: {entry_date!r}')

    # ── 6. PnL columns present ────────────────────────────────────────────────

    def test_pnl_columns_present(self):
        rows = self._get_csv_rows()
        row = next((r for r in rows if r['ticker'] == 'CSVTEST'), None)
        self.assertIsNotNone(row)
        self.assertIn('pnl_pct', row)
        self.assertIn('pnl_amount', row)
        self.assertIn('days', row)

    # ── 7. DataFrame columns match ────────────────────────────────────────────

    def test_running_csv_as_dataframe(self):
        import main
        rows = main._build_running_csv_rows()
        df = pd.DataFrame(rows)
        self.assertListEqual(list(df.columns), EXPECTED_COLUMNS)

    # ── 8. JSON API still returns full internal row shape ─────────────────────

    def test_json_running_api_returns_rich_shape(self):
        """
        /api/screener/running must return the full internal row shape —
        not the trimmed 11-column CSV shape.
        """
        import main, json
        app = main.app.test_client()
        resp = app.get('/api/screener/running')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['mode'], 'running')
        if data['count'] > 0:
            row = data['results'][0]
            # Must have rich fields that are NOT in the CSV
            self.assertIn('entry_at', row)
            self.assertIn('status', row)
            self.assertIn('pnl_pct', row)
            # Must NOT be limited to just 11 keys
            self.assertGreater(len(row.keys()), 11,
                               '/api/screener/running should return the full rich row shape')

    # ── 9. /api/screener/booked is unchanged ─────────────────────────────────

    def test_json_booked_api_intact(self):
        import main, json
        # Seed a booked entry
        entry_id = tracker_store.create_entry(
            ticker='BOOKEDTEST', index_name='nifty50',
            entry_at='2026-07-01T10:00:00', entry_price=1000.0,
            entry_source='close', target_pct=0.15, sl_pct=0.05,
            trail_sl_pct=0.08, report_name='test.csv'
        )
        tracker_store.close_entry(
            entry_id=entry_id, status='target_hit',
            exit_at='2026-07-02T14:00:00', exit_price=1150.0,
            exit_reason='Target', report_name='test.csv'
        )
        app = main.app.test_client()
        resp = app.get('/api/screener/booked')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['mode'], 'booked')
        self.assertGreater(data['count'], 0)
        row = data['results'][0]
        # Booked entries must still have realized_pnl_pct
        self.assertIn('realized_pnl_pct', row)


# =============================================================================
# Regression tests: empty running.csv must emit 11-column header
# =============================================================================

class TestEmptyRunningCsv(unittest.TestCase):
    """
    Regression suite: /api/reports/running.csv must always emit a valid
    11-column header row even when there are zero active running positions.
    """
    DB_PATH = str(Path(__file__).resolve().parent / 'data' / 'test_running_csv_empty.db')

    def setUp(self):
        tracker_store.DB_PATH = self.DB_PATH
        import main
        main.tracker_store.DB_PATH = self.DB_PATH
        if os.path.exists(self.DB_PATH):
            try:
                os.remove(self.DB_PATH)
            except Exception:
                pass
        tracker_store.init_db()   # empty DB — no entries
        try:
            with tracker_store.get_conn() as conn:
                conn.execute("DELETE FROM screen_snapshots;")
                conn.execute("DELETE FROM screen_entries;")
        except Exception:
            pass

    def tearDown(self):
        try:
            with tracker_store.get_conn() as conn:
                conn.execute("DELETE FROM screen_snapshots;")
                conn.execute("DELETE FROM screen_entries;")
        except Exception:
            pass
        if os.path.exists(self.DB_PATH):
            try:
                os.remove(self.DB_PATH)
            except Exception:
                pass

    def test_empty_build_running_csv_rows_returns_empty_list(self):
        """_build_running_csv_rows() returns [] when there are no active entries."""
        import main
        rows = main._build_running_csv_rows()
        self.assertEqual(rows, [],
                         '_build_running_csv_rows() should return [] when DB is empty')

    def test_empty_running_csv_endpoint_has_eleven_column_header(self):
        """
        GET /api/reports/running.csv with no active positions must still
        return a CSV whose first (header) row contains exactly the 11 required
        columns in the correct order.
        """
        import main
        app = main.app.test_client()
        resp = app.get('/api/reports/running.csv')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, 'text/csv')

        content = resp.data.decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        header = next(reader, None)

        self.assertIsNotNone(header, 'CSV response must contain at least a header row')
        self.assertEqual(header, EXPECTED_COLUMNS,
                         f'Header mismatch.\nExpected: {EXPECTED_COLUMNS}\nGot:      {header}')

    def test_empty_running_csv_has_no_data_rows(self):
        """With zero active positions, the CSV must have no data rows after the header."""
        import main
        app = main.app.test_client()
        resp = app.get('/api/reports/running.csv')
        content = resp.data.decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        # rows[0] = header, rows[1:] should be empty (pandas may add a trailing \r\n)
        data_rows = [r for r in rows[1:] if any(r)]   # filter blank lines
        self.assertEqual(len(data_rows), 0,
                         f'Expected zero data rows, got: {data_rows}')


if __name__ == '__main__':
    unittest.main()

import os
import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
from pathlib import Path

import tracker_store
import config

# ── Disable Angel One network calls for all tests ─────────────────────────────
import angel_ltp
angel_ltp.is_configured = lambda: False

_DATA_DIR = Path(__file__).resolve().parent / 'data'
_DATA_DIR.mkdir(exist_ok=True)


def _fresh_db(db_path: str) -> None:
    """Delete and re-initialise a test SQLite database."""
    tracker_store.DB_PATH = db_path
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass
    tracker_store.init_db()


def _remove_db(db_path: str) -> None:
    tracker_store.DB_PATH = db_path
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass


def _run_pipeline_helper(screener_df, index_name='nifty500_custom',
                         report_name='test_sched_scan.csv', db_path=None):
    """
    Bypass run_batch_screener; call downstream pipeline steps directly.
    """
    if db_path:
        tracker_store.DB_PATH = db_path
    import main
    if not screener_df.empty:
        screener_df = main._annotate_first_seen(screener_df)
        screener_df = main.apply_trade_tracking(screener_df, index_name, report_name)
    return screener_df


# =============================================================================
# Tests: score-gating, de-duplication, first_seen annotation
# =============================================================================

class TestScheduledScanPipeline(unittest.TestCase):
    _DB = str(_DATA_DIR / 'test_pipeline.db')

    def setUp(self):
        _fresh_db(self._DB)

    def tearDown(self):
        _remove_db(self._DB)

    # ── 1. qualifying stock creates Running entry ─────────────────────────────

    def test_qualifying_stock_creates_running_entry(self):
        score = config.TRADE_ENTRY_MIN_SCORE + 5
        df = pd.DataFrame([{'ticker': 'TESTPASS', 'close': 1000.0, 'total_score': score}])
        _run_pipeline_helper(df, db_path=self._DB)
        running = tracker_store.get_running_entries()
        tickers = [r['ticker'] for r in running]
        self.assertIn('TESTPASS', tickers)
        entry = next(r for r in running if r['ticker'] == 'TESTPASS')
        self.assertEqual(entry['status'], 'active')
        self.assertEqual(entry['gated_entry'], 1)

    # ── 2. below-threshold stock is NOT inserted ──────────────────────────────

    def test_below_threshold_stock_not_inserted(self):
        score = config.TRADE_ENTRY_MIN_SCORE - 5
        df = pd.DataFrame([{'ticker': 'TESTFAIL', 'close': 500.0, 'total_score': score}])
        _run_pipeline_helper(df, db_path=self._DB)
        running = tracker_store.get_running_entries()
        tickers = [r['ticker'] for r in running]
        self.assertNotIn('TESTFAIL', tickers)

    # ── 3. second scan updates, does NOT duplicate ────────────────────────────

    def test_second_scan_updates_not_duplicates(self):
        score = config.TRADE_ENTRY_MIN_SCORE + 10
        df1 = pd.DataFrame([{'ticker': 'TESTUPD', 'close': 800.0, 'total_score': score}])
        _run_pipeline_helper(df1, db_path=self._DB)
        df2 = pd.DataFrame([{'ticker': 'TESTUPD', 'close': 820.0, 'total_score': score}])
        _run_pipeline_helper(df2, db_path=self._DB)
        running = tracker_store.get_running_entries()
        testupd_entries = [r for r in running if r['ticker'] == 'TESTUPD']
        self.assertEqual(len(testupd_entries), 1)

    # ── 4. mixed batch: only qualifying stocks enter Running ──────────────────

    def test_mixed_batch_filters_correctly(self):
        gate = config.TRADE_ENTRY_MIN_SCORE
        df = pd.DataFrame([
            {'ticker': 'ABOVEPASS', 'close': 200.0, 'total_score': gate + 1},
            {'ticker': 'BELOWFAIL', 'close': 100.0, 'total_score': gate - 1},
            {'ticker': 'EXACTPASS', 'close': 150.0, 'total_score': gate},
        ])
        _run_pipeline_helper(df, db_path=self._DB)
        running = tracker_store.get_running_entries()
        tickers = [r['ticker'] for r in running]
        self.assertIn('ABOVEPASS', tickers)
        self.assertNotIn('BELOWFAIL', tickers)
        self.assertIn('EXACTPASS', tickers)

    # ── 5. _annotate_first_seen adds required columns ─────────────────────────

    def test_annotate_first_seen_adds_columns(self):
        import main
        df = pd.DataFrame([{'ticker': 'RELIANCE', 'close': 2500.0, 'total_score': 80}])
        df_annotated = main._annotate_first_seen(df.copy())
        self.assertIn('first_seen', df_annotated.columns)
        self.assertIn('days_in_screener', df_annotated.columns)
        self.assertGreaterEqual(df_annotated.iloc[0]['days_in_screener'], 0)


# =============================================================================
# End-to-end tests: _run_scan_pipeline() with a mocked screener and Telegram mock
# =============================================================================

class TestRunScanPipelineE2E(unittest.TestCase):
    _DB = str(_DATA_DIR / 'test_e2e_pipeline.db')

    def setUp(self):
        _fresh_db(self._DB)

    def tearDown(self):
        _remove_db(self._DB)

    def _mock_screener_df(self, rows):
        return pd.DataFrame(rows)

    @patch("telegram_alert.send_new_running_trade_alert", return_value=True)
    def test_run_scan_pipeline_persists_qualifying_stock_and_alerts(self, mock_alert):
        """_run_scan_pipeline() must insert qualifying stocks and send running alert exactly once."""
        import main
        tracker_store.DB_PATH = self._DB
        score = config.TRADE_ENTRY_MIN_SCORE + 5
        mock_df = self._mock_screener_df([
            {'ticker': 'E2EPASS', 'close': 900.0, 'total_score': score}
        ])
        
        # 1. Run first scan — should trigger alert
        with patch('main.run_batch_screener', return_value=mock_df):
            main._run_scan_pipeline(
                ['E2EPASS'],
                index_name='nifty500_custom',
                report_name='e2e_test.csv',
                save_csv=False,
                update_bg_cache=False,
            )
        
        running = tracker_store.get_running_entries()
        tickers = [r['ticker'] for r in running]
        self.assertIn('E2EPASS', tickers)
        mock_alert.assert_called_once()
        
        # Verify event was recorded
        entry_id = running[0]["id"]
        self.assertTrue(tracker_store.telegram_event_sent(f"new_running:{entry_id}"))

        # Reset mock
        mock_alert.reset_mock()
        
        # 2. Run scan again — same stock should NOT trigger alert again
        with patch('main.run_batch_screener', return_value=mock_df):
            main._run_scan_pipeline(
                ['E2EPASS'],
                index_name='nifty500_custom',
                report_name='e2e_test.csv',
                save_csv=False,
                update_bg_cache=False,
            )
        mock_alert.assert_not_called()

    def test_run_scan_pipeline_does_not_insert_below_threshold(self):
        """_run_scan_pipeline() must skip stocks below TRADE_ENTRY_MIN_SCORE."""
        import main
        tracker_store.DB_PATH = self._DB
        score = config.TRADE_ENTRY_MIN_SCORE - 5
        mock_df = self._mock_screener_df([
            {'ticker': 'E2EFAIL', 'close': 300.0, 'total_score': score}
        ])
        with patch('main.run_batch_screener', return_value=mock_df):
            main._run_scan_pipeline(
                ['E2EFAIL'],
                index_name='nifty500_custom',
                report_name='e2e_test.csv',
                save_csv=False,
                update_bg_cache=False,
            )
        running = tracker_store.get_running_entries()
        self.assertEqual(len(running), 0)

    def test_run_scan_pipeline_update_bg_cache_false_preserves_cache(self):
        """Scheduled scans with update_bg_cache=False must NOT overwrite _bg['results']."""
        import main
        tracker_store.DB_PATH = self._DB
        sentinel = [{'ticker': 'MANUAL_RESULT', 'total_score': 88}]
        main._bg['results'] = sentinel[:]

        mock_df = pd.DataFrame([
            {'ticker': 'SCHEDULED', 'close': 100.0,
             'total_score': config.TRADE_ENTRY_MIN_SCORE + 1}
        ])
        with patch('main.run_batch_screener', return_value=mock_df):
            main._run_scan_pipeline(
                ['SCHEDULED'],
                index_name='nifty500_custom',
                report_name='cache_test.csv',
                save_csv=False,
                update_bg_cache=False,
            )

        self.assertEqual(main._bg['results'], sentinel,
                         '_bg["results"] was overwritten by a scheduled scan')

    def test_run_scan_pipeline_update_bg_cache_true_updates_cache(self):
        """When update_bg_cache=True (manual path), _bg['results'] IS updated."""
        import main
        tracker_store.DB_PATH = self._DB
        main._bg['results'] = []

        score = config.TRADE_ENTRY_MIN_SCORE + 5
        mock_df = pd.DataFrame([
            {'ticker': 'MANUALUPD', 'close': 200.0, 'total_score': score}
        ])
        with patch('main.run_batch_screener', return_value=mock_df):
            main._run_scan_pipeline(
                ['MANUALUPD'],
                index_name='nifty500_custom',
                report_name='manual_cache_test.csv',
                save_csv=False,
                update_bg_cache=True,
            )

        result_tickers = [r['ticker'] for r in main._bg['results']]
        self.assertIn('MANUALUPD', result_tickers)

    @patch("telegram_alert.send_booked_trade_alert", return_value=True)
    def test_scan_pipeline_booked_trade_sends_alert_once(self, mock_alert):
        """Booked trade during scan runs sends a booked alert exactly once."""
        import main
        tracker_store.DB_PATH = self._DB
        
        # 1. Seed active entry
        from datetime import datetime
        from main import IST
        entry_id = tracker_store.create_entry(
            ticker="BOOKTEST",
            index_name="nifty500_custom",
            entry_at=datetime.now(IST).isoformat(),
            entry_price=100.0,
            entry_source="close",
            target_pct=0.15,
            sl_pct=0.05,
            trail_sl_pct=0.08,
            report_name="test_report.csv"
        )
        
        # 2. Run scan causing stop loss hit (price = 90.0 <= sl_price = 95.0)
        mock_df = self._mock_screener_df([
            {'ticker': 'BOOKTEST', 'close': 90.0, 'total_score': 60}
        ])
        
        with patch('main.run_batch_screener', return_value=mock_df):
            main._run_scan_pipeline(
                ['BOOKTEST'],
                index_name='nifty500_custom',
                report_name='test_book.csv',
                save_csv=False,
                update_bg_cache=False,
            )
            main._run_scan_pipeline(
                ['BOOKTEST'],
                index_name='nifty500_custom',
                report_name='test_book.csv',
                save_csv=False,
                update_bg_cache=False,
            )
            
        # Verify exit and alert sent
        mock_alert.assert_called_once()
        self.assertTrue(tracker_store.telegram_event_sent(f"booked:{entry_id}"))
        
        # Reset and run again
        mock_alert.reset_mock()
        with patch('main.run_batch_screener', return_value=mock_df):
            main._run_scan_pipeline(
                ['BOOKTEST'],
                index_name='nifty500_custom',
                report_name='test_book.csv',
                save_csv=False,
                update_bg_cache=False,
            )
        mock_alert.assert_not_called()


# =============================================================================
# End-to-end tests: _nightly_screener() and _auto_telegram_scan()
# =============================================================================

class TestScheduledJobsE2E(unittest.TestCase):
    _DB = str(_DATA_DIR / 'test_jobs_e2e.db')

    def setUp(self):
        _fresh_db(self._DB)

    def tearDown(self):
        _remove_db(self._DB)

    def test_nightly_screener_persists_tracking_and_preserves_bg_cache(self):
        """
        _nightly_screener() must:
        - Insert qualifying stocks into the tracker DB.
        - NOT overwrite _bg['results'].
        """
        import main
        tracker_store.DB_PATH = self._DB
        sentinel = [{'ticker': 'MANUAL', 'total_score': 99}]
        main._bg['results'] = sentinel[:]

        score = config.TRADE_ENTRY_MIN_SCORE + 5
        mock_df = pd.DataFrame([
            {'ticker': 'NIGHTLY1', 'close': 500.0, 'total_score': score}
        ])

        with patch('main.run_batch_screener', return_value=mock_df):
            main._nightly_screener()

        running = tracker_store.get_running_entries()
        tickers = [r['ticker'] for r in running]
        self.assertIn('NIGHTLY1', tickers)

        self.assertEqual(main._bg['results'], sentinel,
                         '_nightly_screener overwrote _bg["results"]')

    def test_auto_telegram_scan_persists_tracking_and_preserves_bg_cache(self):
        """
        _auto_telegram_scan() must:
        - Insert qualifying stocks into the tracker DB (even when Telegram is down).
        - NOT overwrite _bg['results'].
        """
        import main
        import pytz
        from datetime import datetime as real_datetime

        tracker_store.DB_PATH = self._DB
        sentinel = [{'ticker': 'MANUAL', 'total_score': 99}]
        main._bg['results'] = sentinel[:]

        score = config.TRADE_ENTRY_MIN_SCORE + 5
        mock_df = pd.DataFrame([
            {'ticker': 'AUTOSCAN1', 'close': 400.0, 'total_score': score}
        ])

        # Build a market-hours timestamp (11:00 IST on a weekday)
        IST = pytz.timezone('Asia/Kolkata')
        market_time = IST.localize(real_datetime(2026, 7, 14, 11, 0, 0))

        class _MockDatetime:
            """Minimal datetime stand-in that returns market_time for now(IST)."""
            @staticmethod
            def now(tz=None):
                return market_time
            # Forward class construction to real datetime
            def __new__(cls, *args, **kwargs):
                return real_datetime(*args, **kwargs)

        with patch('main.run_batch_screener', return_value=mock_df),              patch('main.datetime', _MockDatetime):
            main._auto_telegram_scan()

        running = tracker_store.get_running_entries()
        tickers = [r['ticker'] for r in running]
        self.assertIn('AUTOSCAN1', tickers,
                      f'Expected AUTOSCAN1 in running, got: {tickers}')

        self.assertEqual(main._bg['results'], sentinel,
                         '_auto_telegram_scan overwrote _bg["results"]')

    def test_scheduled_scan_tickers_uniqueness(self):
        """Verify that SCHEDULED_SCAN_TICKERS contains unique tickers only (no duplicates)."""
        import main
        self.assertEqual(len(main.SCHEDULED_SCAN_TICKERS), len(set(main.SCHEDULED_SCAN_TICKERS)),
                         "SCHEDULED_SCAN_TICKERS contains duplicate tickers!")

if __name__ == '__main__':
    unittest.main()

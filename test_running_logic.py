import os
import unittest
from unittest.mock import patch
import pandas as pd
from pathlib import Path
import json

import tracker_store
import config
import main

_DATA_DIR = Path(__file__).resolve().parent / 'data'
_DATA_DIR.mkdir(exist_ok=True)
TEST_DB_PATH = str(_DATA_DIR / 'test_running_logic.db')

class TestRunningTabFiltering(unittest.TestCase):
    def setUp(self):
        main.tracker_store.DB_PATH = TEST_DB_PATH
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass
        tracker_store.init_db()
        # Reset cache
        main._bg["results"] = []

    def tearDown(self):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def test_running_tab_score_filtering(self):
        """Test that Running tab only returns active entries with current score >= 70."""
        # 1. Seed two active entries
        tracker_store.create_entry(
            ticker="QUALIFIED",
            index_name="nifty50",
            entry_at="2026-07-10T12:00:00",
            entry_price=100.0,
            entry_source="close",
            target_pct=0.15,
            sl_pct=0.05,
            trail_sl_pct=0.08,
            report_name="test.csv"
        )
        tracker_store.create_entry(
            ticker="LOWSCORE",
            index_name="nifty50",
            entry_at="2026-07-10T12:00:00",
            entry_price=200.0,
            entry_source="close",
            target_pct=0.15,
            sl_pct=0.05,
            trail_sl_pct=0.08,
            report_name="test.csv"
        )

        # 2. Mock current scores: QUALIFIED has 75, LOWSCORE has 60
        mock_scores = {
            "QUALIFIED": 75.0,
            "LOWSCORE": 60.0
        }
        with patch("main._get_latest_screener_scores", return_value=mock_scores):
            rows = main._build_running_rows()
            tickers = [r["ticker"] for r in rows]
            
            # Since we removed score gating on active positions (vanishing trades fix),
            # both QUALIFIED and LOWSCORE should remain visible!
            self.assertIn("QUALIFIED", tickers)
            self.assertIn("LOWSCORE", tickers)
            self.assertEqual(len(tickers), 2)

            # 3. Verify running.csv matches the view
            csv_rows = main._build_running_csv_rows()
            csv_tickers = [r["ticker"] for r in csv_rows]
            self.assertIn("QUALIFIED", csv_tickers)
            self.assertIn("LOWSCORE", csv_tickers)
            self.assertEqual(len(csv_tickers), 2)

    def test_booked_is_not_affected_by_score_filter(self):
        """Test that booked trades are returned regardless of their score."""
        # 1. Seed a booked entry
        entry_id = tracker_store.create_entry(
            ticker="BOOKED",
            index_name="nifty50",
            entry_at="2026-07-10T12:00:00",
            entry_price=100.0,
            entry_source="close",
            target_pct=0.15,
            sl_pct=0.05,
            trail_sl_pct=0.08,
            report_name="test.csv"
        )
        tracker_store.close_entry(
            entry_id=entry_id,
            status="target_hit",
            exit_at="2026-07-15T12:00:00",
            exit_price=115.0,
            exit_reason="Target met",
            report_name="test_exit.csv"
        )

        # 2. Mock score = 50 for BOOKED
        mock_scores = {"BOOKED": 50.0}
        with patch("main._get_latest_screener_scores", return_value=mock_scores):
            rows = main._build_booked_rows()
            tickers = [r["ticker"] for r in rows]
            
            # Booked trade must still appear
            self.assertIn("BOOKED", tickers)
            self.assertEqual(len(tickers), 1)

    def test_re_entry_guard_time_buffer(self):
        """Test that re-entry is blocked within 1 hour of exit but allowed after 1 hour."""
        from datetime import datetime, timedelta
        import config
        from zoneinfo import ZoneInfo
        IST = ZoneInfo("Asia/Kolkata")
        
        # 1. Seed a closed entry that exited 30 minutes ago
        exit_at_recent = (datetime.now(IST) - timedelta(minutes=30)).isoformat()
        entry_id_recent = tracker_store.create_entry(
            ticker="RECENTEXIT", index_name="nifty50",
            entry_at="2026-07-10T10:00:00", entry_price=100.0,
            entry_source="close", target_pct=0.15, sl_pct=0.05,
            trail_sl_pct=0.08, report_name="test.csv"
        )
        tracker_store.close_entry(
            entry_id=entry_id_recent, status="sl_hit",
            exit_at=exit_at_recent, exit_price=95.0,
            exit_reason="SL", report_name="test.csv"
        )
        
        # 2. Seed a closed entry that exited 2 hours ago
        exit_at_old = (datetime.now(IST) - timedelta(hours=2)).isoformat()
        entry_id_old = tracker_store.create_entry(
            ticker="OLDEXIT", index_name="nifty50",
            entry_at="2026-07-10T10:00:00", entry_price=100.0,
            entry_source="close", target_pct=0.15, sl_pct=0.05,
            trail_sl_pct=0.08, report_name="test.csv"
        )
        tracker_store.close_entry(
            entry_id=entry_id_old, status="sl_hit",
            exit_at=exit_at_old, exit_price=95.0,
            exit_reason="SL", report_name="test.csv"
        )
        
        # 3. Call _defend_running_entry_creation
        active_entries = {}
        all_entries = tracker_store.get_all_entries_for_tickers(["RECENTEXIT", "OLDEXIT"])
        
        row_recent = {"ticker": "RECENTEXIT", "total_score": config.TRADE_ENTRY_MIN_SCORE + 5}
        row_old = {"ticker": "OLDEXIT", "total_score": config.TRADE_ENTRY_MIN_SCORE + 5}
        
        # RECENTEXIT (exit 30m ago) should NOT be allowed to re-enter
        can_enter_recent = main._defend_running_entry_creation(row_recent, active_entries, all_entries)
        self.assertFalse(can_enter_recent)
        
        # OLDEXIT (exit 2h ago) should be allowed to re-enter
        can_enter_old = main._defend_running_entry_creation(row_old, active_entries, all_entries)
        self.assertTrue(can_enter_old)


if __name__ == "__main__":
    unittest.main()

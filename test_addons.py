import unittest
import os
import tracker_store
from main import _evaluate_exit
from pathlib import Path

TEST_DB_PATH = str(Path(__file__).resolve().parent / "data" / "test_tracker_store_addons.db")

class TestTrackerStoreAddons(unittest.TestCase):
    def setUp(self):
        self.old_db_path = tracker_store.DB_PATH
        tracker_store.DB_PATH = TEST_DB_PATH
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass
        tracker_store.init_db()

    def tearDown(self):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass
        tracker_store.DB_PATH = self.old_db_path

    def test_scan_ltp_history(self):
        """Test upserting and retrieving from scan_ltp_history table."""
        ticker = "RELIANCE"
        today = "2026-07-17"
        
        # Initial retrieval should be None
        prev = tracker_store.get_prev_scan_ltp(ticker, today)
        self.assertIsNone(prev)
        
        # Upsert price
        tracker_store.upsert_scan_ltp(ticker, 2450.50, today)
        prev = tracker_store.get_prev_scan_ltp(ticker, today)
        self.assertEqual(prev, 2450.50)
        
        # Upsert updated price
        tracker_store.upsert_scan_ltp(ticker, 2465.00, today)
        prev = tracker_store.get_prev_scan_ltp(ticker, today)
        self.assertEqual(prev, 2465.00)

    def test_update_entry_state_dynamic(self):
        """Test update_entry_state optionally updates sl_breach_count and sl_breach_since."""
        ticker = "SBIN"
        entry_id = tracker_store.create_entry(
            ticker=ticker,
            index_name="nifty50",
            entry_at="2026-07-17T12:00:00",
            entry_price=600.00,
            entry_source="close",
            target_pct=0.10,
            sl_pct=0.05,
            trail_sl_pct=0.07,
            report_name="test.csv"
        )
        
        # Check initial breach count is 0/None
        entry = tracker_store.get_active_entry(ticker)
        self.assertEqual(entry.get("sl_breach_count") or 0, 0)
        self.assertIsNone(entry.get("sl_breach_since"))
        
        # Update without breach params
        tracker_store.update_entry_state(
            entry_id=entry_id,
            last_price=610.00,
            last_seen_at="2026-07-17T12:03:00",
            highest_price=610.00,
            current_trail_sl=567.30
        )
        entry = tracker_store.get_active_entry(ticker)
        self.assertEqual(entry["last_price"], 610.00)
        self.assertEqual(entry.get("sl_breach_count") or 0, 0)
        
        # Update WITH breach params
        tracker_store.update_entry_state(
            entry_id=entry_id,
            last_price=560.00,
            last_seen_at="2026-07-17T12:06:00",
            sl_breach_count=1,
            sl_breach_since="2026-07-17T12:06:00"
        )
        entry = tracker_store.get_active_entry(ticker)
        self.assertEqual(entry["last_price"], 560.00)
        self.assertEqual(entry.get("sl_breach_count"), 1)
        self.assertEqual(entry.get("sl_breach_since"), "2026-07-17T12:06:00")

        # Reset breach params
        tracker_store.update_entry_state(
            entry_id=entry_id,
            last_price=590.00,
            last_seen_at="2026-07-17T12:09:00",
            sl_breach_count=0,
            sl_breach_since=None
        )
        entry = tracker_store.get_active_entry(ticker)
        self.assertEqual(entry["last_price"], 590.00)
        self.assertEqual(entry.get("sl_breach_count") or 0, 0)
        self.assertIsNone(entry.get("sl_breach_since"))

    def test_evaluate_exit_logic(self):
        """Test shared exit check logic is robust (SL, trailing SL, target)."""
        entry = {
            "sl_price": 100.0,
            "target_price": 120.0,
            "current_trail_sl": 95.0,
            "highest_price": 105.0,
            "trail_sl_pct": 0.05,
            "sl_breach_count": 0,
            "sl_breach_since": None
        }
        
        # Case 1: Normal price within range
        res = _evaluate_exit(entry, 103.0, "now")
        self.assertEqual(res["status"], "active")
        self.assertEqual(res["sl_breach_count"], 0)
        self.assertIsNone(res["sl_breach_since"])
        self.assertEqual(res["highest_price"], 105.0)  # no new high
        
        # Case 2: New high updates trailing SL
        res = _evaluate_exit(entry, 110.0, "now")
        self.assertEqual(res["status"], "active")
        self.assertEqual(res["highest_price"], 110.0)
        self.assertEqual(res["current_trail_sl"], 104.50)  # 110 * 0.95
        
        # Case 3: Target hit is instant (no breach counting)
        res = _evaluate_exit(entry, 121.0, "now")
        self.assertEqual(res["status"], "target_hit")
        self.assertEqual(res["exit_price"], 121.0)
        
        # Case 4: First SL breach increments count, remains active
        res = _evaluate_exit(entry, 98.0, "breach_time")
        self.assertEqual(res["status"], "active")
        self.assertEqual(res["sl_breach_count"], 1)
        self.assertEqual(res["sl_breach_since"], "breach_time")
        
        # Case 5: Second consecutive breach closes position
        entry_breached = entry.copy()
        entry_breached["sl_breach_count"] = 1
        entry_breached["sl_breach_since"] = "breach_time"
        res = _evaluate_exit(entry_breached, 97.0, "close_time")
        self.assertEqual(res["status"], "sl_hit")
        self.assertEqual(res["exit_price"], 97.0)
        self.assertEqual(res["exit_reason"], "Fixed Stop Loss hit (confirmed)")
        
        # Case 6: Recovery resets breach count
        entry_breached = entry.copy()
        entry_breached["sl_breach_count"] = 1
        entry_breached["sl_breach_since"] = "breach_time"
        res = _evaluate_exit(entry_breached, 102.0, "now")
        self.assertEqual(res["status"], "active")
        self.assertEqual(res["sl_breach_count"], 0)
        self.assertIsNone(res["sl_breach_since"])

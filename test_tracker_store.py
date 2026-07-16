import unittest
import os
import tracker_store
from pathlib import Path

# Use a test DB path
TEST_DB_PATH = str(Path(__file__).resolve().parent / "data" / "test_tracker_store_isolated.db")
tracker_store.DB_PATH = TEST_DB_PATH

class TestTrackerStore(unittest.TestCase):
    def setUp(self):
        tracker_store.DB_PATH = TEST_DB_PATH
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass
        tracker_store.init_db()
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
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def test_init_db(self):
        """Test DB initialization creates the schema and tables."""
        self.assertTrue(os.path.exists(TEST_DB_PATH))

    def test_create_and_get_entry(self):
        """Test active entry creation and retrieval."""
        ticker = "RELIANCE"
        entry_id = tracker_store.create_entry(
            ticker=ticker,
            index_name="nifty50",
            entry_at="2026-07-10T12:00:00",
            entry_price=2500.00,
            entry_source="close",
            target_pct=0.10,
            sl_pct=0.05,
            trail_sl_pct=0.07,
            report_name="test_report.csv"
        )
        self.assertGreater(entry_id, 0)
        
        entry = tracker_store.get_active_entry(ticker)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["ticker"], ticker)
        self.assertEqual(entry["entry_price"], 2500.00)
        self.assertEqual(entry["target_price"], 2750.00)  # 2500 * 1.10
        self.assertEqual(entry["sl_price"], 2375.00)      # 2500 * 0.95
        self.assertEqual(entry["highest_price"], 2500.00)
        self.assertEqual(entry["current_trail_sl"], 2325.00)  # 2500 * 0.93
        self.assertEqual(entry["status"], "active")

    def test_update_entry_state(self):
        """Test active entry state updates (e.g. highest_price, trail_sl)."""
        ticker = "TCS"
        entry_id = tracker_store.create_entry(
            ticker=ticker,
            index_name="nifty50",
            entry_at="2026-07-10T12:00:00",
            entry_price=3500.00,
            entry_source="close",
            target_pct=0.10,
            sl_pct=0.05,
            trail_sl_pct=0.07,
            report_name="test_report.csv"
        )
        
        # Simulate price going up
        tracker_store.update_entry_state(
            entry_id=entry_id,
            last_price=3700.00,
            last_seen_at="2026-07-10T13:00:00",
            highest_price=3700.00,
            current_trail_sl=3441.00,  # 3700 * 0.93
            report_name="test_report_2.csv"
        )
        
        entry = tracker_store.get_active_entry(ticker)
        self.assertEqual(entry["last_price"], 3700.00)
        self.assertEqual(entry["highest_price"], 3700.00)
        self.assertEqual(entry["current_trail_sl"], 3441.00)
        self.assertEqual(entry["last_report_name"], "test_report_2.csv")

    def test_close_entry(self):
        """Test closing an active entry."""
        ticker = "INFY"
        entry_id = tracker_store.create_entry(
            ticker=ticker,
            index_name="nifty50",
            entry_at="2026-07-10T12:00:00",
            entry_price=1500.00,
            entry_source="close",
            target_pct=0.10,
            sl_pct=0.05,
            trail_sl_pct=0.07,
            report_name="test_report.csv"
        )
        
        tracker_store.close_entry(
            entry_id=entry_id,
            status="target_hit",
            exit_at="2026-07-10T14:00:00",
            exit_price=1650.00,
            exit_reason="Target price hit",
            report_name="test_report_exit.csv"
        )
        
        # Should not be returned by get_active_entry
        active = tracker_store.get_active_entry(ticker)
        self.assertIsNone(active)
        
        # Verify in export
        all_entries = tracker_store.export_all_entries()
        self.assertEqual(len(all_entries), 1)
        self.assertEqual(all_entries[0]["status"], "target_hit")
        self.assertEqual(all_entries[0]["exit_reason"], "Target price hit")

    def test_snapshots(self):
        """Test snapshot creation and linking."""
        ticker = "SBIN"
        entry_id = tracker_store.create_entry(
            ticker=ticker,
            index_name="nifty50",
            entry_at="2026-07-10T12:00:00",
            entry_price=600.00,
            entry_source="close",
            target_pct=0.10,
            sl_pct=0.05,
            trail_sl_pct=0.07,
            report_name="test_report.csv"
        )
        
        tracker_store.append_snapshot(
            entry_id=entry_id,
            snapshot_at="2026-07-10T12:30:00",
            price=610.00,
            highest_price=610.00,
            current_trail_sl=567.30,
            status="active",
            report_name="test_report.csv"
        )
        
        with tracker_store.get_conn() as conn:
            row = conn.execute("SELECT * FROM screen_snapshots WHERE entry_id = ?", (entry_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["price"], 610.00)

    def test_telegram_events(self):
        """Test telegram_events table behavior and helpers."""
        event_key = "new_running:999"
        
        # 1. Event should not be sent initially
        self.assertFalse(tracker_store.telegram_event_sent(event_key))
        
        # 2. Record the event
        tracker_store.record_telegram_event(
            event_key=event_key,
            event_type="new_running",
            entry_id=999,
            ticker="EVENTTEST"
        )
        
        # 3. Event should be sent now
        self.assertTrue(tracker_store.telegram_event_sent(event_key))
        
        # 4. Recording the same event again (duplicate key) should be ignored and not crash
        tracker_store.record_telegram_event(
            event_key=event_key,
            event_type="new_running",
            entry_id=999,
            ticker="EVENTTEST"
        )
        self.assertTrue(tracker_store.telegram_event_sent(event_key))
        
        # 5. Verify the columns and sent_at exists in DB
        with tracker_store.get_conn() as conn:
            row = conn.execute("SELECT * FROM telegram_events WHERE event_key = ?", (event_key,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["event_type"], "new_running")
            self.assertEqual(row["entry_id"], 999)
            self.assertEqual(row["ticker"], "EVENTTEST")
            self.assertIsNotNone(row["sent_at"])


if __name__ == "__main__":
    unittest.main()


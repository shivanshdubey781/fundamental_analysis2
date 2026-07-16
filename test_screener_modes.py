import unittest
import os
import tracker_store
from pathlib import Path

TEST_DB_PATH = str(Path(__file__).resolve().parent / "data" / "test_screener_modes.db")
tracker_store.DB_PATH = TEST_DB_PATH

class TestScreenerModes(unittest.TestCase):
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

    def test_get_running_and_booked_entries(self):
        # Create an active entry
        entry_id_active = tracker_store.create_entry(
            ticker="TCS",
            index_name="nifty50",
            entry_at="2026-07-10T12:00:00",
            entry_price=3500.0,
            entry_source="close",
            target_pct=0.15,
            sl_pct=0.05,
            trail_sl_pct=0.08,
            report_name="test_report.csv"
        )
        
        # Create another entry and close it (booked)
        entry_id_booked = tracker_store.create_entry(
            ticker="INFY",
            index_name="nifty50",
            entry_at="2026-07-10T12:00:00",
            entry_price=1500.0,
            entry_source="close",
            target_pct=0.15,
            sl_pct=0.05,
            trail_sl_pct=0.08,
            report_name="test_report.csv"
        )
        
        tracker_store.close_entry(
            entry_id=entry_id_booked,
            status="target_hit",
            exit_at="2026-07-10T14:00:00",
            exit_price=1725.0,
            exit_reason="Target price hit",
            report_name="test_report.csv"
        )
        
        # Query running
        running = tracker_store.get_running_entries()
        self.assertEqual(len(running), 1)
        self.assertEqual(running[0]["ticker"], "TCS")
        self.assertEqual(running[0]["status"], "active")
        
        # Query booked
        booked = tracker_store.get_booked_entries()
        self.assertEqual(len(booked), 1)
        self.assertEqual(booked[0]["ticker"], "INFY")
        self.assertEqual(booked[0]["status"], "target_hit")

    def test_enrich_tracker_rows(self):
        # Insert a running entry and enrich
        entry_id = tracker_store.create_entry(
            ticker="RELIANCE",
            index_name="nifty50",
            entry_at="2026-07-10T12:00:00",
            entry_price=2500.0,
            entry_source="close",
            target_pct=0.15,
            sl_pct=0.05,
            trail_sl_pct=0.08,
            report_name="test_report.csv"
        )
        
        tracker_store.update_entry_state(
            entry_id=entry_id,
            last_price=2600.0,
            last_seen_at="2026-07-11T12:00:00",
            highest_price=2700.0,
            current_trail_sl=2484.0,
            report_name="test_report_2.csv"
        )
        
        running = tracker_store.get_running_entries()
        enriched = tracker_store.enrich_tracker_rows(running)
        
        self.assertEqual(len(enriched), 1)
        row = enriched[0]
        self.assertEqual(row["pnl_pct"], 4.0)          # ((2600-2500)/2500)*100
        self.assertEqual(row["running_amount"], 100.0)  # 2600 - 2500
        self.assertEqual(row["max_gain_pct"], 8.0)      # ((2700-2500)/2500)*100
        self.assertEqual(row["drawdown_from_high_pct"], -3.7) # ((2600-2700)/2700)*100
        self.assertEqual(row["days_running"], 1)

if __name__ == "__main__":
    unittest.main()

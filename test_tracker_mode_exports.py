import unittest
import os
import json
import tracker_store
import main
from pathlib import Path

TEST_DB_PATH = str(Path(__file__).resolve().parent / "data" / "test_tracker_mode_exports.db")
tracker_store.DB_PATH = TEST_DB_PATH

class TestTrackerModeExports(unittest.TestCase):
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
        self.app = main.app.test_client()
        self.app.testing = True

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

    def test_json_endpoints(self):
        # Seed an active entry
        tracker_store.create_entry(
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
        
        # Seed a booked entry
        entry_id = tracker_store.create_entry(
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
            entry_id=entry_id,
            status="target_hit",
            exit_at="2026-07-10T14:00:00",
            exit_price=1725.0,
            exit_reason="Target price hit",
            report_name="test_report.csv"
        )

        # Test /api/screener/new
        # We need to make sure _bg["results"] has some entries to test
        main._bg["results"] = [
            {"ticker": "RELIANCE", "total_score": 78, "days_in_screener": 0, "trade_eligible": True, "trade_active": True},
            {"ticker": "SBIN", "total_score": 62, "days_in_screener": 3, "trade_eligible": False, "trade_active": False}
        ]
        
        resp = self.app.get("/api/screener/new")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["mode"], "new")
        self.assertEqual(data["count"], 2)
        
        # Test today_only parameter
        resp = self.app.get("/api/screener/new?today_only=1")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["ticker"], "RELIANCE")

        # Test /api/screener/running
        resp = self.app.get("/api/screener/running")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["mode"], "running")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["ticker"], "TCS")
        self.assertIn("pnl_pct", data["results"][0])

        # Test /api/screener/booked
        resp = self.app.get("/api/screener/booked")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["mode"], "booked")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["ticker"], "INFY")
        self.assertIn("realized_pnl_pct", data["results"][0])

    def test_csv_endpoints(self):
        # Seed data
        tracker_store.create_entry(
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
        
        # Test /api/reports/running.csv
        resp = self.app.get("/api/reports/running.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "text/csv")
        self.assertIn("attachment; filename=screener_running.csv", resp.headers["Content-Disposition"])
        content = resp.data.decode("utf-8")
        self.assertIn("ticker", content)
        self.assertIn("TCS", content)

    def test_reports_today_absolute_download_url(self):
        """Test that /api/reports/today returns an absolute download_url and /reports/today.csv functions correctly."""
        from datetime import datetime
        today_str = datetime.now(main.IST).strftime('%Y%m%d')
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        report_file = reports_dir / f"screener_{today_str}_120000.csv"
        report_file.write_text("ticker,close\nTCS,3500.0\n", encoding="utf-8")
        
        try:
            resp = self.app.get("/api/reports/today")
            self.assertEqual(resp.status_code, 200)
            data = resp.json
            self.assertTrue(data["ok"])
            self.assertEqual(data["name"], f"screener_{today_str}_120000.csv")
            self.assertTrue(data["download_url"].startswith("http://"))
            self.assertTrue(data["download_url"].endswith("/reports/today.csv"))
            
            resp_csv = self.app.get("/reports/today.csv")
            self.assertEqual(resp_csv.status_code, 200)
            self.assertEqual(resp_csv.mimetype, "text/csv")
            self.assertIn(f"attachment; filename=screener_{today_str}_120000.csv", resp_csv.headers["Content-Disposition"])
            resp_csv.close()
        finally:
            if report_file.exists():
                report_file.unlink()

    def test_download_new_csv(self):
        """Test that /api/reports/new.csv returns only score >= 70, clean UI columns, and no debug columns."""
        main._bg["results"] = [
            {"ticker": "HIGH1", "total_score": 75.0, "first_seen": "15/07/2026", "grade": "A", "signal": "Buy", "close": 100.0, "last_price": 102.0, "stop_loss": 95.0, "rsi": 65.0, "atr": 5.2, "passes_filter": True, "extra_debug_col": "junk"},
            {"ticker": "HIGH2", "total_score": 70.0, "first_seen": "14/07/2026", "grade": "B", "signal": "Watch", "close": 200.0, "last_price": 198.0, "stop_loss": 190.0, "rsi": 55.0, "atr": 10.5, "passes_filter": False, "extra_debug_col": "junk"},
            {"ticker": "LOW", "total_score": 69.0, "first_seen": "10/07/2026", "grade": "C", "signal": "Neutral", "close": 50.0, "last_price": 49.0, "stop_loss": 47.0, "rsi": 45.0, "atr": 2.1, "passes_filter": True, "extra_debug_col": "junk"}
        ]
        
        try:
            resp = self.app.get("/api/reports/new.csv")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.mimetype, "text/csv")
            self.assertIn("attachment; filename=screener_new.csv", resp.headers["Content-Disposition"])
            
            import io
            import pandas as pd
            content = resp.data.decode("utf-8")
            res_df = pd.read_csv(io.StringIO(content))
            
            self.assertEqual(len(res_df), 2)
            tickers = res_df["ticker"].tolist()
            self.assertIn("HIGH1", tickers)
            self.assertIn("HIGH2", tickers)
            self.assertNotIn("LOW", tickers)
            
            expected_cols = ["ticker", "since", "score", "grd", "signal", "close", "ltp", "stop", "rsi", "atr", "filter"]
            self.assertListEqual(list(res_df.columns), expected_cols)
            
            h1 = res_df[res_df["ticker"] == "HIGH1"].iloc[0]
            self.assertEqual(h1["since"], "15/07/2026")
            self.assertEqual(h1["score"], 75.0)
            self.assertEqual(h1["grd"], "A")
            self.assertEqual(h1["signal"], "Buy")
            self.assertEqual(h1["close"], 100.0)
            self.assertEqual(h1["ltp"], 102.0)
            self.assertEqual(h1["stop"], 95.0)
            self.assertEqual(h1["rsi"], 65.0)
            self.assertEqual(h1["atr"], 5.2)
            self.assertEqual(h1["filter"], "PASS")
            
            h2 = res_df[res_df["ticker"] == "HIGH2"].iloc[0]
            self.assertEqual(h2["filter"], "FAIL")
            
            resp.close()
        finally:
            main._bg["results"] = []

    def test_booked_csv_filtering_and_trail_sl(self):
        """Test booked CSV curated column list, trailing SL logic, and JSON rich schema."""
        entry_trail = tracker_store.create_entry(
            ticker="TRAIL_EXIT",
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
            entry_id=entry_trail,
            status="trail_sl_hit",
            exit_at="2026-07-15T12:00:00",
            exit_price=105.0,
            exit_reason="Trailing Stop Loss hit",
            report_name="test_exit.csv"
        )
        with tracker_store.get_conn() as conn:
            conn.execute("UPDATE screen_entries SET highest_price=115.0, current_trail_sl=105.8 WHERE id=?", (entry_trail,))
            conn.commit()

        entry_fixed = tracker_store.create_entry(
            ticker="FIXED_EXIT",
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
            entry_id=entry_fixed,
            status="sl_hit",
            exit_at="2026-07-12T12:00:00",
            exit_price=95.0,
            exit_reason="Fixed Stop Loss hit",
            report_name="test_exit.csv"
        )

        resp_json = self.app.get("/api/screener/booked")
        self.assertEqual(resp_json.status_code, 200)
        data = resp_json.json
        results = data.get("results", [])
        
        self.assertTrue(len(results) >= 2)
        row_trail_json = next(r for r in results if r["ticker"] == "TRAIL_EXIT")
        self.assertIn("index_name", row_trail_json)
        self.assertIn("entry_source", row_trail_json)
        self.assertIn("drawdown_from_high_pct", row_trail_json)

        resp_csv = self.app.get("/api/reports/booked.csv")
        self.assertEqual(resp_csv.status_code, 200)
        self.assertEqual(resp_csv.mimetype, "text/csv")
        
        import io
        import pandas as pd
        content = resp_csv.data.decode("utf-8")
        res_df = pd.read_csv(io.StringIO(content))
        
        expected_cols = [
            "ticker", "entry_date", "exit_date", "entry_price", "exit_price",
            "target", "sl", "trail_sl", "highest",
            "pnl_pct", "pnl_amount", "days", "exit_type"
        ]
        self.assertListEqual(list(res_df.columns), expected_cols)
        
        for col in ["drawdown_from_high_pct", "gated_entry", "last_report_name", "first_report_name", "index_name"]:
            self.assertNotIn(col, res_df.columns)

        row_trail = res_df[res_df["ticker"] == "TRAIL_EXIT"].iloc[0]
        self.assertEqual(row_trail["exit_type"], "trail_sl_hit")
        self.assertEqual(row_trail["trail_sl"], 105.8)

        row_fixed = res_df[res_df["ticker"] == "FIXED_EXIT"].iloc[0]
        self.assertEqual(row_fixed["exit_type"], "sl_hit")
        self.assertTrue(pd.isna(row_fixed["trail_sl"]) or row_fixed["trail_sl"] == "" or row_fixed["trail_sl"] is None)
        
        resp_csv.close()

if __name__ == "__main__":
    unittest.main()

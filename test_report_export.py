import unittest
import os
import pandas as pd
import tracker_store
import main
from pathlib import Path

TEST_DB_PATH = str(Path(__file__).resolve().parent / "data" / "test_report_export_isolated.db")
tracker_store.DB_PATH = TEST_DB_PATH

class TestReportExport(unittest.TestCase):
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

    def test_apply_trade_tracking_enrichment(self):
        """Test apply_trade_tracking adds all tracking and pnl columns to df."""
        df = pd.DataFrame([
            {"ticker": "RELIANCE", "close": 2500.0, "total_score": 75},
            {"ticker": "TCS", "close": 3500.0, "total_score": 82}
        ])
        
        # Disable Angel LTP during tests to ensure yfinance close fallback is used
        import angel_ltp
        original_configured = angel_ltp.is_configured
        angel_ltp.is_configured = lambda: False
        
        try:
            report_name = "test_export.csv"
            df_enriched = main.apply_trade_tracking(df, "nifty50", report_name)
            
            # Verify columns exist
            required_cols = [
                "entry_at", "entry_price", "entry_source", "target_pct", "target_price",
                "sl_pct", "sl_price", "trail_sl_pct", "highest_price", "current_trail_sl",
                "last_price", "last_seen_at", "status", "exit_at", "exit_price", "exit_reason",
                "pnl_pct", "max_gain_pct", "drawdown_from_high_pct"
            ]
            for col in required_cols:
                self.assertIn(col, df_enriched.columns)
                
            # Verify calculations for new entries
            row = df_enriched.iloc[0]
            self.assertEqual(row["pnl_pct"], 0.0)
            self.assertEqual(row["max_gain_pct"], 0.0)
            self.assertEqual(row["drawdown_from_high_pct"], 0.0)
            self.assertEqual(row["status"], "active")
            
        finally:
            angel_ltp.is_configured = original_configured

    def test_apply_trade_tracking_score_gating(self):
        """Test that only rows with score >= 70 create simulated trades, but existing entries keep tracking."""
        df = pd.DataFrame([
            {"ticker": "RELIANCE", "close": 2500.0, "total_score": 69},  # Under 70, should NOT create trade
            {"ticker": "TCS", "close": 3500.0, "total_score": 70},       # Exactly 70, should create trade
            {"ticker": "INFY", "close": 1500.0, "total_score": 60}       # Under 70, but we will seed an active entry first!
        ])
        
        # Seed an active entry for INFY
        tracker_store.create_entry(
            ticker="INFY",
            index_name="nifty50",
            entry_at="2026-07-10T12:00:00",
            entry_price=1400.0,
            entry_source="close",
            target_pct=0.15,
            sl_pct=0.05,
            trail_sl_pct=0.08,
            report_name="test_report.csv"
        )
        
        # Disable Angel LTP
        import angel_ltp
        original_configured = angel_ltp.is_configured
        angel_ltp.is_configured = lambda: False
        
        try:
            report_name = "test_export.csv"
            df_enriched = main.apply_trade_tracking(df, "nifty50", report_name)
            
            # Verify RELIANCE is not tracked
            rel = df_enriched[df_enriched["ticker"] == "RELIANCE"].iloc[0]
            self.assertEqual(rel["trade_eligible"], False)
            self.assertEqual(rel["trade_active"], False)
            self.assertTrue(pd.isna(rel["entry_price"]))
            
            # Verify TCS is tracked
            tcs = df_enriched[df_enriched["ticker"] == "TCS"].iloc[0]
            self.assertEqual(tcs["trade_eligible"], True)
            self.assertEqual(tcs["trade_active"], True)
            self.assertEqual(tcs["entry_price"], 3500.0)
            self.assertEqual(tcs["status"], "active")
            
            # Verify INFY continues tracking even though score is 60 (< 70)
            infy = df_enriched[df_enriched["ticker"] == "INFY"].iloc[0]
            self.assertEqual(infy["trade_eligible"], False)
            self.assertEqual(infy["trade_active"], True)
            self.assertEqual(infy["entry_price"], 1400.0)
            self.assertEqual(infy["last_price"], 1500.0)
            
        finally:
            angel_ltp.is_configured = original_configured

    def test_apply_trade_tracking_score_gating_exit(self):
        """Test that an existing active entry with score < 70 can still hit target/SL and close."""
        # Seed active entry for TGT_STOCK (target hit)
        tracker_store.create_entry(
            ticker="TGT_STOCK",
            index_name="nifty50",
            entry_at="2026-07-10T12:00:00",
            entry_price=1000.0,
            entry_source="close",
            target_pct=0.15,
            sl_pct=0.05,
            trail_sl_pct=0.08,
            report_name="test_report.csv"
        )
        
        # Seed active entry for SL_STOCK (stop loss hit)
        tracker_store.create_entry(
            ticker="SL_STOCK",
            index_name="nifty50",
            entry_at="2026-07-10T12:00:00",
            entry_price=1000.0,
            entry_source="close",
            target_pct=0.15,
            sl_pct=0.05,
            trail_sl_pct=0.08,
            report_name="test_report.csv"
        )

        df = pd.DataFrame([
            {"ticker": "TGT_STOCK", "close": 1200.0, "total_score": 60},
            {"ticker": "SL_STOCK", "close": 940.0, "total_score": 60}
        ])

        # Disable Angel LTP
        import angel_ltp
        original_configured = angel_ltp.is_configured
        angel_ltp.is_configured = lambda: False
        
        try:
            report_name = "test_export.csv"
            # First run: TGT_STOCK should close immediately, SL_STOCK should register breach but remain active
            df_enriched = main.apply_trade_tracking(df, "nifty50", report_name)
            
            tgt = df_enriched[df_enriched["ticker"] == "TGT_STOCK"].iloc[0]
            self.assertEqual(tgt["status"], "target_hit")
            self.assertEqual(tgt["exit_price"], 1200.0)
            
            sl_first = df_enriched[df_enriched["ticker"] == "SL_STOCK"].iloc[0]
            self.assertEqual(sl_first["status"], "active")
            
            # Second run: SL_STOCK should now hit SL and close
            df_enriched_second = main.apply_trade_tracking(df, "nifty50", report_name)
            sl_second = df_enriched_second[df_enriched_second["ticker"] == "SL_STOCK"].iloc[0]
            self.assertEqual(sl_second["status"], "sl_hit")
            self.assertEqual(sl_second["exit_price"], 940.0)
            
        finally:
            angel_ltp.is_configured = original_configured

    def test_today_clean_report_csv(self):
        """Verify that /reports/today_clean.csv returns only score >= 70, clean UI columns, and no debug columns."""
        from pathlib import Path
        main.REPORTS_DIR.mkdir(exist_ok=True)
        from datetime import datetime
        today_str = datetime.now(main.IST).strftime('%Y%m%d')
        report_file = main.REPORTS_DIR / f"screener_{today_str}_120000.csv"
        
        raw_df = pd.DataFrame([
            {"ticker": "HIGH1", "total_score": 75.0, "first_seen": "15/07/2026", "grade": "A", "signal": "Buy", "close": 100.0, "last_price": 102.0, "stop_loss": 95.0, "rsi": 65.0, "atr": 5.2, "passes_filter": True, "extra_debug_col": "junk"},
            {"ticker": "HIGH2", "total_score": 70.0, "first_seen": "14/07/2026", "grade": "B", "signal": "Watch", "close": 200.0, "last_price": 198.0, "stop_loss": 190.0, "rsi": 55.0, "atr": 10.5, "passes_filter": False, "extra_debug_col": "junk"},
            {"ticker": "LOW", "total_score": 69.0, "first_seen": "10/07/2026", "grade": "C", "signal": "Neutral", "close": 50.0, "last_price": 49.0, "stop_loss": 47.0, "rsi": 45.0, "atr": 2.1, "passes_filter": True, "extra_debug_col": "junk"}
        ])
        raw_df.to_csv(report_file, index=False)
        
        try:
            with main.app.test_client() as client:
                resp = client.get("/reports/today_clean.csv")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.mimetype, "text/csv")
                
                import io
                content = resp.data.decode("utf-8")
                res_df = pd.read_csv(io.StringIO(content))
                
                self.assertEqual(len(res_df), 2)
                tickers = res_df["ticker"].tolist()
                self.assertIn("HIGH1", tickers)
                self.assertIn("HIGH2", tickers)
                self.assertNotIn("LOW", tickers)
                
                expected_cols = ["ticker", "since", "score", "grd", "signal", "close", "ltp", "ltp_change_since_scan", "stop", "rsi", "atr", "filter"]
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
            if report_file.exists():
                report_file.unlink()

    def test_new_csv_scan_date_mapping(self):
        """Verify that /api/reports/new.csv maps 'since' to 'scan_date'."""
        main._bg["results"] = [
            {
                "ticker": "TESTSYM",
                "total_score": 85.0,
                "first_seen": "10/07/2026",
                "scan_date": "16/07/2026",
                "grade": "A+",
                "signal": "Strong Buy",
                "close": 500.0,
                "last_price": 505.0,
                "stop_loss": 480.0,
                "rsi": 70.0,
                "atr": 12.0,
                "passes_filter": True,
                "days_in_screener": 0
            }
        ]
        with main.app.test_client() as client:
            resp = client.get("/api/reports/new.csv")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.mimetype, "text/csv")
            
            import io
            content = resp.data.decode("utf-8")
            res_df = pd.read_csv(io.StringIO(content))
            self.assertEqual(len(res_df), 1)
            row = res_df.iloc[0]
            self.assertEqual(row["ticker"], "TESTSYM")
            self.assertEqual(row["since"], "16/07/2026") # should be scan_date, not first_seen (10/07/2026)


if __name__ == "__main__":
    unittest.main()

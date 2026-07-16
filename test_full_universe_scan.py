import unittest
from unittest.mock import patch, MagicMock
import os
import json
from pathlib import Path

import main
import universe_store

# Use a test DB path to avoid conflict
TEST_DB_PATH = str(Path(__file__).resolve().parent / "data" / "test_full_universe_scan.db")

class TestFullUniverseScan(unittest.TestCase):
    def setUp(self):
        main.tracker_store.DB_PATH = TEST_DB_PATH
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass
        main.tracker_store.init_db()

    def tearDown(self):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def test_regression_deduplication(self):
        """Verify that get_full_universe() returns a unique deduplicated ticker list."""
        full_uni = universe_store.get_full_universe()
        self.assertGreater(len(full_uni), 300)
        
        # Verify no duplicates
        self.assertEqual(len(full_uni), len(set(full_uni)), "Full universe contains duplicate tickers!")

    def test_default_scan_tickers_deduped(self):
        """Verify main._default_scan_tickers() returns the broad deduped universe cleanly."""
        default_list = main._default_scan_tickers()
        self.assertGreater(len(default_list), 300)
        self.assertEqual(len(default_list), len(set(default_list)), "_default_scan_tickers contains duplicates!")

    @patch("main._run_screener_async")
    @patch("main.angel_is_configured", return_value=False)
    def test_run_route_no_index_defaults_to_all(self, mock_angel, mock_run_async):
        """Test that /api/screener/run with no index param uses _default_scan_tickers()."""
        # Ensure screener is not flagged as running
        main._bg["running"] = False
        
        with main.app.test_client() as client:
            resp = client.post("/api/screener/run")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertTrue(data["ok"])
            self.assertEqual(data["index"], "all")
            
            # Check length matching default list
            expected_len = len(main._default_scan_tickers())
            self.assertEqual(data["total"], expected_len)
            mock_run_async.assert_called_once()
            
            # Retrieve args passed to thread target
            called_tickers = mock_run_async.call_args[0][0]
            self.assertEqual(len(called_tickers), expected_len)

    @patch("main._run_screener_async")
    @patch("main.angel_is_configured", return_value=False)
    def test_run_route_index_all(self, mock_angel, mock_run_async):
        """Test that /api/screener/run with index=all uses _default_scan_tickers()."""
        main._bg["running"] = False
        
        with main.app.test_client() as client:
            resp = client.post("/api/screener/run?index=all")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertTrue(data["ok"])
            self.assertEqual(data["index"], "all")
            self.assertEqual(data["total"], len(main._default_scan_tickers()))

    @patch("main._run_screener_async")
    @patch("main.angel_is_configured", return_value=False)
    def test_run_route_specific_index(self, mock_angel, mock_run_async):
        """Test that /api/screener/run with index=nifty50 uses Nifty 50 plus route-level fallback extras."""
        main._bg["running"] = False
        
        with main.app.test_client() as client:
            resp = client.post("/api/screener/run?index=nifty50")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertTrue(data["ok"])
            self.assertEqual(data["index"], "nifty50")
            
            expected_tickers = list(set(universe_store.get_universe("nifty50")))
            self.assertEqual(data["total"], len(expected_tickers))

    @patch("main._run_screener_async")
    @patch("main.angel_is_configured", return_value=False)
    def test_run_route_comma_separated_indices(self, mock_angel, mock_run_async):
        """Test that /api/screener/run with index=nifty50,next50 merges, deduplicates."""
        main._bg["running"] = False
        
        with main.app.test_client() as client:
            resp = client.post("/api/screener/run?index=nifty50,next50")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertTrue(data["ok"])
            self.assertEqual(data["index"], "nifty50,next50")
            
            # Check unique union count of nifty50 + next50
            n50 = universe_store.get_universe("nifty50")
            nxt50 = universe_store.get_universe("next50")
            expected_tickers = list(set(n50 + nxt50))
            self.assertEqual(data["total"], len(expected_tickers))

    def test_universe_api_handles_all(self):
        """Test that /api/universe?index=all returns the complete combined deduplicated flat list."""
        with main.app.test_client() as client:
            resp = client.get("/api/universe?index=all")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertIn("combined", data)
            self.assertIn("counts", data)
            
            expected_len = len(main._default_scan_tickers())
            self.assertEqual(data["total"], expected_len)
            self.assertEqual(data["counts"]["all"], expected_len)
            self.assertEqual(data["counts"]["nifty50"], 50)
            self.assertEqual(data["counts"]["nifty500_custom"], len(universe_store.get_universe("nifty500_custom")))

    def test_normalize_ticker(self):
        """Test normalization helper."""
        self.assertEqual(universe_store.normalize_ticker("TCS.NS"), "TCS")
        self.assertEqual(universe_store.normalize_ticker("infy.nse"), "INFY")
        self.assertEqual(universe_store.normalize_ticker("  sbin  "), "SBIN")

    def test_build_unique_universe_deduplication_and_order(self):
        """Test build_unique_universe deduplication, source map and order preservation."""
        tickers, source_map = universe_store.build_unique_universe(["nifty50", "nifty_bank"])
        self.assertIn("HDFCBANK", tickers)
        self.assertEqual(tickers.count("HDFCBANK"), 1)
        self.assertIn("nifty50", source_map["HDFCBANK"])
        self.assertIn("nifty_bank", source_map["HDFCBANK"])
        
        first_nifty50 = universe_store.normalize_ticker(universe_store.get_universe("nifty50")[0])
        self.assertEqual(tickers[0], first_nifty50)

if __name__ == "__main__":
    unittest.main()

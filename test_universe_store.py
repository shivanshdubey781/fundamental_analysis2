import unittest
import os
import json
from pathlib import Path
from unittest.mock import patch
import universe_store

class TestUniverseStore(unittest.TestCase):
    def test_default_fallbacks(self):
        """Test that get_universe returns fallbacks for core index groups."""
        n50 = universe_store.get_universe("nifty50")
        self.assertEqual(len(n50), 50)
        self.assertIn("RELIANCE", n50)
        
        n500 = universe_store.get_universe("nifty500")
        self.assertGreater(len(n500), 200)
        self.assertIn("DIXON", n500)

    def test_get_universe_unknown(self):
        """Test that get_universe returns an empty list for unknown index keys."""
        empty_list = universe_store.get_universe("nonexistent_index_key")
        self.assertEqual(empty_list, [])

    def test_sectoral_indices(self):
        """Test that get_universe resolves sectoral indices correctly."""
        bank = universe_store.get_universe("nifty_bank")
        self.assertGreater(len(bank), 0)
        self.assertIn("HDFCBANK", bank)

    def test_load_universes_structure(self):
        """Test load_universes returns a dictionary with all required keys."""
        universes = universe_store.load_universes()
        self.assertIsInstance(universes, dict)
        for key in universe_store.REQUIRED_KEYS:
            self.assertIn(key, universes)
            self.assertIsInstance(universes[key], list)

    def test_collapse_overlapping_indices(self):
        """Test that overlapping indices collapse correctly to optimize scan complexity."""
        # 1. nifty500_custom collapses child indices
        collapsed = universe_store._collapse_overlapping_indices(["nifty50", "next50", "midcap100", "nifty500_custom"])
        self.assertEqual(sorted(collapsed), ["nifty500_custom"])
        
        # 2. midsmallcap400 collapses smallcap250 and midcap100
        collapsed2 = universe_store._collapse_overlapping_indices(["smallcap250", "midcap100", "midsmallcap400"])
        self.assertEqual(sorted(collapsed2), ["midsmallcap400"])
        
        # 3. 'all' or 'nifty500' maps to nifty500_custom and collapses children
        collapsed3 = universe_store._collapse_overlapping_indices(["all", "nifty50", "midcap100"])
        self.assertEqual(sorted(collapsed3), ["nifty500_custom"])

    def test_nifty500_csv_loading_and_filtering(self):
        """Test that NIFTY-500.csv loading, deduping, and filtering works."""
        raw_symbols = universe_store._load_nifty500_csv_symbols()
        self.assertGreater(len(raw_symbols), 0)
        
        # Verify headers were skipped
        for s in raw_symbols:
            self.assertFalse(s.lower().startswith("nifty"))
            
        # Verify deduplication preserves order
        deduped = universe_store._dedupe_preserve_order(raw_symbols)
        self.assertLessEqual(len(deduped), len(raw_symbols))
        
        # Verify order preservation (e.g. DIXON is first row, column 1)
        self.assertEqual(deduped[0], "DIXON")
        
        # Verify Angel-compatible filtering
        filtered = universe_store._filter_symbols_present_in_angel_master(deduped)
        self.assertGreater(len(filtered), 0)
        self.assertIn("DIXON", filtered)
        self.assertIn("BHEL", filtered)

    @patch("builtins.open", new_callable=unittest.mock.mock_open, read_data="NIFTY 500,NIFTY NEXT 50,NIFTY 50\nSYM1,SYM2,SYM3\nSYM4,,SYM5\n")
    @patch("universe_store.Path.exists", return_value=True)
    def test_row_wise_csv_loading_first_column(self, mock_exists, mock_file):
        """Test that _load_nifty500_csv_symbols reads the broad union row-wise."""
        symbols = universe_store._load_nifty500_csv_symbols()
        self.assertListEqual(symbols, ["SYM1", "SYM2", "SYM3", "SYM4", "SYM5"])


if __name__ == "__main__":
    unittest.main()

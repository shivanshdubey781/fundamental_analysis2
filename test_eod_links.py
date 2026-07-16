import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
import pytz
import os
from pathlib import Path

import config
import tracker_store

# Use a test DB path
TEST_DB_PATH = str(Path(__file__).resolve().parent / "data" / "test_eod_links.db")

class TestEODLinksScheduledJob(unittest.TestCase):
    def setUp(self):
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

    @patch("telegram_alert.send_eod_links_alert", return_value=True)
    @patch("config.TELEGRAM_ENABLE_EOD_LINKS", True)
    def test_eod_links_alert_sends_once_per_day(self, mock_send_alert):
        from main import _maybe_send_eod_links_alert
        
        # 1. First invocation should trigger the send
        _maybe_send_eod_links_alert()
        self.assertEqual(mock_send_alert.call_count, 1)
        
        # Check event recorded in DB
        ist = pytz.timezone("Asia/Kolkata")
        today_str = datetime.now(ist).strftime("%Y-%m-%d")
        event_key = f"eod_links:{today_str}"
        self.assertTrue(tracker_store.telegram_event_sent(event_key))
        
        # 2. Second invocation should be blocked/ignored
        _maybe_send_eod_links_alert()
        self.assertEqual(mock_send_alert.call_count, 1)  # still 1

if __name__ == "__main__":
    unittest.main()

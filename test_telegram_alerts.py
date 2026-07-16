import unittest
from unittest.mock import patch, MagicMock
import telegram_alert

class TestTelegramAlerts(unittest.TestCase):

    def test_format_new_running_trade(self):
        entry_row = {
            "ticker": "RELIANCE",
            "entry_price": 2500.0,
            "target_price": 2875.0,
            "sl_price": 2375.0,
            "current_trail_sl": 2300.0,
            "entry_at": "2026-07-10T12:00:00+05:30"
        }
        msg = telegram_alert.format_new_running_trade(entry_row)
        
        self.assertIn("RELIANCE", msg)
        self.assertIn("2500.00", msg)
        self.assertIn("2875.00", msg)
        self.assertIn("2375.00", msg)
        self.assertIn("2300.00", msg)
        self.assertIn("10 Jul 12:00 IST", msg)

    def test_format_booked_trade(self):
        entry_row = {
            "ticker": "TCS",
            "status": "target_hit",
            "exit_reason": "Target price hit",
            "entry_price": 3500.0,
            "exit_price": 4025.0,
            "pnl_pct": 15.0,
            "running_amount": 525.0,
            "entry_at": "2026-07-01T10:00:00",
            "exit_at": "2026-07-10T14:30:00+05:30"
        }
        msg = telegram_alert.format_booked_trade(entry_row)
        
        self.assertIn("TCS", msg)
        self.assertIn("target_hit", msg)
        self.assertIn("Target price hit", msg)
        self.assertIn("3500.00", msg)
        self.assertIn("4025.00", msg)
        self.assertIn("15.00%", msg)
        self.assertIn("525.00", msg)
        self.assertIn("01 Jul 2026", msg)
        self.assertIn("10 Jul 14:30 IST", msg)

    def test_format_eod_links(self):
        base_url = "http://195.35.23.125:8023"
        date_str = "2026-07-14"
        msg = telegram_alert.format_eod_links(base_url, date_str)
        
        self.assertIn("http://195.35.23.125:8023/api/reports/running.csv", msg)
        self.assertIn("http://195.35.23.125:8023/api/reports/booked.csv", msg)
        self.assertIn("http://195.35.23.125:8023/reports/today_clean.csv", msg)
        self.assertIn("2026-07-14", msg)

    @patch("telegram_alert.send_alert")
    @patch("config.TELEGRAM_ENABLE_NEW_RUNNING_ALERTS", True)
    def test_send_new_running_trade_alert(self, mock_send):
        mock_send.return_value = True
        res = telegram_alert.send_new_running_trade_alert({"ticker": "TEST"})
        self.assertTrue(res)
        mock_send.assert_called_once()

    @patch("telegram_alert.send_alert")
    @patch("config.TELEGRAM_ENABLE_BOOKED_ALERTS", True)
    def test_send_booked_trade_alert(self, mock_send):
        mock_send.return_value = False
        res = telegram_alert.send_booked_trade_alert({"ticker": "TEST"})
        self.assertFalse(res)
        mock_send.assert_called_once()

    @patch("telegram_alert.is_configured", return_value=True)
    @patch("config.TELEGRAM_SEND_ENABLED", False)
    def test_telegram_send_enabled_suppression(self, mock_is_configured):
        """Test that send_alert returns False and does not send requests when TELEGRAM_SEND_ENABLED=False."""
        res = telegram_alert.send_alert("Test message")
        self.assertFalse(res)


if __name__ == "__main__":
    unittest.main()

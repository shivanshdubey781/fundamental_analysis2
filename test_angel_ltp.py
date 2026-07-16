import unittest
from unittest.mock import patch

import angel_ltp


class _RateLimitedSession:
    def ltpData(self, exchange, ticker, token):
        raise Exception("Access denied because of exceeding access rate")


class TestAngelLtp(unittest.TestCase):
    def setUp(self):
        angel_ltp._ltp_cache.clear()
        angel_ltp._obj = None
        angel_ltp._auth_ts = 0.0
        angel_ltp._last_login_attempt_ts = 0.0
        angel_ltp._last_ltp_call_ts = 0.0

    def test_get_ltp_uses_fresh_cache_before_api_call(self):
        angel_ltp._store_cached_ltp("TCS", 4321.0)

        with patch("angel_ltp.is_configured", return_value=True):
            with patch("angel_ltp._get_session") as mock_get_session:
                value = angel_ltp.get_ltp("TCS")

        self.assertEqual(value, 4321.0)
        mock_get_session.assert_not_called()

    def test_get_ltp_returns_cached_value_when_rate_limited(self):
        angel_ltp._store_cached_ltp("TCS", 4310.5)

        with patch("angel_ltp.is_configured", return_value=True):
            with patch("angel_ltp._get_session", return_value=_RateLimitedSession()):
                with patch("angel_ltp._wait_for_ltp_slot"):
                    value = angel_ltp.get_ltp("TCS", _retry=False)

        self.assertEqual(value, 4310.5)


if __name__ == "__main__":
    unittest.main()

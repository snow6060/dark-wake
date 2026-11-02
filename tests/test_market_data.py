import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from src.market_data import get_brent_market_snapshot


def _history(prices, dates):
    return pd.DataFrame(
        {"Close": prices},
        index=pd.to_datetime(dates),
    )


class BrentMarketSnapshotTests(unittest.TestCase):
    @patch("src.market_data.yf.Ticker")
    def test_weekend_uses_latest_close_without_requesting_intraday(self, ticker_factory):
        ticker = MagicMock()
        ticker_factory.return_value = ticker
        ticker.history.return_value = _history(
            [79.25, 80.5],
            ["2026-10-08", "2026-10-09"],
        )

        snapshot = get_brent_market_snapshot(datetime(2026, 10, 10, 12))

        self.assertEqual(snapshot["price"], 80.5)
        self.assertEqual(snapshot["market_status"], "closed")
        self.assertTrue(snapshot["market_is_closed"])
        self.assertEqual(snapshot["price_basis"], "last_close")
        self.assertEqual(snapshot["price_as_of"], "2026-10-09")
        ticker.history.assert_called_once_with(period="5d", interval="1d")

    @patch("src.market_data.yf.Ticker")
    def test_missing_intraday_uses_daily_close_and_labels_it_as_close(self, ticker_factory):
        ticker = MagicMock()
        ticker_factory.return_value = ticker
        ticker.history.side_effect = [
            pd.DataFrame(),
            _history([79.25, 80.5], ["2026-10-08", "2026-10-09"]),
        ]

        snapshot = get_brent_market_snapshot(datetime(2026, 10, 9, 16))

        self.assertEqual(snapshot["price"], 80.5)
        self.assertEqual(snapshot["price_basis"], "last_close")
        self.assertEqual(snapshot["market_status"], "last_close")
        self.assertFalse(snapshot["market_is_closed"])
        self.assertEqual(ticker.history.call_count, 2)
        ticker.history.assert_any_call(period="1d", interval="5m")
        ticker.history.assert_any_call(period="5d", interval="1d")

    @patch("src.market_data.yf.Ticker")
    def test_missing_intraday_and_daily_history_raises_clear_error(self, ticker_factory):
        ticker = MagicMock()
        ticker_factory.return_value = ticker
        ticker.history.side_effect = [pd.DataFrame(), pd.DataFrame()]

        with self.assertRaisesRegex(RuntimeError, "no valid Brent daily closing prices"):
            get_brent_market_snapshot(datetime(2026, 10, 9, 16))

    @patch("src.market_data.yf.Ticker")
    def test_five_day_period_returns_intraday_history(self, ticker_factory):
        ticker = MagicMock()
        ticker_factory.return_value = ticker
        ticker.history.return_value = _history(
            [79.25, 80.5],
            ["2026-10-08 10:00", "2026-10-09 15:00"],
        )

        snapshot = get_brent_market_snapshot(
            datetime(2026, 10, 9, 16),
            period="5d",
        )

        self.assertEqual(snapshot["price"], 80.5)
        self.assertEqual(len(snapshot["history"]), 2)
        self.assertIn("timestamp", snapshot["history"][0])
        ticker.history.assert_called_once_with(period="5d", interval="15m")

    @patch("src.market_data.yf.Ticker")
    def test_three_month_period_uses_daily_history(self, ticker_factory):
        ticker = MagicMock()
        ticker_factory.return_value = ticker
        ticker.history.return_value = _history(
            [79.25, 80.5],
            ["2026-10-08", "2026-10-09"],
        )

        snapshot = get_brent_market_snapshot(
            datetime(2026, 10, 9, 16),
            period="3mo",
        )

        self.assertEqual(snapshot["price"], 80.5)
        self.assertEqual(snapshot["price_basis"], "last_close")
        ticker.history.assert_called_once_with(period="3mo", interval="1d")

    def test_unsupported_chart_period_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported Brent chart period"):
            get_brent_market_snapshot(period="1y")


if __name__ == "__main__":
    unittest.main()

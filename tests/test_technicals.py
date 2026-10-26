import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.technicals import (
    COMMODITY_BASKET,
    _calculate_commodity_indicators,
    get_commodity_technical_indicators,
)


def _history(rows=260):
    close = pd.Series(np.linspace(60, 90, rows))
    return pd.DataFrame(
        {
            "Close": close.to_numpy(),
            "High": (close + 1).to_numpy(),
            "Low": (close - 1).to_numpy(),
            "Volume": np.linspace(1000, 2000, rows),
        },
        index=pd.date_range("2025-01-01", periods=rows, freq="D"),
    )


class CommodityTechnicalIndicatorTests(unittest.TestCase):
    def test_calculates_all_requested_indicators_from_ohlcv_history(self):
        result = _calculate_commodity_indicators(_history())

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["price_basis"], "daily_close")
        indicators = result["indicators"]
        self.assertIsNotNone(indicators["rsi_14"])
        self.assertEqual(
            set(indicators["macd_12_26_9"]),
            {"macd", "signal", "histogram"},
        )
        self.assertTrue(all(indicators[key] is not None for key in ("ema_20", "ema_50", "ema_200")))
        self.assertEqual(
            set(indicators["bollinger_20_2"]),
            {"upper", "middle", "lower"},
        )
        self.assertIsNotNone(indicators["atr_14"])
        self.assertEqual(set(indicators["stochastic_14_3"]), {"k", "d"})
        self.assertIsNotNone(indicators["vwap_20"])

    def test_insufficient_history_reports_unavailable_lagging_values(self):
        result = _calculate_commodity_indicators(_history(15))

        self.assertEqual(result["status"], "available")
        self.assertIsNone(result["indicators"]["ema_50"])
        self.assertIsNone(result["indicators"]["ema_200"])
        self.assertIsNone(result["indicators"]["stochastic_14_3"]["d"])

    @patch("src.technicals.yf.Ticker")
    def test_fetches_the_full_configured_energy_commodity_basket(self, ticker_factory):
        ticker_factory.return_value.history.return_value = _history()

        basket = get_commodity_technical_indicators()

        self.assertEqual(set(basket), set(COMMODITY_BASKET))
        self.assertEqual(ticker_factory.call_count, len(COMMODITY_BASKET))
        for symbol, data in basket.items():
            self.assertEqual(data["name"], COMMODITY_BASKET[symbol])
            self.assertEqual(data["status"], "available")
        self.assertEqual(ticker_factory.return_value.history.call_count, len(COMMODITY_BASKET))
        ticker_factory.return_value.history.assert_called_with(
            period="1y", interval="1d", auto_adjust=False
        )

    @patch("src.technicals.yf.Ticker")
    def test_provider_failure_is_reported_for_the_affected_commodity(self, ticker_factory):
        ticker_factory.side_effect = [RuntimeError("feed unavailable")] + [
            type("Ticker", (), {"history": lambda self, **kwargs: _history()})()
            for _ in range(len(COMMODITY_BASKET) - 1)
        ]

        basket = get_commodity_technical_indicators()

        self.assertEqual(basket["BZ=F"]["status"], "unavailable")
        self.assertIn("feed unavailable", basket["BZ=F"]["error"])
        self.assertTrue(
            all(item["status"] == "available" for item in list(basket.values())[1:])
        )


if __name__ == "__main__":
    unittest.main()

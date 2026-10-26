import math
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


COMMODITY_BASKET = {
    "BZ=F": "Brent Crude",
    "CL=F": "WTI Crude",
    "NG=F": "Natural Gas",
    "HO=F": "Heating Oil",
    "RB=F": "Gasoline",
    "MTF=F": "Coal",
}


def _finite_number(value: Any, decimals: int = 4) -> float | None:
    if value is None or pd.isna(value):
        return None
    result = float(value)
    return round(result, decimals) if math.isfinite(result) else None


def _calculate_commodity_indicators(history: pd.DataFrame) -> dict[str, Any]:
    required = {"Close", "High", "Low"}
    if history.empty or not required.issubset(history.columns):
        return {"status": "unavailable", "error": "Insufficient OHLC price history."}

    frame = history.copy()
    for column in required | {"Volume"}:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["Close", "High", "Low"])
    if frame.empty:
        return {"status": "unavailable", "error": "No valid OHLC price history."}

    close = frame["Close"]
    high = frame["High"]
    low = frame["Low"]
    volume = frame.get("Volume", pd.Series(0.0, index=frame.index)).fillna(0.0)

    delta = close.diff()
    average_gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    average_loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + relative_strength))
    rsi = rsi.mask((average_loss == 0) & (average_gain > 0), 100)
    rsi = rsi.mask((average_gain == 0) & (average_loss == 0), 50)

    ema_12 = close.ewm(span=12, min_periods=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, min_periods=26, adjust=False).mean()
    macd_line = ema_12 - ema_26
    macd_signal = macd_line.ewm(span=9, min_periods=9, adjust=False).mean()
    macd_histogram = macd_line - macd_signal

    middle_band = close.rolling(20, min_periods=20).mean()
    band_std = close.rolling(20, min_periods=20).std(ddof=0)
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    lowest_low = low.rolling(14, min_periods=14).min()
    highest_high = high.rolling(14, min_periods=14).max()
    stochastic_k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    typical_price = (high + low + close) / 3
    volume_total = volume.rolling(20, min_periods=20).sum()
    vwap = (typical_price * volume).rolling(20, min_periods=20).sum() / volume_total.replace(0, np.nan)

    latest = frame.index[-1]
    latest_date = latest.date().isoformat() if hasattr(latest, "date") else str(latest)
    return {
        "status": "available",
        "price": _finite_number(close.iloc[-1], 4),
        "daily_change_pct": _finite_number(close.pct_change().iloc[-1] * 100, 4),
        "price_basis": "daily_close",
        "price_as_of": latest_date,
        "indicators": {
            "rsi_14": _finite_number(rsi.iloc[-1]),
            "macd_12_26_9": {
                "macd": _finite_number(macd_line.iloc[-1]),
                "signal": _finite_number(macd_signal.iloc[-1]),
                "histogram": _finite_number(macd_histogram.iloc[-1]),
            },
            "ema_20": _finite_number(close.ewm(span=20, min_periods=20, adjust=False).mean().iloc[-1]),
            "ema_50": _finite_number(close.ewm(span=50, min_periods=50, adjust=False).mean().iloc[-1]),
            "ema_200": _finite_number(close.ewm(span=200, min_periods=200, adjust=False).mean().iloc[-1]),
            "bollinger_20_2": {
                "upper": _finite_number((middle_band + 2 * band_std).iloc[-1]),
                "middle": _finite_number(middle_band.iloc[-1]),
                "lower": _finite_number((middle_band - 2 * band_std).iloc[-1]),
            },
            "atr_14": _finite_number(true_range.rolling(14, min_periods=14).mean().iloc[-1]),
            "stochastic_14_3": {
                "k": _finite_number(stochastic_k.iloc[-1]),
                "d": _finite_number(stochastic_k.rolling(3, min_periods=3).mean().iloc[-1]),
            },
            "vwap_20": _finite_number(vwap.iloc[-1]),
        },
    }


def get_commodity_technical_indicators() -> dict[str, dict[str, Any]]:
    """Fetch daily OHLCV history and calculate indicators for the energy basket."""
    telemetry = {}
    for symbol, name in COMMODITY_BASKET.items():
        try:
            history = yf.Ticker(symbol).history(
                period="1y",
                interval="1d",
                auto_adjust=False,
            )
        except Exception as exc:
            telemetry[symbol] = {
                "name": name,
                "status": "unavailable",
                "error": f"Yahoo Finance history request failed: {exc}",
            }
            continue

        result = _calculate_commodity_indicators(history)
        telemetry[symbol] = {"name": name, **result}
    return telemetry


def format_commodity_technical_report(basket: dict[str, dict[str, Any]]) -> str:
    """Format structured commodity telemetry for the agent context."""
    lines = ["--- Energy Commodity Technical Indicators (daily close) ---"]
    for symbol, data in basket.items():
        if data["status"] != "available":
            lines.append(f"- {data['name']} ({symbol}): unavailable — {data['error']}")
            continue
        indicators = data["indicators"]
        macd = indicators["macd_12_26_9"]
        lines.append(
            f"- {data['name']} ({symbol}): ${data['price']:.4f}, "
            f"RSI (14) {indicators['rsi_14']}, "
            f"MACD {macd['macd']} / signal {macd['signal']}, "
            f"ATR (14) {indicators['atr_14']}, "
            f"EMA 20/50/200 {indicators['ema_20']}/{indicators['ema_50']}/{indicators['ema_200']}"
        )
    return "\n".join(lines)


def get_technical_indicators() -> str:
    """Return a concise technical report for Brent and the correlated energy basket."""
    return format_commodity_technical_report(get_commodity_technical_indicators())

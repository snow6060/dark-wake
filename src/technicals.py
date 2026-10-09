import yfinance as yf
import pandas as pd
import numpy as np

def get_technical_indicators() -> str:
    """
    Fetches recent historical data for Brent Crude (BZ=F), computes
    technical indicators (SMA 20/50, RSI, OBV trend), and returns a formatted report string.
    """
    try:
        ticker = yf.Ticker("BZ=F")
        df = ticker.history(period="60d", interval="1d")
        
        if df.empty or len(df) < 15:
            return "Insufficient price history available for quantitative technical computation."

        close_prices = df["Close"]
        volume = df["Volume"] if "Volume" in df.columns else pd.Series([0]*len(df), index=df.index)

        # Calculate Moving Averages
        sma_20 = close_prices.rolling(window=20).mean().iloc[-1]
        sma_50 = close_prices.rolling(window=min(50, len(df))).mean().iloc[-1]
        current_close = close_prices.iloc[-1]

        # Calculate Relative Strength Index (RSI - 14 period)
        delta = close_prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1] if not rsi.empty and not pd.isna(rsi.iloc[-1]) else 50.0

        # Calculate On-Balance Volume (OBV) trend check
        obv = (np.sign(close_prices.diff()) * volume).fillna(0).cumsum()
        obv_trend = "Accumulation (Rising OBV)" if obv.iloc[-1] > obv.iloc[-5] else "Distribution (Declining OBV)"

        # Liquidity zone / Support & Resistance estimations
        recent_high = close_prices.tail(20).max()
        recent_low = close_prices.tail(20).min()

        report = (
            f"--- Quantitative Technical Analysis Report ---\n"
            f"- Current Price: ${current_close:.2f}\n"
            f"- SMA 20: ${sma_20:.2f} | SMA 50: ${sma_50:.2f}\n"
            f"- RSI (14): {current_rsi:.1f}\n"
            f"- Volume Trend (OBV): {obv_trend}\n"
            f"- 20-Day Liquidity Range: Support @ ${recent_low:.2f} | Resistance @ ${recent_high:.2f}\n"
            f"- Trend Bias: {'Bullish momentum structure' if current_close > sma_20 else 'Bearish pressure / below short-term mean'}"
        )
        return report

    except Exception as e:
        return f"Error computing technical indicators: {str(e)}"
import yfinance as yf
import pandas as pd
import numpy as np

def get_technical_indicators() -> str:
    try:
        # Fetch daily data for Brent Crude
        df = yf.download("BZ=F", period="3mo", interval="1d", progress=False)
        if df.empty or len(df) < 20:
            return "Insufficient price history for advanced technical structure analysis."
        
        # Flatten multi-index columns if present from newer yfinance versions
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df['Close']
        high = df['High']
        low = df['Low']
        volume = df['Volume']
        
        current_price = float(close.iloc[-1])
        
        # 1. Moving Averages & Trend Context
        sma_20 = float(close.rolling(20).mean().iloc[-1])
        sma_50 = float(close.rolling(50).mean().iloc[-1])
        
        # 2. Volume Profile & Point of Control (POC) approximation
        price_bins = pd.cut(low.combine_first(high), bins=10)
        vol_profile = volume.groupby(price_bins).sum()
        max_vol_bin = vol_profile.idxmax()
        poc_price = float(max_vol_bin.mid) if hasattr(max_vol_bin, 'mid') else current_price

        # 3. Liquidity Pools (Recent Swing Highs and Lows for Stop Hunts)
        recent_high = float(high.iloc[-10:-1].max())
        recent_low = float(low.iloc[-10:-1].min())
        
        # 4. Fair Value Gap (FVG) / Imbalance Detection
        fvg_detected = "None identified"
        for i in range(len(df) - 3, len(df)):
            if i >= 2:
                prev_high = high.iloc[i-2]
                curr_low = low.iloc[i]
                curr_high = high.iloc[i]
                prev_low = low.iloc[i-2]
                
                if curr_low > prev_high:
                    fvg_detected = f"Bullish FVG (Imbalance zone between ${prev_high:.2f} and ${curr_low:.2f})"
                    break
                elif curr_high < prev_low:
                    fvg_detected = f"Bearish FVG (Imbalance zone between ${curr_high:.2f} and ${curr_low:.2f})"
                    break

        # 5. Institutional Accumulation / Distribution Proxy (OBV Trend)
        obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
        obv_trend = "Accumulation (OBV rising with price)" if obv.iloc[-1] > obv.iloc[-5] else "Distribution (OBV lagging/falling)"

        report = f"""
- **Current Price:** ${current_price:.2f}
- **20 SMA:** ${sma_20:.2f} | **50 SMA:** ${sma_50:.2f}
- **Volume Point of Control (POC):** ${poc_price:.2f} (Fair value node where heavy institutional volume traded)
- **Immediate Liquidity Pools:** Buy-side liquidity / Resistance at ${recent_high:.2f}, Sell-side liquidity / Support at ${recent_low:.2f}
- **Market Structure / FVG:** {fvg_detected}
- **Institutional Flow (OBV Proxy):** {obv_trend}
"""
        return report.strip()
        
    except Exception as e:
        return f"Error computing advanced institutional technicals: {e}"
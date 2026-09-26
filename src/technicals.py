import yfinance as yf
import pandas as pd
import numpy as np

def get_technical_indicators():
    ticker = yf.Ticker("BZ=F")
    df = ticker.history(period="3mo", interval="1d")
    
    if df.empty or len(df) < 20:
        return "Error: Insufficient historical technical data."

    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['OBV'] = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()

    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    raw_money_flow = typical_price * df['Volume']
    price_direction = typical_price.diff()
    pos_flow = np.where(price_direction > 0, raw_money_flow, 0)
    neg_flow = np.where(price_direction < 0, raw_money_flow, 0)
    
    pos_mf_14 = pd.Series(pos_flow).rolling(window=14).sum()
    neg_mf_14 = pd.Series(neg_flow).rolling(window=14).sum()
    neg_mf_14 = np.where(neg_mf_14 == 0, 0.001, neg_mf_14)
    mfi_ratio = pos_mf_14 / neg_mf_14
    df['MFI'] = 100 - (100 / (1 + mfi_ratio))

    median_price = (df['High'] + df['Low']) / 2
    df['AO'] = median_price.rolling(window=5).mean() - median_price.rolling(window=34).mean()

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    vol_avg_5 = df['Volume'].rolling(5).mean().iloc[-1]
    vol_trend = "Expanding" if latest['Volume'] > vol_avg_5 else "Shrinking"
    
    recent_high = df['High'].iloc[-20:].max()
    recent_low = df['Low'].iloc[-20:].min()
    current_close = latest['Close']
    
    mfi_val = latest['MFI']
    if pd.isna(mfi_val):
        mfi_val = 50.0
        
    mfi_status = "Overbought (>80)" if mfi_val > 80 else ("Oversold (<20)" if mfi_val < 20 else "Neutral Zone")
    obv_trend = "Accumulation" if latest['OBV'] > prev['OBV'] else "Distribution"

    summary = f"""
--- TECHNICAL ANALYSIS REPORT (Brent Crude - BZ=F) ---
- Current Close Price: ${current_close:.2f}
- 20-Day Simple Moving Average (SMA): ${latest['SMA_20']:.2f}
- 50-Day Simple Moving Average (SMA): ${latest['SMA_50']:.2f}
- Money Flow Index (MFI 14): {mfi_val:.2f} ({mfi_status})
- On-Balance Volume (OBV): {latest['OBV']:,.0f} (Trend: {obv_trend})
- Awesome Oscillator (AO): {latest['AO']:.2f}
- Volume Profile: {vol_trend} (Today's Vol: {latest['Volume']:,.0f} vs 5-Day Avg: {vol_avg_5:,.0f})
- Market Structure / Liquidity Zones (Order Blocks):
  * Recent 20-Day Resistance (Liquidity Pool Above): ${recent_high:.2f}
  * Recent 20-Day Support (Liquidity Pool Below): ${recent_low:.2f}
"""
    return summary
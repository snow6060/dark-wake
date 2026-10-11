from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import feedparser
import pandas as pd
import yfinance as yf


LONDON_TIMEZONE = ZoneInfo("Europe/London")


def _is_weekend(now: datetime | None = None) -> bool:
    current = now or datetime.now(LONDON_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=LONDON_TIMEZONE)
    return current.astimezone(LONDON_TIMEZONE).weekday() >= 5


def _latest_price_data(
    history: pd.DataFrame,
    *,
    daily: bool,
    market_is_closed: bool,
) -> dict[str, Any] | None:
    if history.empty or "Close" not in history:
        return None

    closes = pd.to_numeric(history["Close"], errors="coerce").dropna()
    closes = closes[closes > 0]
    if closes.empty:
        return None

    price = float(closes.iloc[-1])
    reference_price = float(closes.iloc[-2]) if len(closes) > 1 else price
    change_pct = (
        (price - reference_price) / reference_price * 100
        if reference_price
        else 0.0
    )
    history_values = [
        {
            "time": index.strftime("%d %b" if daily else "%I:%M %p"),
            "price": round(float(value), 2),
        }
        for index, value in closes.tail(12).items()
    ]
    as_of = closes.index[-1]
    if daily and hasattr(as_of, "date"):
        as_of_text = as_of.date().isoformat()
    else:
        as_of_text = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)
    return {
        "symbol": "BrentCash (BZ=F)",
        "price": round(price, 2),
        "change_pct": round(change_pct, 2),
        "history": history_values,
        "market_status": "closed" if market_is_closed else ("last_close" if daily else "open"),
        "market_is_closed": market_is_closed,
        "price_basis": "last_close" if daily else "intraday",
        "price_as_of": as_of_text,
    }


def get_brent_market_snapshot(now: datetime | None = None) -> dict[str, Any]:
    """Return an intraday Brent quote or, when unavailable, the latest daily close."""
    market_is_closed = _is_weekend(now)
    ticker = yf.Ticker("BZ=F")
    live_error: Exception | None = None

    if not market_is_closed:
        try:
            intraday = ticker.history(period="1d", interval="5m")
        except Exception as error:
            live_error = error
        else:
            snapshot = _latest_price_data(
                intraday,
                daily=False,
                market_is_closed=False,
            )
            if snapshot is not None:
                return snapshot

    try:
        daily = ticker.history(period="5d", interval="1d")
    except Exception as error:
        detail = f"Yahoo Finance daily history request failed: {error}"
        if live_error:
            detail = f"{live_error}; {detail}"
        raise RuntimeError(f"Could not retrieve a Brent closing price: {detail}") from error

    snapshot = _latest_price_data(
        daily,
        daily=True,
        market_is_closed=market_is_closed,
    )
    if snapshot is None:
        reason = "Yahoo Finance returned no valid Brent daily closing prices."
        if live_error:
            reason = f"{live_error}; {reason}"
        raise RuntimeError(f"Could not retrieve a Brent closing price: {reason}")

    return snapshot


def get_brent_price() -> float:
    """Compatibility helper returning the latest usable Brent price."""
    return float(get_brent_market_snapshot()["price"])


def get_oil_news():
    rss_url = "https://news.google.com/rss/search?q=oil+prices+brent+crude&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(rss_url)
    headlines = []
    for entry in feed.entries[:5]:
        headlines.append({
            "title": entry.title,
            "link": entry.link
        })
    return headlines

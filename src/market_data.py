import math
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import requests


YAHOO_CHART_URLS = (
    "https://query1.finance.yahoo.com/v8/finance/chart/BZ=F",
    "https://query2.finance.yahoo.com/v8/finance/chart/BZ=F",
)


def get_brent_live_quote() -> dict[str, Any]:
    """Fetch the latest Brent quote directly from Yahoo Finance."""
    errors: list[str] = []
    for url in YAHOO_CHART_URLS:
        try:
            response = requests.get(
                url,
                params={"range": "1d", "interval": "1m"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=8,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            errors.append(str(error))
            continue

        if not isinstance(payload, dict):
            errors.append("Yahoo returned an invalid quote response.")
            continue
        chart = payload.get("chart") or {}
        result = (chart.get("result") or [None])[0]
        if not result:
            errors.append(
                str((chart.get("error") or {}).get("description") or "Yahoo returned no quote data")
            )
            continue

        metadata = result.get("meta") or {}
        price = metadata.get("regularMarketPrice")
        quote_timestamp = metadata.get("regularMarketTime")
        if price is None or quote_timestamp is None:
            timestamps = result.get("timestamp") or []
            quotes = (result.get("indicators") or {}).get("quote") or [{}]
            closes = quotes[0].get("close") or []
            latest = None
            for timestamp, close in zip(reversed(timestamps), reversed(closes)):
                try:
                    if close is None or not math.isfinite(float(close)) or float(close) <= 0:
                        continue
                except (TypeError, ValueError):
                    continue
                latest = (timestamp, close)
                break
            if latest is not None:
                quote_timestamp, price = latest

        try:
            price = float(price)
            quote_time = datetime.fromtimestamp(float(quote_timestamp), tz=timezone.utc)
        except (TypeError, ValueError, OSError, OverflowError):
            errors.append("Yahoo returned no valid Brent price and timestamp.")
            continue
        if not math.isfinite(price) or price <= 0:
            errors.append("Yahoo returned no valid Brent price.")
            continue

        previous_close = metadata.get("chartPreviousClose") or metadata.get("previousClose")
        try:
            previous_close = float(previous_close)
        except (TypeError, ValueError):
            previous_close = None
        change_pct = (
            round((price - previous_close) / previous_close * 100, 2)
            if previous_close and math.isfinite(previous_close) and previous_close > 0
            else None
        )
        quote_age = datetime.now(timezone.utc) - quote_time
        is_live = timedelta(minutes=-5) <= quote_age <= timedelta(minutes=30)
        return {
            "symbol": "Brent Crude Oil Futures (BZ=F)",
            "price": round(price, 2),
            "change_pct": change_pct,
            "market_status": "open" if is_live else "closed",
            "market_is_closed": not is_live,
            "price_basis": "intraday" if is_live else "last_close",
            "price_as_of": quote_time.isoformat(),
            "price_source": "Yahoo Finance",
        }

    raise RuntimeError(
        "Could not retrieve a Brent quote directly from Yahoo Finance: "
        + ("; ".join(errors) or "Yahoo returned no usable quote.")
    )


def get_brent_price() -> float:
    """Compatibility helper returning Yahoo Finance's current Brent quote."""
    return float(get_brent_live_quote()["price"])


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

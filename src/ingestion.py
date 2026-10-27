import calendar
from datetime import date, datetime, timedelta, timezone
import urllib.request
import feedparser
import requests
from sqlalchemy import and_
import re
from html import unescape

from src.database import ChokepointRecord, SessionLocal, init_db
from src.supabase_client import supabase

RSS_HEADLINE_LIMIT = 100
RSS_HEADLINE_PRUNE_BATCH_SIZE = 1000

# Targeted commercial energy-market RSS feeds.
RSS_FEEDS = [
    {"name": "OilPrice Energy News", "url": "https://oilprice.com/rss/main"},
    {"name": "CNBC Energy", "url": "https://www.cnbc.com/id/19836768/device/rss/rss.html"},
    {
        "name": "EIA Today in Energy",
        "url": "https://www.eia.gov/rss/todayinenergy.xml",
        "timeout": 30,
    },
    {
        "name": "Google News: Energy Markets",
        "url": (
            "https://news.google.com/rss/search?q=oil+prices+OR+Brent+crude"
            "+OR+energy+markets&hl=en-US&gl=US&ceid=US:en"
        ),
    },
    {
        "name": "Google News: Energy Supply and Demand",
        "url": (
            "https://news.google.com/rss/search?q=energy+supply+OR+oil+inventory"
            "+OR+shipping+routes+OR+fuel+demand&hl=en-US&gl=US&ceid=US:en"
        ),
    },
]

_SENSITIVE_NEWS_PATTERN = re.compile(
    r"\b(?:war|wars|conflict|conflicts|geopolitic\w*|military|armed forces|"
    r"army|navy|naval|attack\w*|strike\w*|invasion\w*|battle\w*|"
    r"ceasefire|sanction\w*|blockade\w*|missile\w*|drone\w*|"
    r"terror\w*|bomb\w*|politic\w*|government|election\w*|president|"
    r"diplomat\w*|protest\w*|troop\w*|border\w*|middle east|iran|iraq|"
    r"israel|gaza|lebanon|syria|yemen|russia|ukraine|taiwan|china|"
    r"saudi arabia|houthi\w*)\b",
    re.IGNORECASE,
)
_NEWS_CATEGORIES = (
    ("inventories", re.compile(r"\b(inventor\w*|stockpile\w*|storage)\b", re.I)),
    ("shipping_routes", re.compile(r"\b(ship\w*|tanker\w*|transit\w*|route\w*|port\w*)\b", re.I)),
    ("trade_volumes", re.compile(r"\b(trade|export\w*|import\w*|volume\w*)\b", re.I)),
    ("demand", re.compile(r"\b(demand|consumption|usage)\b", re.I)),
    ("supply", re.compile(r"\b(supply|production|output|refiner\w*)\b", re.I)),
    ("energy_prices", re.compile(r"\b(price\w*|cost\w*|crude|oil|gas|fuel|energy)\b", re.I)),
)


def sanitize_energy_news(text: str) -> tuple[str, str]:
    """Return a commercial energy-market headline/summary and a category."""
    plain_text = re.sub(r"<[^>]*>", " ", unescape(str(text or "")))
    plain_text = re.sub(r"\s+", " ", plain_text).strip()
    category = next(
        (name for name, pattern in _NEWS_CATEGORIES if pattern.search(plain_text)),
        "energy_markets",
    )
    if _SENSITIVE_NEWS_PATTERN.search(plain_text):
        labels = {
            "inventories": "inventory",
            "shipping_routes": "shipping route",
            "trade_volumes": "trade volume",
            "demand": "demand",
            "supply": "supply",
            "energy_prices": "energy price",
            "energy_markets": "market",
        }
        return (
            f"Energy {labels[category]} update: commercial market conditions under review.",
            category,
        )
    return plain_text[:500], category

def analyze_sentiment(title: str) -> str:
    """
    Keyword-based sentiment analyzer classifying crude oil and supply-chain impact
    into Bullish, Bearish, or Neutral.
    """
    text = title.lower()
    bullish_keywords = ["surge", "jump", "shortage", "disruption", "output drop", "opec+", "inventory draw", "demand growth"]
    bearish_keywords = ["surplus", "glut", "fall", "drop", "decline", "output rise", "recession", "inventory build", "demand decline"]

    score = sum(1 for kw in bullish_keywords if kw in text) - sum(1 for kw in bearish_keywords if kw in text)

    if score > 0:
        return "Bullish"
    elif score < 0:
        return "Bearish"
    else:
        return "Neutral"


def _fetch_rss_feed(feed_info: dict, headers: dict):
    request = urllib.request.Request(feed_info["url"], headers=headers)
    with urllib.request.urlopen(request, timeout=feed_info.get("timeout", 10)) as response:
        return feedparser.parse(response.read())


def _rss_entry_created_at(entry: dict) -> str:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if published:
        return datetime.fromtimestamp(
            calendar.timegm(published),
            tz=timezone.utc,
        ).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _prune_rss_headlines() -> int:
    """Keep only the 100 newest RSS headlines in Supabase."""
    deleted_count = 0
    while True:
        response = (
            supabase.table("rss_news")
            .select("id")
            .order("created_at", desc=True)
            .range(
                RSS_HEADLINE_LIMIT,
                RSS_HEADLINE_LIMIT + RSS_HEADLINE_PRUNE_BATCH_SIZE - 1,
            )
            .execute()
        )
        stale_ids = [
            article["id"]
            for article in (response.data or [])
            if article.get("id") is not None
        ]
        if not stale_ids:
            break

        (
            supabase.table("rss_news")
            .delete()
            .in_("id", stale_ids)
            .execute()
        )
        deleted_count += len(stale_ids)
        if len(stale_ids) < RSS_HEADLINE_PRUNE_BATCH_SIZE:
            break
    return deleted_count


STRAITS_LIVE_STATUS_URL = "https://straits.live/status"
STRAITS_LIVE_HEADERS = {"User-Agent": "dark-wake/0.2.1 (energy-intel; +https://github.com/snow6060/dark-wake)"}


def fetch_straits_live_chokepoint_data() -> dict:
    """Ingest real-time chokepoint telemetry from straits.live (keyless)."""
    try:
        resp = requests.get(STRAITS_LIVE_STATUS_URL, headers=STRAITS_LIVE_HEADERS, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        verdict = payload.get("verdict") or {}
        result = {
            "status": "success",
            "source": "straits.live",
            "verdict_status": verdict.get("status"),
            "verdict_short": verdict.get("short"),
            "transits_ma7": payload.get("transits_ma7"),
            "ais_dark_tankers": payload.get("ais_dark_tankers"),
            "ships_stranded": payload.get("ships_stranded"),
            "ships_stranded_offshore": payload.get("ships_stranded_offshore"),
            "brent_usd": payload.get("brent_usd"),
            "wti_usd": payload.get("wti_usd"),
        }
        assert isinstance(result.get("verdict_status"), (str, type(None)))
        assert isinstance(result.get("transits_ma7"), (int, float, type(None)))
        assert isinstance(result.get("ais_dark_tankers"), (int, float, type(None)))
        return result
    except Exception as exc:
        import logging
        logging.warning("straits.live unavailable (%s). No PortWatch fallback (deprecated).", exc)
        return {"status": "error", "source": "straits.live", "message": str(exc)}


def fetch_and_store_rss_headlines():
    """
    Background job function to fetch RSS feeds using a browser User-Agent header,
    parse headlines, compute sentiment, and push new unique items to Supabase.
    """
    if not supabase:
        print("[Supabase Warning] Credentials missing. Skipping RSS background fetch.")
        return

    print("[RSS Worker] Fetching latest energy-market RSS feeds...")
    supports_summary = True

    # Use a standard browser User-Agent so major news networks don't block the scraper
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

    try:
        for feed_info in RSS_FEEDS:
            try:
                parsed_feed = _fetch_rss_feed(feed_info, headers)
            except Exception as net_err:
                print(f"[RSS Warning] Could not fetch {feed_info['name']}: {net_err}")
                continue

            for entry in parsed_feed.entries[:5]:
                title = entry.get("title", "")
                link = entry.get("link", "")

                if not title or not link:
                    continue

                # Check if headline already exists in Supabase
                existing = supabase.table("rss_news").select("id").eq("link", link).execute()

                if not existing.data:
                    sentiment = analyze_sentiment(title)
                    summary = entry.get("summary") or entry.get("description") or ""
                    if not summary and entry.get("content"):
                        summary = entry["content"][0].get("value", "")
                    sanitized_title, _ = sanitize_energy_news(title)
                    sanitized_summary, _ = sanitize_energy_news(summary)

                    payload = {
                        "title": sanitized_title,
                        "source": feed_info["name"],
                        "link": link,
                        "sentiment": sentiment,
                        "time_ago": "Just now",
                        "created_at": _rss_entry_created_at(entry),
                    }
                    if supports_summary:
                        payload["summary"] = sanitized_summary
                    try:
                        supabase.table("rss_news").insert(payload).execute()
                    except Exception as db_err:
                        error_text = str(db_err)
                        if supports_summary and "PGRST204" in error_text and "'summary'" in error_text:
                            supports_summary = False
                            payload.pop("summary", None)
                            print("[RSS Warning] rss_news has no summary column; storing headlines without summaries.")
                            supabase.table("rss_news").insert(payload).execute()
                        else:
                            raise
                    print(f"[Inserted to Supabase] {feed_info['name']} -> {title} [{sentiment}]")

    except Exception as e:
        print(f"[Error in RSS Worker]: {e}")
    finally:
        try:
            deleted_count = _prune_rss_headlines()
            if deleted_count:
                print(f"[RSS Worker] Removed {deleted_count} old headlines; keeping the newest 50.")
        except Exception as cleanup_error:
            print(f"[RSS Error] Could not enforce the 50-headline limit: {cleanup_error}")

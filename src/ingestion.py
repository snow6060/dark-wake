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

PORTWATCH_QUERY_URL = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
    "Daily_Chokepoints_Data/FeatureServer/0/query"
)
PORTWATCH_CHOKEPOINTS = {
    "chokepoint6": "Strait of Hormuz",
    "chokepoint4": "Bab el-Mandeb",
}
PORTWATCH_FIELDS = (
    "date,portid,n_total,n_tanker,n_container,capacity_tanker"
)
BARRELS_PER_METRIC_TON = 7.33


def _portwatch_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
    return date.fromisoformat(str(value)[:10])


def _fetch_portwatch_features(start_date: date) -> list[dict]:
    where = (
        "portid IN ('chokepoint4','chokepoint6') "
        f"AND date >= '{start_date.isoformat()}'"
    )
    features = []
    offset = 0
    page_size = 1000

    while True:
        try:
            response = requests.get(
                PORTWATCH_QUERY_URL,
                params={
                    "where": where,
                    "outFields": PORTWATCH_FIELDS,
                    "orderByFields": "date ASC",
                    "resultRecordCount": page_size,
                    "resultOffset": offset,
                    "f": "json",
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and "error" in payload:
                # ArcGIS returns 200 with embedded error (e.g., Invalid URL / bad query)
                raise RuntimeError(f"PortWatch query failed: {payload['error']}")
            if not isinstance(payload, dict):
                raise RuntimeError("PortWatch returned non-JSON response.")
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            import logging
            logging.warning("PortWatch request failed (%s); falling back to preserved local telemetry.", exc)
            raise RuntimeError(f"PortWatch endpoint unavailable: {exc}") from exc

        page = payload.get("features")
        if not isinstance(page, list):
            raise RuntimeError("PortWatch returned an invalid feature response.")
        features.extend(page)
        if len(page) < page_size:
            break
        offset += len(page)

    if not features:
        raise RuntimeError("PortWatch returned no chokepoint records.")
    return features


def _prepare_portwatch_records(features: list[dict]) -> list[dict]:
    records = []
    for feature in features:
        attributes = feature.get("attributes")
        if not isinstance(attributes, dict):
            raise RuntimeError("PortWatch returned a feature without attributes.")

        portid = attributes.get("portid")
        chokepoint_name = PORTWATCH_CHOKEPOINTS.get(portid)
        if chokepoint_name is None:
            continue

        records.append({
            "date": _portwatch_date(attributes["date"]),
            "chokepoint_name": chokepoint_name,
            "portid": portid,
            "vessel_count_total": float(attributes.get("n_total") or 0),
            "vessel_count_tanker": float(attributes.get("n_tanker") or 0),
            "vessel_count_container": float(attributes.get("n_container") or 0),
            "capacity_tanker": float(attributes.get("capacity_tanker") or 0),
        })

    if not records:
        raise RuntimeError("PortWatch returned no records for the monitored chokepoints.")

    records.sort(key=lambda record: (record["chokepoint_name"], record["date"]))
    grouped: dict[str, list[dict]] = {}
    for record in records:
        grouped.setdefault(record["chokepoint_name"], []).append(record)

    if set(grouped) != set(PORTWATCH_CHOKEPOINTS.values()):
        raise RuntimeError("PortWatch response did not include both monitored chokepoints.")

    for chokepoint_records in grouped.values():
        for index, record in enumerate(chokepoint_records):
            baseline_records = chokepoint_records[max(0, index - 29):index + 1]
            baseline = sum(item["vessel_count_total"] for item in baseline_records) / len(baseline_records)
            record["baseline_avg"] = round(baseline, 2)
            record["deviation_pct"] = (
                round((record["vessel_count_total"] - baseline) / baseline * 100, 2)
                if baseline
                else 0.0
            )
    return records


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
        return result
    except Exception as exc:
        import logging
        logging.warning("straits.live unavailable (%s); falling back to IMF PortWatch.", exc)
        try:
            return fetch_imf_chokepoint_data()
        except Exception as fallback_exc:
            logging.warning("PortWatch fallback also failed (%s).", fallback_exc)
            return {"status": "error", "source": "straits.live+PortWatch", "message": str(exc)}


def fetch_imf_chokepoint_data():
    """Fetch real IMF PortWatch telemetry and persist it to local SQLite."""
    start_date = datetime.now(timezone.utc).date() - timedelta(days=89)
    try:
        records = _prepare_portwatch_records(_fetch_portwatch_features(start_date))
    except (requests.RequestException, ValueError, KeyError, RuntimeError) as error:
        message = f"PortWatch ingestion failed; existing local telemetry was preserved: {error}"
        print(f"[PortWatch Error] {message}")
        return {
            "status": "error",
            "source": "IMF PortWatch",
            "message": str(error),
        }

    init_db()
    db = SessionLocal()
    try:
        dates = {record["date"] for record in records}
        names = {record["chokepoint_name"] for record in records}
        existing = db.query(ChokepointRecord).filter(
            and_(
                ChokepointRecord.date.in_(dates),
                ChokepointRecord.chokepoint_name.in_(names),
            )
        ).all()
        existing_by_key = {
            (record.date, record.chokepoint_name): record
            for record in existing
        }

        for values in records:
            key = (values["date"], values["chokepoint_name"])
            record = existing_by_key.get(key)
            if record is None:
                db.add(ChokepointRecord(**values))
            else:
                for field, value in values.items():
                    setattr(record, field, value)

        latest_dates = {
            name: max(record["date"] for record in records if record["chokepoint_name"] == name)
            for name in names
        }
        for name, latest_date in latest_dates.items():
            db.query(ChokepointRecord).filter(
                ChokepointRecord.chokepoint_name == name,
                ChokepointRecord.date > latest_date,
            ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    cloud_warning = None
    if supabase:
        cloud_records = [
            {
                **record,
                "date": record["date"].isoformat(),
                "vessel_count_total": record["vessel_count_total"],
                "vessel_count_tanker": record["vessel_count_tanker"],
                "vessel_count_container": record["vessel_count_container"],
            }
            for record in records
        ]
        for record in cloud_records:
            record.pop("capacity_tanker", None)
        try:
            supabase.table("chokepoint_records").upsert(
                cloud_records,
                on_conflict="date,chokepoint_name",
            ).execute()
        except Exception as error:
            cloud_warning = str(error)
            print(f"[PortWatch Warning] Local SQLite updated, Supabase sync failed: {error}")

    result = {
        "status": "success",
        "source": "IMF PortWatch",
        "records_processed": len(records),
        "latest_data_date": {
            name: record_date.isoformat()
            for name, record_date in latest_dates.items()
        },
    }
    if cloud_warning:
        result["supabase_warning"] = cloud_warning
    return result

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

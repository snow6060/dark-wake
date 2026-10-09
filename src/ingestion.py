from datetime import date, datetime, timedelta, timezone
import urllib.request
import feedparser
import requests
from sqlalchemy import and_

from src.database import ChokepointRecord, SessionLocal, init_db
from src.supabase_client import supabase

# Targeted energy & geopolitical RSS feeds.
RSS_FEEDS = [
    {"name": "OilPrice Energy News", "url": "https://oilprice.com/rss/main"},
    {"name": "CNBC Energy", "url": "https://www.cnbc.com/id/19836768/device/rss/rss.html"},
    {"name": "EIA Today in Energy", "url": "https://www.eia.gov/rss/todayinenergy.xml"},
]

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
        if "error" in payload:
            raise RuntimeError(f"PortWatch query failed: {payload['error']}")

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
    Keyword-based sentiment analyzer classifying crude oil & geopolitical impact
    into Bullish, Bearish, or Neutral.
    """
    text = title.lower()
    bullish_keywords = ["surge", "jump", "tension", "conflict", "cut", "shortage", "disruption", "attack", "sanctions", "output drop", "opec+", "war"]
    bearish_keywords = ["surplus", "glut", "fall", "drop", "decline", "peace", "agreement", "output rise", "recession"]

    score = sum(1 for kw in bullish_keywords if kw in text) - sum(1 for kw in bearish_keywords if kw in text)

    if score > 0:
        return "Bullish"
    elif score < 0:
        return "Bearish"
    else:
        return "Neutral"

def fetch_and_store_rss_headlines():
    """
    Background job function to fetch RSS feeds using a browser User-Agent header,
    parse headlines, compute sentiment, and push new unique items to Supabase.
    """
    if not supabase:
        print("[Supabase Warning] Credentials missing. Skipping RSS background fetch.")
        return

    print("[RSS Worker] Fetching latest geopolitical RSS feeds...")
    supports_summary = True

    # Use a standard browser User-Agent so major news networks don't block the scraper
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

    try:
        for feed_info in RSS_FEEDS:
            try:
                req = urllib.request.Request(feed_info["url"], headers=headers)
                with urllib.request.urlopen(req, timeout=10) as response:
                    xml_data = response.read()
                    parsed_feed = feedparser.parse(xml_data)
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

                    payload = {
                        "title": title,
                        "source": feed_info["name"],
                        "link": link,
                        "sentiment": sentiment,
                        "time_ago": "Just now",
                        "created_at": datetime.utcnow().isoformat()
                    }
                    if supports_summary:
                        payload["summary"] = summary
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
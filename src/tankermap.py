import json
import threading
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests

from src.database import (
    LiveChokepointSnapshot,
    SessionLocal,
    TankerMapDailyRecord,
    init_db,
)

TANKERMAP_PAGES = {
    "hormuz": {
        "name": "Strait of Hormuz",
        "url": "https://tankermap.com/analytics/straits/hormuz",
    },
    "bab_el_mandeb": {
        "name": "Bab el-Mandeb",
        "url": "https://tankermap.com/analytics/straits/bab-el-mandeb",
    },
}
TANKERMAP_NEWS_URL = "https://tankermap.com/news"
TANKERMAP_LIVE_MAX_AGE = timedelta(hours=2)
NEWS_CACHE_TTL = timedelta(minutes=30)
REQUEST_HEADERS = {
    "Accept": "text/html",
    "User-Agent": "DarkWake/1.0 (public TankerMap page data)",
}

_news_cache: list[dict] = []
_news_cache_updated_at: datetime | None = None
_news_lock = threading.Lock()


class _StraitPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.template_parts: list[str] = []
        self.in_template = False
        self.in_vessel_table = False
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None
        self.vessel_rows: list[list[str]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "template" and attributes.get("id") == "analyticsStraitData":
            self.in_template = True
        elif tag == "tbody" and attributes.get("id") == "vesselZoneTbody":
            self.in_vessel_table = True
        elif self.in_vessel_table and tag == "tr":
            self.current_row = []
        elif self.in_vessel_table and tag == "td" and self.current_row is not None:
            self.current_cell = []

    def handle_endtag(self, tag):
        if tag == "template" and self.in_template:
            self.in_template = False
        elif tag == "td" and self.current_cell is not None:
            if self.current_row is not None:
                self.current_row.append(" ".join("".join(self.current_cell).split()))
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            self.vessel_rows.append(self.current_row)
            self.current_row = None
        elif tag == "tbody" and self.in_vessel_table:
            self.in_vessel_table = False

    def handle_data(self, data):
        if self.in_template:
            self.template_parts.append(data)
        if self.current_cell is not None:
            self.current_cell.append(data)


class _NewsPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.articles: list[dict] = []
        self.current_article: dict | None = None
        self.capture_field: str | None = None
        self.capture_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "a" and any(class_name.startswith("news-card") for class_name in classes):
            self.current_article = {
                "link": urljoin(TANKERMAP_NEWS_URL, attributes.get("href", "")),
            }
        elif self.current_article is not None and tag == "div" and "news-card-title" in classes:
            self._start_capture("title")
        elif self.current_article is not None and tag == "span" and "news-date" in classes:
            self._start_capture("date")
        elif self.current_article is not None and tag == "span" and any(
            class_name.startswith("news-tag-") for class_name in classes
        ):
            self.current_article["tag"] = next(
                class_name.removeprefix("news-tag-")
                for class_name in classes
                if class_name.startswith("news-tag-")
            )

    def handle_endtag(self, tag):
        if tag == "div" and self.capture_field == "title":
            self.current_article["title"] = self._finish_capture()
        elif tag == "span" and self.capture_field == "date":
            self.current_article["date"] = self._finish_capture()
        elif tag == "a" and self.current_article is not None:
            if self.current_article.get("title") and self.current_article.get("date"):
                self.articles.append(self.current_article)
            self.current_article = None

    def handle_data(self, data):
        if self.capture_field:
            self.capture_parts.append(data)

    def _start_capture(self, field: str):
        self.capture_field = field
        self.capture_parts = []

    def _finish_capture(self) -> str:
        value = " ".join("".join(self.capture_parts).split())
        self.capture_field = None
        self.capture_parts = []
        return value


def _nonnegative_number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"TankerMap returned an invalid {field} value.")
    return float(value)


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError as error:
        raise ValueError("TankerMap returned an invalid vessel-position timestamp.") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_strait_page(html: str, chokepoint_key: str) -> tuple[list[dict], dict]:
    parser = _StraitPageParser()
    parser.feed(html)
    if not parser.template_parts:
        raise ValueError("TankerMap public page is missing its daily analytics data.")
    try:
        boot_data = json.loads("".join(parser.template_parts))
    except json.JSONDecodeError as error:
        raise ValueError("TankerMap public page contains invalid daily analytics data.") from error

    if boot_data.get("cpKey") != chokepoint_key:
        raise ValueError("TankerMap public page returned the wrong chokepoint.")
    chart = boot_data.get("chart")
    if not isinstance(chart, dict):
        raise ValueError("TankerMap public page is missing its daily transit series.")

    dates = chart.get("dates")
    series = {
        "lng": chart.get("lng"),
        "crude": chart.get("crude"),
        "product": chart.get("product"),
        "total": chart.get("total"),
    }
    if not isinstance(dates, list) or not dates or any(
        not isinstance(value, str) for value in dates
    ):
        raise ValueError("TankerMap returned an invalid daily date series.")
    if any(not isinstance(values, list) or len(values) != len(dates) for values in series.values()):
        raise ValueError("TankerMap returned mismatched daily transit series.")

    daily_records = []
    for index, value in enumerate(dates):
        try:
            record_date = date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("TankerMap returned an invalid transit date.") from error
        lng = _nonnegative_number(series["lng"][index], "LNG transit count")
        crude = _nonnegative_number(series["crude"][index], "crude transit count")
        product = _nonnegative_number(series["product"][index], "product transit count")
        total_value = series["total"][index]
        total = (
            lng + crude + product
            if total_value is None
            else _nonnegative_number(total_value, "total transit count")
        )
        daily_records.append({
            "date": record_date,
            "chokepoint_name": TANKERMAP_PAGES[chokepoint_key]["name"],
            "vessel_count_total": total,
            "vessel_count_lng": lng,
            "vessel_count_crude": crude,
            "vessel_count_product": product,
        })

    valid_rows = [row for row in parser.vessel_rows if len(row) >= 6 and row[0]]
    if not valid_rows and parser.vessel_rows:
        raise ValueError("TankerMap returned malformed in-zone vessel rows.")
    observed_times = [_parse_timestamp(row[5]) for row in valid_rows]
    if observed_times:
        observed_at = max(observed_times)
    else:
        observed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    tanker_count = sum(
        "tanker" in row[1].lower()
        for row in valid_rows
        if len(row) > 1
    )
    snapshot = {
        "chokepoint_name": TANKERMAP_PAGES[chokepoint_key]["name"],
        "vessels_observed": len(valid_rows),
        "tankers_identified": tanker_count,
        "vessels_classified": sum(bool(row[1]) for row in valid_rows if len(row) > 1),
        "active_window_minutes": 60,
        "snapshot_at": observed_at,
    }
    return daily_records, snapshot


def _parse_news_published_at(value: str, now: datetime) -> datetime:
    cleaned = value.removesuffix(" UTC").strip()
    for year in (now.year, now.year - 1):
        try:
            parsed = datetime.strptime(f"{cleaned} {year}", "%b %d, %H:%M %Y")
        except ValueError:
            continue
        parsed = parsed.replace(tzinfo=timezone.utc)
        if parsed <= now + timedelta(days=1):
            return parsed
    raise ValueError(f"TankerMap returned an invalid news publication date: {value!r}")


def _parse_news_page(html: str, now: datetime | None = None) -> list[dict]:
    parser = _NewsPageParser()
    parser.feed(html)
    now = now or datetime.now(timezone.utc)
    articles = []
    seen_links = set()
    for article in parser.articles:
        link = article["link"]
        if not link.startswith("https://tankermap.com/news/") or link in seen_links:
            continue
        published_at = _parse_news_published_at(article["date"], now)
        seen_links.add(link)
        articles.append({
            "id": f"tankermap:{link.rsplit('/', 1)[-1]}",
            "title": article["title"],
            "source": "TankerMap",
            "link": link,
            "sentiment": "Neutral",
            "published_at": published_at.isoformat(),
            "created_at": published_at.isoformat(),
            "time_ago": article["date"],
        })
    return articles


def _fetch_page(url: str) -> str:
    response = requests.get(
        url,
        headers=REQUEST_HEADERS,
        timeout=(5, 20),
    )
    response.raise_for_status()
    return response.text


def fetch_tankermap_chokepoint_data() -> dict:
    """Ingest public, server-rendered TankerMap chokepoint pages (not private API routes)."""
    parsed_pages = {}
    errors = {}
    for key, page in TANKERMAP_PAGES.items():
        try:
            parsed_pages[key] = _parse_strait_page(_fetch_page(page["url"]), key)
        except (requests.RequestException, ValueError) as error:
            errors[page["name"]] = str(error)

    if not parsed_pages:
        message = "TankerMap public chokepoint pages could not be refreshed."
        print(f"[TankerMap Error] {message} {errors}")
        return {"status": "error", "source": "TankerMap", "errors": errors}

    init_db()
    db = SessionLocal()
    records_processed = 0
    try:
        for key, (daily_records, snapshot_data) in parsed_pages.items():
            dates = [record["date"] for record in daily_records]
            chokepoint_name = snapshot_data["chokepoint_name"]
            existing = db.query(TankerMapDailyRecord).filter(
                TankerMapDailyRecord.date.in_(dates),
                TankerMapDailyRecord.chokepoint_name == chokepoint_name,
            ).all()
            existing_by_key = {
                record.date: record
                for record in existing
            }
            for values in daily_records:
                record = existing_by_key.get(values["date"])
                if record is None:
                    db.add(TankerMapDailyRecord(**values))
                else:
                    for field, value in values.items():
                        setattr(record, field, value)
                records_processed += 1

            # Straits.live remains the live Hormuz source; TankerMap supplies Bab el-Mandeb.
            if key == "bab_el_mandeb":
                snapshot = db.query(LiveChokepointSnapshot).filter_by(
                    chokepoint_name=chokepoint_name
                ).one_or_none()
                values = {
                    "vessels_observed": snapshot_data["vessels_observed"],
                    "tankers_identified": snapshot_data["tankers_identified"],
                    "vessels_classified": snapshot_data["vessels_classified"],
                    "source": "TankerMap",
                    "active_window_minutes": snapshot_data["active_window_minutes"],
                    "snapshot_at": snapshot_data["snapshot_at"],
                    "capture_seconds": 0,
                }
                if snapshot is None:
                    db.add(LiveChokepointSnapshot(
                        chokepoint_name=chokepoint_name,
                        **values,
                    ))
                else:
                    for field, value in values.items():
                        setattr(snapshot, field, value)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    result = {
        "status": "partial_error" if errors else "success",
        "source": "TankerMap",
        "records_processed": records_processed,
        "latest_data_date": {
            TANKERMAP_PAGES[key]["name"]: daily_records[-1]["date"].isoformat()
            for key, (daily_records, _) in parsed_pages.items()
            if daily_records
        },
    }
    if errors:
        result["errors"] = errors
        print(f"[TankerMap Warning] Some public chokepoint pages failed: {errors}")
    return result


def get_tankermap_news() -> list[dict]:
    """Return recent headlines from TankerMap's public news page with a short cache."""
    global _news_cache, _news_cache_updated_at
    now = datetime.now(timezone.utc)
    with _news_lock:
        if (
            _news_cache_updated_at is not None
            and now - _news_cache_updated_at < NEWS_CACHE_TTL
        ):
            return [dict(article) for article in _news_cache]

        _news_cache_updated_at = now
        try:
            updated_articles = _parse_news_page(_fetch_page(TANKERMAP_NEWS_URL), now)
        except (requests.RequestException, ValueError) as error:
            print(f"[TankerMap News Warning] Public news page refresh failed: {error}")
            return [dict(article) for article in _news_cache]

        _news_cache = updated_articles
        return [dict(article) for article in _news_cache]

"""SAM 3.1 Computer Vision module + live AWS Earth Search STAC ingestion."""
import os
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

# Mock endpoint for SAM 3.1 vision calls (no live API credits during tests/dev)
SAM_3_1_ENABLED = False

# AWS Earth Search STAC API (Element 84) — free, no auth required
STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"

LOCATION_BBOXES = {
    "Strait of Hormuz": [55.5, 26.0, 56.5, 27.0],
    "Bab el-Mandeb": [43.0, 12.5, 43.8, 13.2],
    "Port of Fujairah": [56.3, 25.1, 56.45, 25.3],
    "Suez Canal": [32.2, 30.4, 32.6, 31.0],
    "Malacca Strait": [103.5, 1.1, 104.2, 1.5],
    "Port of Singapore": [103.7, 1.2, 104.0, 1.35],
    "Port of Rotterdam": [3.9, 51.88, 4.15, 51.98],
    "Port of Jebel Ali": [54.95, 24.95, 55.15, 25.1],
}

# Backward-compatible alias used by other modules
CHOKEPOINT_BBOXES = LOCATION_BBOXES

FALLBACK_ASSETS = {
    "Strait of Hormuz": "/assets/satellite_chokepoints/hormuz.png",
    "Bab el-Mandeb": "/assets/satellite_chokepoints/bab_el_mandeb.png",
    "Malacca Strait": "/assets/satellite_chokepoints/malacca.png",
    "Port of Fujairah": "/assets/satellite_chokepoints/fujairah.png",
    "Suez Canal": "/assets/satellite_chokepoints/suez.png",
    "Port of Singapore": "/assets/satellite_chokepoints/singapore.png",
    "Port of Rotterdam": "/assets/satellite_chokepoints/rotterdam.png",
    "Port of Jebel Ali": "/assets/satellite_chokepoints/jebel_ali.png",
}

CHOKEPOINTS = [
    {"name": "Strait of Hormuz", "asset": "assets/satellite_chokepoints/hormuz.png"},
    {"name": "Bab el-Mandeb", "asset": "assets/satellite_chokepoints/bab_el_mandeb.png"},
    {"name": "Malacca Strait / Singapore Hub", "asset": "assets/satellite_chokepoints/malacca.png"},
]


def process_satellite_tile(chokepoint_name: str) -> dict[str, Any]:
    """Process a satellite tile and return spatial congestion tokens."""
    if not SAM_3_1_ENABLED:
        # Zero-fail fallback using benchmark snapshot
        snapshot_path = next(
            (c["asset"] for c in CHOKEPOINTS if c["name"] == chokepoint_name),
            None,
        )
        return {
            "chokepoint": chokepoint_name,
            "spatial_congestion_index": 42,
            "estimated_vessel_count": 18,
            "latency_risk_score": 0.35,
            "segment_bboxes": [{"label": "vessel_cluster", "bbox": [10, 20, 120, 140]}],
            "mask_reference": snapshot_path,
            "token_metadata": {"model": "SAM 3.1 (mocked)", "resolution": "high"},
        }
    # Live SAM 3.1 endpoint would be called here when enabled
    raise NotImplementedError("Live SAM 3.1 endpoint not configured.")


def get_spatial_telemetry(chokepoint_name: str) -> dict[str, Any]:
    return process_satellite_tile(chokepoint_name)


def _query_stac(bbox: list, dt_range: str) -> dict | None:
    """Query AWS Earth Search STAC API for the best recent Sentinel-2 tile.

    Tries the newer ``sentinel-2-c1-l2a`` collection first, then falls back to
    ``sentinel-2-l2a`` if nothing is returned.
    """
    collections_to_try = ["sentinel-2-c1-l2a", "sentinel-2-l2a"]
    for collection in collections_to_try:
        # Try with cloud cover filter first, then without if cloudy period
        for query_filter in [{"eo:cloud_cover": {"lt": 35}}, None]:
            payload = {
                "collections": [collection],
                "bbox": bbox,
                "datetime": dt_range,
                "limit": 1,
                "sortby": [{"field": "properties.datetime", "direction": "desc"}],
            }
            if query_filter:
                payload["query"] = query_filter

            try:
                resp = requests.post(STAC_SEARCH_URL, json=payload, timeout=12)
                if not resp.ok:
                    continue
                data = resp.json()
                features = data.get("features", [])
                if features:
                    return features[0]
            except Exception as exc:
                print(f"[STAC] Collection '{collection}' query failed: {exc}")
                continue
    return None


def _extract_thumbnail_url(feature: dict) -> str | None:
    """Extract browser-compatible preview/thumbnail URL (JPEG/PNG) from STAC feature."""
    assets = feature.get("assets", {})
    # Prioritize web-compatible image formats (JPEG/PNG), avoid TIFF
    for key in ("thumbnail", "preview", "rendered_preview"):
        asset = assets.get(key)
        if asset and asset.get("href"):
            href = asset["href"]
            if not href.endswith(".tif") and not href.endswith(".tiff"):
                return href
    return None


def fetch_and_store_daily_snapshots():
    """Live STAC ingestion: query AWS Earth Search, download thumbnail, upload to Supabase."""
    from src.supabase_client import supabase
    from src.database import SessionLocal, SpatialSnapshot

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=30)
    # STAC specification requires RFC3339 formatted datetimes (YYYY-MM-DDTHH:MM:SSZ)
    dt_range = f"{start_date.strftime('%Y-%m-%dT00:00:00Z')}/{end_date.strftime('%Y-%m-%dT23:59:59Z')}"

    stored = 0
    for loc_name, bbox in LOCATION_BBOXES.items():
        fallback_url = FALLBACK_ASSETS.get(loc_name, "/assets/satellite_chokepoints/hormuz.png")
        capture_time = end_date
        try:
            feature = _query_stac(bbox, dt_range)
            if not feature:
                print(f"[STAC] No satellite tiles in window for {loc_name}, using benchmark asset.")
                _insert_fallback(SessionLocal, SpatialSnapshot, loc_name, fallback_url, end_date)
                stored += 1
                continue

            thumbnail_url = _extract_thumbnail_url(feature)
            if not thumbnail_url:
                print(f"[STAC] No JPEG preview found for {loc_name}, using benchmark asset.")
                _insert_fallback(SessionLocal, SpatialSnapshot, loc_name, fallback_url, end_date)
                stored += 1
                continue

            # Parse satellite scene capture timestamp if available
            raw_datetime = feature.get("properties", {}).get("datetime")
            if raw_datetime:
                try:
                    capture_time = datetime.fromisoformat(raw_datetime.replace("Z", "+00:00"))
                except Exception:
                    capture_time = end_date

            image_url = thumbnail_url  # default to direct public S3 preview URL

            # Download thumbnail and upload to Supabase storage bucket
            try:
                img_resp = requests.get(thumbnail_url, timeout=12)
                if img_resp.status_code == 200 and len(img_resp.content) > 100:
                    image_bytes = img_resp.content
                    if supabase:
                        clean_loc = loc_name.lower().replace(" ", "_").replace("/", "_")
                        filename = f"{clean_loc}_{capture_time.strftime('%Y%m%d_%H%M')}.jpg"
                        try:
                            supabase.storage.from_("satellite-snapshots").upload(
                                filename,
                                image_bytes,
                                {"content-type": "image/jpeg", "upsert": "true"},
                            )
                            image_url = supabase.storage.from_("satellite-snapshots").get_public_url(filename)
                            print(f"[STAC] Uploaded {filename} to Supabase bucket.")
                        except Exception as upload_err:
                            print(f"[STAC] Supabase upload failed for {loc_name}: {upload_err}")
                            # image_url remains thumbnail_url (direct public AWS S3 URL)
            except Exception as dl_err:
                print(f"[STAC] Thumbnail download failed for {loc_name}: {dl_err}")

            # Persist record to local SQLite table
            db = SessionLocal()
            try:
                db.add(SpatialSnapshot(
                    location_name=loc_name,
                    image_url=image_url,
                    fallback_url=fallback_url,
                    captured_at=capture_time,
                ))
                db.commit()
                stored += 1
                print(f"[STAC] Stored snapshot for {loc_name} ({capture_time.strftime('%Y-%m-%d %H:%M')}).")
            finally:
                db.close()

        except Exception as e:
            print(f"[STAC] Error processing {loc_name}: {e}")
            _insert_fallback(SessionLocal, SpatialSnapshot, loc_name, fallback_url, end_date)
            stored += 1

    # 3-day rolling cleanup (keep snapshots within 3 days of most recent capture)
    db = SessionLocal()
    try:
        cutoff = end_date - timedelta(days=3)
        deleted = db.query(SpatialSnapshot).filter(SpatialSnapshot.captured_at < cutoff).delete(synchronize_session=False)
        db.commit()
        if deleted:
            print(f"[STAC] Cleaned up {deleted} snapshot(s) older than 3 days.")
    finally:
        db.close()

    print(f"[STAC] Ingestion complete — {stored}/{len(LOCATION_BBOXES)} snapshots stored.")
    return {"status": "success", "snapshots_stored": stored, "source": "aws-earth-search-stac"}


def _insert_fallback(SessionLocal, SpatialSnapshot, loc_name: str, fallback_url: str, captured_at: datetime):
    """Insert a fallback record so the spatial_snapshots table is never empty for a location."""
    db = SessionLocal()
    try:
        db.add(SpatialSnapshot(
            location_name=loc_name,
            image_url=fallback_url,
            fallback_url=fallback_url,
            captured_at=captured_at,
        ))
        db.commit()
    except Exception as e:
        print(f"[STAC] Failed to insert fallback for {loc_name}: {e}")
        db.rollback()
    finally:
        db.close()

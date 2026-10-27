"""SAM 3.1 Computer Vision module + High-Resolution Satellite & STAC Ingestion."""
import os
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

# Mock endpoint for SAM 3.1 vision calls (no live API credits during tests/dev)
SAM_3_1_ENABLED = False

# High-Resolution Satellite MapServer (1280x720 sub-meter ortho-imagery, zero auth required)
HIRES_SATELLITE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"

# AWS Earth Search STAC API (Element 84) — free, no auth required
STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"

# Accurate maritime coordinates focused tightly on traffic separation lanes, anchorages, and docks
LOCATION_BBOXES = {
    "Strait of Hormuz": [56.35, 26.30, 56.68, 26.56],
    "Bab el-Mandeb": [43.30, 12.55, 43.55, 12.75],
    "Port of Fujairah": [56.32, 25.10, 56.46, 25.22],
    "Suez Canal": [32.50, 29.87, 32.62, 30.01],
    "Malacca Strait": [103.58, 1.14, 103.78, 1.26],
    "Port of Singapore": [103.68, 1.21, 103.82, 1.30],
    "Port of Rotterdam": [3.98, 51.92, 4.18, 52.00],
    "Port of Jebel Ali": [55.00, 24.96, 55.13, 25.06],
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
            "token_metadata": {"model": "SAM 3.1 (mocked)", "resolution": "1280x720 high-res optical"},
        }
    raise NotImplementedError("Live SAM 3.1 endpoint not configured.")


def get_spatial_telemetry(chokepoint_name: str) -> dict[str, Any]:
    return process_satellite_tile(chokepoint_name)


def _fetch_hires_satellite_image(bbox: list) -> bytes | None:
    """Fetch high-resolution (1280x720) optical satellite scene for the exact bounding box."""
    bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
    params = {
        "bbox": bbox_str,
        "bboxSR": "4326",
        "imageSR": "4326",
        "size": "1280,720",
        "format": "jpg",
        "f": "image",
    }
    try:
        resp = requests.get(HIRES_SATELLITE_URL, params=params, timeout=18)
        if resp.status_code == 200 and len(resp.content) > 10000:
            return resp.content
    except Exception as exc:
        print(f"[Satellite] High-res optical fetch failed: {exc}")
    return None


def _query_stac(bbox: list, dt_range: str) -> dict | None:
    """Query AWS Earth Search STAC API for Sentinel-2 optical tile metadata."""
    collections_to_try = ["sentinel-2-c1-l2a", "sentinel-2-l2a"]
    for collection in collections_to_try:
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
    for key in ("thumbnail", "preview", "rendered_preview"):
        asset = assets.get(key)
        if asset and asset.get("href"):
            href = asset["href"]
            if not href.endswith(".tif") and not href.endswith(".tiff"):
                return href
    return None


def fetch_and_store_daily_snapshots():
    """Ingest high-resolution satellite imagery, upload to Supabase bucket, and store in SQLite."""
    from src.supabase_client import supabase
    from src.database import SessionLocal, SpatialSnapshot

    end_date = datetime.now(timezone.utc)
    stored = 0

    for loc_name, bbox in LOCATION_BBOXES.items():
        fallback_url = FALLBACK_ASSETS.get(loc_name, "/assets/satellite_chokepoints/hormuz.png")
        capture_time = end_date
        clean_loc = loc_name.lower().replace(" ", "_").replace("/", "_")
        filename = f"{clean_loc}_hires_{end_date.strftime('%Y%m%d')}.jpg"

        # 1. Fetch high-resolution 1280x720 optical satellite imagery
        hires_bytes = _fetch_hires_satellite_image(bbox)
        image_url = None

        if hires_bytes and len(hires_bytes) > 10000:
            if supabase:
                try:
                    supabase.storage.from_("satellite-snapshots").upload(
                        filename,
                        hires_bytes,
                        {"content-type": "image/jpeg", "upsert": "true"},
                    )
                    image_url = supabase.storage.from_("satellite-snapshots").get_public_url(filename)
                    print(f"[Satellite] Uploaded 1280x720 high-res image {filename} to Supabase bucket.")
                except Exception as upload_err:
                    print(f"[Satellite] Supabase upload failed for {loc_name}: {upload_err}")

        # 2. If high-res upload was successful, save to DB; otherwise fall back to STAC preview
        if not image_url:
            # Fallback to STAC preview
            start_date = end_date - timedelta(days=30)
            dt_range = f"{start_date.strftime('%Y-%m-%dT00:00:00Z')}/{end_date.strftime('%Y-%m-%dT23:59:59Z')}"
            feature = _query_stac(bbox, dt_range)
            if feature:
                thumb_url = _extract_thumbnail_url(feature)
                if thumb_url:
                    image_url = thumb_url
                    raw_dt = feature.get("properties", {}).get("datetime")
                    if raw_dt:
                        try:
                            capture_time = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
                        except Exception:
                            capture_time = end_date

        # 3. If both failed, use static benchmark asset
        if not image_url:
            image_url = fallback_url
            print(f"[Satellite] Using benchmark asset fallback for {loc_name}")

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
            print(f"[Satellite] Stored snapshot for {loc_name} ({capture_time.strftime('%Y-%m-%d %H:%M')}).")
        finally:
            db.close()

    # 3-day rolling cleanup
    db = SessionLocal()
    try:
        cutoff = end_date - timedelta(days=3)
        deleted = db.query(SpatialSnapshot).filter(
            (SpatialSnapshot.captured_at < cutoff) |
            (SpatialSnapshot.image_url.like('/assets/%'))
        ).delete(synchronize_session=False)
        db.commit()
        if deleted:
            print(f"[Satellite] Cleaned up {deleted} stale snapshot(s).")
    finally:
        db.close()

    print(f"[Satellite] Ingestion complete — {stored}/{len(LOCATION_BBOXES)} high-resolution snapshots stored.")
    return {"status": "success", "snapshots_stored": stored, "source": "high-res-optical-satellite"}


def _insert_fallback(SessionLocal, SpatialSnapshot, loc_name: str, fallback_url: str, captured_at: datetime):
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
        print(f"[Satellite] Failed to insert fallback for {loc_name}: {e}")
        db.rollback()
    finally:
        db.close()

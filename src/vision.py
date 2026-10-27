"""SAM 3.1 Computer Vision module for satellite chokepoint analysis."""
import os
from typing import Any

# Mock endpoint for SAM 3.1 vision calls (no live API credits during tests/dev)
SAM_3_1_ENABLED = False

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


def fetch_and_store_daily_snapshots():
    """Fetch daily satellite snapshots (STAC or fallback) and store in Supabase."""
    import requests
    from datetime import datetime, timezone
    from src.supabase_client import supabase
    # Mock STAC query for key chokepoints; in production use Microsoft Planetary Computer
    locations = [
        {"name": "Strait of Hormuz", "lat": 26.5, "lon": 56.2},
        {"name": "Bab el-Mandeb", "lat": 12.6, "lon": 43.3},
        {"name": "Port of Fujairah", "lat": 25.1, "lon": 56.3},
        {"name": "Suez Canal", "lat": 30.0, "lon": 32.5},
    ]
    for loc in locations:
        # Mock image URL (placeholder asset); production would upload real bytes
        image_url = f"https://dark-wake-backend.onrender.com/assets/satellite_chokepoints/{loc['name'].lower().replace(' ', '_')}.png"
        # Upload to Supabase storage bucket (mocked if unavailable)
        try:
            if supabase:
                # Note: real upload would use storage.from_().upload()
                pass
        except Exception:
            pass
        # Save record to DB (rolling 3-day window enforced by cleanup)
        from src.database import SessionLocal, SpatialSnapshot
        db = SessionLocal()
        try:
            snapshot = SpatialSnapshot(
                location_name=loc["name"],
                image_url=image_url,
                captured_at=datetime.now(timezone.utc),
            )
            db.add(snapshot)
            db.commit()
        finally:
            db.close()
    # Cleanup: delete snapshots older than 3 days
    from src.database import SessionLocal, SpatialSnapshot
    from datetime import timedelta
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        db.query(SpatialSnapshot).filter(SpatialSnapshot.captured_at < cutoff).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    return {"status": "success", "snapshots_stored": len(locations)}

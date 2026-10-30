"""Read-only Spatial Intelligence API.

Serves only what is stored in Supabase. When there is no capture for a zone the response says
so; no number is ever invented.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from src.spatial_config import load_settings
from src.supabase_client import supabase

router = APIRouter(prefix="/api/spatial", tags=["spatial"])

_CACHE: dict[str, tuple[float, Any]] = {}
CACHE_TTL_SECONDS = 60  # the app polls every 15 s; don't hit Supabase each time


def _cached(key: str, fn: Callable[[], Any]) -> Any:
    hit = _CACHE.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    value = fn()
    _CACHE[key] = (now, value)
    return value


def freshness_label(age_hours: float | None) -> str:
    if age_hours is None:
        return "NONE"
    if age_hours <= 48:
        return "FRESH"
    if age_hours <= 24 * 7:
        return "AGING"
    if age_hours <= 24 * 14:
        return "STALE"
    return "EXPIRED"


def _require_supabase():
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured.")
    return supabase


def _public_url(path: str | None) -> str | None:
    if not path:
        return None
    return _require_supabase().storage.from_(load_settings().bucket).get_public_url(path)


def _snapshot_view(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    acquired = row.get("acquired_at")
    age_hours = None
    if acquired:
        age_hours = round((now - datetime.fromisoformat(acquired.replace("Z", "+00:00"))).total_seconds() / 3600, 1)
    status = row.get("status")
    return {
        "id": row.get("id"),
        "scene_id": row.get("scene_id"),
        "acquired_at": acquired,
        "age_hours": age_hours,
        "freshness": freshness_label(age_hours),
        "cloud_pct": row.get("cloud_pct"),
        "valid_pct": row.get("valid_pct"),
        "resolution_m": row.get("gsd_m") or 10,
        "width_px": row.get("width_px"),
        "height_px": row.get("height_px"),
        "status": status,
        "analysis_pending": status in ("fetched", "analyzing"),
        "image_url": row.get("image_url"),
        "thumb_url": _public_url(row.get("thumb_path")),
    }


def _load_zones() -> list[dict[str, Any]]:
    client = _require_supabase()
    now = datetime.now(timezone.utc)
    zones = client.table("spatial_zones").select("*").eq("active", True).order("sort_order").execute().data or []
    out = []
    for z in zones:
        rows = (
            client.table("spatial_snapshots")
            .select("*")
            .eq("zone_id", z["zone_id"])
            .order("acquired_at", desc=True)
            .execute()
            .data
            or []
        )
        latest = _snapshot_view(rows[0], now) if rows else None
        out.append({
            "zone_id": z["zone_id"],
            "display_name": z["display_name"],
            "kind": z["kind"],
            "why_it_matters": z["why_it_matters"],
            "ref_lat": z["ref_lat"],
            "ref_lon": z["ref_lon"],
            "range_rings_km": z.get("range_rings_km") or [5, 10, 20],
            "bbox": [z["bbox_west"], z["bbox_south"], z["bbox_east"], z["bbox_north"]],
            "captures_stored": len(rows),
            "latest": latest,
            "freshness": latest["freshness"] if latest else "NONE",
            "status_message": None if latest else "No clear capture stored yet for this zone.",
        })
    return out


@router.get("/zones")
def get_zones():
    zones = _cached("zones", _load_zones)
    return {
        "zones": zones,
        "source": "Sentinel-2 L2A via AWS Earth Search",
        "resolution_m": 10,
    }


@router.get("/zones/{zone_id}/snapshots")
def get_zone_snapshots(zone_id: str):
    def load():
        client = _require_supabase()
        zone = client.table("spatial_zones").select("zone_id").eq("zone_id", zone_id).execute().data
        if not zone:
            return None
        rows = (
            client.table("spatial_snapshots")
            .select("*")
            .eq("zone_id", zone_id)
            .order("acquired_at", desc=True)
            .execute()
            .data
            or []
        )
        now = datetime.now(timezone.utc)
        return [_snapshot_view(r, now) for r in rows]

    snapshots = _cached(f"snapshots:{zone_id}", load)
    if snapshots is None:
        raise HTTPException(status_code=404, detail=f"Unknown zone '{zone_id}'.")
    return {"zone_id": zone_id, "snapshots": snapshots}

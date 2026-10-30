"""Spatial Intelligence settings and zone loading.

Zones live in the Supabase table `spatial_zones`; nothing about a zone is hard-coded in
Python or in the frontend. Thresholds can be overridden with SPATIAL_* environment variables.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from src.supabase_client import supabase


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return int(default)


@dataclass(frozen=True)
class SpatialSettings:
    stac_url: str = "https://earth-search.aws.element84.com/v1"
    # Tried in order; the first collection that returns scenes is used (the second is a fallback).
    collections: tuple[str, ...] = ("sentinel-2-c1-l2a", "sentinel-2-l2a")
    bucket: str = "satellite-snapshots"
    lookback_days: int = 25
    max_cloud_pct: float = 25.0      # cloud + shadow inside the zone box
    min_valid_pct: float = 90.0      # share of the zone box the scene actually covers
    keep_per_zone: int = 4
    max_candidates: int = 15         # newest scenes examined per zone per run
    tile_cloud_prefilter: int = 80   # coarse whole-tile cloud filter used in the STAC query


def load_settings() -> SpatialSettings:
    return SpatialSettings(
        stac_url=os.getenv("SPATIAL_STAC_URL", SpatialSettings.stac_url),
        bucket=os.getenv("SPATIAL_BUCKET", SpatialSettings.bucket),
        lookback_days=_env_int("SPATIAL_LOOKBACK_DAYS", SpatialSettings.lookback_days),
        max_cloud_pct=_env_float("SPATIAL_MAX_CLOUD_PCT", SpatialSettings.max_cloud_pct),
        min_valid_pct=_env_float("SPATIAL_MIN_VALID_PCT", SpatialSettings.min_valid_pct),
        keep_per_zone=_env_int("SPATIAL_KEEP_PER_ZONE", SpatialSettings.keep_per_zone),
        max_candidates=_env_int("SPATIAL_MAX_CANDIDATES", SpatialSettings.max_candidates),
    )


@dataclass(frozen=True)
class Zone:
    zone_id: str
    display_name: str
    kind: str
    bbox: tuple[float, float, float, float]  # west, south, east, north
    analysis_polygon: dict | None
    ref_lat: float
    ref_lon: float
    range_rings_km: tuple[float, ...]
    min_declared_length_m: int


def zone_from_row(row: dict[str, Any]) -> Zone:
    rings = row.get("range_rings_km") or [5, 10, 20]
    return Zone(
        zone_id=row["zone_id"],
        display_name=row["display_name"],
        kind=row["kind"],
        bbox=(
            float(row["bbox_west"]),
            float(row["bbox_south"]),
            float(row["bbox_east"]),
            float(row["bbox_north"]),
        ),
        analysis_polygon=row.get("analysis_polygon"),
        ref_lat=float(row["ref_lat"]),
        ref_lon=float(row["ref_lon"]),
        range_rings_km=tuple(float(r) for r in rings),
        min_declared_length_m=int(row.get("min_declared_length_m") or 100),
    )


def load_active_zones(zone_ids: list[str] | None = None) -> list[Zone]:
    """Read active zones from Supabase, in display order."""
    if supabase is None:
        raise RuntimeError("Supabase is not configured (check SUPABASE_URL and SUPABASE_KEY).")
    query = supabase.table("spatial_zones").select("*").eq("active", True).order("sort_order")
    rows = query.execute().data or []
    zones = [zone_from_row(r) for r in rows]
    if zone_ids:
        wanted = set(zone_ids)
        zones = [z for z in zones if z.zone_id in wanted]
    return zones
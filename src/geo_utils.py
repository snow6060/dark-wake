"""Pure geometry helpers for Spatial Intelligence (no network, no database)."""
from __future__ import annotations

import math

from rasterio.transform import rowcol, xy
from rasterio.warp import transform as warp_transform
from shapely.geometry import Point, shape

EARTH_RADIUS_M = 6371000.0
KNOT_TO_MS = 0.514444


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two lat/lon points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def range_bearing_km(ref_lat: float, ref_lon: float, lat: float, lon: float) -> tuple[float, float]:
    """Distance (km) and bearing (degrees clockwise from north) from a reference point.

    This is what the radar draws: x = r*sin(bearing), y = -r*cos(bearing).
    """
    dist_km = haversine_m(ref_lat, ref_lon, lat, lon) / 1000.0
    phi1, phi2 = math.radians(ref_lat), math.radians(lat)
    dlambda = math.radians(lon - ref_lon)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return dist_km, (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def dead_reckon(
    lat: float, lon: float, sog_knots: float, cog_deg: float, dt_seconds: float
) -> tuple[float, float]:
    """Move a position along its course for dt_seconds (negative moves it back in time)."""
    delta = (sog_knots * KNOT_TO_MS * dt_seconds) / EARTH_RADIUS_M
    theta = math.radians(cog_deg)
    phi1, lam1 = math.radians(lat), math.radians(lon)
    phi2 = math.asin(
        math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    )
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    lon2 = (math.degrees(lam2) + 540.0) % 360.0 - 180.0  # normalise to [-180, 180)
    return math.degrees(phi2), lon2


def point_in_polygon(lat: float, lon: float, polygon_geojson: dict) -> bool:
    """True if the point lies inside a GeoJSON geometry (Polygon or MultiPolygon)."""
    return bool(shape(polygon_geojson).covers(Point(lon, lat)))


def bbox_contains(bbox: tuple[float, float, float, float], lat: float, lon: float) -> bool:
    """bbox = (west, south, east, north)."""
    west, south, east, north = bbox
    return west <= lon <= east and south <= lat <= north


def pixel_to_lonlat(transform, crs, col: float, row: float) -> tuple[float, float]:
    """Centre of pixel (col, row) -> (lon, lat) in EPSG:4326.

    `transform` is the affine transform of the image window (stored as window_transform)
    and `crs` its coordinate system (stored as crs, e.g. 'EPSG:32640').
    """
    xs, ys = xy(transform, [row], [col], offset="center")
    lons, lats = warp_transform(crs, "EPSG:4326", [xs[0]], [ys[0]])
    return float(lons[0]), float(lats[0])


def lonlat_to_pixel(transform, crs, lon: float, lat: float) -> tuple[int, int]:
    """(lon, lat) -> (col, row) in the image window described by transform and crs."""
    xs, ys = warp_transform("EPSG:4326", crs, [lon], [lat])
    rows, cols = rowcol(transform, [xs[0]], [ys[0]])
    return int(cols[0]), int(rows[0])

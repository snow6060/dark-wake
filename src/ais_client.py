import os

import requests
from dotenv import load_dotenv

load_dotenv()
BASE = os.getenv("AIS_API_BASE", "https://sandbox.aisvesseltracker.com")


def parse_features(data):
    ships = []
    for f in data.get("features", []):
        p, (lon, lat) = f.get("properties") or {}, f["geometry"]["coordinates"][:2]
        ships.append({
            "mmsi": p.get("mmsi"), "name": p.get("name"), "lat": lat, "lon": lon,
            "sog": p.get("sog") or 0, "cog": p.get("cog"), "heading": p.get("heading"),
            "nav": p.get("navStatus"), "type_code": p.get("type"), "ship_type": p.get("shipType"),
            "time_utc": p.get("time_utc"),
        })
    return ships


def fetch_bbox_history(bbox, at_iso, window_s=86400, key=None, timeout=60):
    key = key or os.environ["VOYAGE_RADAR_API_KEY"]
    west, south, east, north = bbox
    r = requests.get(
        f"{BASE}/v1/vessels/bbox/history",
        headers={"X-API-Key": key},
        params={"swLat": south, "swLng": west, "neLat": north, "neLng": east, "at": at_iso, "window": window_s},
        timeout=timeout,
    )
    credits = r.headers.get("X-Credits-Remaining")
    if r.status_code == 204:
        return [], credits
    r.raise_for_status()
    return parse_features(r.json()), credits
import logging
import os
import time
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()
BASE = os.getenv("AIS_API_BASE", "https://data.aisvesseltracker.com").rstrip("/")
log = logging.getLogger(__name__)
HISTORY_REQUEST_ATTEMPTS = 6
HISTORY_WINDOW_FALLBACKS = (86400, 21600, 3600, 900)


def _is_unsupported_history_window(response):
    if response.status_code != 500:
        return False
    try:
        body = response.json()
    except (AttributeError, ValueError):
        return False
    error = body.get("error") if isinstance(body, dict) else None
    return (
        isinstance(error, dict)
        and error.get("code") == "server_error"
        and error.get("message")
        == "failed to query vessels in bounding box at the requested time"
    )


def parse_features(data):
    ships = []
    for f in data.get("features", []):
        p = f.get("properties") or {}
        geometry = f.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if len(coordinates) >= 2:
            lon, lat = coordinates[:2]
        elif p.get("longitude") is not None and p.get("latitude") is not None:
            lon, lat = p["longitude"], p["latitude"]
        else:
            raise ValueError("AIS feature is missing vessel coordinates.")
        ships.append({
            "mmsi": p.get("mmsi") or p.get("id"),
            "name": p.get("shipName") or p.get("name"),
            "lat": lat,
            "lon": lon,
            "sog": p.get("sog") or p.get("speedOverGround") or 0,
            "cog": p.get("cog") if p.get("cog") is not None else p.get("courseOverGround"),
            "heading": p.get("heading"),
            "nav": p.get("navStatus") or p.get("navigationalStatus"),
            "type_code": p.get("type"),
            "ship_type": p.get("shipType"),
            "country": p.get("country"),
            "flag": p.get("flag"),
            "imo": p.get("imo") or p.get("imoNumber"),
            "time_utc": p.get("time_utc") or p.get("timestamp"),
        })
    return ships


def fetch_bbox_history(bbox, at_iso, window_s=86400, key=None, timeout=60):
    host = urlparse(BASE).hostname
    if not host or "sandbox" in host.lower():
        raise RuntimeError("Live AIS is required, but AIS_API_BASE points to the sandbox.")
    key = key or os.environ["VOYAGE_RADAR_API_KEY"]
    west, south, east, north = bbox
    params = {
        "swLat": south,
        "swLng": west,
        "neLat": north,
        "neLng": east,
        "at": at_iso,
        "window": window_s,
    }
    windows = list(dict.fromkeys(
        [window_s, *(value for value in HISTORY_WINDOW_FALLBACKS if value < window_s)]
    ))
    for window_index, current_window in enumerate(windows):
        params["window"] = current_window
        for attempt in range(HISTORY_REQUEST_ATTEMPTS):
            try:
                r = requests.get(
                    f"{BASE}/v1/vessels/bbox/history",
                    headers={"X-API-Key": key},
                    params=params,
                    timeout=timeout,
                )
            except (requests.Timeout, requests.ConnectionError):
                if attempt + 1 == HISTORY_REQUEST_ATTEMPTS:
                    raise
                delay = 2 ** attempt
                log.warning(
                    "AIS history request failed to connect; retrying in %s seconds "
                    "(attempt %s/%s).",
                    delay,
                    attempt + 1,
                    HISTORY_REQUEST_ATTEMPTS,
                )
                time.sleep(delay)
                continue

            if r.status_code < 500:
                credits = r.headers.get("X-Credits-Remaining")
                if r.status_code == 204:
                    return [], credits, current_window
                r.raise_for_status()
                return parse_features(r.json()), credits, current_window

            if _is_unsupported_history_window(r):
                if window_index + 1 < len(windows):
                    log.warning(
                        "AIS history provider could not query the %s-second window; "
                        "trying the next narrower window.",
                        current_window,
                    )
                    break
                log.error(
                    "AIS history provider could not query the final %s-second window.",
                    current_window,
                )
                r.raise_for_status()

            if attempt + 1 < HISTORY_REQUEST_ATTEMPTS:
                delay = 2 ** attempt
                log.warning(
                    "AIS history service returned HTTP %s for %s; response: %s. "
                    "Retrying in %s seconds (attempt %s/%s).",
                    r.status_code,
                    getattr(r, "url", f"{BASE}/v1/vessels/bbox/history"),
                    (getattr(r, "text", "") or "").replace("\r", " ").replace("\n", " ")[:500],
                    delay,
                    attempt + 1,
                    HISTORY_REQUEST_ATTEMPTS,
                )
                time.sleep(delay)
                continue

            if window_index + 1 < len(windows):
                log.warning(
                    "AIS history service returned HTTP %s for a %s-second window; "
                    "response: %s. Retrying with a narrower historical window.",
                    r.status_code,
                    current_window,
                    (getattr(r, "text", "") or "").replace("\r", " ").replace("\n", " ")[:500],
                )
                break
            log.error(
                "AIS history service returned HTTP %s after retries for %s; response: %s.",
                r.status_code,
                getattr(r, "url", f"{BASE}/v1/vessels/bbox/history"),
                (getattr(r, "text", "") or "").replace("\r", " ").replace("\n", " ")[:500],
            )
            r.raise_for_status()

    raise RuntimeError("AIS history request ended without a response.")
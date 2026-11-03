"""Sentinel-2 imagery fetch for the Spatial Intelligence zones.

For every active zone (table `spatial_zones`) this module:
  1. searches the AWS Earth Search STAC catalogue (free, no key) for recent Sentinel-2 L2A scenes,
  2. reads ONLY the zone's box from the 20 m scene-classification layer and rejects cloudy or
     partly-covered scenes (cheap: a few hundred KB per scene),
  3. reads the same box at native 10 m from the true-colour layer for the scenes that passed,
  4. uploads a full-resolution JPEG and a thumbnail to the Supabase bucket,
  5. records one row per capture in `spatial_snapshots` (status 'fetched'),
  6. keeps only the newest N captures per zone.

Nothing here invents data: if no scene is clear enough the zone simply gets no new capture.
"""
from __future__ import annotations

import os

# Public Sentinel-2 files: no AWS credentials, and don't waste requests listing directories.
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "3")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
# Speed up reading cloud-optimised GeoTIFFs over a high-latency connection.
os.environ.setdefault("GDAL_HTTP_MULTIPLEX", "YES")
os.environ.setdefault("GDAL_HTTP_VERSION", "2")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
# GDAL's default HTTP read size is only 16 KB, which means thousands of round trips on a slow link.
os.environ.setdefault("CPL_VSIL_CURL_CHUNK_SIZE", "2097152")
os.environ.setdefault("CPL_VSIL_CURL_CACHE_SIZE", "200000000")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("VSI_CACHE_SIZE", "50000000")
os.environ.setdefault("GDAL_CACHEMAX", "256")

import io
import logging
import math
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from PIL import Image
from rasterio.enums import Resampling
from pystac_client import Client
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, bounds as window_bounds, from_bounds
from scipy import ndimage as ndi

from src.spatial_config import SpatialSettings, Zone, load_active_zones, load_settings
from src.supabase_client import supabase
from src.job_reporter import Reporter

log = logging.getLogger("spatial.fetch")

# Sentinel-2 scene classification values: 3 cloud shadow, 8/9 cloud (medium/high prob.), 10 thin cirrus.
CLOUD_CLASSES = (3, 8, 9, 10)


# --------------------------------------------------------------------------- reading rasters

def _asset_href(item, key: str) -> str:
    asset = item.assets.get(key)
    if asset is None:
        raise KeyError(f"asset '{key}' not found on {item.id}; available: {sorted(item.assets)}")
    return asset.href


def _snap_window(win: Window, width: int, height: int) -> tuple[Window | None, int]:
    """Round a float window out to whole pixels and clip it to the raster.

    Returns (clipped_window or None if there is no overlap, number of pixels requested).
    """
    col_off = math.floor(win.col_off)
    row_off = math.floor(win.row_off)
    w = math.ceil(win.col_off + win.width) - col_off
    h = math.ceil(win.row_off + win.height) - row_off
    requested = max(w, 1) * max(h, 1)
    col0, row0 = max(col_off, 0), max(row_off, 0)
    col1, row1 = min(col_off + w, width), min(row_off + h, height)
    if col1 <= col0 or row1 <= row0:
        return None, requested
    return Window(col0, row0, col1 - col0, row1 - row0), requested


def read_scl(item, bbox: tuple[float, float, float, float]) -> dict[str, Any] | None:
    """Read the zone box from the 20 m scene-classification layer.

    Returns None when the scene does not overlap the box at all.
    """
    with rasterio.open(_asset_href(item, "scl")) as src:
        left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *bbox, densify_pts=21)
        win, requested = _snap_window(
            from_bounds(left, bottom, right, top, transform=src.transform), src.width, src.height
        )
        if win is None:
            return None
        return {
            "scl": src.read(1, window=win),
            "requested_pixels": requested,
            "bounds": window_bounds(win, src.transform),  # in the scene's own CRS
        }


def scl_quality(scl: np.ndarray, requested_pixels: int) -> tuple[float, float]:
    """(valid_pct, cloud_pct).

    valid_pct: share of the requested zone box that the scene covers with real data.
    cloud_pct: cloud, cloud shadow and cirrus as a share of the valid pixels in the box.
    """
    valid = scl != 0
    n_valid = int(valid.sum())
    valid_pct = 100.0 * n_valid / max(requested_pixels, 1)
    cloud_pct = 100.0 * int((np.isin(scl, CLOUD_CLASSES) & valid).sum()) / max(n_valid, 1)
    return round(valid_pct, 1), round(cloud_pct, 1)


def _read_strips(href: str, win: Window, count: int, workers: int, on_strip=None) -> np.ndarray:
    col_off, row_off = int(win.col_off), int(win.row_off)
    width, height = int(win.width), int(win.height)
    out = np.zeros((count, height, width), dtype=np.uint8)
    n_strips = max(1, min(32, height // 128))
    edges = np.linspace(0, height, n_strips + 1).astype(int)
    done = [0]
    lock = threading.Lock()

    def read_strip(i: int) -> None:
        r0, r1 = int(edges[i]), int(edges[i + 1])
        with rasterio.open(href) as strip_src:
            out[:, r0:r1, :] = strip_src.read(window=Window(col_off, row_off + r0, width, r1 - r0))
        if on_strip:
            with lock:
                done[0] += 1
                on_strip(done[0], n_strips)

    with ThreadPoolExecutor(max_workers=max(1, min(workers, n_strips))) as pool:
        list(pool.map(read_strip, range(n_strips)))
    return out


def read_visual(item, bounds: tuple[float, float, float, float], workers: int | None = None):
    """Read one tile's part of a ground box at native 10 m from the true-colour (TCI) layer.

    Returns (rgb array shaped (3, h, w), window affine transform, crs string) or None.
    """
    workers = workers or int(os.getenv("SPATIAL_READ_WORKERS", "8"))
    href = _asset_href(item, "visual")
    with rasterio.open(href) as src:
        win, _ = _snap_window(from_bounds(*bounds, transform=src.transform), src.width, src.height)
        if win is None:
            return None
        transform = src.window_transform(win)
        crs = src.crs.to_string()
        count = src.count
    return _read_strips(href, win, count, workers), transform, crs


# --------------------------------------------------------------------------- passes and mosaics
#
# A zone can straddle two Sentinel-2 tiles. Tiles from the same satellite pass share an acquisition
# time, so they can be merged into one picture of the zone.

def platform_code(item) -> str:
    """'S2A', 'S2B', 'S2C' from the STAC platform property or the scene id."""
    props = getattr(item, "properties", None) or {}
    platform = str(props.get("platform") or "").lower()
    if platform.startswith("sentinel-2") and len(platform) > len("sentinel-2"):
        return "S2" + platform[-1].upper()
    return str(item.id)[:3].upper() if str(item.id).upper().startswith("S2") else "S2X"


def group_scenes_by_pass(items: list, max_gap_minutes: int = 15) -> list[list]:
    """Group tiles that belong to the same satellite pass. Newest group first."""
    groups: list[list] = []
    for item in sorted(items, key=lambda i: i.datetime, reverse=True):
        code = platform_code(item)
        for group in groups:
            gap = abs((group[0].datetime - item.datetime).total_seconds())
            if platform_code(group[0]) == code and gap <= max_gap_minutes * 60:
                group.append(item)
                break
        else:
            groups.append([item])
    return groups


def group_time(group: list) -> datetime:
    return min(i.datetime for i in group).astimezone(timezone.utc)


def pass_scene_id(group: list, zone_id: str) -> str:
    """Stable id for one pass over one zone, e.g. S2A_20261026_fujairah."""
    return f"{platform_code(group[0])}_{group_time(group):%Y%m%d}_{zone_id}"


def paste_valid(canvas: np.ndarray, tile: np.ndarray, row_off: int, col_off: int) -> None:
    """Copy tile pixels into the canvas only where the tile has data and the canvas does not yet.

    A tile's black (no-data) edge therefore never overwrites good pixels from another tile.
    Works for 2-D (scene classification) and 3-D (bands, rows, cols) arrays.
    """
    h, w = tile.shape[-2:]
    target = canvas[..., row_off:row_off + h, col_off:col_off + w]
    tile_valid = tile.any(axis=0) if tile.ndim == 3 else tile != 0
    canvas_valid = target.any(axis=0) if target.ndim == 3 else target != 0
    take = tile_valid & ~canvas_valid
    if tile.ndim == 3:
        target[:, take] = tile[:, take]
    else:
        target[take] = tile[take]


def _canvas_window(src, bounds: tuple[float, float, float, float]):
    """Window of a tile that overlaps the canvas bounds, plus the canvas origin in tile pixels.

    Returns (clipped Window or None, (col_off, row_off, width, height) of the full canvas
    expressed in this tile's pixel grid). Tiles of one UTM zone share an aligned grid.
    """
    left, bottom, right, top = bounds
    res_x, res_y = src.res
    col_off = round((left - src.transform.c) / res_x)
    row_off = round((src.transform.f - top) / res_y)
    width = round((right - left) / res_x)
    height = round((top - bottom) / res_y)
    c0, r0 = max(col_off, 0), max(row_off, 0)
    c1, r1 = min(col_off + width, src.width), min(row_off + height, src.height)
    if c1 <= c0 or r1 <= r0:
        return None, (col_off, row_off, width, height)
    return Window(c0, r0, c1 - c0, r1 - r0), (col_off, row_off, width, height)


def read_scl_mosaic(group: list, bbox: tuple[float, float, float, float]) -> dict[str, Any] | None:
    """Scene-classification layer for the zone box, merged across all tiles of one pass.

    Returns None when no tile overlaps the box. 'items' lists the tiles that contributed.
    """
    canvas = None
    crs = None
    bounds = None
    used = []
    for item in group:
        with rasterio.open(_asset_href(item, "scl")) as src:
            if crs is None:
                crs = src.crs.to_string()
                left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *bbox, densify_pts=21)
                bounds = (math.floor(left / 20) * 20, math.floor(bottom / 20) * 20,
                          math.ceil(right / 20) * 20, math.ceil(top / 20) * 20)
                canvas = np.zeros((round((bounds[3] - bounds[1]) / 20), round((bounds[2] - bounds[0]) / 20)),
                                  dtype=np.uint8)
            elif src.crs.to_string() != crs:
                log.info("skipping %s: different map projection (%s) from the rest of the pass", item.id, src.crs)
                continue
            win, full = _canvas_window(src, bounds)
            if win is None:
                continue
            tile = src.read(1, window=win)
        paste_valid(canvas, tile, int(win.row_off) - full[1], int(win.col_off) - full[0])
        used.append(item)
    if canvas is None or not used:
        return None
    return {"scl": canvas, "requested_pixels": int(canvas.size), "bounds": bounds, "crs": crs, "items": used}


def read_visual_mosaic(items: list, bounds: tuple[float, float, float, float], crs: str,
                       workers: int | None = None, on_progress=None):
    workers = workers or int(os.getenv("SPATIAL_READ_WORKERS", "8"))
    left, bottom, right, top = bounds
    canvas = np.zeros((3, round((top - bottom) / 10), round((right - left) / 10)), dtype=np.uint8)
    for k, item in enumerate(items):
        href = _asset_href(item, "visual")
        with rasterio.open(href) as src:
            if src.crs.to_string() != crs:
                continue
            win, full = _canvas_window(src, bounds)
            count = src.count
        if win is None:
            continue
        tick = (lambda d, t, k=k: on_progress((k + d / t) / len(items))) if on_progress else None
        tile = _read_strips(href, win, count, workers, tick)
        paste_valid(canvas, tile, int(win.row_off) - full[1], int(win.col_off) - full[0])
    return canvas, from_origin(left, top, 10, 10), crs


def build_water_mask(
    scl: np.ndarray,
    scl_bounds: tuple[float, float, float, float],
    scl_crs: str,
    image_shape: tuple[int, int],
    image_transform: Affine,
    image_crs: str,
) -> np.ndarray:
    """Reproject Sentinel-2's 20 m water class to the image grid, excluding uncertain shore pixels."""
    left, _, _, top = scl_bounds
    water_20m = (scl == 6).astype(np.uint8)
    water = np.zeros(image_shape, dtype=np.uint8)
    reproject(
        source=water_20m,
        destination=water,
        src_transform=from_origin(left, top, 20, 20),
        src_crs=scl_crs,
        dst_transform=image_transform,
        dst_crs=image_crs,
        resampling=Resampling.nearest,
    )
    return ndi.binary_erosion(water.astype(bool), iterations=2)


def encode_water_mask(mask: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(mask.astype(np.uint8) * 255).save(buffer, format="PNG")
    return buffer.getvalue()


def _water_mask_path(snapshot: dict[str, Any], zone_id: str) -> str:
    image_path = snapshot.get("image_path")
    if image_path:
        image_path = str(image_path)
        for extension in (".jpeg", ".jpg"):
            if image_path.lower().endswith(extension):
                return image_path[:-len(extension)] + "_water.png"
    return f"{zone_id}/{snapshot['scene_id']}_water.png"


def load_water_mask(
    zone: Zone,
    snapshot: dict[str, Any],
    image_shape: tuple[int, int],
    image_transform: Affine,
    image_crs: str,
    reporter: Reporter | None = None,
) -> np.ndarray:
    """Load a saved mask or create one from the exact Sentinel pass for an older capture."""
    settings = load_settings()
    storage = _require_supabase().storage.from_(settings.bucket)
    mask_path = _water_mask_path(snapshot, zone.zone_id)
    stored_error = None
    try:
        data = storage.download(mask_path)
        mask = np.asarray(Image.open(io.BytesIO(data)).convert("L")) > 0
        if mask.shape == image_shape:
            return mask
        stored_error = ValueError(
            f"stored mask dimensions {mask.shape} do not match image dimensions {image_shape}"
        )
    except Exception as exc:
        stored_error = exc
    message = (
        f"Water mask unavailable for {snapshot['scene_id']} ({stored_error}); "
        "rebuilding from Sentinel classification."
    )
    log.warning(message)
    if reporter:
        reporter.log(message)

    acquired_at = datetime.fromisoformat(snapshot["acquired_at"].replace("Z", "+00:00"))
    items = search_scenes(
        Client.open(settings.stac_url),
        zone,
        acquired_at - timedelta(minutes=15),
        acquired_at + timedelta(minutes=15),
        settings,
    )
    for group in group_scenes_by_pass(items):
        if pass_scene_id(group, zone.zone_id) != snapshot["scene_id"]:
            continue
        info = read_scl_mosaic(group, zone.bbox)
        if info is None:
            break
        mask = build_water_mask(
            info["scl"], info["bounds"], info["crs"],
            image_shape, image_transform, image_crs,
        )
        storage.upload(mask_path, encode_water_mask(mask), {"content-type": "image/png", "upsert": "true"})
        return mask

    raise RuntimeError(
        f"Could not restore Sentinel water mask for '{snapshot['scene_id']}'. "
        f"Stored mask error: {stored_error}"
    ) from stored_error


def render_jpeg(rgb: np.ndarray, max_side: int | None = None, stretch: bool = True, quality: int = 90) -> bytes:
    """Encode (3, h, w) uint8 as JPEG. Full resolution unless max_side is given (thumbnails).

    Open water is very dark in true colour, so a percentile stretch is applied for viewing.
    """
    img = np.moveaxis(rgb, 0, -1).astype(np.float32)
    if stretch:
        valid = img.sum(axis=2) > 0
        if valid.any():
            sample = img[valid][::10]
            lo, hi = np.percentile(sample, (1, 99.5))
            if hi > lo:
                img = np.clip((img - lo) / (hi - lo) * 255.0, 0, 255)
    im = Image.fromarray(img.astype(np.uint8), "RGB")
    if max_side:
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


# --------------------------------------------------------------------------- STAC search

def search_scenes(stac_client, zone: Zone, start: datetime, end: datetime, settings: SpatialSettings) -> list:
    """Newest-first candidate scenes intersecting the zone box.

    Collections are tried in order and the first one that returns scenes is used, so the same
    scene is not read twice from two catalogues.
    """
    for collection in settings.collections:
        search = stac_client.search(
            collections=[collection],
            bbox=list(zone.bbox),
            datetime=f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}",
            query={"eo:cloud_cover": {"lt": settings.tile_cloud_prefilter}},
            max_items=80,
        )
        items = [i for i in search.items() if i.datetime is not None]
        if items:
            items.sort(key=lambda i: i.datetime, reverse=True)
            return items
        log.info("[%s] no scenes in collection %s, trying the next one", zone.zone_id, collection)
    return []


# --------------------------------------------------------------------------- Supabase

def _require_supabase():
    if supabase is None:
        raise RuntimeError("Supabase is not configured (check SUPABASE_URL and SUPABASE_KEY).")
    return supabase


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def known_snapshots(zone_id: str) -> list[dict[str, Any]]:
    """Stored captures for a zone, newest first, with acquired_at parsed."""
    rows = (
        _require_supabase()
        .table("spatial_snapshots")
        .select("id,scene_id,acquired_at,image_path,thumb_path")
        .eq("zone_id", zone_id)
        .order("acquired_at", desc=True)
        .execute()
        .data
        or []
    )
    for row in rows:
        row["acquired_at"] = _parse_ts(row["acquired_at"]) if row.get("acquired_at") else None
    return [r for r in rows if r["acquired_at"] is not None]


def upload_image(bucket: str, path: str, data: bytes, content_type: str = "image/jpeg") -> str:
    storage = _require_supabase().storage.from_(bucket)
    storage.upload(path, data, {"content-type": content_type, "upsert": "true"})
    return storage.get_public_url(path)


def insert_snapshot_row(zone: Zone, cand: dict[str, Any], paths: dict[str, str], image_url: str,
                        size: tuple[int, int], crs: str, transform) -> None:
    group = cand["group"]
    acquired = cand["when"].isoformat()
    row = {
        "zone_id": zone.zone_id,
        "location_name": zone.display_name,
        "scene_id": cand["scene_id"],
        "tile_ids": [i.id for i in cand["items"]],
        "source": group[0].collection_id or "sentinel-2-l2a",
        "acquired_at": acquired,
        "captured_at": acquired,
        "cloud_pct": cand["cloud_pct"],
        "valid_pct": cand["valid_pct"],
        "gsd_m": 10,
        "crs": crs,
        "window_transform": list(transform)[:6],
        "width_px": size[0],
        "height_px": size[1],
        "image_path": paths["image"],
        "thumb_path": paths["thumb"],
        "image_url": image_url,
        "status": "fetched",
    }
    _require_supabase().table("spatial_snapshots").upsert(row, on_conflict="zone_id,scene_id").execute()


def prune_zone(zone_id: str, keep_n: int, bucket: str) -> int:
    """Delete captures (rows and bucket files) beyond the newest keep_n. Returns rows removed."""
    rows = known_snapshots(zone_id)
    stale = rows[keep_n:]
    if not stale:
        return 0
    files = [
        p
        for r in stale
        for p in (r.get("image_path"), r.get("thumb_path"), _water_mask_path(r, zone_id))
        if p
    ]
    client = _require_supabase()
    if files:
        client.storage.from_(bucket).remove(files)
    client.table("spatial_snapshots").delete().in_("id", [r["id"] for r in stale]).execute()
    return len(stale)


# --------------------------------------------------------------------------- orchestration

def process_zone(zone: Zone, settings: SpatialSettings, stac_client, dry_run: bool = False,
                 local_dir: str | None = None, limit: int | None = None, reporter=None) -> dict[str, Any]:
    rep = reporter or Reporter(echo=False)
    result: dict[str, Any] = {
        "zone": zone.zone_id, "status": "ok", "scenes_found": 0, "passes_found": 0, "examined": 0,
        "already_stored": 0, "accepted": [], "rejected": [], "stored": [], "pruned": 0,
    }
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=settings.lookback_days)

    rep.progress(3, f"Searching Sentinel-2 catalogue ({zone.display_name})")
    items = search_scenes(stac_client, zone, start, end, settings)
    result["scenes_found"] = len(items)
    if not items:
        result["status"] = "no_scene"
        rep.log(f"no scenes in the last {settings.lookback_days} days")
        return result
    groups = group_scenes_by_pass(items)
    result["passes_found"] = len(groups)
    rep.log(f"{len(items)} tiles in {len(groups)} satellite passes found")

    known = known_snapshots(zone.zone_id) if supabase is not None else []
    known_ids = {k["scene_id"] for k in known}
    known_days = {k["acquired_at"].date() for k in known}
    oldest_kept = None
    if len(known) >= settings.keep_per_zone:
        oldest_kept = min(k["acquired_at"] for k in known[: settings.keep_per_zone])

    best_by_day: dict[Any, dict[str, Any]] = {}
    for group in groups:
        if result["examined"] >= settings.max_candidates:
            break
        scene_id = pass_scene_id(group, zone.zone_id)
        when = group_time(group)
        if scene_id in known_ids or when.date() in known_days:
            result["already_stored"] += 1
            continue
        if oldest_kept is not None and when <= oldest_kept:
            continue
        day = when.date()
        if day not in best_by_day and len(best_by_day) >= settings.keep_per_zone:
            break
        result["examined"] += 1
        rep.progress(5 + 8 * result["examined"] / max(1, min(len(groups), settings.max_candidates)),
                     "Checking cloud cover")
        try:
            info = read_scl_mosaic(group, zone.bbox)
        except Exception as exc:
            result["rejected"].append({"scene": scene_id, "reason": f"read error: {exc}"})
            rep.log(f"{scene_id}: read error: {exc}")
            continue
        if info is None:
            result["rejected"].append({"scene": scene_id, "reason": "no overlap with zone box"})
            continue
        valid_pct, cloud_pct = scl_quality(info["scl"], info["requested_pixels"])
        if valid_pct < settings.min_valid_pct:
            result["rejected"].append({"scene": scene_id, "reason": f"covers only {valid_pct}% of the zone box"})
            continue
        if cloud_pct > settings.max_cloud_pct:
            result["rejected"].append({"scene": scene_id, "reason": f"{cloud_pct}% cloud/shadow in the zone box"})
            rep.log(f"{scene_id}: rejected, {cloud_pct}% cloud")
            continue
        prev = best_by_day.get(day)
        if prev is None or valid_pct > prev["valid_pct"]:
            best_by_day[day] = {
                "group": group, "scene_id": scene_id, "when": when, "items": info["items"],
                "valid_pct": valid_pct, "cloud_pct": cloud_pct, "bounds": info["bounds"], "crs": info["crs"],
                "scl": info["scl"],
            }

    candidates = sorted(best_by_day.values(), key=lambda c: c["when"], reverse=True)
    if limit:
        candidates = candidates[:limit]
    result["accepted"] = [
        {"scene": c["scene_id"], "acquired_at": c["when"].isoformat(), "tiles": [i.id for i in c["items"]],
         "valid_pct": c["valid_pct"], "cloud_pct": c["cloud_pct"], "collection": c["group"][0].collection_id}
        for c in candidates
    ]
    if not candidates:
        result["status"] = "no_clear_scene"
        rep.log("no new clear capture; the latest stored one will be analysed")
        if not dry_run:
            result["pruned"] = prune_zone(zone.zone_id, settings.keep_per_zone, settings.bucket)
        return result
    rep.log(f"{len(candidates)} new clear capture(s): " + ", ".join(c["scene_id"] for c in candidates))
    if dry_run and not local_dir:
        return result

    bucket = settings.bucket
    for idx, cand in enumerate(candidates):
        lo, span = 15 + 62 * idx / len(candidates), 62 / len(candidates)
        rep.progress(lo, "Downloading satellite image (10 m)")
        rep.log(f"downloading {cand['scene_id']} ({len(cand['items'])} tiles)")
        t0 = time.monotonic()
        rgb, transform, crs = read_visual_mosaic(
            cand["items"], cand["bounds"], cand["crs"],
            on_progress=lambda f, lo=lo, span=span: rep.progress(lo + span * f, f"Downloading satellite image {f * 100:.0f}%"))
        height, width = rgb.shape[1], rgb.shape[2]
        rep.log(f"downloaded {width}x{height} px in {time.monotonic() - t0:.0f} s")
        rep.progress(lo + span, "Encoding images")
        full = render_jpeg(rgb)
        thumb = render_jpeg(rgb, max_side=640)
        paths = {"image": f"{zone.zone_id}/{cand['scene_id']}.jpg",
                 "thumb": f"{zone.zone_id}/{cand['scene_id']}_thumb.jpg",
                 "water": f"{zone.zone_id}/{cand['scene_id']}_water.png"}
        water = build_water_mask(
            cand["scl"], cand["bounds"], cand["crs"],
            (height, width), transform, crs,
        )
        water_png = encode_water_mask(water)
        if local_dir:
            out = Path(local_dir) / zone.zone_id
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{cand['scene_id']}.jpg").write_bytes(full)
            (out / f"{cand['scene_id']}_thumb.jpg").write_bytes(thumb)
            (out / f"{cand['scene_id']}_water.png").write_bytes(water_png)
        if not dry_run:
            rep.progress(lo + span, "Uploading to storage")
            image_url = upload_image(bucket, paths["image"], full)
            upload_image(bucket, paths["thumb"], thumb)
            upload_image(bucket, paths["water"], water_png, "image/png")
            insert_snapshot_row(zone, cand, paths, image_url, (width, height), crs, transform)
            result["stored"].append({"scene": cand["scene_id"], "size_px": [width, height],
                                     "image_path": paths["image"], "water_mask_path": paths["water"]})
            rep.log(f"stored {cand['scene_id']} ({width}x{height}, cloud {cand['cloud_pct']}%)")
        del rgb, full, thumb, water, water_png

    if not dry_run:
        result["pruned"] = prune_zone(zone.zone_id, settings.keep_per_zone, bucket)
    return result


def run_fetch_cycle(settings: SpatialSettings | None = None, stac_client=None,
                    zone_ids: list[str] | None = None, dry_run: bool = False,
                    local_dir: str | None = None, limit: int | None = None,
                    reporter=None) -> list[dict[str, Any]]:
    """Fetch every active zone. One zone failing never stops the others."""
    settings = settings or load_settings()
    zones = load_active_zones(zone_ids)
    if not zones:
        log.warning("No active zones found in spatial_zones (zone filter: %s)", zone_ids)
        return []
    stac_client = stac_client or Client.open(settings.stac_url)
    results = []
    for zone in zones:
        try:
            results.append(process_zone(zone, settings, stac_client, dry_run=dry_run,
                                        local_dir=local_dir, limit=limit, reporter=reporter))
        except Exception as exc:
            log.exception("[%s] fetch failed", zone.zone_id)
            results.append({"zone": zone.zone_id, "status": "error", "error": str(exc)})
    return results
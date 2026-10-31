import io
import math
from datetime import datetime, timezone

import numpy as np
import requests
from affine import Affine
from PIL import Image
from rasterio.transform import rowcol, xy
from rasterio.warp import transform as warp
from scipy import ndimage as ndi

from src import vessel_census as vc
from src.ais_client import fetch_bbox_history, parse_features
from src.ais_match import match
from src.job_reporter import Reporter
from src.spatial_config import load_active_zones
from src.supabase_client import supabase

Image.MAX_IMAGE_PIXELS = None


def to_lonlat(tr, crs, cols, rows):
    xs, ys = xy(tr, rows, cols, offset="center")
    lons, lats = warp(crs, "EPSG:4326", list(xs), list(ys))
    return np.array(lons), np.array(lats)


def build_hulls(cands, tr, crs):
    items = []
    for c in cands:
        L, W = c.length_px * vc.GSD_M, c.width_px * vc.GSD_M
        if c.wide:  # two hulls fused in one blob -> two hulls side by side
            th = math.radians(c.angle_deg)
            px, py = math.cos(th), math.sin(th)
            for sgn in (-1, 1):
                items.append((c.cx + sgn * px * c.width_px / 4, c.cy + sgn * py * c.width_px / 4,
                              L, W / 2, c.angle_deg, True))
        else:
            items.append((c.cx, c.cy, L, W, c.angle_deg, False))
    if not items:
        return []
    lons, lats = to_lonlat(tr, crs, np.array([i[0] for i in items]), np.array([i[1] for i in items]))
    return [{"id": k, "lat": float(lats[k]), "lon": float(lons[k]), "length_m": round(i[2]),
             "width_m": round(i[3]), "axis_deg": round(i[4]), "size_class": vc.size_class(i[2]),
             "pair": i[5], "col": round(i[0]), "row": round(i[1])} for k, i in enumerate(items)]


def cloud_checker(rgb, tr, crs):
    cm = ndi.binary_dilation(vc.cloud_mask(rgb)[::8, ::8], iterations=3)

    def is_cloudy(lat, lon):
        xs, ys = warp("EPSG:4326", crs, [lon], [lat])
        r, c = rowcol(tr, [xs[0]], [ys[0]])
        r, c = int(r[0]) // 8, int(c[0]) // 8
        return bool(0 <= r < cm.shape[0] and 0 <= c < cm.shape[1] and cm[r, c])
    return is_cloudy


def download_image(url, rep, lo=80, hi=88):
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total, got, buf = int(r.headers.get("content-length", 0)), 0, io.BytesIO()
        for chunk in r.iter_content(1 << 16):
            buf.write(chunk)
            got += len(chunk)
            if total:
                rep.progress(lo + (hi - lo) * got / total, f"Downloading image {100 * got / total:.0f}%")
    buf.seek(0)
    return Image.open(buf)


def analyze_latest(zone_id, rep=None, ais_json=None, image=None, write=True):
    rep = rep or Reporter(echo=False)
    zone = load_active_zones([zone_id])[0]
    snap = (supabase.table("spatial_snapshots").select("*").eq("zone_id", zone_id)
            .order("acquired_at", desc=True).limit(1).execute().data or [None])[0]
    if not snap:
        raise RuntimeError("no stored capture for this zone")
    pass_time = datetime.fromisoformat(snap["acquired_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
    tr, crs = Affine(*snap["window_transform"]), snap["crs"]

    rep.progress(80, "Loading image")
    img = Image.open(image) if image else download_image(snap["image_url"], rep)
    rgb = np.asarray(img.convert("RGB"))
    rep.progress(89, "Detecting vessels in the image")
    hulls = build_hulls(vc.propose_candidates(rgb), tr, crs)
    rep.log(f"{len(hulls)} vessels detected in the image")

    rep.progress(93, "Fetching AIS history")
    if ais_json:
        import json
        ships, credits = parse_features(json.load(open(ais_json, encoding="utf-8-sig"))), "replay"
    else:
        ships, credits = fetch_bbox_history(zone.bbox, pass_time.strftime("%Y-%m-%dT%H:%M:%SZ"))
    rep.log(f"{len(ships)} AIS ships in the feed (credits left: {credits})")

    rep.progress(96, "Comparing AIS with the image")
    res = match(hulls, ships, pass_time, is_cloudy=cloud_checker(rgb, tr, crs))
    status = {}
    for m in res["matched"]:
        status[m["hull"]] = {"status": "matched", "mmsi": m["mmsi"], "name": m["name"], "state": m["state"]}
    for m in res["displaced"]:
        status[m["hull"]] = {"status": "displaced", "mmsi": m["mmsi"], "name": m["name"], "offset_m": m["offset_m"]}
    for d in res["dark"]:
        status[d["hull"]] = {"status": "dark"}
    for h in hulls:
        h.update(status.get(h["id"], {"status": "unmatched_small" if h["length_m"] < 150 else "unknown"}))

    large = [h for h in hulls if h["length_m"] >= 150]
    large_matched = sum(1 for h in large if h["status"] == "matched")
    large_none = sum(1 for h in large if h["status"] == "dark")

    area_km2 = rgb.shape[0] * rgb.shape[1] * 1e-4
    n = len(hulls)
    summary = {
        "scene_id": snap["scene_id"], "acquired_at": snap["acquired_at"], "image_km2": round(area_km2),
        "vessels_total": n,
        "large_total": len(large), "large_matched": large_matched, "no_ais_large": large_none,
        "size_classes": {k: sum(1 for h in hulls if h["size_class"] == k) for k in ("LARGE", "MEDIUM", "SMALL")},
        "alongside_pairs": sum(1 for h in hulls if h["pair"]) // 2,
        "density_per_1000km2": round(n / area_km2 * 1000, 1),
        "ais_in_feed": len(ships), "matched": len(res["matched"]), "displaced": len(res["displaced"]),
        "ghost": len(res["ghost"]), "dark": len(res["dark"]), "stale": res["stale"],
        "not_observable": res["not_observable"], "moving_dropped": res["moving_dropped"],
        "ais_visible_pct": round(100 * len(res["matched"]) / max(n, 1)),
        "feed_coverage_large": res["feed_coverage_large"], "ais_credits_left": credits,
        "ais_note": "Voyage Radar terrestrial history; anchored ships trusted 24 h, moving 30 min",
        "method": "classical proposals (SAM refinement pending)",
    }
    rep.log(f"{n} vessels seen; {len(res['matched'])} matched to AIS in the feed; "
            f"{len(res['dark'])} dark candidates; {len(res['ghost'])} ghosts; {len(res['displaced'])} displaced")
    if write:
        rep.progress(98, "Saving results")
        supabase.table("spatial_analysis").upsert({
            "snapshot_id": snap["id"], "zone_id": zone_id, "scene_id": snap["scene_id"],
            "acquired_at": snap["acquired_at"], "summary": summary, "hulls": hulls, "flags": res,
            "method": summary["method"],
        }, on_conflict="snapshot_id").execute()
        supabase.table("spatial_snapshots").update(
            {"status": "verified", "analyzed_at": datetime.now(timezone.utc).isoformat()}).eq("id", snap["id"]).execute()
    return summary
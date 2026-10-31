from datetime import datetime

import numpy as np
from scipy.optimize import linear_sum_assignment

from src.geo_utils import dead_reckon, haversine_m

STATIONARY_KN = 1.0
BIG = 1e9


def _age_min(time_utc, pass_time):
    t = datetime.fromisoformat(time_utc.replace("Z", "+00:00"))
    return (pass_time - t).total_seconds() / 60.0


def prepare_ais(ships, pass_time, max_stationary_h=24, max_moving_min=30):
    usable, dropped = [], 0
    for s in ships:
        age = _age_min(s["time_utc"], pass_time)
        if age < 0:
            continue
        s = dict(s, age_min=age)
        if s["sog"] <= STATIONARY_KN:
            if age <= max_stationary_h * 60:
                usable.append(s)
        elif age <= max_moving_min and s.get("cog") is not None:
            s["lat"], s["lon"] = dead_reckon(s["lat"], s["lon"], s["sog"], s["cog"], age * 60)
            usable.append(s)
        else:
            dropped += 1
    return usable, dropped


def _assign(ais, hulls, radius_m):
    if not ais or not hulls:
        return []
    cost = np.full((len(ais), len(hulls)), BIG)
    for i, a in enumerate(ais):
        for j, h in enumerate(hulls):
            d = haversine_m(a["lat"], a["lon"], h["lat"], h["lon"])
            if d <= radius_m:
                cost[i, j] = d
    rows, cols = linear_sum_assignment(cost)
    return [(int(i), int(j), float(cost[i, j])) for i, j in zip(rows, cols) if cost[i, j] < BIG]


def match(hulls, ships, pass_time, is_cloudy=lambda lat, lon: False,
          match_m=600, displaced_m=3000, ghost_max_age_h=6, dark_min_len_m=150, displaced_max_age_h=6):
    """hulls: dicts with lat, lon, length_m, pair (bool). pass_time: aware datetime (UTC)."""
    ais, dropped = prepare_ais(ships, pass_time)
    pairs = _assign(ais, hulls, match_m)
    m_ais = {i for i, _, _ in pairs}
    m_hull = {j for _, j, _ in pairs}
    left_ais = [i for i in range(len(ais)) if i not in m_ais]
    left_hull = [j for j in range(len(hulls)) if j not in m_hull]
    near_ais = [i for i in left_ais if ais[i]["age_min"] <= displaced_max_age_h * 60]
    sub = _assign([ais[i] for i in near_ais], [hulls[j] for j in left_hull], displaced_m)
    displaced = [(near_ais[i], left_hull[j], d) for i, j, d in sub]
    d_ais = {i for i, _, _ in displaced}
    d_hull = {j for _, j, _ in displaced}

    out = {"matched": [], "displaced": [], "ghost": [], "dark": [], "stale": 0,
           "not_observable": 0, "moving_dropped": dropped}
    for i, j, d in pairs:
        out["matched"].append({"mmsi": ais[i]["mmsi"], "name": ais[i]["name"], "hull": j, "offset_m": round(d),
                               "state": "anchored" if ais[i]["sog"] <= STATIONARY_KN else "moving"})
    for i, j, d in displaced:
        out["displaced"].append({"mmsi": ais[i]["mmsi"], "name": ais[i]["name"], "hull": j, "offset_m": round(d)})
    for i in left_ais:
        if i in d_ais:
            continue
        a = ais[i]
        if a["age_min"] > ghost_max_age_h * 60:
            out["stale"] += 1
        elif is_cloudy(a["lat"], a["lon"]):
            out["not_observable"] += 1
        else:
            out["ghost"].append({"mmsi": a["mmsi"], "name": a["name"], "lat": a["lat"], "lon": a["lon"],
                                 "age_min": round(a["age_min"])})
    for j in left_hull:
        h = hulls[j]
        if j in d_hull or h["length_m"] < dark_min_len_m:
            continue
        if is_cloudy(h["lat"], h["lon"]):
            out["not_observable"] += 1
        else:
            out["dark"].append({"hull": j, "lat": h["lat"], "lon": h["lon"],
                                "length_m": round(h["length_m"]), "pair": bool(h.get("pair"))})
    large = [h for h in hulls if h["length_m"] >= dark_min_len_m]
    hit = len([1 for _, j, _ in pairs if hulls[j]["length_m"] >= dark_min_len_m])
    out["feed_coverage_large"] = round(hit / max(len(large), 1), 2)
    return out
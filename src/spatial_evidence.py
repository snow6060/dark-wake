"""Honest spatial evidence for Strategy Desk agents. Never invents counts."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from src.supabase_client import supabase


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

SPATIAL_GUARDRAIL = (
    "Spatial evidence is Sentinel-2 optical at 10 m per pixel. It cannot confirm cargo, "
    "flag, or ship class. Alongside pairs are candidates, not proof of transfer. Dwell is a "
    "lower bound. Unverified AIS is not proof of spoofing. Unmatched hulls matter only where "
    "AIS coverage was normal. If a zone is unavailable, say so and never fill the gap."
)


def tag_freshness(age_hours: float | None) -> str:
    return freshness_label(age_hours)


def _age_hours(acquired_at: str | None, now: datetime) -> float | None:
    if not acquired_at:
        return None
    ts = datetime.fromisoformat(acquired_at.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts.astimezone(timezone.utc)).total_seconds() / 3600.0


def format_zone_line(zone_row: dict[str, Any], now: datetime) -> str:
    name = zone_row.get("display_name") or zone_row.get("zone_id") or "Unknown zone"
    summary = zone_row.get("summary") or {}
    acquired = zone_row.get("acquired_at")
    if not summary:
        if zone_row.get("has_snapshot"):
            age = _age_hours(acquired, now)
            freshness = tag_freshness(age)
            age_txt = "unknown age" if age is None else f"{age:.0f} h old"
            cloud = zone_row.get("cloud_pct")
            cloud_txt = "cloud unknown" if cloud is None else f"{cloud:g}% cloud"
            status = zone_row.get("snapshot_status")
            state = "analysis pending" if status in {"fetched", "analyzing"} else "analysis unavailable"
            return f"{name}: capture stored ({freshness}, {age_txt}, {cloud_txt}); {state}."
        return f"{name}: unavailable (no clear scene in 25 days)."
    age = _age_hours(acquired, now)
    freshness = tag_freshness(age)
    if freshness == "EXPIRED":
        return f"{name}: unavailable (scene expired, {age:.0f} h old)."
    cloud = summary.get("cloud_pct")
    if cloud is None:
        cloud = zone_row.get("cloud_pct")
    age_txt = "unknown age" if age is None else f"{age:.0f} h old"
    cloud_txt = "cloud unknown" if cloud is None else f"{cloud:g}% cloud"
    vessels = summary.get("vessels_total")
    large = summary.get("large_total")
    matched = summary.get("large_matched")
    dark = summary.get("no_ais_large", summary.get("dark"))
    ghost = summary.get("ghost")
    displaced = summary.get("displaced")
    pairs = summary.get("alongside_pairs")
    share = round(100 * matched / large) if matched is not None and large else 0
    coverage = summary.get("feed_coverage_large")
    coverage_pct = round(100 * coverage) if coverage is not None else None
    coverage_txt = "unknown" if coverage_pct is None else f"{coverage_pct}%"
    return (
        f"{freshness} {name} (Sentinel-2, 10 m, scene {age_txt}, {cloud_txt}): "
        f"{vessels if vessels is not None else 'n/a'} vessels "
        f"({large if large is not None else 'n/a'} large); "
        f"{matched if matched is not None else 'n/a'}/{large if large is not None else 'n/a'} "
        f"large matched ({share}%; AIS feed coverage {coverage_txt}); "
        f"{dark if dark is not None else 0} large with no AIS match; "
        f"{displaced if displaced is not None else 0} displaced; "
        f"{ghost if ghost is not None else 0} ghost candidates; "
        f"{pairs if pairs is not None else 0} alongside pairs."
    )


def build_spatial_evidence(zone_rows: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    lines = [format_zone_line(row, now) for row in zone_rows]
    usable = [r for r in zone_rows if r.get("summary") and tag_freshness(_age_hours(r.get("acquired_at"), now)) != "EXPIRED"]
    ages = [a for a in (_age_hours(r.get("acquired_at"), now) for r in usable) if a is not None]
    flags = 0
    for r in usable:
        s = r.get("summary") or {}
        flags += int(s.get("dark") or 0) + int(s.get("ghost") or 0) + int(s.get("displaced") or 0)
    global_line = (
        f"{len(usable)} of {len(zone_rows)} active zones have a usable scene"
        + (f"; oldest scene {max(ages):.0f} h." if ages else ".")
        + f" Combined dark/ghost/displaced flags: {flags}."
    )
    quality = (
        "Data quality: optical 10 m Sentinel-2; AIS history coverage varies by zone. "
        "Missing zones are unavailable, not zero."
    )
    return {
        "per_zone": lines,
        "global": global_line,
        "quality": quality,
        "guardrail": SPATIAL_GUARDRAIL,
        "usable_zones": len(usable),
        "flag_count": flags,
        "singapore": next((ln for row, ln in zip(zone_rows, lines) if row.get("zone_id") == "singapore"), None),
    }


def evidence_for_agent(agent_name: str, evidence: dict[str, Any]) -> str:
    name = (agent_name or "").lower()
    if "technical" in name:
        return ""
    block = [SPATIAL_GUARDRAIL]
    if "demand" in name:
        block.extend(evidence.get("per_zone") or [])
        block.append(evidence.get("global") or "")
        block.append(evidence.get("quality") or "")
    elif "synthesis" in name or "risk" in name or "desk" in name:
        block.append(evidence.get("global") or "")
        block.append(evidence.get("quality") or "")
    else:
        block.extend(evidence.get("per_zone") or [])
        block.append(evidence.get("global") or "")
        block.append(evidence.get("quality") or "")
    return "\n".join(x for x in block if x)


def build_spatial_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "usable_zones": evidence.get("usable_zones"),
        "flag_count": evidence.get("flag_count"),
        "global": evidence.get("global"),
        "per_zone": evidence.get("per_zone"),
        "quality": evidence.get("quality"),
        "singapore": evidence.get("singapore"),
        "guardrail": SPATIAL_GUARDRAIL,
    }


def load_zone_evidence_rows() -> list[dict[str, Any]]:
    if supabase is None:
        return []
    zones = (
        supabase.table("spatial_zones")
        .select("zone_id,display_name")
        .eq("active", True)
        .order("sort_order")
        .execute()
        .data
        or []
    )
    rows = []
    for z in zones:
        zid = z["zone_id"]
        snapshots = (
            supabase.table("spatial_snapshots")
            .select("id,cloud_pct,acquired_at,status")
            .eq("zone_id", zid)
            .order("acquired_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        snap = snapshots[0] if snapshots else None
        analysis = []
        if snap:
            snaps = (
                supabase.table("spatial_analysis")
                .select("summary,acquired_at")
                .eq("snapshot_id", snap["id"])
                .limit(1)
                .execute()
                .data
                or []
            )
            analysis = snaps
        row = {
            "zone_id": zid,
            "display_name": z.get("display_name"),
            "summary": (analysis[0].get("summary") if analysis else None),
            "acquired_at": (analysis[0].get("acquired_at") if analysis else (snap or {}).get("acquired_at")),
            "cloud_pct": (snap or {}).get("cloud_pct"),
            "has_snapshot": snap is not None,
            "snapshot_status": (snap or {}).get("status"),
        }
        rows.append(row)
    return rows


def get_spatial_telemetry(chokepoint: str | None = None) -> dict[str, Any]:
    enabled = os.getenv("SPATIAL_EVIDENCE_ENABLED", "true").lower() == "true"
    if not enabled:
        return {
            "available": False,
            "message": "Spatial evidence unavailable",
            "guardrail": SPATIAL_GUARDRAIL,
        }
    try:
        evidence = build_spatial_evidence(load_zone_evidence_rows())
        return {
            "available": True,
            "evidence_text": "\n".join(evidence["per_zone"]),
            "spatial_behaviour": build_spatial_payload(evidence),
            "guardrail": SPATIAL_GUARDRAIL,
            "spatial_congestion_index": None,
        }
    except Exception as exc:
        return {
            "available": False,
            "message": f"Spatial evidence unavailable ({exc})",
            "guardrail": SPATIAL_GUARDRAIL,
            "spatial_congestion_index": None,
        }

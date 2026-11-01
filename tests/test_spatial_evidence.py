from datetime import datetime, timezone

from src.spatial_evidence import (
    SPATIAL_GUARDRAIL,
    build_spatial_evidence,
    evidence_for_agent,
    format_zone_line,
    tag_freshness,
)

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _row(zone_id, hours, large=10, matched=8, dark=1, ghost=0, displaced=0, cloud=4):
    acquired = datetime.fromtimestamp(NOW.timestamp() - hours * 3600, tz=timezone.utc).isoformat()
    return {
        "zone_id": zone_id,
        "display_name": zone_id,
        "acquired_at": acquired,
        "cloud_pct": cloud,
        "summary": {
            "large_total": large,
            "large_matched": matched,
            "no_ais_large": dark,
            "dark": dark,
            "ghost": ghost,
            "displaced": displaced,
            "cloud_pct": cloud,
        },
    }


def test_freshness_thresholds():
    assert tag_freshness(10) == "FRESH"
    assert tag_freshness(72) == "AGING"
    assert tag_freshness(200) == "STALE"
    assert tag_freshness(400) == "EXPIRED"
    assert tag_freshness(None) == "NONE"


def test_expired_omits_counts():
    line = format_zone_line(_row("kharg-island", 400), NOW)
    assert "unavailable" in line
    assert "matched" not in line


def test_empty_zone():
    line = format_zone_line({"zone_id": "kharg-island", "display_name": "Kharg"}, NOW)
    assert "unavailable" in line


def test_agent_routing():
    ev = build_spatial_evidence(
        [_row("fujairah", 20), _row("singapore", 30, dark=3)],
        NOW,
    )
    assert evidence_for_agent("Technical Analysis", ev) == ""
    demand = evidence_for_agent("Demand Thesis", ev)
    assert "singapore" in demand
    assert SPATIAL_GUARDRAIL in demand
    supply = evidence_for_agent("Supply Thesis", ev)
    assert "fujairah" in supply
    synth = evidence_for_agent("Desk Signal & Risk Synthesis", ev)
    assert "Combined" in synth or "flags" in synth.lower()

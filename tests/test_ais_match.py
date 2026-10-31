from datetime import datetime, timezone

from src.ais_match import match


PASS = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def _ship(mmsi, hours_ago, lat=25.18, lon=56.37, sog=0.2):
    t = datetime.fromtimestamp(PASS.timestamp() - hours_ago * 3600, tz=timezone.utc)
    return {
        "mmsi": mmsi,
        "name": mmsi,
        "lat": lat,
        "lon": lon,
        "sog": sog,
        "cog": 90,
        "time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def test_displaced_ignores_ais_older_than_six_hours():
    hulls = [{"lat": 25.19, "lon": 56.385, "length_m": 250, "pair": False}]
    fresh = _ship("111", 2)
    stale = _ship("222", 8)
    res = match(hulls, [fresh, stale], PASS, displaced_m=3000, match_m=50)
    assert [d["mmsi"] for d in res["displaced"]] == ["111"]
    assert res["stale"] == 1


def test_match_summary_counts_large_dark():
    hulls = [
        {"lat": 25.18, "lon": 56.37, "length_m": 250, "pair": False},
        {"lat": 25.181, "lon": 56.371, "length_m": 40, "pair": False},
    ]
    res = match(hulls, [], PASS)
    assert len(res["dark"]) == 1
    assert res["feed_coverage_large"] == 0.0

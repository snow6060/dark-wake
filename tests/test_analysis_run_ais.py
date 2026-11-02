from types import SimpleNamespace

import numpy as np

from src import analysis_run


class SupabaseQuery:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.filters = {}
        self.operation = None
        self.values = None
        self.conflict = None

    def select(self, _columns):
        self.operation = "select"
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    def update(self, values):
        self.operation = "update"
        self.values = values
        return self

    def upsert(self, values, on_conflict=None):
        self.operation = "upsert"
        self.values = values
        self.conflict = on_conflict
        return self

    def execute(self):
        if self.table_name == "spatial_snapshots" and self.operation == "select":
            return SimpleNamespace(data=[self.client.snapshot])
        if self.table_name == "spatial_analysis" and self.operation == "upsert":
            self.client.saved_analysis = self.values
            return SimpleNamespace(data=[self.values])
        return SimpleNamespace(data=[])


class FakeSupabase:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.saved_analysis = None

    def table(self, name):
        return SupabaseQuery(self, name)


def test_analysis_requests_ais_at_scene_timestamp_and_persists_vessels(monkeypatch):
    acquired_at = "2026-10-26T12:34:56Z"
    supabase = FakeSupabase({
        "id": 42,
        "zone_id": "hormuz",
        "scene_id": "scene-1",
        "acquired_at": acquired_at,
        "window_transform": [10, 0, 0, 0, -10, 0],
        "crs": "EPSG:4326",
        "image_url": "https://example.test/scene.jpg",
        "cloud_pct": 0,
    })
    events = []
    vessels = [{
        "mmsi": 123456789,
        "name": "Example Vessel",
        "lat": 26.5,
        "lon": 56.4,
        "sog": 0,
        "cog": 0,
        "ship_type": "Tanker",
        "country": "Panama",
        "flag": "PA",
        "time_utc": acquired_at,
    }]
    flags = {
        "matched": [], "displaced": [], "ghost": [], "dark": [],
        "stale": 0, "not_observable": 0, "moving_dropped": 0,
        "feed_coverage_large": 0.0,
    }

    monkeypatch.setattr(analysis_run, "supabase", supabase)
    monkeypatch.setattr(
        analysis_run,
        "load_active_zones",
        lambda _zone_ids: [SimpleNamespace(zone_id="hormuz", bbox=(56.0, 26.0, 57.0, 27.0))],
    )
    monkeypatch.setattr(analysis_run, "build_hulls", lambda *_args: [])
    monkeypatch.setattr(analysis_run.vc, "propose_candidates", lambda _rgb: [])
    monkeypatch.setattr(analysis_run, "cloud_checker", lambda *_args: lambda _lat, _lon: False)
    monkeypatch.setattr(
        analysis_run,
        "fetch_bbox_history",
        lambda bbox, at_iso: events.append(("ais", bbox, at_iso)) or (vessels, "credits", 86400),
    )
    monkeypatch.setattr(analysis_run, "match", lambda *_args, **_kwargs: dict(flags))
    monkeypatch.setattr(
        analysis_run,
        "download_image",
        lambda *_args: events.append(("image",)) or SimpleNamespace(
            convert=lambda _mode: np.zeros((2, 2, 3), dtype=np.uint8)
        ),
    )

    analysis_run.analyze_latest("hormuz", sam_enabled=False)

    assert events[0] == ("ais", (56.0, 26.0, 57.0, 27.0), acquired_at)
    assert events[1] == ("image",)
    assert supabase.saved_analysis["ais_vessels"] == vessels
    assert supabase.saved_analysis["summary"]["ais_window_s"] == 86400

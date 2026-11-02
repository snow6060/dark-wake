from types import SimpleNamespace

import pytest

from src import spatial_jobs


class StartupStateQuery:
    def __init__(self, client):
        self.client = client
        self.filters = {}
        self.values = None
        self.returning = False

    def select(self, _columns):
        self.returning = True
        return self

    def update(self, values):
        self.values = values
        self.returning = False
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, _count):
        return self

    def execute(self):
        row = self.client.row
        if all(row.get(key) == value for key, value in self.filters.items()):
            if self.values is None:
                return SimpleNamespace(data=[dict(row)])
            if self.values.get("status") == "running":
                self.client.claims += 1
            row.update(self.values)
            return SimpleNamespace(data=[dict(row)] if self.returning else [])
        return SimpleNamespace(data=[])


class StartupSupabase:
    def __init__(self):
        self.row = {
            "startup_key": "spatial_image_ais_bootstrap_v2",
            "status": "pending",
        }
        self.claims = 0

    def table(self, name):
        if name != "spatial_startup_state":
            raise AssertionError(f"Unexpected table: {name}")
        return StartupStateQuery(self)


def test_bootstrap_fetches_images_then_scene_matched_ais_once(monkeypatch):
    client = StartupSupabase()
    events = []
    monkeypatch.setattr("src.supabase_client.supabase", client)
    monkeypatch.setattr(spatial_jobs, "_fetch_missing_zones", lambda: events.append("images"))
    monkeypatch.setattr(
        spatial_jobs,
        "_analyze_latest_zones_with_live_ais",
        lambda: events.append("scene-matched-ais"),
    )

    spatial_jobs.run_startup_spatial_bootstrap()
    spatial_jobs.run_startup_spatial_bootstrap()

    assert events == ["images", "scene-matched-ais"]
    assert client.claims == 1
    assert client.row["status"] == "complete"


def test_failed_bootstrap_can_resume_on_later_startup(monkeypatch):
    client = StartupSupabase()
    events = []
    analysis_attempts = 0

    def fail_analysis():
        nonlocal analysis_attempts
        analysis_attempts += 1
        events.append("scene-matched-ais")
        if analysis_attempts == 1:
            raise RuntimeError("live AIS unavailable")

    monkeypatch.setattr("src.supabase_client.supabase", client)
    monkeypatch.setattr(spatial_jobs, "_fetch_missing_zones", lambda: events.append("images"))
    monkeypatch.setattr(spatial_jobs, "_analyze_latest_zones_with_live_ais", fail_analysis)

    with pytest.raises(RuntimeError, match="live AIS unavailable"):
        spatial_jobs.run_startup_spatial_bootstrap()
    assert client.row["status"] == "failed"
    assert "live AIS unavailable" in client.row["error"]

    spatial_jobs.run_startup_spatial_bootstrap()
    spatial_jobs.run_startup_spatial_bootstrap()

    assert events == ["images", "scene-matched-ais", "images", "scene-matched-ais"]
    assert client.claims == 2
    assert client.row["status"] == "complete"

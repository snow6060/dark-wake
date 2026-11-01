import pytest
from fastapi import HTTPException

from src import spatial_api


class ActiveZonesQuery:
    def __init__(self):
        self.zone_ids = []

    def select(self, _columns):
        return self

    def eq(self, _column, _value):
        return self

    def in_(self, _column, values):
        self.zone_ids = values
        return self

    def execute(self):
        return type("Response", (), {"data": [{"zone_id": zone_id} for zone_id in self.zone_ids]})()


class FakeSupabase:
    def table(self, _name):
        return ActiveZonesQuery()


def test_batch_route_starts_only_the_selected_active_zones(monkeypatch):
    started = []
    monkeypatch.setattr(spatial_api, "_require_supabase", lambda: FakeSupabase())
    monkeypatch.setattr(spatial_api, "start_batch_job", lambda zone_ids: started.append(zone_ids) or "job-1")

    response = spatial_api.run_zones(spatial_api.BatchRunRequest(zone_ids=["kharg", "hormuz", "kharg"]))

    assert response == {"job_id": "job-1", "zone_ids": ["kharg", "hormuz"]}
    assert started == [["kharg", "hormuz"]]


@pytest.mark.parametrize("zone_ids", [[], ["unknown-zone"]])
def test_batch_route_rejects_empty_or_unknown_zone_selection(monkeypatch, zone_ids):
    monkeypatch.setattr(spatial_api, "_require_supabase", lambda: FakeSupabase())

    with pytest.raises(HTTPException) as exc_info:
        spatial_api.run_zones(spatial_api.BatchRunRequest(zone_ids=zone_ids))

    assert exc_info.value.status_code == 422


def test_batch_route_rejects_zones_that_are_not_active(monkeypatch):
    class NoActiveZonesQuery(ActiveZonesQuery):
        def execute(self):
            return type("Response", (), {"data": []})()

    class NoActiveZonesDB:
        def table(self, _name):
            return NoActiveZonesQuery()

    monkeypatch.setattr(spatial_api, "_require_supabase", lambda: NoActiveZonesDB())

    with pytest.raises(HTTPException, match="not active") as exc_info:
        spatial_api.run_zones(spatial_api.BatchRunRequest(zone_ids=["kharg"]))

    assert exc_info.value.status_code == 422

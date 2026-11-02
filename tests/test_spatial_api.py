import pytest
from fastapi import HTTPException

from src import spatial_api


class ActiveZonesQuery:
    def __init__(self, available=("kharg", "hormuz", "singapore")):
        self.zone_ids = []
        self.available = available

    def select(self, _columns):
        return self

    def eq(self, _column, _value):
        return self

    def in_(self, _column, values):
        self.zone_ids = values
        return self

    def execute(self):
        return type("Response", (), {
            "data": [{"zone_id": zone_id} for zone_id in self.zone_ids if zone_id in self.available]
        })()


class FakeSupabase:
    def table(self, _name):
        return ActiveZonesQuery()


def test_batch_route_starts_only_the_selected_active_zones(monkeypatch):
    started = []
    monkeypatch.setattr(spatial_api, "_require_supabase", lambda: FakeSupabase())
    monkeypatch.setattr(
        spatial_api,
        "start_batch_job",
        lambda zone_ids, sam_enabled: started.append((zone_ids, sam_enabled)) or "job-1",
    )

    response = spatial_api.run_zones(spatial_api.BatchRunRequest(zone_ids=["kharg", "hormuz", "kharg"]))

    assert response == {"job_id": "job-1", "zone_ids": ["kharg", "hormuz"]}
    assert started == [(["kharg", "hormuz"], True)]


@pytest.mark.parametrize("zone_ids", [[], ["unknown-zone"]])
def test_batch_route_rejects_empty_or_unknown_zone_selection(monkeypatch, zone_ids):
    monkeypatch.setattr(spatial_api, "_require_supabase", lambda: FakeSupabase())

    with pytest.raises(HTTPException) as exc_info:
        spatial_api.run_zones(spatial_api.BatchRunRequest(zone_ids=zone_ids))

    assert exc_info.value.status_code == 422


def test_batch_route_rejects_zones_that_are_not_active(monkeypatch):
    class NoActiveZonesQuery(ActiveZonesQuery):
        def __init__(self):
            super().__init__(available=())

        def execute(self):
            return type("Response", (), {"data": []})()

    class NoActiveZonesDB:
        def table(self, _name):
            return NoActiveZonesQuery()

    monkeypatch.setattr(spatial_api, "_require_supabase", lambda: NoActiveZonesDB())

    with pytest.raises(HTTPException, match="not active") as exc_info:
        spatial_api.run_zones(spatial_api.BatchRunRequest(zone_ids=["kharg"]))

    assert exc_info.value.status_code == 422


class ZoneCreationQuery:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.values = None

    def select(self, _columns):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    def eq(self, _column, _value):
        return self

    def insert(self, values):
        self.values = values
        return self

    def execute(self):
        if self.values is not None:
            self.client.inserted.append(self.values)
            return type("Response", (), {"data": [self.values]})()
        return type("Response", (), {"data": self.client.existing})()


class ZoneCreationDB:
    def __init__(self):
        self.existing = [{"zone_id": "hormuz", "display_name": "Strait of Hormuz", "sort_order": 5}]
        self.inserted = []

    def table(self, name):
        return ZoneCreationQuery(self, name)


def test_create_zone_persists_bounding_box_and_starts_sam_analysis(monkeypatch):
    database = ZoneCreationDB()
    started = []
    monkeypatch.setattr(spatial_api, "_require_supabase", lambda: database)
    monkeypatch.setattr(
        spatial_api,
        "start_batch_job",
        lambda zone_ids, sam_enabled: started.append((zone_ids, sam_enabled)) or "job-2",
    )

    result = spatial_api.create_zone(spatial_api.CreateZoneRequest(
        display_name="Khasab Approach",
        bbox_west=56.0,
        bbox_south=25.85,
        bbox_east=56.85,
        bbox_north=26.5,
    ))

    assert result == {
        "zone_id": "custom_khasab_approach",
        "display_name": "Khasab Approach",
        "job_id": "job-2",
    }
    assert database.inserted[0]["bbox_south"] == 25.85
    assert database.inserted[0]["ref_lat"] == 26.175
    assert started == [(["custom_khasab_approach"], True)]


def test_create_zone_rejects_reversed_or_oversized_bounds(monkeypatch):
    monkeypatch.setattr(spatial_api, "_require_supabase", lambda: ZoneCreationDB())
    with pytest.raises(HTTPException, match="west/south"):
        spatial_api.create_zone(spatial_api.CreateZoneRequest(
            display_name="Invalid Bounds",
            bbox_west=57,
            bbox_south=26,
            bbox_east=56,
            bbox_north=27,
        ))
    with pytest.raises(HTTPException, match="limited to 4 degrees"):
        spatial_api.create_zone(spatial_api.CreateZoneRequest(
            display_name="Oversized Zone",
            bbox_west=50,
            bbox_south=20,
            bbox_east=55,
            bbox_north=22,
        ))

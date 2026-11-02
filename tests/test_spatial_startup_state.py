from types import SimpleNamespace

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
        self.row = {"startup_key": "live_ais_bootstrap", "status": "pending"}
        self.claims = 0

    def table(self, name):
        if name == "spatial_startup_state":
            return StartupStateQuery(self)
        if name == "spatial_snapshots":
            return StartupSnapshotQuery()
        raise AssertionError(f"Unexpected table: {name}")


class StartupSnapshotQuery:
    def select(self, _columns):
        return self

    def eq(self, _column, _value):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    def execute(self):
        return SimpleNamespace(data=[{"id": 1}])


def test_startup_live_analysis_claims_persisted_gate_once(monkeypatch):
    client = StartupSupabase()
    monkeypatch.setattr("src.supabase_client.supabase", client)
    monkeypatch.setattr("src.spatial_config.load_active_zones", lambda: [])

    spatial_jobs._run_startup_live_analysis()
    spatial_jobs._run_startup_live_analysis()

    assert client.claims == 1
    assert client.row["status"] == "complete"


def test_failed_startup_live_analysis_is_not_retried_automatically(monkeypatch):
    client = StartupSupabase()
    attempts = []

    def fail_analysis(zone_id, **_kwargs):
        attempts.append(zone_id)
        raise RuntimeError("live AIS unavailable")

    monkeypatch.setattr("src.supabase_client.supabase", client)
    monkeypatch.setattr(
        "src.spatial_config.load_active_zones",
        lambda: [SimpleNamespace(zone_id="hormuz")],
    )
    monkeypatch.setattr("src.analysis_run.analyze_latest", fail_analysis)

    spatial_jobs._run_startup_live_analysis()
    spatial_jobs._run_startup_live_analysis()

    assert attempts == ["hormuz"]
    assert client.claims == 1
    assert client.row["status"] == "failed"
    assert "live AIS unavailable" in client.row["error"]

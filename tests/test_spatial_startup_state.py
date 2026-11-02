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
        assert name == "spatial_startup_state"
        return StartupStateQuery(self)


def test_startup_live_analysis_claims_persisted_gate_once(monkeypatch):
    client = StartupSupabase()
    monkeypatch.setattr("src.supabase_client.supabase", client)
    monkeypatch.setattr("src.spatial_config.load_active_zones", lambda: [])

    spatial_jobs._run_startup_live_analysis()
    spatial_jobs._run_startup_live_analysis()

    assert client.claims == 1
    assert client.row["status"] == "complete"

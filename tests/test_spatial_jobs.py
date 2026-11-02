import threading
from types import SimpleNamespace

import pytest

from src import spatial_jobs
from src.job_reporter import Reporter


def test_batch_job_runs_zones_sequentially_and_reports_failures(monkeypatch):
    seen = []

    def process(zone_id, reporter, sam_enabled=True):
        seen.append(zone_id)
        reporter.progress(50, "fetch")
        reporter.phase = "analysis"
        reporter.progress(100, "analysis")
        if zone_id == "kharg":
            raise RuntimeError("test failure")

    monkeypatch.setattr(spatial_jobs, "_process_zone", process)
    reporter = Reporter(echo=False)

    spatial_jobs._run_batch(["hormuz", "kharg", "singapore"], reporter)

    assert seen == ["hormuz", "kharg", "singapore"]
    assert reporter.done
    assert "kharg" in reporter.error
    assert reporter.pct == 100
    assert any("test failure" in line for line in reporter.lines)


def test_batch_start_reserves_each_zone_for_one_job(monkeypatch):
    class ThreadStub:
        def __init__(self, *, target, args, daemon):
            self.target, self.args, self.daemon = target, args, daemon
            self.started = False

        def start(self):
            self.started = True

    threads = []

    def make_thread(**kwargs):
        thread = ThreadStub(**kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(spatial_jobs, "_LOCK", threading.Lock())
    monkeypatch.setattr(spatial_jobs, "_ACTIVE", {})
    monkeypatch.setattr(spatial_jobs, "JOBS", {})
    monkeypatch.setattr(spatial_jobs.threading, "Thread", make_thread)

    job_id = spatial_jobs.start_batch_job(["hormuz", "kharg", "hormuz"])

    assert spatial_jobs._ACTIVE == {"hormuz": job_id, "kharg": job_id}
    assert threads[0].started
    with pytest.raises(RuntimeError, match="hormuz"):
        spatial_jobs.start_batch_job(["hormuz"])


def test_startup_fetch_only_fetches_zones_without_snapshots(monkeypatch):
    stored = {"fujairah": True}

    class Query:
        def __init__(self, zone_id=None):
            self.zone_id = zone_id

        def select(self, _columns):
            return self

        def eq(self, _column, zone_id):
            self.zone_id = zone_id
            return self

        def order(self, *_args, **_kwargs):
            return self

        def limit(self, _count):
            return self

        def execute(self):
            rows = (
                [{"id": 1, "image_url": f"https://example.test/{self.zone_id}.jpg"}]
                if stored.get(self.zone_id)
                else []
            )
            return SimpleNamespace(data=rows)

    class FakeSupabase:
        def table(self, _name):
            return Query()

    fetched = []

    def fake_fetch(**kwargs):
        fetched.append(kwargs)
        stored["hormuz"] = True
        return [{"zone": "hormuz", "status": "ok", "stored": [{"scene": "scene"}]}]

    monkeypatch.setattr("src.supabase_client.supabase", FakeSupabase())
    monkeypatch.setattr(
        "src.spatial_config.load_active_zones",
        lambda: [SimpleNamespace(zone_id="hormuz"), SimpleNamespace(zone_id="fujairah")],
    )
    monkeypatch.setattr(
        "src.satellite_fetch.run_fetch_cycle",
        fake_fetch,
    )

    spatial_jobs._fetch_missing_zones()

    assert fetched == [{"zone_ids": ["hormuz"], "limit": 1}]


def test_startup_ais_analysis_skips_already_verified_snapshots(monkeypatch):
    class SnapshotQuery:
        def __init__(self):
            self.zone_id = None

        def select(self, _columns):
            return self

        def eq(self, _column, zone_id):
            self.zone_id = zone_id
            return self

        def order(self, *_args, **_kwargs):
            return self

        def limit(self, _count):
            return self

        def execute(self):
            return SimpleNamespace(data=[{
                "id": self.zone_id,
                "image_url": f"https://example.test/{self.zone_id}.jpg",
                "acquired_at": "2026-10-26T07:02:15Z",
                "status": "verified" if self.zone_id == "hormuz" else "fetched",
            }])

    class FakeSupabase:
        def table(self, name):
            assert name == "spatial_snapshots"
            return SnapshotQuery()

    zones = [
        SimpleNamespace(zone_id="hormuz"),
        SimpleNamespace(zone_id="fujairah"),
    ]
    analyzed = []

    monkeypatch.setattr("src.supabase_client.supabase", FakeSupabase())
    monkeypatch.setattr("src.spatial_config.load_active_zones", lambda: zones)
    monkeypatch.setattr(
        "src.analysis_run.analyze_latest",
        lambda zone_id, sam_enabled: analyzed.append((zone_id, sam_enabled)),
    )

    spatial_jobs._analyze_latest_zones_with_live_ais()

    assert analyzed == [("fujairah", True)]

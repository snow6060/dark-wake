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
    class Query:
        def __init__(self, zone_id=None):
            self.zone_id = zone_id

        def select(self, _columns):
            return self

        def eq(self, _column, zone_id):
            self.zone_id = zone_id
            return self

        def limit(self, _count):
            return self

        def execute(self):
            rows = [{"id": 1, "image_url": "https://example.test/fujairah.jpg"}] if self.zone_id == "fujairah" else []
            return SimpleNamespace(data=rows)

    class FakeSupabase:
        def table(self, _name):
            return Query()

    fetched = []
    monkeypatch.setattr("src.supabase_client.supabase", FakeSupabase())
    monkeypatch.setattr(
        "src.spatial_config.load_active_zones",
        lambda: [SimpleNamespace(zone_id="hormuz"), SimpleNamespace(zone_id="fujairah")],
    )
    monkeypatch.setattr(
        "src.satellite_fetch.run_fetch_cycle",
        lambda **kwargs: fetched.append(kwargs) or [{"zone": "hormuz", "status": "ok"}],
    )

    spatial_jobs._fetch_missing_zones()

    assert fetched == [{"zone_ids": ["hormuz"], "limit": 1}]

import asyncio

import main
import pytest


def test_spatial_bootstrap_finishes_before_other_startup_fetches(monkeypatch):
    events = []

    async def run_in_thread(function):
        events.append("bootstrap:start")
        function()
        events.append("bootstrap:complete")

    monkeypatch.setattr(main, "init_db", lambda: events.append("database"))
    monkeypatch.setattr(main.asyncio, "to_thread", run_in_thread)
    monkeypatch.setattr(main, "fetch_straits_live_chokepoint_data", lambda: events.append("straits"))
    monkeypatch.setattr(main, "fetch_straits_live_hormuz_data", lambda: events.append("hormuz"))
    monkeypatch.setattr(main, "fetch_and_store_rss_headlines", lambda: events.append("rss"))
    monkeypatch.setattr(main, "start_scheduler", lambda: events.append("scheduler"))
    monkeypatch.setattr(
        "src.spatial_jobs.run_startup_spatial_bootstrap",
        lambda: events.append("bootstrap:work"),
    )

    async def start_and_stop():
        async with main.lifespan(main.app):
            events.append("serving")

    asyncio.run(start_and_stop())

    assert events == [
        "database",
        "bootstrap:start",
        "bootstrap:work",
        "bootstrap:complete",
        "straits",
        "hormuz",
        "rss",
        "scheduler",
        "serving",
    ]


def test_spatial_bootstrap_failure_stops_backend_startup(monkeypatch):
    events = []

    async def run_in_thread(function):
        events.append("bootstrap:start")
        function()

    monkeypatch.setattr(main, "init_db", lambda: events.append("database"))
    monkeypatch.setattr(main.asyncio, "to_thread", run_in_thread)
    monkeypatch.setattr(main, "fetch_straits_live_chokepoint_data", lambda: events.append("straits"))
    monkeypatch.setattr(main, "fetch_straits_live_hormuz_data", lambda: events.append("hormuz"))
    monkeypatch.setattr(main, "fetch_and_store_rss_headlines", lambda: events.append("rss"))
    monkeypatch.setattr(main, "start_scheduler", lambda: events.append("scheduler"))

    def fail_bootstrap():
        raise RuntimeError("satellite fetch failed")

    monkeypatch.setattr(
        "src.spatial_jobs.run_startup_spatial_bootstrap",
        fail_bootstrap,
    )

    async def start_backend():
        async with main.lifespan(main.app):
            pass

    with pytest.raises(RuntimeError, match="satellite fetch failed"):
        asyncio.run(start_backend())

    assert events == ["database", "bootstrap:start"]

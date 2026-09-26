"""Runs the PortWatch ingest immediately, then on a recurring interval.

PortWatch only refreshes weekly, but polling hourly is cheap and means we
pick up new data soon after it's published without needing to guess their
exact refresh time. `upsert_rows` makes repeated runs safe (no duplicates).
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from darkwake.config import settings
from darkwake.ingest.portwatch import ingest_all

logger = logging.getLogger("darkwake.scheduler")
logging.basicConfig(level=logging.INFO)


def run_job() -> None:
    try:
        summary = ingest_all()
        logger.info("Scheduled ingest complete: %s", summary)
    except Exception:
        logger.exception("Scheduled ingest failed")


def main() -> None:
    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_job,
        trigger=IntervalTrigger(hours=settings.ingest_interval_hours),
        id="portwatch_ingest",
        next_run_time=None,  # we trigger the first run manually, below
    )
    logger.info(
        "Starting scheduler: ingest every %d hour(s)", settings.ingest_interval_hours
    )
    run_job()  # run once immediately on startup
    scheduler.start()


if __name__ == "__main__":
    main()

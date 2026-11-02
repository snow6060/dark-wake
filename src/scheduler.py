from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from src.ingestion import fetch_straits_live_chokepoint_data, fetch_and_store_rss_headlines
from src.straits_live import fetch_straits_live_hormuz_data
import os

def start_scheduler():
    scheduler = BackgroundScheduler()
    # Run chokepoint ingestion every hour
    scheduler.add_job(fetch_straits_live_chokepoint_data, 'interval', hours=1, id='straits_live_sync', replace_existing=True)
    if os.getenv("SPATIAL_FETCH_ENABLED", "false").lower() == "true":
        def _spatial_fetch():
            from src.satellite_fetch import run_fetch_cycle
            run_fetch_cycle(limit=1)
        scheduler.add_job(_spatial_fetch, 'interval', hours=6, id='spatial_snapshot_sync', replace_existing=True)
    # Refresh the free live Hormuz AIS aggregate every five minutes.
    scheduler.add_job(
        fetch_straits_live_hormuz_data,
        'interval',
        minutes=5,
        id='straits_live_hormuz_snapshot',
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5),
        max_instances=1,
        coalesce=True,
    )
    # Run RSS headline scraping every 10 minutes (regulated from 60s spam)
    scheduler.add_job(fetch_and_store_rss_headlines, 'interval', minutes=10, id='rss_fetch_job', replace_existing=True)
    scheduler.start()
    print("⏰ Background APScheduler initialized for straits.live, RSS, and spatial imagery.")
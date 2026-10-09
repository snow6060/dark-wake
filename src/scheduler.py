from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from src.ingestion import fetch_imf_chokepoint_data, fetch_and_store_rss_headlines
from src.straits_live import fetch_straits_live_hormuz_data
from src.tankermap import fetch_tankermap_chokepoint_data
from src.agents import run_debate_if_due

def start_scheduler():
    scheduler = BackgroundScheduler()
    # Run chokepoint ingestion every hour
    scheduler.add_job(fetch_imf_chokepoint_data, 'interval', hours=1, id='portwatch_sync', replace_existing=True)
    scheduler.add_job(
        fetch_tankermap_chokepoint_data,
        'interval',
        hours=1,
        id='tankermap_chokepoint_sync',
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5),
        max_instances=1,
        coalesce=True,
    )
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
    # Run RSS headline scraping every 60 seconds
    scheduler.add_job(fetch_and_store_rss_headlines, 'interval', seconds=60, id='rss_fetch_job', replace_existing=True)
    # Refresh the War Room every 12 hours at 09:00 and 21:00 London time.
    scheduler.add_job(
        run_debate_if_due,
        'cron',
        hour='9,21',
        minute=0,
        timezone='Europe/London',
        id='war_room_debate_refresh',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    print("⏰ Background APScheduler initialized for PortWatch, TankerMap, Straits.live, RSS, and War Room analysis.")
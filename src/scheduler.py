from apscheduler.schedulers.background import BackgroundScheduler
from src.ingestion import fetch_imf_chokepoint_data

def start_scheduler():
    scheduler = BackgroundScheduler()
    # Run ingestion daily or hourly (PortWatch updates weekly, hourly check is safe & idempotent)
    scheduler.add_job(fetch_imf_chokepoint_data, 'interval', hours=1, id='portwatch_sync', replace_existing=True)
    scheduler.start()
    print("⏰ Background APScheduler initialized for Chokepoint data synchronization.")
import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

from src.database import (
    ChokepointRecord,
    LiveChokepointSnapshot,
    SessionLocal,
    TankerMapDailyRecord,
    init_db,
)
from src.straits_live import STRAITS_LIVE_MAX_AGE, fetch_straits_live_hormuz_data
from src.supabase_client import supabase
from src.ingestion import (
    RSS_HEADLINE_LIMIT,
    fetch_straits_live_chokepoint_data,
    fetch_and_store_rss_headlines,
    sanitize_energy_news,
)
from src.scheduler import start_scheduler
from src.vision import fetch_and_store_daily_snapshots
from src.agents import (
    MetaModelQuotaError,
    get_recent_debates,
    run_debate_if_due,
)
from src.market_data import get_brent_market_snapshot

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Phase 1: immediate spatial ingestion if table empty
    try:
        from src.database import SessionLocal, SpatialSnapshot
        db = SessionLocal()
        count = db.query(SpatialSnapshot).count()
        db.close()
        if count == 0:
            fetch_and_store_daily_snapshots()
    except Exception:
        pass
    fetch_straits_live_chokepoint_data()
    fetch_straits_live_hormuz_data()
    fetch_and_store_rss_headlines()
    start_scheduler()
    yield

app = FastAPI(
    title="Dark Wake Strategy Desk API",
    description="Backend service for energy markets, maritime route analytics, and supply chain intelligence.",
    version="2.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.isdir("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "Oil Chokepoint Intelligence API",
        "endpoints": [
            "/api/chokepoints",
            "/api/ingest-trigger",
            "/api/run-analysis",
            "/api/market/prices",
            "/api/news/feed",
            "/api/strategy-desk/debates",
            "/api/strategy-desk/run",
        ]
    }

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/spatial/snapshots")
def get_spatial_snapshots():
    from src.database import SessionLocal, SpatialSnapshot
    db = SessionLocal()
    try:
        rows = db.query(SpatialSnapshot).order_by(SpatialSnapshot.captured_at.desc()).limit(60).all()
        return {
            "snapshots": [
                {
                    "id": r.id,
                    "location_name": r.location_name,
                    "image_url": r.image_url,
                "fallback_url": r.fallback_url,
                "captured_at": r.captured_at.isoformat() if r.captured_at else None,
            }
                for r in rows
            ],
            "rolling_window_days": 3,
            "source": "Sentinel-2 L2A / AWS Earth Search STAC",
        }
    finally:
        db.close()

@app.post("/api/spatial/fetch-now")
def trigger_spatial_fetch():
    """Manual trigger to ingest satellite snapshots immediately."""
    result = fetch_and_store_daily_snapshots()
    return result


@app.get("/api/chokepoints")
def get_chokepoints(chokepoint_name: str = None, db: Session = Depends(get_db)):
    # Straits.live is the sole live telemetry source; PortWatch/TankerMap deprecated
    try:
        live_result = fetch_straits_live_chokepoint_data()
    except Exception as exc:
        live_result = {"status": "error", "message": str(exc)}
    # Build historical array from local chokepoint_telemetry DB for chart rendering
    telemetry_query = db.query(ChokepointRecord)
    if chokepoint_name:
        telemetry_query = telemetry_query.filter(
            ChokepointRecord.chokepoint_name.like(f"%{chokepoint_name}%")
        )
    telemetry_rows = telemetry_query.order_by(ChokepointRecord.date.desc()).limit(90).all()
    historical = [
        {
            "date": str(row.date),
            "chokepoint": row.chokepoint_name,
            "tankers": row.vessel_count_tanker,
            "estimated_oil_flow": row.capacity_tanker,
            "source": getattr(row, "source", None) or "straits.live",
        }
        for row in telemetry_rows
    ]
    # Live snapshot from DB (straits.live feed)
    live_query = db.query(LiveChokepointSnapshot)
    if chokepoint_name:
        live_query = live_query.filter(
            LiveChokepointSnapshot.chokepoint_name.like(f"%{chokepoint_name}%")
        )
    now = datetime.now(timezone.utc)
    live_snapshots = {}
    for snapshot in live_query.all():
        live_snapshots[snapshot.chokepoint_name] = {
            "vessels_observed": snapshot.vessels_observed,
            "tankers_identified": snapshot.tankers_identified,
            "vessels_classified": snapshot.vessels_classified,
            "observed_at": snapshot.snapshot_at.replace(tzinfo=timezone.utc).isoformat() if snapshot.snapshot_at else None,
            "source": snapshot.source or "straits.live",
            "fresh": (now - snapshot.snapshot_at.replace(tzinfo=timezone.utc) <= timedelta(hours=2)) if snapshot.snapshot_at else False,
        }
    return {
        "count": len(historical),
        "source": "straits.live",
        "live": live_snapshots,
        "data_as_of": str(historical[0]["date"]) if historical else None,
        "data": historical,
        "straits_live_status": live_result.get("verdict_status"),
        "straits_live_transits_ma7": live_result.get("transits_ma7"),
        "message": "Telemetry from straits.live feed" if historical else "No telemetry available yet.",
    }

@app.post("/api/ingest-trigger")
def trigger_ingestion():
    result = fetch_straits_live_chokepoint_data()
    if result["status"] != "success":
        raise HTTPException(status_code=502, detail=result)
    return {"message": "Ingestion executed successfully", "details": result}

@app.post("/api/run-analysis")
def trigger_agent_analysis():
    try:
        result = run_debate_if_due()
        return {
            "status": "success",
            "timestamp": str(datetime.now()),
            "analysis": result
        }
    except MetaModelQuotaError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/strategy-desk/debates")
@app.get("/api/war-room/debates", include_in_schema=False)
def get_strategy_desk_debates():
    try:
        return get_recent_debates()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

@app.post("/api/strategy-desk/run")
@app.post("/api/war-room/run", include_in_schema=False)
def run_strategy_desk_analysis():
    try:
        return run_debate_if_due()
    except MetaModelQuotaError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


get_war_room_debates = get_strategy_desk_debates
run_war_room_debate = run_strategy_desk_analysis


@app.get("/api/market/prices")
def get_market_prices():
    try:
        return get_brent_market_snapshot()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

@app.get("/api/news/feed")
def get_news_feed():
    data = []
    supabase_error = None
    try:
        if supabase:
            response = (
                supabase.table("rss_news")
                .select("*")
                .order("created_at", desc=True)
                .limit(100)
                .execute()
            )
            data = response.data or []
    except Exception as e:
        supabase_error = e

    sanitized_data = []
    for article in data:
        title, category = sanitize_energy_news(str(article.get("title") or ""))
        summary, _ = sanitize_energy_news(str(article.get("summary") or ""))
        article["title"] = title
        article["summary"] = summary
        article["category"] = category
        if not article.get("published_at"):
            article["published_at"] = article.get("created_at")
        sanitized_data.append(article)
    data = sanitized_data
    data.sort(
        key=lambda article: article.get("published_at") or "",
        reverse=True,
    )
    if supabase_error:
        if not data:
            raise HTTPException(status_code=500, detail=str(supabase_error))
        print(f"[News Warning] Supabase feed unavailable; returning public TankerMap headlines: {supabase_error}")
    return data

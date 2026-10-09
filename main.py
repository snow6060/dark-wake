import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
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
from src.ingestion import fetch_imf_chokepoint_data, fetch_and_store_rss_headlines
from src.scheduler import start_scheduler
from src.tankermap import (
    TANKERMAP_LIVE_MAX_AGE,
    fetch_tankermap_chokepoint_data,
    get_tankermap_news,
)
from src.agents import (
    GoogleAIQuotaError,
    get_recent_debates,
    run_debate_if_due,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    fetch_imf_chokepoint_data()
    fetch_straits_live_hormuz_data()
    fetch_tankermap_chokepoint_data()
    fetch_and_store_rss_headlines()
    start_scheduler()
    yield

app = FastAPI(
    title="Oil Chokepoint Intelligence API",
    description="Backend intelligence service providing real-time chokepoint vessel tracking and multi-agent market intelligence.",
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
            "/api/war-room/debates",
            "/api/war-room/run",
        ]
    }

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/chokepoints")
def get_chokepoints(chokepoint_name: str = None, db: Session = Depends(get_db)):
    portwatch_query = db.query(ChokepointRecord)
    tankermap_query = db.query(TankerMapDailyRecord)
    if chokepoint_name:
        portwatch_query = portwatch_query.filter(
            ChokepointRecord.chokepoint_name.like(f"%{chokepoint_name}%")
        )
        tankermap_query = tankermap_query.filter(
            TankerMapDailyRecord.chokepoint_name.like(f"%{chokepoint_name}%")
        )
    portwatch_records = portwatch_query.order_by(ChokepointRecord.date.desc()).all()
    tankermap_records = tankermap_query.order_by(TankerMapDailyRecord.date.desc()).all()

    portwatch_by_name = {}
    for record in portwatch_records:
        portwatch_by_name.setdefault(record.chokepoint_name, []).append(record)
    tankermap_by_name = {}
    for record in tankermap_records:
        tankermap_by_name.setdefault(record.chokepoint_name, []).append(record)
    selected_records = []
    for name in set(portwatch_by_name) | set(tankermap_by_name):
        portwatch_latest = portwatch_by_name.get(name, [])
        tankermap_latest = tankermap_by_name.get(name, [])
        if tankermap_latest and (
            not portwatch_latest or tankermap_latest[0].date >= portwatch_latest[0].date
        ):
            selected_records.extend(
                (record, "TankerMap") for record in tankermap_latest
            )
        else:
            selected_records.extend(
                (record, "IMF PortWatch") for record in portwatch_latest
            )
    selected_records.sort(key=lambda item: item[0].date, reverse=True)

    live_query = db.query(LiveChokepointSnapshot)
    if chokepoint_name:
        live_query = live_query.filter(
            LiveChokepointSnapshot.chokepoint_name.like(f"%{chokepoint_name}%")
        )
    now = datetime.now(timezone.utc)
    max_age_by_source = {
        "Straits.live": STRAITS_LIVE_MAX_AGE,
        "TankerMap": TANKERMAP_LIVE_MAX_AGE,
    }
    live_snapshots = {
        snapshot.chokepoint_name: {
            "vessels_observed": snapshot.vessels_observed,
            "tankers_identified": snapshot.tankers_identified,
            "vessels_classified": snapshot.vessels_classified,
            "observed_at": snapshot.snapshot_at.replace(tzinfo=timezone.utc).isoformat(),
            "capture_seconds": snapshot.capture_seconds,
            "source": snapshot.source,
            "fresh": (
                now - snapshot.snapshot_at.replace(tzinfo=timezone.utc)
                <= max_age_by_source.get(snapshot.source, timedelta(0))
            ),
        }
        for snapshot in live_query.all()
    }
    
    if not selected_records:
        return {
            "data": [],
            "source": "TankerMap / IMF PortWatch",
            "live": live_snapshots,
            "message": "No chokepoint records are available yet.",
        }

    sources = sorted({source for _, source in selected_records})
    latest_dates = [record.date for record, _ in selected_records]
    return {
        "count": len(selected_records),
        "source": sources[0] if len(sources) == 1 else "Multiple sources",
        "live": live_snapshots,
        "data_as_of": str(max(latest_dates)),
        "portwatch_data_as_of": (
            str(max(record.date for record in portwatch_records))
            if portwatch_records
            else None
        ),
        "data": [
            (
                {
                    "date": str(record.date),
                    "chokepoint": record.chokepoint_name,
                    "total_vessels": None,
                    "tankers": record.vessel_count_total,
                    "total_tanker_transits": record.vessel_count_total,
                    "containers": None,
                    "capacity_tanker": None,
                    "estimated_oil_flow_million_bbl": None,
                    "tanker_breakdown": {
                        "lng": record.vessel_count_lng,
                        "crude": record.vessel_count_crude,
                        "product": record.vessel_count_product,
                    },
                    "baseline_avg": None,
                    "deviation_pct": None,
                    "source": source,
                }
                if source == "TankerMap"
                else {
                    "date": str(record.date),
                    "chokepoint": record.chokepoint_name,
                    "total_vessels": record.vessel_count_total,
                    "tankers": record.vessel_count_tanker,
                    "containers": record.vessel_count_container,
                    "capacity_tanker": record.capacity_tanker,
                    "estimated_oil_flow_million_bbl": (
                        record.capacity_tanker * 7.33 / 1_000_000
                    ) if record.capacity_tanker is not None else None,
                    "baseline_avg": record.baseline_avg,
                    "deviation_pct": record.deviation_pct,
                    "source": source,
                }
            )
            for record, source in selected_records
        ]
    }

@app.post("/api/ingest-trigger")
def trigger_ingestion():
    result = fetch_imf_chokepoint_data()
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
    except GoogleAIQuotaError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/war-room/debates")
def get_war_room_debates():
    try:
        run_debate_if_due()
        return get_recent_debates()
    except GoogleAIQuotaError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/war-room/run")
def run_war_room_debate():
    try:
        return run_debate_if_due()
    except GoogleAIQuotaError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/market/prices")
def get_market_prices():
    try:
        brent = yf.Ticker("BZ=F")
        hist = brent.history(period="1d", interval="5m")

        if hist.empty:
            hist = brent.history(period="2d")

        if not hist.empty:
            current_price = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[0]) if len(hist) > 1 else current_price
            change_pct = ((current_price - prev_close) / prev_close) * 100 if prev_close else 0.0

            price_history = []
            for idx, row in hist.tail(12).iterrows():
                time_str = idx.strftime("%I:%M %p")
                price_history.append({"time": time_str, "price": round(float(row["Close"]), 2)})
        else:
            current_price = 100.95
            change_pct = -0.61
            price_history = [
                { "time": "02:00 AM", "price": 100.50 },
                { "time": "03:00 AM", "price": 100.95 }
            ]

        return {
            "symbol": "BrentCash (BZ=F)",
            "price": round(current_price, 2),
            "change_pct": round(change_pct, 2),
            "history": price_history
        }
    except Exception as e:
        return {"error": str(e), "price": 100.95, "change_pct": -0.61, "history": []}

@app.get("/api/news/feed")
def get_news_feed():
    data = []
    supabase_error = None
    try:
        if supabase:
            response = supabase.table("rss_news").select("*").limit(50).execute()
            data = response.data or []
    except Exception as e:
        supabase_error = e

    data.extend(get_tankermap_news())
    for article in data:
        if not article.get("published_at"):
            article["published_at"] = article.get("created_at")
    data.sort(
        key=lambda article: article.get("published_at") or "",
        reverse=True,
    )
    if supabase_error:
        if not data:
            raise HTTPException(status_code=500, detail=str(supabase_error))
        print(f"[News Warning] Supabase feed unavailable; returning public TankerMap headlines: {supabase_error}")
    return data
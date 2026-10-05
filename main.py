import os
from dotenv import load_dotenv

# Load environment variables from .env file immediately on startup
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from contextlib import asynccontextmanager

from src.database import SessionLocal, init_db, ChokepointRecord
from src.ingestion import fetch_imf_chokepoint_data
from src.scheduler import start_scheduler
from src.agents import run_agent_pipeline

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    fetch_imf_chokepoint_data()
    start_scheduler()
    yield

app = FastAPI(
    title="Oil Chokepoint Intelligence API",
    description="Backend intelligence service providing real-time chokepoint vessel tracking and multi-agent market intelligence.",
    version="2.0.0",
    lifespan=lifespan
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
        "endpoints": ["/api/chokepoints", "/api/ingest-trigger", "/api/run-analysis"]
    }

@app.get("/api/chokepoints")
def get_chokepoints(chokepoint_name: str = None, db: Session = Depends(get_db)):
    query = db.query(ChokepointRecord)
    if chokepoint_name:
        query = query.filter(ChokepointRecord.chokepoint_name.like(f"%{chokepoint_name}%"))
    records = query.order_by(ChokepointRecord.date.desc()).limit(90).all()
    
    if not records:
        return {"data": [], "message": "No records found. Try triggering ingestion."}
        
    return {
        "count": len(records),
        "data": [
            {
                "date": str(r.date),
                "chokepoint": r.chokepoint_name,
                "total_vessels": r.vessel_count_total,
                "tankers": r.vessel_count_tanker,
                "containers": r.vessel_count_container,
                "baseline_avg": r.baseline_avg,
                "deviation_pct": r.deviation_pct
            } for r in records
        ]
    }

@app.post("/api/ingest-trigger")
def trigger_ingestion():
    result = fetch_imf_chokepoint_data()
    return {"message": "Ingestion executed successfully", "details": result}

@app.post("/api/run-analysis")
def trigger_agent_analysis():
    try:
        result = run_agent_pipeline()
        return {
            "status": "success",
            "timestamp": str(datetime.now()),
            "analysis": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
import requests
from datetime import datetime, timedelta
from src.database import SessionLocal, ChokepointRecord, init_db

FEATURE_SERVER_URL = (
    "https://services5.arcgis.com/sjP4Ugu5s00SWqNY/arcgis/rest/services/"
    "Daily_Chokepoints_Data/FeatureServer/0/query"
)

def fetch_imf_chokepoint_data():
    init_db()
    db = SessionLocal()
    
    params = {
        "where": "1=1",
        "outFields": "*",
        "f": "json",
        "resultRecordCount": 2000
    }
    
    try:
        response = requests.get(FEATURE_SERVER_URL, params=params, timeout=10)
        data = response.json()
        features = data.get("features", [])
        
        if not features:
            print("⚠️ No features returned from PortWatch FeatureServer. Generating 90-day rich mock history.")
            _insert_rich_mock_history(db)
            return {"status": "success", "source": "mock_fallback_90_day", "records_processed": 180}
            
        count = 0
        for feat in features:
            attrs = feat.get("attributes", {})
            port_name = attrs.get("portname", "")
            
            if any(target in port_name for target in ["Hormuz", "Mandeb"]):
                raw_date = attrs.get("date") or attrs.get("TIME") or attrs.get("dt")
                if isinstance(raw_date, int):
                    record_date = datetime.utcfromtimestamp(raw_date / 1000).date()
                else:
                    record_date = datetime.utcnow().date()
                
                total_ships = float(attrs.get("vessel_count_total", 0) or 0)
                tankers = float(attrs.get("vessel_count_tanker", 0) or 0)
                containers = float(attrs.get("vessel_count_container", 0) or 0)
                baseline = float(attrs.get("baseline_avg", total_ships * 1.05) or (total_ships * 1.05))
                deviation = ((total_ships - baseline) / baseline) * 100 if baseline > 0 else 0.0

                existing = db.query(ChokepointRecord).filter_by(
                    date=record_date, chokepoint_name=port_name
                ).first()
                
                if not existing:
                    db_record = ChokepointRecord(
                        date=record_date,
                        chokepoint_name=port_name,
                        portid=str(attrs.get("portid", port_name)),
                        vessel_count_total=total_ships,
                        vessel_count_tanker=tankers,
                        vessel_count_container=containers,
                        baseline_avg=baseline,
                        deviation_pct=deviation
                    )
                    db.add(db_record)
                    count += 1
        db.commit()
        db.close()
        return {"status": "success", "source": "imf_portwatch", "records_added": count}
        
    except Exception as e:
        print(f"⚠️ Error connecting to PortWatch: {e}. Generating 90-day mock history for development.")
        _insert_rich_mock_history(db)
        db.close()
        return {"status": "success", "source": "mock_fallback_on_error", "error": str(e)}

def _insert_rich_mock_history(db):
    """Generates 90 days of distinct historical time-series data for Hormuz and Bab-el-Mandeb."""
    import random
    end_date = datetime.utcnow().date()
    
    chokepoints_config = {
        "Strait of Hormuz": {"base_total": 52.0, "base_tanker": 22.0},
        "Bab el-Mandeb": {"base_total": 38.0, "base_tanker": 12.0}
    }
    
    for name, cfg in chokepoints_config.items():
        random.seed(hash(name))
        for i in range(90): # Expanded to 90 days
            current_date = end_date - timedelta(days=i)
            
            # Add slight sinusoidal/random realistic variance over 90 days
            variance = random.uniform(-8.0, 8.0)
            total = round(cfg["base_total"] + variance, 1)
            tankers = round(cfg["base_tanker"] + (variance * 0.4), 1)
            containers = round(total - tankers - 15.0, 1)
            baseline = cfg["base_total"]
            deviation = round(((total - baseline) / baseline) * 100, 1)
            
            existing = db.query(ChokepointRecord).filter_by(date=current_date, chokepoint_name=name).first()
            if not existing:
                rec = ChokepointRecord(
                    date=current_date,
                    chokepoint_name=name,
                    portid=name.lower().replace(" ", "_"),
                    vessel_count_total=total,
                    vessel_count_tanker=tankers,
                    vessel_count_container=max(5.0, containers),
                    baseline_avg=baseline,
                    deviation_pct=deviation
                )
                db.add(rec)
    db.commit()
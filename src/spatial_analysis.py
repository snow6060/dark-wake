import os
from sqlalchemy import create_engine, text
from src.geo_utils import dead_reckon, point_in_polygon

def analyze_snapshot(snapshot_id):
    engine = create_engine(os.getenv("DATABASE_URL"))
    with engine.connect() as conn:
        snap = conn.execute(text("SELECT * FROM satellite_snapshots WHERE id = :sid"), {"sid": snapshot_id}).mappings().first()
        zone = conn.execute(text("SELECT * FROM zones WHERE id = :zid"), {"zid": snap["zone_id"]}).mappings().first()
        vessels = conn.execute(text("SELECT * FROM public.vessels WHERE zone_id = :zid"), {"zid": zone["id"]}).mappings().all()
        for v in vessels:
            pred_lat, pred_lon = dead_reckon(v["last_lat"], v["last_lon"], v["sog"], v["cog"], 3600)
            if point_in_polygon(pred_lat, pred_lon, zone["polygon"]):
                status = "VERIFIED"
            else:
                status = "NO_VESSEL_AT_CLAIM"
            conn.execute(text("INSERT INTO vessel_verifications (snapshot_id, vessel_id, status) VALUES (:sid,:vid,:st)"),
                         {"sid": snapshot_id, "vid": v["mmsi"], "st": status})
        conn.execute(text("INSERT INTO unmatched_detections (snapshot_id, lat, lon) SELECT :sid, lat, lon FROM detections WHERE snapshot_id = :sid"),
                     {"sid": snapshot_id})
        conn.execute(text("INSERT INTO spatial_zone_summaries (zone_id, verified, mismatched, not_observable) VALUES (:zid, (SELECT COUNT(*) FROM vessel_verifications WHERE snapshot_id = :sid AND status = 'VERIFIED'), 0, 0)"),
                     {"zid": zone["id"], "sid": snapshot_id})
        conn.commit()

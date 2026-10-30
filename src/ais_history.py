import os
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta

def fetch_and_store_ais_for_zone(zone, window_hours=24):
    engine = create_engine(os.getenv("DATABASE_URL"))
    bbox = zone.get("bbox")
    since = datetime.utcnow() - timedelta(hours=window_hours)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM ais_feed WHERE bbox && ST_MakeEnvelope(:minx,:miny,:maxx,:maxy,4326) AND ts > :since"),
                              {"minx": bbox[0], "miny": bbox[1], "maxx": bbox[2], "maxy": bbox[3], "since": since})
        for row in result:
            conn.execute(text("INSERT INTO public.ais_positions (mmsi, lat, lon, ts, speed) VALUES (:mmsi,:lat,:lon,:ts,:speed) ON CONFLICT DO NOTHING"),
                         dict(row._mapping))
        conn.execute(text("UPDATE public.vessels SET length_m = :l, beam_m = :b, imo = :imo, callsign = :cs WHERE mmsi = :mmsi"),
                     {"l": zone.get("length_m"), "b": zone.get("beam_m"), "imo": zone.get("imo"), "cs": zone.get("callsign"), "mmsi": zone.get("mmsi")})
        conn.commit()

def purge_old_ais_positions(keep_days=4):
    engine = create_engine(os.getenv("DATABASE_URL"))
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM public.ais_positions WHERE ts < NOW() - INTERVAL ':days days'"), {"days": keep_days})
        conn.commit()

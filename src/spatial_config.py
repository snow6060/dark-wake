import os
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine, text

class SpatialSettings(BaseSettings):
    zone_buffer_m: float = float(os.getenv("ZONE_BUFFER_M", "500"))
    active_zone_table: str = os.getenv("ACTIVE_ZONE_TABLE", "zones")
    class Config:
        env_prefix = "SPATIAL_"

def load_active_zones(db_url: str = None):
    url = db_url or os.getenv("DATABASE_URL")
    engine = create_engine(url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT zone_id, geom FROM zones WHERE active = 1"))
        return [dict(row._mapping) for row in result]

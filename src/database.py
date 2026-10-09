import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, UniqueConstraint, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = os.getenv("DATABASE_URL", "sqlite:///oil_intelligence.db")

connect_args = {"check_same_thread": False} if DB_PATH.startswith("sqlite") else {}
engine = create_engine(DB_PATH, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ChokepointRecord(Base):
    __tablename__ = "chokepoint_daily"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)
    chokepoint_name = Column(String, nullable=False) # e.g. "Strait of Hormuz"
    portid = Column(String, nullable=False)
    vessel_count_total = Column(Float, default=0.0)
    vessel_count_tanker = Column(Float, default=0.0)
    vessel_count_container = Column(Float, default=0.0)
    capacity_tanker = Column(Float, default=0.0)
    baseline_avg = Column(Float, default=0.0)
    deviation_pct = Column(Float, default=0.0)

    __table_args__ = (
        UniqueConstraint('date', 'chokepoint_name', name='uq_date_chokepoint'),
    )


class LiveChokepointSnapshot(Base):
    __tablename__ = "chokepoint_live_snapshot"

    id = Column(Integer, primary_key=True, index=True)
    chokepoint_name = Column(String, nullable=False, unique=True)
    vessels_observed = Column(Integer, nullable=True)
    tankers_identified = Column(Integer, nullable=True)
    vessels_classified = Column(Integer, nullable=False, default=0)
    source = Column(String, nullable=False, default="TankerMap")
    active_window_minutes = Column(Integer, nullable=True)
    snapshot_at = Column(DateTime, nullable=False)
    capture_seconds = Column(Integer, nullable=False)


class TankerMapDailyRecord(Base):
    __tablename__ = "tankermap_chokepoint_daily"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)
    chokepoint_name = Column(String, nullable=False)
    vessel_count_total = Column(Float, nullable=False)
    vessel_count_lng = Column(Float, nullable=False)
    vessel_count_crude = Column(Float, nullable=False)
    vessel_count_product = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("date", "chokepoint_name", name="uq_tankermap_date_chokepoint"),
    )


def init_db():
    Base.metadata.create_all(bind=engine)
    columns = {column["name"] for column in inspect(engine).get_columns("chokepoint_daily")}
    if "capacity_tanker" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE chokepoint_daily ADD COLUMN capacity_tanker FLOAT DEFAULT 0.0")
            )
    snapshot_columns = {
        column["name"]
        for column in inspect(engine).get_columns("chokepoint_live_snapshot")
    } if inspect(engine).has_table("chokepoint_live_snapshot") else set()
    if "source" not in snapshot_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE chokepoint_live_snapshot ADD COLUMN source VARCHAR DEFAULT 'TankerMap'")
            )
    if "active_window_minutes" not in snapshot_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE chokepoint_live_snapshot ADD COLUMN active_window_minutes INTEGER")
            )
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM chokepoint_live_snapshot WHERE source = 'AISStream'")
        )
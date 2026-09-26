import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = "sqlite:///oil_intelligence.db"

engine = create_engine(DB_PATH, connect_args={"check_same_thread": False})
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
    baseline_avg = Column(Float, default=0.0)
    deviation_pct = Column(Float, default=0.0)

    __table_args__ = (
        UniqueConstraint('date', 'chokepoint_name', name='uq_date_chokepoint'),
    )

def init_db():
    Base.metadata.create_all(bind=engine)
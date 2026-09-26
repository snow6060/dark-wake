"""SQLite storage layer, written to make a later Postgres swap painless.

Everything DB-specific lives behind `get_engine()` / `SessionLocal` and the
declarative models below. Swapping to Postgres later should only mean
changing `DATABASE_URL` (plus, if we want native upsert speed, swapping the
`sqlite`-dialect `insert()` in ingest/portwatch.py for the `postgresql`
one — noted there).
"""
from __future__ import annotations

import datetime as dt
import os

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from darkwake.config import settings


class Base(DeclarativeBase):
    pass


class ChokepointTransit(Base):
    """One row = one chokepoint on one date."""

    __tablename__ = "chokepoint_transits"
    __table_args__ = (
        UniqueConstraint("chokepoint_key", "date", name="uq_chokepoint_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Our internal key, e.g. "hormuz" — see config.py's chokepoint registry.
    chokepoint_key: Mapped[str] = mapped_column(String(64), index=True)
    # Raw portname as returned by PortWatch, kept for traceability.
    portname: Mapped[str] = mapped_column(String(255))

    date: Mapped[dt.date] = mapped_column(Date, index=True)

    n_container: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_dry_bulk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_general_cargo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_roro: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_tanker: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_cargo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_total: Mapped[int | None] = mapped_column(Integer, nullable=True)

    capacity_tanker: Mapped[float | None] = mapped_column(Float, nullable=True)
    capacity: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Computed at ingest time: (n_total - baseline) / baseline, using the
    # trailing mean of n_total for this chokepoint up to (and excluding)
    # this date. Null until enough history exists.
    baseline_n_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    deviation_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    ingested_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime,
        default=lambda: dt.datetime.now(dt.timezone.utc),
        onupdate=lambda: dt.datetime.now(dt.timezone.utc),
    )


def get_engine():
    db_url = settings.database_url
    if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:////"):
        # Relative sqlite path: make sure the parent dir exists.
        rel_path = db_url.replace("sqlite:///", "", 1)
        parent = os.path.dirname(rel_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    return create_engine(db_url, connect_args=connect_args)


engine = get_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
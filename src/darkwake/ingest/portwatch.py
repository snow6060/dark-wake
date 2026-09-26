"""Ingest daily chokepoint transit data from the IMF PortWatch
`Daily_Chokepoints_Data` ArcGIS FeatureServer.

Design notes:
- We match chokepoints by a `portname` substring instead of a hardcoded
  `portid`, since PortWatch hasn't published a documented, stable portid
  list for this table (see config.py). Adding a chokepoint later is a
  one-line registry edit, no ingestion-logic change.
- The FeatureServer caps `resultRecordCount` at 1000, so we page with
  `resultOffset` until a page comes back short.
- Upserts are keyed on (chokepoint_key, date) so re-running the job never
  creates duplicate rows — safe to run hourly against a weekly-refresh feed.
- Baseline/deviation are recomputed per chokepoint after each ingest run,
  using the trailing mean of `n_total` for all *prior* dates on file for
  that chokepoint. This is intentionally simple for Phase 1 (no seasonal
  adjustment) and cheap to redo in full each run.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import requests
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from darkwake.config import settings
from darkwake.db import ChokepointTransit, SessionLocal, init_db

logger = logging.getLogger("darkwake.ingest.portwatch")
logging.basicConfig(level=logging.INFO)

PAGE_SIZE = 1000
REQUEST_TIMEOUT = 30


def _name_filter_clause(name_fragments: list[str]) -> str:
    ors = " OR ".join(f"UPPER(portname) LIKE '%{frag.upper()}%'" for frag in name_fragments)
    return f"({ors})"


def _fetch_rows(where: str) -> list[dict[str, Any]]:
    """Page through the FeatureServer query endpoint for a given WHERE clause."""
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "where": where,
            "outFields": "*",
            "orderByFields": "date ASC",
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
            "f": "json",
        }
        resp = requests.get(settings.portwatch_url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        if "error" in payload:
            raise RuntimeError(f"PortWatch API error: {payload['error']}")

        features = payload.get("features", [])
        rows.extend(f["attributes"] for f in features)

        if len(features) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return rows


def _parse_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # ArcGIS date fields commonly serialize as epoch milliseconds.
        return dt.datetime.fromtimestamp(value / 1000, tz=dt.timezone.utc).date()
    if isinstance(value, str):
        # DateOnly fields can come back as "YYYY-MM-DD" or a full ISO string.
        return dt.date.fromisoformat(value[:10])
    raise ValueError(f"Unrecognized date value: {value!r}")


def fetch_chokepoint(chokepoint_key: str, name_fragments: list[str]) -> list[dict[str, Any]]:
    cutoff = dt.date.today() - dt.timedelta(days=settings.lookback_days)
    name_clause = _name_filter_clause(name_fragments)

    # The `date` field is esriFieldTypeDateOnly; ArcGIS's accepted literal
    # syntax for that has varied across service versions (`DATE 'YYYY-MM-DD'`
    # vs `TIMESTAMP 'YYYY-MM-DD HH:MI:SS'`). We haven't been able to hit this
    # FeatureServer from the build sandbox to pin down which one this
    # instance wants, so we try both and, failing that, fall back to pulling
    # by name only and trimming to `lookback_days` client-side.
    candidate_wheres = [
        f"{name_clause} AND date >= DATE '{cutoff.isoformat()}'",
        f"{name_clause} AND date >= TIMESTAMP '{cutoff.isoformat()} 00:00:00'",
        name_clause,
    ]

    raw_rows: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for where in candidate_wheres:
        try:
            raw_rows = _fetch_rows(where)
            logger.info("Fetching %s (where=%s)", chokepoint_key, where)
            break
        except Exception as exc:  # noqa: BLE001 - deliberately broad, we try next candidate
            last_error = exc
            logger.warning("Query failed for %s with where=%r: %s", chokepoint_key, where, exc)
    else:
        raise RuntimeError(
            f"All WHERE-clause variants failed for {chokepoint_key}"
        ) from last_error

    if where == name_clause:
        # Client-side trim since we couldn't push the date filter down.
        raw_rows = [
            r for r in raw_rows if (d := _parse_date(r.get("date"))) and d >= cutoff
        ]

    logger.info("Fetched %d raw rows for %s", len(raw_rows), chokepoint_key)

    parsed = []
    for r in raw_rows:
        date = _parse_date(r.get("date"))
        if date is None:
            continue
        parsed.append(
            {
                "chokepoint_key": chokepoint_key,
                "portname": r.get("portname") or "",
                "date": date,
                "n_container": r.get("n_container"),
                "n_dry_bulk": r.get("n_dry_bulk"),
                "n_general_cargo": r.get("n_general_cargo"),
                "n_roro": r.get("n_roro"),
                "n_tanker": r.get("n_tanker"),
                "n_cargo": r.get("n_cargo"),
                "n_total": r.get("n_total"),
                "capacity_tanker": r.get("capacity_tanker"),
                "capacity": r.get("capacity"),
            }
        )
    return parsed


def upsert_rows(rows: list[dict[str, Any]]) -> int:
    """Idempotent insert-or-update keyed on (chokepoint_key, date)."""
    if not rows:
        return 0
    with SessionLocal() as session:
        stmt = sqlite_insert(ChokepointTransit).values(rows)
        update_cols = {
            c.name: getattr(stmt.excluded, c.name)
            for c in ChokepointTransit.__table__.columns
            if c.name not in ("id", "chokepoint_key", "date", "ingested_at")
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["chokepoint_key", "date"],
            set_=update_cols,
        )
        session.execute(stmt)
        session.commit()
    return len(rows)


def recompute_baseline(chokepoint_key: str) -> None:
    """Recompute trailing-mean baseline & deviation for every stored row of
    this chokepoint, using only prior dates' n_total for each row's baseline.
    """
    with SessionLocal() as session:
        records = (
            session.execute(
                select(ChokepointTransit)
                .where(ChokepointTransit.chokepoint_key == chokepoint_key)
                .order_by(ChokepointTransit.date.asc())
            )
            .scalars()
            .all()
        )

        history: list[float] = []
        for rec in records:
            if history:
                baseline = sum(history) / len(history)
                rec.baseline_n_total = baseline
                rec.deviation_pct = (
                    ((rec.n_total - baseline) / baseline) if (rec.n_total and baseline) else None
                )
            else:
                rec.baseline_n_total = None
                rec.deviation_pct = None
            if rec.n_total is not None:
                history.append(rec.n_total)

        session.commit()


def ingest_all() -> dict[str, int]:
    init_db()
    results: dict[str, int] = {}
    for key, fragments in settings.chokepoints.items():
        rows = fetch_chokepoint(key, fragments)
        count = upsert_rows(rows)
        recompute_baseline(key)
        results[key] = count
        logger.info("Upserted %d rows for %s", count, key)
    return results


if __name__ == "__main__":
    summary = ingest_all()
    logger.info("Ingest complete: %s", summary)

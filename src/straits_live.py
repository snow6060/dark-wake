from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from src.database import LiveChokepointSnapshot, SessionLocal, init_db

STRAITS_LIVE_VESSELS_URL = "https://straits.live/api/v1/vessels"
STRAITS_LIVE_REGION = "hormuz"
STRAITS_LIVE_MAX_AGE = timedelta(minutes=10)


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Straits.live response is missing its asOf timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Straits.live returned an invalid asOf timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError("Straits.live asOf timestamp must include a timezone.")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"Straits.live returned an invalid {field} count.")
    return int(value)


def _parse_vessel_snapshot(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Straits.live returned an invalid response.")
    if payload.get("degraded") is True:
        raise RuntimeError(
            f"Straits.live vessel data is degraded: {payload.get('degradedNote') or 'unspecified'}"
        )

    by_region = payload.get("byRegion")
    by_type = payload.get("byType")
    if not isinstance(by_region, dict) or not isinstance(by_type, dict):
        raise ValueError("Straits.live response is missing vessel breakdowns.")
    if _nonnegative_int(by_region.get(STRAITS_LIVE_REGION), "Hormuz region") != _nonnegative_int(
        payload.get("count"), "total"
    ):
        raise ValueError("Straits.live region count does not match its total count.")

    type_counts = {
        name: _nonnegative_int(by_type.get(name), name)
        for name in ("tanker", "cargo", "military", "other")
    }
    active_window = _nonnegative_int(
        payload.get("activeWindowMinutes"),
        "active-window",
    )
    if active_window == 0:
        raise ValueError("Straits.live returned a zero-length active window.")

    return {
        "vessels_observed": _nonnegative_int(payload.get("count"), "total"),
        "tankers_identified": type_counts["tanker"],
        "vessels_classified": sum(type_counts.values()),
        "active_window_minutes": active_window,
        "snapshot_at": _parse_timestamp(payload.get("asOf")),
    }


def fetch_straits_live_hormuz_data() -> dict[str, Any]:
    """Fetch and persist Straits.live's live AIS vessel count for the Hormuz region."""
    try:
        response = requests.get(
            STRAITS_LIVE_VESSELS_URL,
            params={"region": STRAITS_LIVE_REGION},
            headers={"Accept": "application/json", "User-Agent": "DarkWake/1.0"},
            timeout=(5, 15),
        )
        response.raise_for_status()
        snapshot_data = _parse_vessel_snapshot(response.json())
    except (requests.RequestException, ValueError, RuntimeError) as error:
        message = f"Straits.live update failed; existing snapshot was preserved: {error}"
        print(f"[Straits.live Error] {message}")
        return {
            "status": "error",
            "source": "Straits.live",
            "message": str(error),
        }

    init_db()
    db = SessionLocal()
    try:
        snapshot = db.query(LiveChokepointSnapshot).filter_by(
            chokepoint_name="Strait of Hormuz"
        ).one_or_none()
        values = {
            "vessels_observed": snapshot_data["vessels_observed"],
            "tankers_identified": snapshot_data["tankers_identified"],
            "vessels_classified": snapshot_data["vessels_classified"],
            "source": "Straits.live",
            "active_window_minutes": snapshot_data["active_window_minutes"],
            "snapshot_at": snapshot_data["snapshot_at"],
            "capture_seconds": 0,
        }
        if snapshot is None:
            db.add(LiveChokepointSnapshot(
                chokepoint_name="Strait of Hormuz",
                **values,
            ))
        else:
            for field, value in values.items():
                setattr(snapshot, field, value)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return {
        "status": "success",
        "source": "Straits.live",
        "chokepoint": "Strait of Hormuz",
        "vessels_observed": snapshot_data["vessels_observed"],
        "tankers_identified": snapshot_data["tankers_identified"],
        "vessels_classified": snapshot_data["vessels_classified"],
        "active_window_minutes": snapshot_data["active_window_minutes"],
        "as_of": snapshot_data["snapshot_at"].replace(tzinfo=timezone.utc).isoformat(),
    }

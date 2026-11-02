from datetime import datetime, timedelta, timezone
import threading
import uuid
import logging

from src.job_reporter import Reporter

log = logging.getLogger(__name__)

JOBS: dict[str, Reporter] = {}
_ACTIVE: dict[str, str] = {}
_LOCK = threading.Lock()
_WORK_LOCK = threading.Lock()
_STARTUP_BOOTSTRAP_KEY = "spatial_image_ais_bootstrap_v2"
_STARTUP_LEASE_HEARTBEAT_SECONDS = 20
_STARTUP_LEASE_TIMEOUT = timedelta(minutes=2)


class _BatchReporter:
    def __init__(self, reporter, zone_id, start_pct, span_pct):
        self.reporter = reporter
        self.zone_id = zone_id
        self.start_pct = start_pct
        self.span_pct = span_pct
        self.phase = "fetch"

    def progress(self, pct, stage=None):
        if self.phase == "analysis":
            fraction = max(0.0, min((float(pct) - 80.0) / 20.0, 1.0))
            label = f"{self.zone_id}: analysis"
        else:
            fraction = max(0.0, min(float(pct) / 80.0, 1.0)) * 0.5
            label = f"{self.zone_id}: fetch"
        self.reporter.progress(self.start_pct + self.span_pct * fraction, f"{label} · {stage or ''}".strip())

    def log(self, message):
        self.reporter.log(f"[{self.zone_id}] {message}")


def _process_zone(zone_id, reporter, sam_enabled=True):
    from src.analysis_run import analyze_latest
    from src.satellite_fetch import run_fetch_cycle

    reporter.progress(1, f"{zone_id}: starting")
    fetch_results = run_fetch_cycle(zone_ids=[zone_id], limit=1, reporter=reporter)
    if not fetch_results:
        raise RuntimeError(f"No active spatial zone found for '{zone_id}'.")
    fetch_result = fetch_results[0]
    if fetch_result.get("status") == "error":
        reporter.log(f"image fetch failed: {fetch_result.get('error', 'unknown error')}")
    else:
        reporter.log(
            f"image fetch status: {fetch_result.get('status')}; "
            f"new captures stored: {len(fetch_result.get('stored', []))}"
        )
    reporter.progress(80, f"{zone_id}: analysing latest capture")
    reporter.phase = "analysis"
    analyze_latest(zone_id, reporter, sam_enabled=sam_enabled)


def _run(zone_id, rep, sam_enabled=True):
    try:
        with _WORK_LOCK:
            _process_zone(zone_id, rep, sam_enabled=sam_enabled)
        rep.finish()
    except Exception as exc:
        log.exception("Spatial analysis job failed for %s", zone_id)
        rep.fail(str(exc))


def _run_batch(zone_ids, rep, sam_enabled=True):
    failures = []
    zone_span = 100.0 / len(zone_ids)
    with _WORK_LOCK:
        for index, zone_id in enumerate(zone_ids):
            adapter = _BatchReporter(rep, zone_id, index * zone_span, zone_span)
            try:
                _process_zone(zone_id, adapter, sam_enabled=sam_enabled)
            except Exception as exc:
                failures.append(zone_id)
                adapter.log(f"analysis failed: {exc}")
                log.exception("Spatial batch analysis failed for %s", zone_id)
    if failures:
        rep.fail(f"Analysis failed for: {', '.join(failures)}")
    else:
        rep.finish()


def start_job(zone_id, sam_enabled=True):
    with _LOCK:
        jid = _ACTIVE.get(zone_id)
        if jid and not JOBS[jid].done:
            return jid, False
        jid = uuid.uuid4().hex[:8]
        JOBS[jid] = Reporter(echo=True)
        _ACTIVE[zone_id] = jid
    threading.Thread(target=_run, args=(zone_id, JOBS[jid], sam_enabled), daemon=True).start()
    return jid, True


def start_batch_job(zone_ids, sam_enabled=True):
    ordered_ids = list(dict.fromkeys(zone_ids))
    if not ordered_ids:
        raise ValueError("Select at least one zone.")
    with _LOCK:
        active = [
            zone_id for zone_id in ordered_ids
            if (job_id := _ACTIVE.get(zone_id)) and not JOBS[job_id].done
        ]
        if active:
            raise RuntimeError(f"A spatial job is already running for: {', '.join(active)}.")
        job_id = uuid.uuid4().hex[:8]
        JOBS[job_id] = Reporter(echo=True)
        for zone_id in ordered_ids:
            _ACTIVE[zone_id] = job_id
    threading.Thread(
        target=_run_batch,
        args=(ordered_ids, JOBS[job_id], sam_enabled),
        daemon=True,
    ).start()
    return job_id


def _fetch_missing_zones():
    from src.satellite_fetch import run_fetch_cycle
    from src.spatial_config import load_active_zones
    from src.supabase_client import supabase

    if supabase is None:
        raise RuntimeError("One-time spatial bootstrap requires Supabase.")
    zones = load_active_zones()
    if not zones:
        raise RuntimeError("One-time spatial bootstrap found no active zones.")

    missing = []
    for zone in zones:
        snapshots = (
            supabase.table("spatial_snapshots")
            .select("id,image_url")
            .eq("zone_id", zone.zone_id)
            .order("acquired_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not snapshots or not snapshots[0].get("image_url"):
            missing.append(zone.zone_id)
    if not missing:
        log.info("One-time spatial bootstrap: every active zone already has an image.")
        return

    log.info("One-time spatial bootstrap fetching missing zones: %s", ", ".join(missing))
    results = run_fetch_cycle(zone_ids=missing, limit=1)
    failed = [result for result in results if result.get("status") == "error"]
    if failed:
        details = "; ".join(
            f"{item.get('zone')}: {item.get('error', 'satellite fetch failed')}" for item in failed
        )
        raise RuntimeError(f"One-time satellite image fetch failed: {details}")

    for zone_id in missing:
        snapshots = (
            supabase.table("spatial_snapshots")
            .select("id,image_url")
            .eq("zone_id", zone_id)
            .order("acquired_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not snapshots or not snapshots[0].get("image_url"):
            raise RuntimeError(
                f"One-time satellite fetch completed without storing an image for '{zone_id}'."
            )


def _analyze_latest_zones_with_live_ais():
    from src.analysis_run import analyze_latest
    from src.spatial_config import load_active_zones
    from src.supabase_client import supabase

    if supabase is None:
        raise RuntimeError("One-time live AIS analysis requires Supabase.")
    zones = load_active_zones()
    if not zones:
        raise RuntimeError("One-time live AIS analysis found no active zones.")
    for zone in zones:
        snapshots = (
            supabase.table("spatial_snapshots")
            .select("id,image_url,acquired_at,status")
            .eq("zone_id", zone.zone_id)
            .order("acquired_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not snapshots or not snapshots[0].get("image_url"):
            raise RuntimeError(
                f"Cannot fetch scene-matched AIS for '{zone.zone_id}': latest satellite image is missing."
            )
        if snapshots[0].get("status") == "verified":
            log.info(
                "Skipping scene-matched AIS analysis for %s; latest snapshot is already verified.",
                zone.zone_id,
            )
            continue
        analyze_latest(zone.zone_id, sam_enabled=True)
        log.info(
            "One-time scene-matched live AIS analysis completed for %s (%s).",
            zone.zone_id,
            snapshots[0].get("acquired_at"),
        )


def _heartbeat_startup_lease(state_table, lease_token, stop, lost_lease):
    while not stop.wait(_STARTUP_LEASE_HEARTBEAT_SECONDS):
        try:
            updated = (
                state_table.update({
                    "started_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("startup_key", _STARTUP_BOOTSTRAP_KEY)
                .eq("status", "running")
                .eq("error", lease_token)
                .select("startup_key")
                .execute()
                .data
                or []
            )
        except Exception:
            log.exception("Could not renew the one-time spatial bootstrap lease.")
            lost_lease.set()
            return
        if not updated:
            log.error("Lost ownership of the one-time spatial bootstrap lease.")
            lost_lease.set()
            return


def run_startup_spatial_bootstrap():
    from src.supabase_client import supabase

    if supabase is None:
        raise RuntimeError("One-time spatial bootstrap requires Supabase.")

    state_table = supabase.table("spatial_startup_state")
    state = (
        state_table.select("status,started_at,error")
        .eq("startup_key", _STARTUP_BOOTSTRAP_KEY)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not state:
        state_table.insert({
            "startup_key": _STARTUP_BOOTSTRAP_KEY,
            "status": "pending",
        }).execute()
        state = (
            state_table.select("status,started_at,error")
            .eq("startup_key", _STARTUP_BOOTSTRAP_KEY)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not state:
            raise RuntimeError("Could not initialize the one-time spatial bootstrap state.")
    state_row = state[0]
    status = state_row["status"]
    if status == "complete":
        log.info("One-time spatial bootstrap already completed; skipping.")
        return
    if status == "running":
        started_at = state_row.get("started_at")
        if not started_at:
            raise RuntimeError(
                "One-time spatial bootstrap is running without a lease timestamp; "
                "inspect spatial_startup_state before restarting."
            )
        running_since = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        if running_since.tzinfo is None:
            running_since = running_since.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - running_since.astimezone(timezone.utc)
        if age <= _STARTUP_LEASE_TIMEOUT:
            raise RuntimeError(
                "One-time spatial bootstrap is active "
                f"(lease heartbeat {age.total_seconds():.0f}s ago); "
                "inspect spatial_startup_state before restarting."
            )
        log.warning(
            "Reclaiming stale spatial bootstrap lease; last heartbeat was %.0f seconds ago.",
            age.total_seconds(),
        )
    elif status not in {"pending", "failed"}:
        raise RuntimeError(
            f"One-time spatial bootstrap is {status}; inspect spatial_startup_state before restarting."
        )
    if status == "failed":
        log.warning("Resuming the incomplete one-time spatial bootstrap after a prior failure.")

    lease_token = uuid.uuid4().hex
    claim_query = (
        state_table.update({
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "error": lease_token,
        })
        .eq("startup_key", _STARTUP_BOOTSTRAP_KEY)
        .eq("status", status)
    )
    if status == "running":
        claim_query = claim_query.eq("started_at", state_row["started_at"])
        if state_row.get("error") is None:
            claim_query = claim_query.is_("error", "null")
        else:
            claim_query = claim_query.eq("error", state_row["error"])
    claim = claim_query.select("startup_key").execute().data or []
    if not claim:
        raise RuntimeError(
            "Another backend instance changed or claimed the one-time spatial bootstrap."
        )

    stop_heartbeat = threading.Event()
    lost_lease = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_startup_lease,
        args=(state_table, lease_token, stop_heartbeat, lost_lease),
        name="spatial-bootstrap-heartbeat",
        daemon=True,
    )
    heartbeat.start()
    try:
        with _WORK_LOCK:
            _fetch_missing_zones()
            _analyze_latest_zones_with_live_ais()
        if lost_lease.is_set():
            raise RuntimeError("One-time spatial bootstrap lost its database lease.")
    except Exception as exc:
        try:
            state_table.update({
                "status": "failed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc)[:2000],
            }).eq("startup_key", _STARTUP_BOOTSTRAP_KEY).eq("status", "running").eq(
                "error", lease_token
            ).execute()
        except Exception:
            log.exception("Could not persist the one-time spatial bootstrap failure state.")
        log.exception("One-time spatial bootstrap failed; backend startup will stop.")
        raise RuntimeError(f"One-time spatial bootstrap failed: {exc}") from exc
    finally:
        stop_heartbeat.set()
        heartbeat.join(timeout=_STARTUP_LEASE_HEARTBEAT_SECONDS + 1)

    completed = (
        state_table.update({
            "status": "complete",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        })
        .eq("startup_key", _STARTUP_BOOTSTRAP_KEY)
        .eq("status", "running")
        .eq("error", lease_token)
        .select("startup_key")
        .execute()
        .data
        or []
    )
    if not completed:
        raise RuntimeError("Could not mark the one-time spatial bootstrap complete.")
    log.info("One-time satellite-image and scene-matched AIS bootstrap completed.")
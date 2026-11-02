from datetime import datetime, timezone
import threading
import uuid
import logging

from src.job_reporter import Reporter

log = logging.getLogger(__name__)

JOBS: dict[str, Reporter] = {}
_ACTIVE: dict[str, str] = {}
_LOCK = threading.Lock()
_WORK_LOCK = threading.Lock()
_STARTUP_FETCH_LOCK = threading.Lock()
_STARTUP_FETCH_STARTED = False


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


def _process_zone(zone_id, reporter):
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
    analyze_latest(zone_id, reporter)


def _run(zone_id, rep):
    try:
        with _WORK_LOCK:
            _process_zone(zone_id, rep)
        rep.finish()
    except Exception as exc:
        log.exception("Spatial analysis job failed for %s", zone_id)
        rep.fail(str(exc))


def _run_batch(zone_ids, rep):
    failures = []
    zone_span = 100.0 / len(zone_ids)
    with _WORK_LOCK:
        for index, zone_id in enumerate(zone_ids):
            adapter = _BatchReporter(rep, zone_id, index * zone_span, zone_span)
            try:
                _process_zone(zone_id, adapter)
            except Exception as exc:
                failures.append(zone_id)
                adapter.log(f"analysis failed: {exc}")
                log.exception("Spatial batch analysis failed for %s", zone_id)
    if failures:
        rep.fail(f"Analysis failed for: {', '.join(failures)}")
    else:
        rep.finish()


def start_job(zone_id):
    with _LOCK:
        jid = _ACTIVE.get(zone_id)
        if jid and not JOBS[jid].done:
            return jid, False
        jid = uuid.uuid4().hex[:8]
        JOBS[jid] = Reporter(echo=True)
        _ACTIVE[zone_id] = jid
    threading.Thread(target=_run, args=(zone_id, JOBS[jid]), daemon=True).start()
    return jid, True


def start_batch_job(zone_ids):
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
    threading.Thread(target=_run_batch, args=(ordered_ids, JOBS[job_id]), daemon=True).start()
    return job_id


def _fetch_missing_zones():
    from src.satellite_fetch import run_fetch_cycle
    from src.spatial_config import load_active_zones
    from src.supabase_client import supabase

    with _WORK_LOCK:
        if supabase is None:
            log.warning("Startup spatial fetch skipped: Supabase is not configured.")
            return
        missing = []
        for zone in load_active_zones():
            snapshots = (
                supabase.table("spatial_snapshots")
                .select("id,image_url")
                .eq("zone_id", zone.zone_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            if not snapshots or not snapshots[0].get("image_url"):
                missing.append(zone.zone_id)
        if not missing:
            log.info("Startup spatial fetch skipped: every active zone has a stored image.")
            return
        log.info("Startup spatial fetch checking zones without images: %s", ", ".join(missing))
        results = run_fetch_cycle(zone_ids=missing, limit=1)
        for result in results:
            log.info("Startup spatial fetch %s: %s", result.get("zone"), result.get("status"))


def _run_startup_live_analysis():
    from src.analysis_run import analyze_latest
    from src.spatial_config import load_active_zones
    from src.supabase_client import supabase

    if supabase is None:
        log.warning("Startup live AIS analysis skipped: Supabase is not configured.")
        return

    state_table = supabase.table("spatial_startup_state")
    state = (
        state_table.select("status")
        .eq("startup_key", "live_ais_bootstrap")
        .limit(1)
        .execute()
        .data
        or []
    )
    if not state:
        log.error("Startup live AIS analysis not started: run sql/clear_mock_spatial_ais.sql first.")
        return
    if state[0]["status"] != "pending":
        log.info("Startup live AIS analysis already attempted (status: %s).", state[0]["status"])
        return

    claim = (
        state_table.update({
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        })
        .eq("startup_key", "live_ais_bootstrap")
        .eq("status", "pending")
        .select("startup_key")
        .execute()
        .data
        or []
    )
    if not claim:
        log.info("Startup live AIS analysis was claimed by another backend instance.")
        return

    failures = []
    try:
        with _WORK_LOCK:
            for zone in load_active_zones():
                try:
                    snapshots = (
                        supabase.table("spatial_snapshots")
                        .select("id")
                        .eq("zone_id", zone.zone_id)
                        .order("acquired_at", desc=True)
                        .limit(1)
                        .execute()
                        .data
                        or []
                    )
                    if not snapshots:
                        log.info("Startup live AIS analysis skipped %s: no stored image.", zone.zone_id)
                        continue
                    analyze_latest(zone.zone_id)
                    log.info("Startup live AIS analysis completed for %s.", zone.zone_id)
                except Exception as exc:
                    failures.append(f"{zone.zone_id}: {exc}")
                    log.exception("Startup live AIS analysis failed for %s.", zone.zone_id)
    except Exception as exc:
        failures.append(f"startup: {exc}")
        log.exception("Could not load active zones for startup live AIS analysis.")

    status = "failed" if failures else "complete"
    update = {
        "status": status,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "error": "; ".join(failures)[:2000] if failures else None,
    }
    state_table.update(update).eq("startup_key", "live_ais_bootstrap").eq("status", "running").execute()
    if failures:
        log.error("Startup live AIS analysis completed with errors: %s", "; ".join(failures))
    else:
        log.info("One-time startup live AIS analysis completed.")


def start_missing_zone_fetch():
    global _STARTUP_FETCH_STARTED
    with _STARTUP_FETCH_LOCK:
        if _STARTUP_FETCH_STARTED:
            return
        _STARTUP_FETCH_STARTED = True
    def run():
        try:
            _fetch_missing_zones()
        except Exception:
            log.exception("Startup spatial fetch failed.")
        try:
            _run_startup_live_analysis()
        except Exception:
            log.exception("One-time startup live AIS analysis failed.")

    thread = threading.Thread(target=run, name="spatial-startup-tasks", daemon=True)
    thread.start()
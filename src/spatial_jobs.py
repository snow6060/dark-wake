import threading
import uuid

from src.job_reporter import Reporter

JOBS: dict[str, Reporter] = {}
_ACTIVE: dict[str, str] = {}
_LOCK = threading.Lock()


def _run(zone_id, rep):
    try:
        from src.analysis_run import analyze_latest
        from src.satellite_fetch import run_fetch_cycle
        rep.progress(1, "Starting")
        run_fetch_cycle(zone_ids=[zone_id], limit=1, reporter=rep)
        rep.progress(80, "Satellite image ready")
        analyze_latest(zone_id, rep)
        rep.finish()
    except Exception as exc:
        rep.fail(str(exc))


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
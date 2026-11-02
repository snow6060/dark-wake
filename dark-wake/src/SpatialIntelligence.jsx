import { useCallback, useEffect, useRef, useState } from "react";

const API = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const COLORS = { matched: "#34d399", dark: "#ef4444", displaced: "#f59e0b", unknown: "#64748b", unmatched_small: "#475569" };
const RADIUS = { LARGE: 3.4, MEDIUM: 2.4, SMALL: 1.7 };
const HORMUZ_AOIS = [
  { id: "full", label: "FULL STRAIT · COMBINED", bbox: null },
  { id: "bandar", label: "BANDAR ABBAS / RAJAEE", bbox: [56.0, 26.85, 56.75, 27.4] },
  { id: "western", label: "WESTERN APPROACH", bbox: [55.6, 26.35, 56.45, 27.0] },
  { id: "musandam", label: "MUSANDAM / KHASAB", bbox: [56.0, 25.85, 56.85, 26.5] },
];

const css = `
.sp{background:#05080d;color:#c8d6e5;font-family:ui-monospace,Menlo,Consolas,monospace;padding:16px;min-height:100%}
.sp .titlebar{display:flex;align-items:center;justify-content:space-between;gap:12px}
.sp h2{margin:0 0 4px;color:#7dd3fc;letter-spacing:2px;font-size:18px}
.sp .sub{color:#64748b;font-size:11px;margin-bottom:12px}
.sp .zone-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;margin:12px 0}
.sp .toolbar-actions{display:flex;align-items:center;gap:8px}
.sp .toolbar-actions .add-zone{background:#101b28;border-color:#58758b;color:#c8d6e5}
.sp .zone-card{background:#080d14;border:1px solid #16303f;padding:9px}
.sp .zone-card.active{border-color:#34d399}
.sp .zone-card-head{display:flex;align-items:center;gap:8px}
.sp .zone-focus{background:none;border:0;color:#9fb7c9;padding:4px 0;text-align:left;cursor:pointer;font:inherit;font-size:12px}
.sp .zone-card.active .zone-focus{color:#34d399}
.sp .zone-stats{display:grid;grid-template-columns:1fr auto;gap:2px 8px;margin-top:6px;color:#8296a8;font-size:10px}
.sp .zone-stats b{text-align:right;color:#c8d6e5}
.sp .box{background:#080d14;border:1px solid #16303f;padding:10px}
.sp .tabs{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.sp .tabs button,.sp .toolbar button,.sp .runbtn{background:none;border:1px solid #1e3a4c;color:#9fb7c9;padding:5px 10px;cursor:pointer;font:inherit;font-size:11px}
.sp .tabs button.on{background:#12304a;color:#7dd3fc}
.sp .toolbar button.on{border-color:#34d399;color:#34d399}
.sp .titlebar .runbtn{background:#0e2a3b;border-color:#38bdf8;color:#7dd3fc;padding:8px 12px}
.sp .head{font-size:15px;color:#e2f3ff;margin-bottom:8px;line-height:1.4}
.sp .kv{display:grid;grid-template-columns:1fr auto;gap:2px 10px;font-size:12px;margin:8px 0}
.sp .kv b{text-align:right}
.sp details{border-top:1px solid #16303f;padding:6px 0;font-size:11px}
.sp summary{cursor:pointer;color:#9fb7c9}
.sp .row{display:flex;justify-content:space-between;gap:8px;padding:2px 0;color:#8aa0b3}
.sp .note{font-size:10px;color:#64748b;margin-top:8px;line-height:1.4}
.sp .toolbar .runbtn{background:#0e2a3b;border-color:#38bdf8;color:#7dd3fc;padding:8px 12px}
.sp .runbtn:disabled{opacity:.5;cursor:wait}
.sp .viewer{margin-bottom:12px}
.sp .viewport{height:min(62vh,640px);min-height:280px;background:#020508;overflow:hidden;display:flex;align-items:center;justify-content:center;touch-action:none;position:relative}
.sp .viewport svg{display:block;width:min(100%,62vh,640px);height:auto;max-height:100%;flex:none;touch-action:none}
.sp .viewport .opt-canvas{position:relative;flex:none;max-width:100%;max-height:100%;transform-origin:center;touch-action:none}
.sp .opt-canvas img{display:block;width:100%;height:100%;object-fit:contain}
.sp .opt-canvas svg{position:absolute;inset:0;width:100%;height:100%;max-height:none}
.sp .viewport.dragging{cursor:grabbing}
.sp .viewport.zoomed{cursor:grab}
.sp .toolbar{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.sp .toolbar .spacer{flex:1}
.sp .vessel-table-wrap{overflow:auto;max-height:480px}
.sp .vessel-table{border-collapse:collapse;width:100%;font-size:11px;min-width:680px}
.sp .vessel-table th,.sp .vessel-table td{border-bottom:1px solid #16303f;padding:7px 8px;text-align:left;white-space:nowrap}
.sp .vessel-table th{position:sticky;top:0;background:#0b121a;color:#7dd3fc}
.sp .vessel-table td{color:#b4c4d2}
.sp .pill{border:1px solid #385366;border-radius:10px;padding:2px 7px;color:#fbbf24}
.sp .hover-card{position:absolute;z-index:5;width:248px;max-width:calc(100% - 20px);padding:11px 12px;background:#1e293b;border:1px solid #37618b;border-radius:8px;box-shadow:0 10px 24px #0009;color:#e2e8f0;font:12px Arial,sans-serif;pointer-events:none}
.sp .hover-card:after{content:"";position:absolute;left:var(--arrow-left,20px);bottom:-7px;width:12px;height:12px;background:#1e293b;border-right:1px solid #37618b;border-bottom:1px solid #37618b;transform:rotate(45deg)}
.sp .hover-title{display:flex;align-items:center;gap:7px;margin-bottom:8px;color:#93c5fd;font-size:15px;font-weight:700}
.sp .hover-dot{width:9px;height:9px;border-radius:50%;background:#fb7185;box-shadow:0 0 0 3px #fb718533}
.sp .hover-line{display:flex;gap:5px;margin:4px 0}
.sp .hover-line span{color:#94a3b8}
.sp .hover-line b{color:#f8fafc;font-weight:500}
.sp .run{margin-top:12px}
.sp .bar{height:10px;background:#0b1320;border:1px solid #1e3a4c;margin:8px 0;position:relative;overflow:hidden}
.sp .bar>i{display:block;height:100%;background:linear-gradient(90deg,#0ea5e9,#34d399);transition:width .4s}
.sp .bar.active:after{content:"";position:absolute;inset:0 auto 0 -35%;width:35%;background:linear-gradient(90deg,transparent,#e0f2feaa,transparent);animation:sp-progress-sweep 1.5s ease-in-out infinite}
@keyframes sp-progress-sweep{to{left:100%}}
.sp .log{max-height:130px;overflow:auto;font-size:11px;color:#8aa0b3;background:#05080d;border:1px solid #16303f;padding:6px}
.sp .sweep{transform-origin:320px 320px;animation:spsw 6s linear infinite}
@keyframes spsw{to{transform:rotate(360deg)}}
.sp .dialog-backdrop{position:fixed;inset:0;z-index:1000;background:#000b;display:grid;place-items:center;padding:16px}
.sp .dialog{width:min(520px,100%);max-height:min(80vh,700px);overflow:auto;background:#080d14;border:1px solid #27516a;padding:16px;box-shadow:0 20px 70px #000}
.sp .dialog h3{margin:0 0 6px;color:#7dd3fc}
.sp .form-field{display:grid;gap:5px;margin:12px 0;color:#9fb7c9;font-size:11px}
.sp .form-field input{min-width:0;background:#05080d;border:1px solid #28485b;color:#e2f3ff;padding:8px;font:inherit}
.sp .form-field input:focus{outline:1px solid #38bdf8}
.sp .bbox-fields{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}
.sp .dialog-list{display:grid;gap:7px;margin:12px 0}
.sp .dialog-list label{display:flex;gap:9px;align-items:center;color:#c8d6e5}
.sp .dialog-list input{accent-color:#34d399}
.sp .dialog-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap}
.sp .dialog-actions button{background:#0e2a3b;border:1px solid #38bdf8;color:#7dd3fc;padding:7px 10px;cursor:pointer;font:inherit}
.sp .dialog-actions button:disabled{opacity:.5;cursor:not-allowed}
@media(max-width:700px){.sp .titlebar{align-items:flex-start;flex-direction:column}.sp{padding:10px}.sp .viewport{height:52vh}}
`;

const age = (iso) => (iso ? Math.round((Date.now() - new Date(iso).getTime()) / 36e5) : null);
const dataAge = (iso) => {
  if (!iso) return "Unknown";
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h ago`;
  return `${Math.floor(minutes / (24 * 60))} days ago`;
};

async function responseJson(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return body;
}

export default function SpatialIntelligence() {
  const [zones, setZones] = useState([]);
  const [zone, setZone] = useState(null);
  const [selectedZones, setSelectedZones] = useState(null);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [view, setView] = useState("radar");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const [zoneDialog, setZoneDialog] = useState(false);
  const [addZoneDialog, setAddZoneDialog] = useState(false);
  const [newZone, setNewZone] = useState({ display_name: "", bbox_west: "", bbox_south: "", bbox_east: "", bbox_north: "" });
  const [hormuzSector, setHormuzSector] = useState("full");
  const [hoverCard, setHoverCard] = useState(null);
  const [job, setJob] = useState(null);
  const timer = useRef(null);
  const dragStart = useRef(null);
  const viewportRef = useRef(null);
  const zoneRef = useRef(zone);
  zoneRef.current = zone;

  const loadZones = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/spatial/zones?refresh=true`);
      const j = await responseJson(r);
      const nextZones = (j.zones || []).filter((item) => item.zone_id !== "hormuz");
      const nextIds = nextZones.map((item) => item.zone_id);
      setZones(nextZones);
      setSelectedZones((current) => current === null ? nextIds : current.filter((id) => nextIds.includes(id)));
      setZone((current) => current || nextIds[0] || null);
      if (!nextZones.length) setErr("No spatial zones are available from the backend.");
    } catch (e) { setErr("Could not load zones: " + e.message); }
  }, []);

  const loadAnalysis = useCallback(async (id) => {
    if (!id) return;
    try {
      const r = await fetch(`${API}/api/spatial/zones/${id}/analysis`);
      setData(await responseJson(r));
      setErr(null);
    } catch (e) { setErr("Could not load analysis: " + e.message); }
  }, []);

  useEffect(() => { loadZones(); }, [loadZones]);
  useEffect(() => {
    setData(null);
    setPan({ x: 0, y: 0 });
    setZoom(1);
    setHormuzSector("full");
    loadAnalysis(zone);
  }, [zone, loadAnalysis]);
  useEffect(() => () => clearInterval(timer.current), []);

  const followJob = (jobId, zoneIds) => {
    setJob({
      id: jobId, pct: 0, stage: `Starting ${zoneIds.length} zone(s)`,
      lines: [], done: false, error: null, next: 0,
    });
    clearInterval(timer.current);
    let next = 0;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const response = await fetch(`${API}/api/spatial/jobs/${jobId}?since=${next}`);
        const status = await responseJson(response);
        next = status.next ?? next;
        setJob((current) => ({
          ...status,
          id: jobId,
          lines: [...(current?.lines || []), ...(status.lines || [])],
          next,
        }));
        if (status.done) {
          clearInterval(timer.current);
          loadZones();
          if (zoneRef.current && zoneIds.includes(zoneRef.current)) {
            loadAnalysis(zoneRef.current);
          }
        }
      } catch (e) {
        clearInterval(timer.current);
        setJob((current) => ({ ...current, done: true, error: e.message }));
        setErr("Could not track analysis job: " + e.message);
      } finally {
        polling = false;
      }
    };
    timer.current = setInterval(poll, 1200);
    void poll();
  };

  const run = async (requestedZoneIds) => {
    const zoneIds = Array.isArray(requestedZoneIds)
      ? requestedZoneIds
      : selectedZones || zones.map((item) => item.zone_id);
    if (!zoneIds.length) return;
    try {
      setErr(null);
      setJob({
        id: null,
        pct: 0,
        stage: `Submitting ${zoneIds.length} zone(s)…`,
        lines: [],
        done: false,
        error: null,
        next: 0,
      });
      const response = await fetch(`${API}/api/spatial/zones/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ zone_ids: zoneIds }),
      });
      const { job_id: jobId } = await responseJson(response);
      if (!jobId) throw new Error("The backend did not return a job ID.");
      setZoneDialog(false);
      followJob(jobId, zoneIds);
    } catch (e) {
      setJob((current) => ({ ...current, done: true, error: e.message }));
      setErr("Could not start analysis: " + e.message);
    }
  };

  const createZone = async (event) => {
    event.preventDefault();
    if (
      !newZone.display_name.trim()
      || ["bbox_west", "bbox_south", "bbox_east", "bbox_north"].some((key) => !newZone[key].trim())
    ) {
      setErr("Enter a zone name and four valid bounding-box coordinates.");
      return;
    }
    const payload = {
      display_name: newZone.display_name.trim(),
      bbox_west: Number(newZone.bbox_west),
      bbox_south: Number(newZone.bbox_south),
      bbox_east: Number(newZone.bbox_east),
      bbox_north: Number(newZone.bbox_north),
    };
    if (Object.values(payload).some((value) => value === "" || (typeof value === "number" && !Number.isFinite(value)))) {
      setErr("Enter a zone name and four valid bounding-box coordinates.");
      return;
    }
    try {
      setErr(null);
      const response = await fetch(`${API}/api/spatial/zones`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await responseJson(response);
      if (!result.job_id || !result.zone_id) throw new Error("The backend did not return the new zone job.");
      setAddZoneDialog(false);
      setNewZone({ display_name: "", bbox_west: "", bbox_south: "", bbox_east: "", bbox_north: "" });
      setZone(result.zone_id);
      setSelectedZones((current) => [...new Set([...(current || zones.map((item) => item.zone_id)), result.zone_id])]);
      loadZones();
      followJob(result.job_id, [result.zone_id]);
    } catch (e) {
      setErr("Could not create and analyze zone: " + e.message);
    }
  };

  const selectedZoneSet = new Set(selectedZones || zones.map((item) => item.zone_id));
  const toggleZone = (zoneId) => {
    setSelectedZones((current) => {
      const selected = new Set(current || zones.map((item) => item.zone_id));
      if (selected.has(zoneId)) selected.delete(zoneId);
      else selected.add(zoneId);
      return [...selected];
    });
  };
  const selectAllZones = () => setSelectedZones(zones.map((item) => item.zone_id));
  const clearZones = () => setSelectedZones([]);
  const setViewerZoom = (value) => {
    setZoom(value);
    if (value === 1) setPan({ x: 0, y: 0 });
  };
  const startPan = (event) => {
    if (zoom === 1) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStart.current = { x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y };
    setDragging(true);
  };
  const movePan = (event) => {
    if (!dragStart.current) return;
    setPan({
      x: dragStart.current.panX + event.clientX - dragStart.current.x,
      y: dragStart.current.panY + event.clientY - dragStart.current.y,
    });
  };
  const endPan = () => {
    dragStart.current = null;
    setDragging(false);
  };

  const hulls = data?.hulls || [];
  const aisVessels = data?.ais_vessels || [];
  const S = data?.summary || null;
  const snap = data?.snapshot || null;
  const bbox = data?.zone?.bbox || [
    data?.zone?.bbox_west, data?.zone?.bbox_south,
    data?.zone?.bbox_east, data?.zone?.bbox_north,
  ];
  const selectedAoi = HORMUZ_AOIS.find((item) => item.id === hormuzSector) || HORMUZ_AOIS[0];
  const sectorBounds = selectedAoi.bbox && bbox.every(Number.isFinite)
    ? [
      Math.max(selectedAoi.bbox[0], bbox[0]),
      Math.max(selectedAoi.bbox[1], bbox[1]),
      Math.min(selectedAoi.bbox[2], bbox[2]),
      Math.min(selectedAoi.bbox[3], bbox[3]),
    ]
    : selectedAoi.bbox;
  const inSector = (item) => !sectorBounds || (
    Number.isFinite(item.lat) && Number.isFinite(item.lon)
    && item.lon >= sectorBounds[0] && item.lon <= sectorBounds[2]
    && item.lat >= sectorBounds[1] && item.lat <= sectorBounds[3]
  );
  const visibleHulls = hulls.filter(inSector);
  const visibleAisVessels = aisVessels.filter(inSector);
  const visibleGhosts = (data?.ghosts || []).filter(inSector);
  const rings = data?.zone?.range_rings_km || [5, 10, 20];
  const maxR = Math.max(
    ...rings,
    ...visibleHulls.map((h) => h.range_km),
    ...visibleGhosts.map((g) => g.range_km),
    1,
  ) * 1.04;
  const xy = (o) => {
    const a = (o.bearing_deg * Math.PI) / 180;
    const r = (o.range_km / maxR) * 300;
    return [320 + r * Math.sin(a), 320 - r * Math.cos(a)];
  };
  const dark = visibleHulls.filter((h) => h.status === "dark");
  const displaced = visibleHulls.filter((h) => h.status === "displaced");
  const pairs = visibleHulls.filter((h) => h.pair);
  const ghosts = visibleGhosts;
  const largeHulls = visibleHulls.filter((h) => h.length_m >= 150);
  const largeMatched = largeHulls.filter((h) => h.status === "matched").length;
  const largeUnmatched = largeHulls.filter((h) => h.status === "dark").length;
  const a = S ? age(S.acquired_at) : null;
  const running = job && !job.done;
  const showHoverCard = (event, item) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();
    const width = 268;
    const height = 184;
    const x = Math.max(10, Math.min(event.clientX - rect.left + 12, rect.width - width - 10));
    const y = Math.max(10, Math.min(event.clientY - rect.top - height - 12, rect.height - height - 10));
    setHoverCard({ item, x, y });
  };
  const hideHoverCard = () => setHoverCard(null);

  const imageWidth = Number(snap?.width_px) || 1;
  const imageHeight = Number(snap?.height_px) || 1;
  const imageRatio = imageWidth / imageHeight;
  const imageFitHeight = Math.min(window.innerHeight * 0.62, 640);
  const imageFitWidth = Math.min(window.innerWidth - 40, imageFitHeight * imageRatio);

  return (
    <div className="sp">
      <style>{css}</style>
      <div className="titlebar">
        <h2>SPATIAL INTELLIGENCE</h2>
        <div className="toolbar-actions">
          <button type="button" className="add-zone" onClick={() => setAddZoneDialog(true)}>ADD ZONE</button>
          <button
            type="button"
            className="runbtn"
            disabled={running || zones.length === 0}
            onClick={() => setZoneDialog(true)}
          >
            {running ? "FETCHING + ANALYSING…" : "FETCH LATEST IMAGE AND RUN ANALYSIS"}
          </button>
        </div>
      </div>
      <div className="sub">
        Sentinel-2 optical · AIS history matched to scene timestamp · SAM 3.1 enabled for requested analyses
      </div>
      {job && (
        <div className="box run" aria-live="polite">
          <div
            className={`bar${running ? " active" : ""}`}
            role="progressbar"
            aria-label="Fetch and analyze progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={job.pct}
          >
            <i style={{ width: `${job.pct}%` }} />
          </div>
          <div style={{ fontSize: 11 }}>
            {job.pct}% · {job.error ? `ERROR: ${job.error}` : job.stage}
          </div>
          <div className="log">{(job.lines || []).map((line, index) => <div key={index}>{line}</div>)}</div>
        </div>
      )}
      <div className="zone-grid">
        {zones.map((item) => {
          const summary = item.summary;
          const latest = item.latest;
          return (
            <div className={"zone-card" + (item.zone_id === zone ? " active" : "")} key={item.zone_id}>
              <div className="zone-card-head">
                <button type="button" className="zone-focus" onClick={() => setZone(item.zone_id)}>
                  {item.display_name}
                </button>
              </div>
              <div className="zone-stats">
                <span>Vessels / large</span>
                <b>{summary ? `${summary.vessels_total} / ${summary.large_total}` : "No analysis"}</b>
                <span>Large AIS matches</span>
                <b>{summary ? `${summary.large_matched} / ${summary.large_total}` : "—"}</b>
                <span>No AIS match · pairs</span>
                <b>{summary ? `${summary.no_ais_large} · ${summary.alongside_pairs}` : "—"}</b>
                <span>Capture</span>
                <b>{latest?.image_url ? `${latest.freshness} · ${latest.cloud_pct ?? "?"}% cloud` : "No image stored"}</b>
              </div>
            </div>
          );
        })}
      </div>
      {err && <div className="note" role="alert" style={{ color: "#f87171" }}>{err}</div>}
      {data && !snap && <div className="box">{data.message || "No satellite capture is available for this zone."}</div>}
      {data && snap && (
        <>
          {zone === "hormuz" && (
            <div className="tabs" aria-label="Strait of Hormuz sectors">
              {HORMUZ_AOIS.map((aoi) => (
                <button key={aoi.id} className={hormuzSector === aoi.id ? "on" : ""} onClick={() => setHormuzSector(aoi.id)}>
                  {aoi.label}
                </button>
              ))}
              {sectorBounds && (
                <span className="note">
                  AOI {sectorBounds[0].toFixed(3)}°E, {sectorBounds[1].toFixed(3)}°N – {sectorBounds[2].toFixed(3)}°E, {sectorBounds[3].toFixed(3)}°N
                </span>
              )}
              {sectorBounds && (
                <span className="note">Approximate congestion-monitoring boxes, not surveyed or official TSS boundaries.</span>
              )}
            </div>
          )}
          <section className="box viewer">
            <div className="toolbar">
              <button className={view === "radar" ? "on" : ""} onClick={() => setView("radar")}>RADAR</button>
              <button className={view === "optical" ? "on" : ""} onClick={() => setView("optical")}>OPTICAL + SAM</button>
              <span className="spacer" />
              {[1, 2, 4].map((value) => (
                <button key={value} className={zoom === value ? "on" : ""} onClick={() => setViewerZoom(value)}>
                  {value}x
                </button>
              ))}
              <span className="note">{snap.acquired_at ? `Scene ${snap.acquired_at}` : "Latest stored scene"}</span>
            </div>
            <div
              ref={viewportRef}
              className={`viewport${zoom > 1 ? " zoomed" : ""}${dragging ? " dragging" : ""}`}
              onPointerDown={startPan}
              onPointerMove={movePan}
              onPointerUp={endPan}
              onPointerCancel={endPan}
              onLostPointerCapture={endPan}
              onPointerLeave={hideHoverCard}
            >
              {view === "radar" ? (
                <svg
                  viewBox="0 0 640 640"
                  style={{
                    aspectRatio: "1 / 1",
                    transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                  }}
                >
                  <rect width="640" height="640" fill="#04090d" />
                  {rings.map((r) => (
                    <g key={r}>
                      <circle cx="320" cy="320" r={(r / maxR) * 300} fill="none" stroke="#12435a" strokeWidth="1" />
                      <text x="324" y={320 - (r / maxR) * 300 - 3} fill="#2d6a86" fontSize="10">{r} km</text>
                    </g>
                  ))}
                  <line x1="20" y1="320" x2="620" y2="320" stroke="#0e2f3f" />
                  <line x1="320" y1="20" x2="320" y2="620" stroke="#0e2f3f" />
                  <text x="316" y="14" fill="#2d6a86" fontSize="11">N</text>
                  <g className="sweep">
                    <path d="M320 320 L320 20 A300 300 0 0 1 420 37 Z" fill="#34d39914" />
                    <line x1="320" y1="320" x2="320" y2="20" stroke="#34d39955" />
                  </g>
                  {visibleAisVessels.filter((vessel) => Number.isFinite(vessel.range_km) && Number.isFinite(vessel.bearing_deg)).map((vessel, index) => {
                    const [x, y] = xy(vessel);
                    const matchedHull = hulls.find((hull) => String(hull.mmsi) === String(vessel.mmsi));
                    const item = { ...vessel, scene_status: matchedHull?.status || "AIS report" };
                    return (
                      <circle
                        key={`ais-${vessel.mmsi || index}`}
                        cx={x}
                        cy={y}
                        r="5"
                        fill="#38bdf8"
                        stroke="#e0f2fe"
                        strokeWidth="1.2"
                        onPointerEnter={(event) => showHoverCard(event, item)}
                        onPointerLeave={hideHoverCard}
                      >
                        <title>{vessel.name || `MMSI ${vessel.mmsi}`}</title>
                      </circle>
                    );
                  })}
                  {visibleHulls.map((h) => {
                    const [x, y] = xy(h);
                    const vessel = visibleAisVessels.find((item) => String(item.mmsi) === String(h.mmsi));
                    const hoverItem = vessel
                      ? { ...vessel, scene_status: h.status, length_m: h.length_m }
                      : { name: h.name, mmsi: h.mmsi, ship_type: null, flag: null, country: null, nav: null, time_utc: null, scene_status: h.status, length_m: h.length_m };
                    return (
                      <g key={h.id}>
                        {h.pair && <circle cx={x} cy={y} r={RADIUS[h.size_class] + 3.5} fill="none" stroke="#22d3ee" strokeWidth="0.8" />}
                        <circle
                          cx={x}
                          cy={y}
                          r={RADIUS[h.size_class]}
                          fill={COLORS[h.status] || COLORS.unknown}
                          opacity={h.status === "unmatched_small" ? 0.55 : 0.95}
                          onPointerEnter={(event) => showHoverCard(event, hoverItem)}
                          onPointerLeave={hideHoverCard}
                        >
                          <title>{`${h.status} · ${h.length_m} m${h.name ? " · " + h.name : ""}`}</title>
                        </circle>
                      </g>
                    );
                  })}
                  {ghosts.map((ghost, index) => {
                    const [x, y] = xy(ghost);
                    return (
                      <g key={`ghost-${index}`}>
                        <circle
                          cx={x}
                          cy={y}
                          r="5"
                          fill="none"
                          stroke="#fb7185"
                          strokeDasharray="2 2"
                          onPointerEnter={(event) => showHoverCard(event, {
                            ...ghost,
                            scene_status: "Ghost AIS candidate",
                          })}
                          onPointerLeave={hideHoverCard}
                        />
                        <line x1={x - 3} y1={y - 3} x2={x + 3} y2={y + 3} stroke="#fb7185" />
                        <line x1={x - 3} y1={y + 3} x2={x + 3} y2={y - 3} stroke="#fb7185" />
                        <title>{`ghost AIS · ${ghost.name || ghost.mmsi}`}</title>
                      </g>
                    );
                  })}
                  <circle cx="320" cy="320" r="2.5" fill="#7dd3fc" />
                </svg>
              ) : snap.image_url ? (
                <div
                  className="opt-canvas"
                  style={{
                    width: `${imageFitWidth}px`,
                    aspectRatio: `${imageWidth} / ${imageHeight}`,
                    transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                  }}
                >
                  <img src={snap.image_url} alt={`${data.zone?.display_name || "Zone"} satellite capture`} />
                  <svg viewBox={`0 0 ${imageWidth} ${imageHeight}`} preserveAspectRatio="none">
                    {visibleHulls
                      .filter((h) => (h.status !== "unmatched_small" && h.status !== "unknown") || h.length_m >= 150)
                      .map((h) => (
                        <circle
                          key={h.id}
                          cx={h.col}
                          cy={h.row}
                          r={h.pair ? 22 : 14}
                          fill="none"
                          stroke={h.pair ? "#22d3ee" : COLORS[h.status] || COLORS.unknown}
                          strokeWidth="3"
                          onPointerEnter={(event) => {
                            const vessel = visibleAisVessels.find((item) => String(item.mmsi) === String(h.mmsi));
                            showHoverCard(event, vessel
                              ? { ...vessel, scene_status: h.status, length_m: h.length_m }
                              : { name: h.name, mmsi: h.mmsi, scene_status: h.status, length_m: h.length_m });
                          }}
                          onPointerLeave={hideHoverCard}
                        />
                      ))}
                  </svg>
                </div>
              ) : <div className="note">No image stored.</div>}
              {hoverCard && (
                <div className="hover-card" style={{ left: hoverCard.x, top: hoverCard.y }}>
                  <div className="hover-title"><i className="hover-dot" />{hoverCard.item.name || "Unidentified vessel"}</div>
                  <div className="hover-line"><span>Flag:</span><b>{hoverCard.item.flag || "Not reported"}{hoverCard.item.country ? ` · ${hoverCard.item.country}` : ""}</b></div>
                  <div className="hover-line"><span>Type:</span><b>{hoverCard.item.ship_type || hoverCard.item.type_code || "Not reported"}</b></div>
                  <div className="hover-line"><span>Status:</span><b>{hoverCard.item.nav || "Not reported"} · {hoverCard.item.scene_status || "AIS report"}</b></div>
                  <div className="hover-line"><span>MMSI:</span><b>{hoverCard.item.mmsi || "Not reported"}</b></div>
                  {hoverCard.item.length_m && <div className="hover-line"><span>Image length:</span><b>{hoverCard.item.length_m} m</b></div>}
                  <div className="hover-line"><span>Last data:</span><b>{dataAge(hoverCard.item.time_utc)}</b></div>
                </div>
              )}
            </div>
          </section>
          <section className="box">
            <div className="head">
              {S
                ? `${visibleHulls.length} vessels seen · ${largeHulls.length} large (150 m+) · ${largeMatched} large AIS matches`
                : "Analysis pending for this satellite capture"}
            </div>
            {S && (
              <div className="kv">
                <span style={{ color: "#ef4444" }}>No AIS match (large)</span><b>{largeUnmatched}</b>
                <span style={{ color: "#f59e0b" }}>AIS position offsets</span><b>{displaced.length}</b>
                <span style={{ color: "#fb7185" }}>Ghost AIS signals</span><b>{ghosts.length}</b>
                <span style={{ color: "#22d3ee" }}>Hull-to-hull pairs</span><b>{Math.floor(pairs.length / 2)}</b>
                <span>AIS ships in selected area</span><b>{visibleAisVessels.length}</b>
                <span>Scene / cloud cover</span><b>{a == null ? "?" : `${a} h old`} · {snap.cloud_pct ?? "?"}%</b>
              </div>
            )}
            <h3>AIS VESSEL DETAILS ({visibleAisVessels.length})</h3>
            {visibleAisVessels.length > 0 ? (
              <div className="vessel-table-wrap">
                <table className="vessel-table">
                  <thead>
                    <tr><th>Vessel</th><th>MMSI</th><th>Category / type</th><th>Flag</th><th>Country</th><th>Sanctions</th><th>Scene status</th></tr>
                  </thead>
                  <tbody>
                    {visibleAisVessels.map((vessel, index) => {
                      const matchedHull = visibleHulls.find((hull) => String(hull.mmsi) === String(vessel.mmsi));
                      return (
                        <tr key={`${vessel.mmsi || "ais"}-${index}`}>
                          <td>{vessel.name || "Unknown vessel"}</td>
                          <td>{vessel.mmsi || "—"}</td>
                          <td>{vessel.ship_type || vessel.type_code || "Unknown"}</td>
                          <td>{vessel.flag || "—"}</td>
                          <td>{vessel.country || "—"}</td>
                          <td><span className="pill">Not assessed</span></td>
                          <td>{matchedHull?.status || "AIS only / no image match"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="note">{S ? "No AIS vessel details were stored for this scene or sector." : "AIS vessel details will appear after analysis."}</div>
            )}
            <div className="note">
              Voyage Radar documents vessel type, flag, and country, but does not provide sanctions determinations. “Not assessed” is not a finding that a vessel is unsanctioned.
              {S ? ` ${S.ais_note}.` : ""}
              {hormuzSector !== "full" && sectorBounds && " Sector filtering is applied to stored AIS and image-derived vessel coordinates; the full capture remains available in the combined view."}
            </div>
            {S && (
              <>
                <details><summary>Dark / no AIS match ({dark.length})</summary>
                  {dark.map((h) => <div className="row" key={h.id}><span>#{h.id} {h.length_m} m{h.pair ? " · pair" : ""}</span><span>{h.lat.toFixed(4)}, {h.lon.toFixed(4)}</span></div>)}
                </details>
                <details><summary>Position offsets ({displaced.length})</summary>
                  {displaced.map((h) => <div className="row" key={h.id}><span>{h.name || h.mmsi}</span><span>{h.offset_m} m from claim</span></div>)}
                </details>
                <details><summary>Ghost AIS signals ({ghosts.length})</summary>
                  {ghosts.map((ghost, index) => <div className="row" key={index}><span>{ghost.name || ghost.mmsi}</span><span>{ghost.lat.toFixed(4)}, {ghost.lon.toFixed(4)} · {ghost.age_min} min old</span></div>)}
                </details>
                <details><summary>Hull-to-hull pairs ({Math.floor(pairs.length / 2)})</summary>
                  {pairs.map((h) => <div className="row" key={h.id}><span>#{h.id} {h.length_m} m</span><span>{h.lat.toFixed(4)}, {h.lon.toFixed(4)}</span></div>)}
                </details>
              </>
            )}
          </section>
        </>
      )}
      {zoneDialog && (
        <div className="dialog-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setZoneDialog(false);
        }}>
          <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="zone-run-title">
            <h3 id="zone-run-title">Fetch and analyze zones</h3>
            <div className="note">Choose the satellite zones to refresh. AIS history will be requested at each new capture’s timestamp.</div>
            {job?.id === null && !job.done && (
              <div className="box run" aria-live="polite">
                <div className="bar active" role="progressbar" aria-label="Starting analysis" aria-valuemin={0} aria-valuemax={100} aria-valuenow={0}>
                  <i style={{ width: "0%" }} />
                </div>
                <div style={{ fontSize: 11 }}>{job.stage}</div>
              </div>
            )}
            <div className="dialog-actions">
              <button type="button" onClick={selectAllZones}>Select all</button>
              <button type="button" onClick={clearZones}>Clear</button>
            </div>
            <div className="dialog-list">
              {zones.map((item) => (
                <label key={item.zone_id}>
                  <input
                    type="checkbox"
                    checked={selectedZoneSet.has(item.zone_id)}
                    onChange={() => toggleZone(item.zone_id)}
                  />
                  {item.display_name}
                </label>
              ))}
            </div>
            <div className="dialog-actions">
              <button type="button" onClick={() => setZoneDialog(false)}>Cancel</button>
              <button type="button" disabled={selectedZoneSet.size === 0 || running} onClick={run}>
                Fetch + analyze {selectedZoneSet.size} zone(s)
              </button>
            </div>
          </section>
        </div>
      )}
      {addZoneDialog && (
        <div className="dialog-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setAddZoneDialog(false);
        }}>
          <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="zone-create-title" onSubmit={createZone}>
            <h3 id="zone-create-title">Add a satellite analysis zone</h3>
            <div className="note">
              Enter a name and a WGS84 bounding box in decimal degrees. Creating the zone immediately fetches its latest eligible Sentinel-2 image and runs AIS-matched analysis with SAM 3.1 enabled.
            </div>
            <label className="form-field">
              Zone name
              <input
                autoFocus
                required
                minLength={3}
                maxLength={80}
                value={newZone.display_name}
                onChange={(event) => setNewZone((current) => ({ ...current, display_name: event.target.value }))}
                placeholder="e.g. Bandar Abbas Anchorage"
              />
            </label>
            <div className="bbox-fields">
              {[
                ["bbox_west", "West longitude"],
                ["bbox_south", "South latitude"],
                ["bbox_east", "East longitude"],
                ["bbox_north", "North latitude"],
              ].map(([field, label]) => (
                <label className="form-field" key={field}>
                  {label}
                  <input
                    type="number"
                    required
                    step="any"
                    min={field.includes("west") || field.includes("east") ? -180 : -90}
                    max={field.includes("west") || field.includes("east") ? 180 : 90}
                    value={newZone[field]}
                    onChange={(event) => setNewZone((current) => ({ ...current, [field]: event.target.value }))}
                    placeholder={field.includes("west") || field.includes("east") ? "longitude" : "latitude"}
                  />
                </label>
              ))}
            </div>
            <div className="note">Bounds must be ordered west &lt; east and south &lt; north; each dimension is limited to 4°.</div>
            <div className="dialog-actions">
              <button type="button" onClick={() => setAddZoneDialog(false)}>Cancel</button>
              <button type="submit" disabled={running}>Create + fetch + analyze</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
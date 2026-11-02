import { useCallback, useEffect, useRef, useState } from "react";

const API = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const COLORS = { matched: "#34d399", dark: "#ef4444", displaced: "#f59e0b", unknown: "#64748b", unmatched_small: "#475569" };
const RADIUS = { LARGE: 3.4, MEDIUM: 2.4, SMALL: 1.7 };

const css = `
.sp{background:#05080d;color:#c8d6e5;font-family:ui-monospace,Menlo,Consolas,monospace;padding:16px;min-height:100%}
.sp .titlebar{display:flex;align-items:center;justify-content:space-between;gap:12px}
.sp h2{margin:0 0 4px;color:#7dd3fc;letter-spacing:2px;font-size:18px}
.sp .sub{color:#64748b;font-size:11px;margin-bottom:12px}
.sp .zone-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;margin:12px 0}
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
.sp .run{margin-top:12px}
.sp .bar{height:10px;background:#0b1320;border:1px solid #1e3a4c;margin:8px 0}
.sp .bar>i{display:block;height:100%;background:linear-gradient(90deg,#0ea5e9,#34d399);transition:width .4s}
.sp .log{max-height:130px;overflow:auto;font-size:11px;color:#8aa0b3;background:#05080d;border:1px solid #16303f;padding:6px}
.sp .sweep{transform-origin:320px 320px;animation:spsw 6s linear infinite}
@keyframes spsw{to{transform:rotate(360deg)}}
.sp .dialog-backdrop{position:fixed;inset:0;z-index:1000;background:#000b;display:grid;place-items:center;padding:16px}
.sp .dialog{width:min(520px,100%);max-height:min(80vh,700px);overflow:auto;background:#080d14;border:1px solid #27516a;padding:16px;box-shadow:0 20px 70px #000}
.sp .dialog h3{margin:0 0 6px;color:#7dd3fc}
.sp .dialog-list{display:grid;gap:7px;margin:12px 0}
.sp .dialog-list label{display:flex;gap:9px;align-items:center;color:#c8d6e5}
.sp .dialog-list input{accent-color:#34d399}
.sp .dialog-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap}
.sp .dialog-actions button{background:#0e2a3b;border:1px solid #38bdf8;color:#7dd3fc;padding:7px 10px;cursor:pointer;font:inherit}
.sp .dialog-actions button:disabled{opacity:.5;cursor:not-allowed}
@media(max-width:700px){.sp .titlebar{align-items:flex-start;flex-direction:column}.sp{padding:10px}.sp .viewport{height:52vh}}
`;

const age = (iso) => (iso ? Math.round((Date.now() - new Date(iso).getTime()) / 36e5) : null);

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
  const [hormuzSector, setHormuzSector] = useState("full");
  const [job, setJob] = useState(null);
  const timer = useRef(null);
  const dragStart = useRef(null);
  const zoneRef = useRef(zone);
  zoneRef.current = zone;

  const loadZones = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/spatial/zones?refresh=true`);
      const j = await responseJson(r);
      const nextZones = j.zones || [];
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

  const run = async () => {
    const zoneIds = selectedZones || zones.map((item) => item.zone_id);
    if (!zoneIds.length) return;
    try {
      setErr(null);
      setJob(null);
      const response = await fetch(`${API}/api/spatial/zones/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ zone_ids: zoneIds }),
      });
      const { job_id: jobId } = await responseJson(response);
      if (!jobId) throw new Error("The backend did not return a job ID.");
      setZoneDialog(false);
      setJob({
        id: jobId, pct: 0, stage: `Starting ${zoneIds.length} zone(s)`,
        lines: [], done: false, error: null, next: 0,
      });
      clearInterval(timer.current);

      let next = 0;
      let polling = false;
      timer.current = setInterval(async () => {
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
      }, 1200);
    } catch (e) {
      setErr("Could not start analysis: " + e.message);
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
  const midpointLat = Number.isFinite(bbox[1]) && Number.isFinite(bbox[3]) ? (bbox[1] + bbox[3]) / 2 : null;
  const sectorBounds = hormuzSector === "iran" && midpointLat !== null
    ? [bbox[0], midpointLat, bbox[2], bbox[3]]
    : hormuzSector === "oman" && midpointLat !== null
      ? [bbox[0], bbox[1], bbox[2], midpointLat]
      : null;
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
        <button
          type="button"
          className="runbtn"
          disabled={running || zones.length === 0}
          onClick={() => setZoneDialog(true)}
        >
          {running ? "FETCHING + ANALYSING…" : "FETCH LATEST IMAGE AND RUN ANALYSIS"}
        </button>
      </div>
      <div className="sub">
        Sentinel-2 optical · per-zone analysis · AIS history matched to each scene timestamp
      </div>
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
          {zone === "hormuz" && midpointLat !== null && (
            <div className="tabs" aria-label="Strait of Hormuz sectors">
              <button className={hormuzSector === "full" ? "on" : ""} onClick={() => setHormuzSector("full")}>
                FULL STRAIT · COMBINED
              </button>
              <button className={hormuzSector === "iran" ? "on" : ""} onClick={() => setHormuzSector("iran")}>
                IRAN-SIDE SECTOR
              </button>
              <button className={hormuzSector === "oman" ? "on" : ""} onClick={() => setHormuzSector("oman")}>
                OMAN-SIDE SECTOR
              </button>
              {sectorBounds && (
                <span className="note">
                  Bounds {sectorBounds[0].toFixed(3)}, {sectorBounds[1].toFixed(3)} to {sectorBounds[2].toFixed(3)}, {sectorBounds[3].toFixed(3)}
                </span>
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
              className={`viewport${zoom > 1 ? " zoomed" : ""}${dragging ? " dragging" : ""}`}
              onPointerDown={startPan}
              onPointerMove={movePan}
              onPointerUp={endPan}
              onPointerCancel={endPan}
              onLostPointerCapture={endPan}
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
                  {visibleHulls.map((h) => {
                    const [x, y] = xy(h);
                    return (
                      <g key={h.id}>
                        {h.pair && <circle cx={x} cy={y} r={RADIUS[h.size_class] + 3.5} fill="none" stroke="#22d3ee" strokeWidth="0.8" />}
                        <circle cx={x} cy={y} r={RADIUS[h.size_class]} fill={COLORS[h.status] || COLORS.unknown} opacity={h.status === "unmatched_small" ? 0.55 : 0.95}>
                          <title>{`${h.status} · ${h.length_m} m${h.name ? " · " + h.name : ""}`}</title>
                        </circle>
                      </g>
                    );
                  })}
                  {ghosts.map((ghost, index) => {
                    const [x, y] = xy(ghost);
                    return (
                      <g key={`ghost-${index}`}>
                        <circle cx={x} cy={y} r="5" fill="none" stroke="#fb7185" strokeDasharray="2 2" />
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
                        />
                      ))}
                  </svg>
                </div>
              ) : <div className="note">No image stored.</div>}
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
              {hormuzSector !== "full" && sectorBounds && " Hormuz lane sectors split the configured Strait bounding box at its latitude midpoint; the full Strait view retains the combined coverage."}
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
      {job && (
        <div className="box run" aria-live="polite">
          <div className="bar"><i style={{ width: `${job.pct}%` }} /></div>
          <div style={{ fontSize: 11 }}>{job.pct}% · {job.error ? "ERROR: " + job.error : job.stage}</div>
          <div className="log">{job.lines.map((line, index) => <div key={index}>{line}</div>)}</div>
        </div>
      )}
      {zoneDialog && (
        <div className="dialog-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setZoneDialog(false);
        }}>
          <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="zone-run-title">
            <h3 id="zone-run-title">Fetch and analyze zones</h3>
            <div className="note">Choose the satellite zones to refresh. AIS history will be requested at each new capture’s timestamp.</div>
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
    </div>
  );
}
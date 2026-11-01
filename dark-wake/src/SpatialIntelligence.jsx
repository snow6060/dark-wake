import { useCallback, useEffect, useRef, useState } from "react";

const API = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const COLORS = { matched: "#34d399", dark: "#ef4444", displaced: "#f59e0b", unknown: "#64748b", unmatched_small: "#475569" };
const RADIUS = { LARGE: 3.4, MEDIUM: 2.4, SMALL: 1.7 };

const css = `
.sp{background:#05080d;color:#c8d6e5;font-family:ui-monospace,Menlo,Consolas,monospace;padding:16px;min-height:100%}
.sp h2{margin:0 0 4px;color:#7dd3fc;letter-spacing:2px;font-size:18px}
.sp .sub{color:#64748b;font-size:11px;margin-bottom:12px}
.sp .zones{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.sp .zb{background:#0b1320;border:1px solid #1e3a4c;color:#9fb7c9;padding:8px 12px;cursor:pointer;font:inherit;font-size:12px}
.sp .zb.on{border-color:#34d399;color:#34d399;box-shadow:0 0 8px #34d39955}
.sp .grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(300px,1fr);gap:14px}
.sp .box{background:#080d14;border:1px solid #16303f;padding:10px}
.sp .tabs button{background:none;border:1px solid #1e3a4c;color:#9fb7c9;padding:4px 10px;margin-right:6px;cursor:pointer;font:inherit;font-size:11px}
.sp .tabs button.on{background:#12304a;color:#7dd3fc}
.sp .head{font-size:15px;color:#e2f3ff;margin-bottom:8px;line-height:1.4}
.sp .kv{display:grid;grid-template-columns:1fr auto;gap:2px 10px;font-size:12px;margin:8px 0}
.sp .kv b{text-align:right}
.sp details{border-top:1px solid #16303f;padding:6px 0;font-size:11px}
.sp summary{cursor:pointer;color:#9fb7c9}
.sp .row{display:flex;justify-content:space-between;gap:8px;padding:2px 0;color:#8aa0b3}
.sp .note{font-size:10px;color:#64748b;margin-top:8px;line-height:1.4}
.sp .run{margin-top:12px}
.sp .runbtn{background:#0e2a3b;border:1px solid #38bdf8;color:#7dd3fc;padding:8px 16px;cursor:pointer;font:inherit}
.sp .runbtn:disabled{opacity:.5;cursor:wait}
.sp .bar{height:10px;background:#0b1320;border:1px solid #1e3a4c;margin:8px 0}
.sp .bar>i{display:block;height:100%;background:linear-gradient(90deg,#0ea5e9,#34d399);transition:width .4s}
.sp .log{max-height:130px;overflow:auto;font-size:11px;color:#8aa0b3;background:#05080d;border:1px solid #16303f;padding:6px}
.sp .sweep{transform-origin:320px 320px;animation:spsw 6s linear infinite}
@keyframes spsw{to{transform:rotate(360deg)}}
.sp .opt{position:relative;overflow:auto;max-height:640px;background:#000}
.sp .opt svg{position:absolute;inset:0;width:100%;height:100%}
`;

const age = (iso) => (iso ? Math.round((Date.now() - new Date(iso).getTime()) / 36e5) : null);

export default function SpatialIntelligence() {
  const [zones, setZones] = useState([]);
  const [zone, setZone] = useState(null);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [view, setView] = useState("radar");
  const [zoom, setZoom] = useState(1);
  const [job, setJob] = useState(null);
  const timer = useRef(null);

  const loadZones = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/spatial/zones`);
      const j = await r.json();
      setZones(j.zones || []);
      setZone((z) => z || (j.zones && j.zones[0] ? j.zones[0].zone_id : null));
    } catch (e) { setErr("Backend unreachable: " + e.message); }
  }, []);

  const loadAnalysis = useCallback(async (id) => {
    if (!id) return;
    try {
      const r = await fetch(`${API}/api/spatial/zones/${id}/analysis`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
      setErr(null);
    } catch (e) { setErr("Could not load analysis: " + e.message); }
  }, []);

  useEffect(() => { loadZones(); }, [loadZones]);
  useEffect(() => { setData(null); loadAnalysis(zone); }, [zone, loadAnalysis]);
  useEffect(() => () => clearInterval(timer.current), []);

  const run = async () => {
    const r = await fetch(`${API}/api/spatial/zones/${zone}/run`, { method: "POST" });
    const { job_id } = await r.json();
    setJob({ id: job_id, pct: 0, stage: "Starting", lines: [], done: false, error: null, next: 0 });
    clearInterval(timer.current);
    timer.current = setInterval(async () => {
      try {
        const cur = await new Promise((res) => setJob((j) => { res(j); return j; }));
        const s = await (await fetch(`${API}/api/spatial/jobs/${job_id}?since=${cur ? cur.next : 0}`)).json();
        setJob((j) => ({ ...s, id: job_id, lines: [...(j ? j.lines : []), ...s.lines], next: s.next }));
        if (s.done) { clearInterval(timer.current); loadAnalysis(zone); loadZones(); }
      } catch (e) { /* keep polling */ }
    }, 1200);
  };

  const hulls = data && data.hulls ? data.hulls : [];
  const S = data && data.summary ? data.summary : null;
  const rings = data && data.zone ? data.zone.range_rings_km || [5, 10, 20] : [5, 10, 20];
  const maxR = Math.max(...rings, ...hulls.map((h) => h.range_km), ...((data && data.ghosts) || []).map((g) => g.range_km), 1) * 1.04;
  const xy = (o) => { const a = (o.bearing_deg * Math.PI) / 180, r = (o.range_km / maxR) * 300; return [320 + r * Math.sin(a), 320 - r * Math.cos(a)]; };
  const snap = data && data.snapshot ? data.snapshot : null;
  const dark = hulls.filter((h) => h.status === "dark");
  const displaced = hulls.filter((h) => h.status === "displaced");
  const ghosts = (data && data.ghosts) || [];
  const pairs = hulls.filter((h) => h.pair);
  const a = S ? age(S.acquired_at) : null;
  const running = job && !job.done;

  return (
    <div className="sp">
      <style>{css}</style>
      <h2>SPATIAL INTELLIGENCE</h2>
      <div className="sub">Sentinel-2 optical, 10 m per pixel · SAM 3 verification · AIS: Voyage Radar terrestrial history</div>
      <div className="zones">
        {zones.map((z) => (
          <button key={z.zone_id} className={"zb" + (z.zone_id === zone ? " on" : "")} onClick={() => setZone(z.zone_id)}>
            {z.display_name}
          </button>
        ))}
      </div>
      {err && <div className="note" style={{ color: "#f87171" }}>{err}</div>}
      {data && !S && <div className="box">{data.message || "No analysis yet."} Press "Run new analysis" below.</div>}
      {S && (
        <div className="grid">
          <div className="box">
            <div className="tabs">
              <button className={view === "radar" ? "on" : ""} onClick={() => setView("radar")}>RADAR</button>
              <button className={view === "optical" ? "on" : ""} onClick={() => setView("optical")}>OPTICAL + SAM</button>
              {view === "optical" && [1, 2, 4].map((z) => <button key={z} className={zoom === z ? "on" : ""} onClick={() => setZoom(z)}>{z}x</button>)}
            </div>
            {view === "radar" ? (
              <svg viewBox="0 0 640 640" style={{ width: "100%", maxHeight: 640 }}>
                <rect width="640" height="640" fill="#04090d" />
                {rings.map((r) => (
                  <g key={r}><circle cx="320" cy="320" r={(r / maxR) * 300} fill="none" stroke="#12435a" strokeWidth="1" />
                    <text x="324" y={320 - (r / maxR) * 300 - 3} fill="#2d6a86" fontSize="10">{r} km</text></g>
                ))}
                <line x1="20" y1="320" x2="620" y2="320" stroke="#0e2f3f" /><line x1="320" y1="20" x2="320" y2="620" stroke="#0e2f3f" />
                <text x="316" y="14" fill="#2d6a86" fontSize="11">N</text>
                <g className="sweep"><path d="M320 320 L320 20 A300 300 0 0 1 420 37 Z" fill="#34d39914" /><line x1="320" y1="320" x2="320" y2="20" stroke="#34d39955" /></g>
                {hulls.map((h) => { const [x, y] = xy(h); return (
                  <g key={h.id}>
                    {h.pair && <circle cx={x} cy={y} r={RADIUS[h.size_class] + 3.5} fill="none" stroke="#22d3ee" strokeWidth="0.8" />}
                    <circle cx={x} cy={y} r={RADIUS[h.size_class]} fill={COLORS[h.status] || COLORS.unknown} opacity={h.status === "unmatched_small" ? 0.55 : 0.95}>
                      <title>{`${h.status} · ${h.length_m} m${h.name ? " · " + h.name : ""}`}</title></circle>
                  </g>); })}
                {ghosts.map((g, i) => { const [x, y] = xy(g); return (
                  <g key={"g" + i}><circle cx={x} cy={y} r="5" fill="none" stroke="#fb7185" strokeDasharray="2 2" /><line x1={x - 3} y1={y - 3} x2={x + 3} y2={y + 3} stroke="#fb7185" /><line x1={x - 3} y1={y + 3} x2={x + 3} y2={y - 3} stroke="#fb7185" />
                    <title>{`ghost AIS · ${g.name || g.mmsi}`}</title></g>); })}
                <circle cx="320" cy="320" r="2.5" fill="#7dd3fc" />
              </svg>
            ) : snap && snap.image_url ? (
              <div className="opt">
                <div style={{ width: `${zoom * 100}%`, position: "relative" }}>
                  <img src={snap.image_url} alt="satellite" style={{ width: "100%", display: "block" }} />
                  <svg viewBox={`0 0 ${snap.width_px} ${snap.height_px}`} preserveAspectRatio="none">
                    {hulls.filter((h) => (h.status !== "unmatched_small" && h.status !== "unknown") || h.length_m >= 150).map((h) => (
                      <circle key={h.id} cx={h.col} cy={h.row} r={h.pair ? 22 : 14} fill="none" stroke={h.pair ? "#22d3ee" : COLORS[h.status] || COLORS.unknown} strokeWidth="3" />
                    ))}
                  </svg>
                </div>
              </div>
            ) : <div className="note">No image stored.</div>}
          </div>
          <div className="box">
            <div className="head">
              {S.vessels_total} vessels seen · {S.large_total} large (150 m+) · <span style={{ color: "#34d399" }}>{S.large_matched} with AIS in feed</span>
              {" "}({Math.round((100 * S.large_matched) / Math.max(S.large_total, 1))}%)
            </div>
            <div className="kv">
              <span style={{ color: "#ef4444" }}>No AIS match (large)</span><b>{S.no_ais_large}</b>
              <span style={{ color: "#f59e0b" }}>AIS position offset</span><b>{S.displaced}</b>
              <span style={{ color: "#fb7185" }}>Ghost AIS (no vessel)</span><b>{S.ghost}</b>
              <span style={{ color: "#22d3ee" }}>Hull-to-hull pairs</span><b>{S.alongside_pairs}{S.sam_contact_pairs ? ` (${S.sam_contact_pairs} SAM contact)` : ""}</b>
              <span>AIS ships in feed</span><b>{S.ais_in_feed}</b>
              <span>Moving, position unknown</span><b>{S.moving_dropped}</b>
              <span>Scene</span><b>{a == null ? "?" : a + " h old"} · {snap ? snap.cloud_pct : "?"}% cloud</b>
            </div>
            <details open><summary>Dark / no AIS match ({dark.length})</summary>
              {dark.slice(0, 60).map((h) => <div className="row" key={h.id}><span>#{h.id} {h.length_m} m{h.pair ? " · pair" : ""}</span><span>{h.lat.toFixed(4)}, {h.lon.toFixed(4)} · motion unknown</span></div>)}</details>
            <details><summary>Position offsets ({displaced.length})</summary>
              {displaced.map((h) => <div className="row" key={h.id}><span>{h.name || h.mmsi}</span><span>{h.offset_m} m from claim</span></div>)}</details>
            <details><summary>Ghost AIS signals ({ghosts.length})</summary>
              {ghosts.map((g, i) => <div className="row" key={i}><span>{g.name || g.mmsi}</span><span>{g.lat.toFixed(4)}, {g.lon.toFixed(4)} · {g.age_min} min old</span></div>)}</details>
            <details><summary>Hull-to-hull pairs ({(pairs.length / 2) | 0})</summary>
              {pairs.map((h) => <div className="row" key={h.id}><span>#{h.id} {h.length_m} m</span><span>{h.lat.toFixed(4)}, {h.lon.toFixed(4)}</span></div>)}</details>
            <div className="note">
              "No AIS match" means no report in the provider's history within 24 h of the pass. Feed coverage of large vessels: {Math.round(S.feed_coverage_large * 100)}%.
              Ghost = no vessel at the claimed position (not proof of spoofing). Pairs are candidates: the image shows two hulls in contact, not a cargo transfer.
            </div>
          </div>
        </div>
      )}
      <div className="box run">
        <button className="runbtn" disabled={running || !zone} onClick={run}>{running ? "ANALYSIS RUNNING…" : "RUN NEW ANALYSIS"}</button>
        {job && (<>
          <div className="bar"><i style={{ width: `${job.pct}%` }} /></div>
          <div style={{ fontSize: 11 }}>{job.pct}% · {job.error ? "ERROR: " + job.error : job.stage}</div>
          <div className="log">{job.lines.map((l, i) => <div key={i}>{l}</div>)}</div>
        </>)}
      </div>
    </div>
  );
}
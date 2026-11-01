import React, { useEffect, useMemo, useState } from 'react';
import OpticalViewer from './OpticalViewer.jsx';
import RadarScope from './RadarScope.jsx';
import './spatial.css';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');

function badge(zone) {
  const latest = zone?.latest;
  if (!latest) return { cls: 'warn', text: 'NO CAPTURE' };
  if (latest.status === 'analyzing' || latest.analysis_pending) return { cls: 'warn', text: 'ANALYZING' };
  if (latest.status === 'verified') return { cls: '', text: 'SYNCED' };
  return { cls: '', text: (latest.status || 'STORED').toUpperCase() };
}

export default function SpatialIntelligence() {
  const [zones, setZones] = useState([]);
  const [zoneId, setZoneId] = useState('fujairah');
  const [analysis, setAnalysis] = useState(null);
  const [job, setJob] = useState(null);
  const [cursor, setCursor] = useState(0);
  const [error, setError] = useState('');

  const loadZones = () => {
    fetch(`${API_BASE_URL}/api/spatial/zones`)
      .then((r) => r.json())
      .then((d) => {
        const list = d.zones || [];
        setZones(list);
        if (list.length && !list.some((z) => z.zone_id === zoneId)) setZoneId(list[0].zone_id);
      })
      .catch(() => setError('API unreachable'));
  };

  const loadAnalysis = (id) => {
    fetch(`${API_BASE_URL}/api/spatial/zones/${id}/analysis`)
      .then((r) => r.json())
      .then(setAnalysis)
      .catch(() => setAnalysis(null));
  };

  useEffect(() => { loadZones(); }, []);
  useEffect(() => { if (zoneId) loadAnalysis(zoneId); }, [zoneId]);

  useEffect(() => {
    if (!job?.job_id || job.done) return undefined;
    const t = setInterval(() => {
      fetch(`${API_BASE_URL}/api/spatial/jobs/${job.job_id}?since=${cursor}`)
        .then((r) => r.json())
        .then((snap) => {
          setJob((prev) => ({
            ...prev,
            ...snap,
            lines: [...(prev.lines || []), ...(snap.lines || [])],
          }));
          setCursor(snap.next || cursor);
          if (snap.done) {
            loadAnalysis(zoneId);
            loadZones();
          }
        })
        .catch(() => {});
    }, 1500);
    return () => clearInterval(t);
  }, [job?.job_id, job?.done, cursor, zoneId]);

  const run = () => {
    fetch(`${API_BASE_URL}/api/spatial/zones/${zoneId}/run`, { method: 'POST' })
      .then((r) => r.json())
      .then((d) => {
        setCursor(0);
        setJob({ job_id: d.job_id, lines: [], pct: 0, done: false });
      });
  };

  const zoneMeta = zones.find((z) => z.zone_id === zoneId);
  const summary = analysis?.summary || {};
  const hulls = analysis?.hulls || [];
  const dark = hulls.filter((h) => h.status === 'dark');
  const ghosts = analysis?.ghosts || [];
  const displaced = analysis?.displaced || [];
  const census = useMemo(() => hulls.slice().sort((a, b) => (b.length_m || 0) - (a.length_m || 0)), [hulls]);
  const b = badge(zoneMeta);
  if (dark.length || ghosts.length) b.cls = 'alert';
  if (dark.length || ghosts.length) b.text = 'ANOMALY';

  return (
    <div className="sp-root">
      <div className="sp-toolbar">
        {zones.map((z) => {
          const bb = badge(z);
          return (
            <button key={z.zone_id} type="button" className={`sp-zone-btn ${z.zone_id === zoneId ? 'active' : ''}`} onClick={() => setZoneId(z.zone_id)}>
              <span className="sp-zone-name">{z.display_name}</span>
              <span className={`sp-badge ${bb.cls}`}>{bb.text}</span>
            </button>
          );
        })}
      </div>
      <div className="sp-actions">
        <button type="button" onClick={run}>RUN ANALYSIS</button>
        <span className={`sp-badge ${b.cls}`}>{zoneMeta?.display_name || zoneId} · Sentinel-2 optical, 10 m per pixel</span>
      </div>
      {error && <div className="sp-empty">{error}</div>}
      {!zoneMeta?.latest && <div className="sp-empty">{zoneMeta?.status_message || 'No clear capture stored yet.'}</div>}
      <div className="sp-main">
        <div className="sp-panel">
          <h3>TACTICAL RADAR</h3>
          <RadarScope zone={analysis?.zone || zoneMeta} hulls={hulls} ghosts={ghosts} />
        </div>
        <div className="sp-panel">
          <h3>OPTICAL INSPECTOR</h3>
          <OpticalViewer
            imageUrl={analysis?.snapshot?.image_url || zoneMeta?.latest?.image_url}
            hulls={hulls}
            widthPx={analysis?.snapshot?.width_px || zoneMeta?.latest?.width_px}
            heightPx={analysis?.snapshot?.height_px || zoneMeta?.latest?.height_px}
          />
        </div>
        <div className="sp-panel sp-drawers">
          <details className="sp-drawer" open>
            <summary>DARK VESSELS ({dark.length})</summary>
            {dark.length === 0 && <div className="sp-empty">None in this scene.</div>}
            {dark.map((h) => (
              <div className="sp-row" key={h.id}><span>{Math.round(h.length_m)} m</span><span>{h.lat?.toFixed(3)}, {h.lon?.toFixed(3)}</span></div>
            ))}
          </details>
          <details className="sp-drawer">
            <summary>GHOST / DISPLACED ({ghosts.length + displaced.length})</summary>
            {ghosts.map((g, i) => (
              <div className="sp-row" key={`g${i}`}><span>{g.name || g.mmsi}</span><span>age {g.age_min} min</span></div>
            ))}
            {displaced.map((d, i) => (
              <div className="sp-row" key={`d${i}`}><span>{d.name || d.mmsi}</span><span>offset {d.offset_m} m</span></div>
            ))}
          </details>
          <details className="sp-drawer">
            <summary>VESSEL CENSUS ({census.length})</summary>
            <div className="sp-row"><span>LARGE {summary.large_total ?? '—'}</span><span>MATCHED {summary.large_matched ?? '—'}</span></div>
            <div className="sp-row"><span>NO AIS LARGE {summary.no_ais_large ?? '—'}</span><span>GHOST {summary.ghost ?? 0}</span></div>
            {census.slice(0, 40).map((h) => (
              <div className="sp-row" key={`c${h.id}`}>
                <span>{h.size_class} {Math.round(h.length_m)}×{Math.round(h.width_m || 0)} m</span>
                <span>{h.status}</span>
              </div>
            ))}
          </details>
        </div>
      </div>
      <div className="sp-log">
        <div className="sp-bar"><i style={{ width: `${job?.pct || 0}%` }} /></div>
        <div>{job ? `${job.pct || 0}% ${job.stage || ''}` : 'Idle. Run analysis to stream job logs.'}</div>
        {(job?.lines || []).map((ln, i) => <div key={i}>{ln}</div>)}
        {job?.error && <div>ERROR: {job.error}</div>}
      </div>
    </div>
  );
}

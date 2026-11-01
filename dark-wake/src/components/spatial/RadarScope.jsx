import React, { useMemo, useState } from 'react';

function toXY(rangeKm, bearingDeg, maxRange, size) {
  const r = (rangeKm / maxRange) * (size / 2 - 16);
  const rad = (bearingDeg * Math.PI) / 180;
  return [size / 2 + r * Math.sin(rad), size / 2 - r * Math.cos(rad)];
}

const COLOR = {
  matched: '#34d399',
  displaced: '#f59e0b',
  dark: '#f43f5e',
  ghost: '#fb7185',
  unmatched_small: '#64748b',
};

export default function RadarScope({ zone, hulls = [], ghosts = [], maxRange: maxRangeProp }) {
  const [zoom, setZoom] = useState(1);
  const [grid, setGrid] = useState(true);
  const size = 420;
  const rings = zone?.range_rings_km || [5, 10, 20];
  const maxRange = maxRangeProp || rings[rings.length - 1] || 20;

  const marks = useMemo(() => {
    const items = hulls.map((h) => ({
      key: `h-${h.id}`,
      range_km: h.range_km,
      bearing_deg: h.bearing_deg,
      status: h.status,
      title: `${h.status} ${Math.round(h.length_m || 0)}m`,
    }));
    ghosts.forEach((g, i) => {
      items.push({
        key: `g-${i}`,
        range_km: g.range_km,
        bearing_deg: g.bearing_deg,
        status: 'ghost',
        title: `ghost ${g.mmsi || ''}`,
      });
    });
    return items.filter((m) => m.range_km != null && m.bearing_deg != null);
  }, [hulls, ghosts]);

  return (
    <div>
      <div className="sp-toggles">
        <label><input type="checkbox" checked={grid} onChange={() => setGrid((v) => !v)} /> GRID</label>
        <button type="button" onClick={() => setZoom((z) => Math.min(3, z + 0.25))}>ZOOM+</button>
        <button type="button" onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}>ZOOM-</button>
      </div>
      <svg className="sp-radar" viewBox={`0 0 ${size} ${size}`} style={{ transform: `scale(${zoom})`, transformOrigin: 'center' }}>
        {grid && [0.25, 0.5, 0.75, 1].map((f) => (
          <circle key={f} cx={size / 2} cy={size / 2} r={(size / 2 - 16) * f} fill="none" stroke="#1e293b" />
        ))}
        {rings.map((km) => (
          <circle key={km} cx={size / 2} cy={size / 2} r={(km / maxRange) * (size / 2 - 16)} fill="none" stroke="#06b6d4" strokeOpacity="0.35" />
        ))}
        <line x1={size / 2} y1={8} x2={size / 2} y2={size - 8} stroke="#1e293b" />
        <line x1={8} y1={size / 2} x2={size - 8} y2={size / 2} stroke="#1e293b" />
        <circle cx={size / 2} cy={size / 2} r="3" fill="#06b6d4" />
        {marks.map((m) => {
          const [x, y] = toXY(m.range_km, m.bearing_deg, maxRange, size);
          return <circle key={m.key} cx={x} cy={y} r={m.status === 'dark' ? 5 : 3.5} fill={COLOR[m.status] || '#94a3b8'}><title>{m.title}</title></circle>;
        })}
      </svg>
    </div>
  );
}

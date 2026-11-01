import React from 'react';

function hullPath(h, w, ht) {
  const col = h.col;
  const row = h.row;
  if (col == null || row == null || !w || !ht) return null;
  const lx = (h.length_m || 40) / 20;
  const ly = (h.width_m || 12) / 20;
  const x = (col / w) * 100;
  const y = (row / ht) * 100;
  return { cx: `${x}%`, cy: `${y}%`, rx: `${Math.max(0.4, lx)}%`, ry: `${Math.max(0.25, ly)}%` };
}

export default function OpticalViewer({ imageUrl, hulls = [], widthPx, heightPx }) {
  if (!imageUrl) {
    return <div className="sp-empty">No clear capture stored yet for this zone.</div>;
  }
  return (
    <div className="sp-opt">
      <img src={imageUrl} alt="Sentinel-2 10m optical" />
      <svg viewBox="0 0 100 100" preserveAspectRatio="none">
        {hulls.map((h) => {
          const p = hullPath(h, widthPx, heightPx);
          if (!p) return null;
          const stroke = h.status === 'dark' ? '#f43f5e' : h.status === 'matched' ? '#06b6d4' : '#f59e0b';
          return (
            <ellipse
              key={h.id}
              cx={p.cx}
              cy={p.cy}
              rx={p.rx}
              ry={p.ry}
              fill="none"
              stroke={stroke}
              strokeWidth="0.35"
            />
          );
        })}
      </svg>
    </div>
  );
}

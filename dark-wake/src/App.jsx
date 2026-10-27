import React, { useState, useEffect } from 'react';
import './App.css';
import { getDailyTrafficDisplay } from './dailyTrafficDisplay.js';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000')
  .replace(/\/+$/, '');

const formatLondonDateTime = value => {
  if (!value) return 'NO ANALYSIS RECORDED';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'TIME UNAVAILABLE';
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/London',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(date);
};

const formatDeskAgentName = name => ({
  'Bull Case': 'Supply Thesis',
  'Bear Case': 'Demand Thesis',
  'Risk Manager': 'Desk Signal & Risk Synthesis',
}[name] || name);

export default function App() {
  const [activeTab, setActiveTab] = useState('news');
  const [brentData, setBrentData] = useState({ price: '100.95', change_pct: '-0.61' });
  const [articles, setArticles] = useState([]);
  const [showAllModal, setShowAllModal] = useState(false);
  const [strategyDeskAnalyses, setStrategyDeskAnalyses] = useState([]);
  const [activeAnalysis, setActiveAnalysis] = useState(null);
  const [strategyDeskLoading, setStrategyDeskLoading] = useState(false);
  const [strategyDeskError, setStrategyDeskError] = useState('');

  // Chokepoint telemetry data state
  const [chokepointRecords, setChokepointRecords] = useState([]);
  const [portwatchDataAsOf, setPortwatchDataAsOf] = useState(null);
  const [chokepointTab, setChokepointTab] = useState('hormuz');
  const [showFullChokepointModal, setShowFullChokepointModal] = useState(false);
  const [spatialChokepoint, setSpatialChokepoint] = useState('hormuz');
  const [spatialSnapshots, setSpatialSnapshots] = useState([]);
  const [snapshotsLoading, setSnapshotsLoading] = useState(false);

  const fetchSnapshots = () => {
    setSnapshotsLoading(true);
    fetch(`${API_BASE_URL}/api/spatial/snapshots`)
      .then(r => r.json())
      .then(data => setSpatialSnapshots(data.snapshots || []))
      .catch(() => setSpatialSnapshots([]))
      .finally(() => setSnapshotsLoading(false));
  };

  useEffect(() => {
    fetchSnapshots();
  }, []);

  const [spatialTelemetry] = useState({
    hormuz: { index: 62, vessels: 47, latency: 'Medium' },
    bab: { index: 38, vessels: 31, latency: 'Low' },
    malacca: { index: 71, vessels: 58, latency: 'High' },
  });
  const [spatialSnapshots, setSpatialSnapshots] = useState([]);

  const [priceHistory, setPriceHistory] = useState([
    { time: '2:00 AM', price: 100.50 },
    { time: '4:00 AM', price: 100.80 },
    { time: '6:00 AM', price: 99.20 },
    { time: '8:00 AM', price: 98.50 },
    { time: '10:00 AM', price: 97.60 },
    { time: '12:00 PM', price: 100.95 }
  ]);

  const defaultArticles = [
    { id: 1, title: 'OPEC+ Signals Potential Output Adjustments as Brent Prices Shift', source: 'Reuters Energy', time_ago: '12m ago', sentiment: 'Bullish' },
    { id: 2, title: 'Tanker Traffic Holds Steady Across Key Maritime Routes', source: 'Lloyd’s List', time_ago: '45m ago', sentiment: 'Neutral' },
  ];

  useEffect(() => {
    const fetchData = () => {
      // Fetch the latest available Brent market snapshot
      fetch(`${API_BASE_URL}/api/market/prices`)
        .then(res => res.json())
        .then(data => {
          if (data.price) {
            setBrentData(data);
            if (Array.isArray(data.history) && data.history.length > 0) {
              setPriceHistory(data.history);
            }
          }
        })
        .catch(() => console.log("Market endpoint offline."));

      // Fetch news feed
      fetch(`${API_BASE_URL}/api/news/feed`)
        .then(res => res.json())
        .then(data => {
          if (Array.isArray(data) && data.length > 0) {
            const sortedData = [...data].sort((a, b) => {
              const aTime = Date.parse(a.published_at || a.created_at || '') || 0;
              const bTime = Date.parse(b.published_at || b.created_at || '') || 0;
              return bTime - aTime;
            });
            setArticles(sortedData);
          } else {
            setArticles(defaultArticles);
          }
        })
        .catch(() => setArticles(prev => prev.length > 0 ? prev : defaultArticles));

      // Fetch Chokepoint telemetry records
      fetch(`${API_BASE_URL}/api/chokepoints`)
        .then(res => res.json())
        .then(resData => {
          if (resData.data && Array.isArray(resData.data)) {
            setChokepointRecords(resData.data);
          }
          setPortwatchDataAsOf(resData.portwatch_data_as_of || null);
        })
        .catch(() => console.log("Chokepoint API offline."));
    };

    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (activeTab !== 'strategy-desk') return;
    let cancelled = false;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);

    setStrategyDeskLoading(true);
    setStrategyDeskError('');
    fetch(`${API_BASE_URL}/api/strategy-desk/debates`, { signal: controller.signal })
      .then(async response => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not load Strategy Desk history.');
        return data;
      })
      .then(data => {
        if (cancelled) return;
        setStrategyDeskAnalyses(Array.isArray(data) ? data : []);
        setActiveAnalysis(data?.[0] || null);
        setStrategyDeskError('');
      })
      .catch(error => {
        if (cancelled) return;
        setStrategyDeskError(error.name === 'AbortError'
          ? 'Loading saved Strategy Desk analyses timed out. Check the backend connection and try again.'
          : error.message || 'Strategy Desk API is unavailable.');
      })
      .finally(() => {
        clearTimeout(timeout);
        if (!cancelled) setStrategyDeskLoading(false);
      });

    return () => {
      cancelled = true;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [activeTab]);

  // Filter chokepoint data by selected tab ('hormuz' or 'bab')
  const filteredChokepoints = chokepointRecords.filter(r => {
    const name = (r.chokepoint || '').toLowerCase();
    if (chokepointTab === 'hormuz') {
      return name.includes('hormuz');
    } else {
      return name.includes('bab') || name.includes('mandeb');
    }
  });

  // Use each chokepoint's actual latest source record; missing values stay unavailable.
  const getLatestRecord = predicate => chokepointRecords
    .filter(predicate)
    .reduce((latest, record) => !latest || record.date > latest.date ? record : latest, null);
  const hormuzLatest = getLatestRecord(r => (r.chokepoint || '').toLowerCase().includes('hormuz'));
  const babLatest = getLatestRecord(r => {
    const name = (r.chokepoint || '').toLowerCase();
    return name.includes('bab') || name.includes('mandeb');
  });
  const hormuzTraffic = getDailyTrafficDisplay(hormuzLatest);
  const babTraffic = getDailyTrafficDisplay(babLatest);

  // Prepare chart data for last 90 days vs full history
  const sortedCPData = [...filteredChokepoints].sort((a, b) => new Date(a.date) - new Date(b.date));
  const last90DaysData = sortedCPData.slice(-90);
  const chartSource = sortedCPData.at(-1)?.source || 'No source data';
  const chartHasOilFlow = last90DaysData.some(
    record => Number.isFinite(record.estimated_oil_flow_million_bbl)
  );
  const latestTransitCount = sortedCPData.at(-1)?.tankers ?? sortedCPData.at(-1)?.vessel_count_tanker ?? null;
  const recentTransitRecords = sortedCPData.slice(-7);
  const averageRecentTransits = recentTransitRecords.length
    ? recentTransitRecords.reduce(
      (total, record) => total + (record.tankers ?? record.vessel_count_tanker ?? 0),
      0
    ) / recentTransitRecords.length
    : null;

  // PortWatch reports tanker capacity in metric tons; convert to approximate barrel equivalents.
  const maxBarrels = Math.max(...last90DaysData.map(d => d.estimated_oil_flow_million_bbl ?? 0), 1);
  const barrelPointsString = last90DaysData.map((rec, idx) => {
    const barrels = rec.estimated_oil_flow_million_bbl ?? 0;
    const x = last90DaysData.length > 1 ? (idx / (last90DaysData.length - 1)) * 800 : 400;
    const y = 160 - (barrels / maxBarrels) * 130;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');

  // Price chart calculations
  const prices = priceHistory.map(p => p.price);
  const minPrice = Math.min(...prices) * 0.995;
  const maxPrice = Math.max(...prices) * 1.005;
  const priceRange = maxPrice - minPrice || 1;

  const pointsString = priceHistory.map((p, idx) => {
    const x = (idx / (priceHistory.length - 1 || 1)) * 500;
    const y = 200 - ((p.price - minPrice) / priceRange) * 200;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');

  const polygonPoints = `0,200 ${pointsString} 500,200`;
  const lastPoint = priceHistory[priceHistory.length - 1] || { price: 100.95 };
  const lastY = 200 - ((lastPoint.price - minPrice) / priceRange) * 200;

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="header-left">
          <div className="status-dot"></div>
          <h1 className="app-title">DARK WAKE</h1>
          <span className="badge">MARITIME INTEL v0.2.1</span>
        </div>

        <nav className="nav-tabs">
          {[
            { id: 'news', label: 'News & Price' },
            { id: 'strategy-desk', label: 'Energy Strategy Desk' },
            { id: 'spatial-intelligence', label: 'Spatial Intelligence' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`nav-btn ${activeTab === tab.id ? 'active' : ''}`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="main-content">
        {activeTab === 'news' && (
          <div className="space-y-6">
            {/* Top Cards Row */}
            <div className="cards-grid-5">
              <div className="card">
                <p className="card-label">BrentCash (BZ=F)</p>
                <p className="card-value emerald">
                  ${brentData.price}{' '}
                  <span className={Number(brentData.change_pct) >= 0 ? 'text-emerald' : 'text-rose'}>
                    {Number(brentData.change_pct) >= 0 ? `+${brentData.change_pct}%` : `${brentData.change_pct}%`}
                  </span>
                </p>
                <span className="source-tag">
                  {brentData.price_basis === 'last_close'
                    ? `Yahoo Finance · Last close ${brentData.price_as_of || ''}`
                    : 'Source: Yahoo Finance'}
                </span>
              </div>
              <div className="card">
                <p className="card-label">Strait of Hormuz Traffic</p>
                <p className="card-value">
                  {hormuzTraffic.value}
                </p>
                <p className="card-subdate">
                  {hormuzTraffic.date}
                </p>
                <span className="source-tag">{hormuzTraffic.source}</span>
              </div>
              <div className="card">
                <p className="card-label">Bab el-Mandeb Traffic</p>
                <p className="card-value">{babTraffic.value}</p>
                <p className="card-subdate">{babTraffic.date}</p>
                <span className="source-tag">{babTraffic.source}</span>
              </div>
              <div className="card">
                <p className="card-label">News Sources</p>
                <p className="card-value">4 Sources</p>
                <span className="source-tag">3 RSS feeds · TankerMap News</span>
              </div>
              <div className="card">
                <p className="card-label">System Status</p>
                <p className="card-value emerald">Online</p>
                <span className="source-tag">Source: Internal Health Check</span>
              </div>
            </div>

            <div className="news-layout">
              {/* SVG Line Chart Panel */}
              <div className="chart-panel">
                <div className="panel-header-flex">
                  <div>
                    <h3 className="panel-title">Brent Crude Oil Futures (BZ=F)</h3>
                    <span className="chart-subtext">
                      {brentData.price_basis === 'last_close'
                        ? 'NY Mercantile // Daily Closing Prices'
                        : 'NY Mercantile // Intraday Spot Trend'}
                    </span>
                  </div>
                  <span className="source-badge">Yahoo Finance</span>
                </div>

                <div className="chart-canvas-area">
                  <div className="chart-wrapper">
                    <svg className="line-chart-svg" viewBox="0 0 500 200" preserveAspectRatio="none">
                      <defs>
                        <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#f43f5e" stopOpacity="0.35" />
                          <stop offset="100%" stopColor="#f43f5e" stopOpacity="0.0" />
                        </linearGradient>
                      </defs>

                      <line x1="0" y1="0" x2="500" y2="0" stroke="#1e293b" strokeDasharray="4 4" />
                      <line x1="0" y1="50" x2="500" y2="50" stroke="#1e293b" strokeDasharray="4 4" />
                      <line x1="0" y1="100" x2="500" y2="100" stroke="#1e293b" strokeDasharray="4 4" />
                      <line x1="0" y1="150" x2="500" y2="150" stroke="#1e293b" strokeDasharray="4 4" />
                      <line x1="0" y1="200" x2="500" y2="200" stroke="#1e293b" strokeDasharray="4 4" />

                      <polygon fill="url(#chartGradient)" points={polygonPoints} />
                      <polyline fill="none" stroke="#f43f5e" strokeWidth="2" points={pointsString} />
                      <circle cx="500" cy={isNaN(lastY) ? 100 : lastY} r="4" fill="#f43f5e" />
                    </svg>

                    <div className="chart-y-axis">
                      <span>{maxPrice.toFixed(2)}</span>
                      <span>{(minPrice + priceRange * 0.75).toFixed(2)}</span>
                      <span>{(minPrice + priceRange * 0.5).toFixed(2)}</span>
                      <span>{(minPrice + priceRange * 0.25).toFixed(2)}</span>
                      <span>{minPrice.toFixed(2)}</span>
                    </div>
                  </div>

                  <div className="chart-x-axis">
                    {priceHistory.map((p, idx) => (
                      <span key={idx}>{p.time}</span>
                    ))}
                  </div>
                </div>
              </div>

              {/* News Feed Panel */}
              <div className="news-panel">
                <div className="panel-header-flex">
                  <h3 className="panel-title">Energy Market & Supply Chain News</h3>
                  <button onClick={() => setShowAllModal(true)} className="view-all-btn">
                    View All ({articles.length})
                  </button>
                </div>
                <div className="news-feed-list">
                  {articles.slice(0, 10).map((art, idx) => (
                    <div key={idx} className="news-item">
                      <div className="news-meta">
                        <span className="news-source">{art.source}</span>
                        <span className="news-time">{art.time_ago || 'Just now'}</span>
                      </div>
                      <h4 className="news-headline">
                        <a href={art.link} target="_blank" rel="noopener noreferrer" className="news-link">
                          {art.title}
                        </a>
                      </h4>
                      <span className={`sentiment-badge ${art.sentiment?.toLowerCase() || 'neutral'}`}>
                        {art.sentiment || 'Neutral'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Chokepoint Maritime Intelligence Section */}
            <div className="chokepoint-section">
              <div className="panel-header-flex">
                <div>
                  <h3 className="panel-title">Maritime Route Density & Bottleneck Analytics</h3>
                  <span className="chart-subtext">
                    {chartSource === 'TankerMap'
                      ? `Daily AIS tanker transits · TankerMap data through ${sortedCPData.at(-1)?.date || 'unavailable'}${portwatchDataAsOf ? ` · IMF PortWatch oil-flow data is separate (latest ${portwatchDataAsOf})` : ''}`
                      : `Daily vessel counts & estimated oil flow · ${chartSource} latest record ${sortedCPData.at(-1)?.date || 'unavailable'}`}
                  </span>
                </div>
                <div className="chokepoint-controls">
                  <div className="tab-group">
                    <button
                      onClick={() => setChokepointTab('hormuz')}
                      className={`sub-tab-btn ${chokepointTab === 'hormuz' ? 'active' : ''}`}
                    >
                      Strait of Hormuz
                    </button>
                    <button
                      onClick={() => setChokepointTab('bab')}
                      className={`sub-tab-btn ${chokepointTab === 'bab' ? 'active' : ''}`}
                    >
                      Bab el-Mandeb
                    </button>
                  </div>
                  <button onClick={() => setShowFullChokepointModal(true)} className="view-all-btn">
                    View Full Chart ({sortedCPData.length} Days)
                  </button>
                </div>
              </div>

              <div className="chokepoint-chart-container telemetry-chart">
                <div className="telemetry-chart-summary">
                  <div>
                    <span className="telemetry-stat-label">LATEST DAILY TRANSITS</span>
                    <strong>{latestTransitCount ?? '—'}</strong>
                    <span className="telemetry-stat-date">{sortedCPData.at(-1)?.date || 'No recent record'}</span>
                  </div>
                  <div>
                    <span className="telemetry-stat-label">7-DAY DAILY AVERAGE</span>
                    <strong>{averageRecentTransits == null ? '—' : averageRecentTransits.toFixed(1)}</strong>
                    <span className="telemetry-stat-date">Tanker transits / day</span>
                  </div>
                  <div className="telemetry-source-pill">
                    <span className="telemetry-source-dot" />
                    {chartSource}
                  </div>
                </div>
                <div className="chokepoint-chart-header-info">
                  <span className="legend-item"><span className="dot-tankers"></span> Daily tanker transits</span>
                  {chartHasOilFlow && (
                    <span className="legend-item"><span className="dot-barrels"></span> Est. Oil Flow (Million bbl eq./day)</span>
                  )}
                  <span className="telemetry-range-label">LAST {last90DaysData.length} DAYS</span>
                </div>

                {last90DaysData.length === 0 ? (
                  <div className="no-data-msg">No chokepoint telemetry is available.</div>
                ) : (
                  <div className="chokepoint-chart-overlap-wrapper telemetry-plot">
                    {chartHasOilFlow && (
                      <svg className="chokepoint-line-overlay" viewBox="0 0 800 160" preserveAspectRatio="none">
                        <polyline fill="none" stroke="#f59e0b" strokeWidth="2.5" points={barrelPointsString} />
                      </svg>
                    )}

                    {/* Underlying Bars for Vessels */}
                    <div className="chokepoint-bars-grid telemetry-bars-grid">
                      {last90DaysData.map((rec, i) => {
                        const maxTankers = Math.max(...last90DaysData.map(d => d.tankers ?? d.vessel_count_tanker ?? 0), 1);
                        const tCount = rec.tankers ?? rec.vessel_count_tanker ?? 0;
                        const heightPct = (tCount / maxTankers) * 100;
                        const estimatedBarrels = (rec.estimated_oil_flow_million_bbl ?? 0).toFixed(2);

                        return (
                          <div key={i} className="chokepoint-bar-col telemetry-bar-column" title={`Date: ${rec.date}\nTanker transits: ${tCount}${rec.estimated_oil_flow_million_bbl == null ? '' : `\nEst. Oil Flow: ${estimatedBarrels}M bbl equivalent/day`}`}>
                            <div className="bar-tooltip-val telemetry-bar-value">{tCount}</div>
                            <div className="bar-fill-track">
                              <div className="bar-fill-tankers telemetry-bar-fill" style={{ height: `${heightPct}%` }}></div>
                            </div>
                            <span className="bar-date-label telemetry-date-label">{rec.date.slice(5)}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'spatial-intelligence' && (
          <div className="space-y-6">
            <div className="panel-header-flex">
              <div>
                <h2 className="panel-title">SAM 3.1 Spatial Intelligence</h2>
                <span className="chart-subtext">Satellite segmentation · Chokepoint congestion · Vessel cluster masks</span>
              </div>
              <span className="source-badge">Mock SAM 3.1 · Zero-fail fallback</span>
            </div>

            <div className="cards-grid-3">
              <button onClick={() => setSpatialChokepoint('hormuz')} className={`card ${spatialChokepoint === 'hormuz' ? 'active-card' : ''}`}>
                <p className="card-label">Strait of Hormuz</p>
                <p className="card-value">{spatialTelemetry.hormuz.index}</p>
                <span className="source-tag">Congestion Index 0–100</span>
              </button>
              <button onClick={() => setSpatialChokepoint('bab')} className={`card ${spatialChokepoint === 'bab' ? 'active-card' : ''}`}>
                <p className="card-label">Bab el-Mandeb</p>
                <p className="card-value">{spatialTelemetry.bab.index}</p>
                <span className="source-tag">Congestion Index 0–100</span>
              </button>
              <button onClick={() => setSpatialChokepoint('malacca')} className={`card ${spatialChokepoint === 'malacca' ? 'active-card' : ''}`}>
                <p className="card-label">Malacca Strait</p>
                <p className="card-value">{spatialTelemetry.malacca.index}</p>
                <span className="source-tag">Congestion Index 0–100</span>
              </button>
            </div>

            <div className="spatial-snapshots-panel">
              <div className="panel-header-flex">
                <div>
                  <h3>Satellite Snapshots — {spatialChokepoint === 'hormuz' ? 'Strait of Hormuz' : spatialChokepoint === 'bab' ? 'Bab el-Mandeb' : spatialChokepoint === 'malacca' ? 'Malacca Strait' : 'Suez Canal'}</h3>
                  <span className="chart-subtext">Last 3 days · {snapshotsLoading ? 'Loading…' : snapshots.length + ' records'}</span>
                </div>
                <button onClick={fetchSnapshots} className="refresh-btn" disabled={snapshotsLoading}>↻ Refresh</button>
              </div>
              {snapshotsLoading ? (
                <div className="snapshot-grid"><p className="no-data-msg">Loading satellite snapshots…</p></div>
              ) : snapshots.length === 0 ? (
                <div className="snapshot-grid"><p className="no-data-msg">No satellite snapshots loaded yet.</p></div>
              ) : (
                <div className="snapshot-grid">
                  {snapshots.map((snap, i) => (
                    <div key={snap.id || i} className="snapshot-card">
                      <img src={snap.image_url} alt={snap.location_name} className="snapshot-img" />
                      <div className="snapshot-meta">
                        <strong>{snap.location_name}</strong>
                        <span>{snap.captured_at ? new Date(snap.captured_at).toLocaleString() : '—'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="telemetry-panel">
              <h3>Spatial Telemetry — {spatialChokepoint === 'hormuz' ? 'Strait of Hormuz' : spatialChokepoint === 'bab' ? 'Bab el-Mandeb' : spatialChokepoint === 'malacca' ? 'Malacca Strait' : 'Suez Canal'}</h3>
              <div className="telemetry-grid">
                <div><span>Spatial Congestion Index</span><strong>{spatialTelemetry[spatialChokepoint].index} / 100</strong></div>
                <div><span>Estimated Vessel Count</span><strong>{spatialTelemetry[spatialChokepoint].vessels}</strong></div>
                <div><span>Transit Latency Risk</span><strong>{spatialTelemetry[spatialChokepoint].latency}</strong></div>
                <div><span>SAM 3.1 Token</span><strong>mock-token-{spatialChokepoint}</strong></div>
              </div>
            </div>

            <div className="spatial-snapshots-panel">
              <h3>Satellite Snapshots — 3-Day Rolling Window</h3>
              <div className="snapshot-grid">
                {spatialSnapshots.length === 0 ? (
                  <p className="no-data-msg">No satellite snapshots loaded yet.</p>
                ) : (
                  spatialSnapshots.map((snap, i) => (
                    <div key={snap.id || i} className="snapshot-card">
                      <img src={snap.image_url} alt={snap.location_name} className="snapshot-img" />
                      <div className="snapshot-meta">
                        <strong>{snap.location_name}</strong>
                        <span>{snap.captured_at ? new Date(snap.captured_at).toLocaleString() : '—'}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'strategy-desk' && (
          <section className="war-room">
            <div className="war-room-header">
              <div>
                <div className="war-room-eyebrow"><span className="war-room-live-dot" /> DARK WAKE / ENERGY INTELLIGENCE</div>
                <h2>Brent crude <span>Strategy Desk</span></h2>
                <p>Multi-agent market analysis · Instrument <b>Brent / BZ=F</b></p>
              </div>
              <div className="daily-debate-status" aria-live="polite">
                <span>{strategyDeskLoading ? 'LOADING SAVED ANALYSIS' : 'SCHEDULED ANALYSIS · 09:00 / 21:00 LONDON'}</span>
                <span className="daily-debate-last-run">
                  LAST ANALYSIS · {strategyDeskLoading && !activeAnalysis
                    ? 'LOADING…'
                    : formatLondonDateTime(activeAnalysis?.created_at)}
                </span>
              </div>
            </div>

            {strategyDeskError && <div className="war-room-error" role="alert">{strategyDeskError}</div>}
            {strategyDeskLoading && (
              <div className="war-room-progress" role="status">
                <span className="war-room-progress-pulse" />
                Loading the latest saved Strategy Desk analysis…
              </div>
            )}

            <div className="war-room-grid">
              <section className="debate-panel">
                <div className="war-panel-heading">
                  <div>
                    <span className="war-section-index">01 / ANALYSIS TRANSCRIPT</span>
                    <h3>Evidence & Thesis Transcript</h3>
                  </div>
                  <span className="war-round-count">{activeAnalysis?.transcript?.length || 0} ANALYSES</span>
                </div>

                {activeAnalysis?.transcript?.length ? (
                  <div className="debate-stream">
                    {activeAnalysis.transcript.map((turn, index) => (
                      <article className={`debate-message debate-${turn.role || 'risk'}`} key={`${activeAnalysis.id}-${index}`}>
                        <div className="debate-message-topline">
                          <span className="debate-agent"><i />{formatDeskAgentName(turn.agent || 'Desk Signal & Risk Synthesis')}</span>
                          <span className="debate-phase">
                            {turn.role === 'bullish'
                              ? 'SUPPLY THESIS'
                              : turn.role === 'bearish' || turn.phase === 'bearish-rebuttal'
                                ? 'DEMAND THESIS'
                                : turn.phase === 'initial-analysis'
                                  ? 'OPENING THESIS'
                                  : 'MARKET ANALYSIS'}
                          </span>
                        </div>
                        <p>{turn.message}</p>
                      </article>
                    ))}
                    {activeAnalysis.verdict?.rationale && (
                      <article className="debate-message debate-risk">
                        <div className="debate-message-topline">
                          <span className="debate-agent"><i />Desk Signal & Risk Synthesis</span>
                          <span className="debate-phase">DESK SYNTHESIS</span>
                        </div>
                        <p>{activeAnalysis.verdict.rationale}</p>
                      </article>
                    )}
                  </div>
                ) : (
                  <div className="war-room-empty">
                    <div className="empty-radar">◎</div>
                    <h3>{strategyDeskLoading ? 'Preparing Strategy Desk' : 'No analyses recorded yet'}</h3>
                    <p>{strategyDeskLoading
                      ? 'Loading saved analysis from the backend.'
                      : 'No Strategy Desk analysis has been saved yet. The backend checks for a scheduled run at 09:00 and 21:00 Europe/London.'}</p>
                  </div>
                )}

                {strategyDeskAnalyses.length > 1 && (
                  <div className="debate-history">
                    <span className="war-section-index">RECENT ANALYSES</span>
                    <div className="debate-history-list">
                      {strategyDeskAnalyses.slice(0, 5).map((analysis, index) => {
                        const isSelected = activeAnalysis?.id && analysis.id
                          ? activeAnalysis.id === analysis.id
                          : activeAnalysis?.created_at === analysis.created_at;
                        const signal = analysis.signal || analysis.verdict?.signal || '—';
                        const dateLabel = new Date(analysis.created_at).toLocaleString();

                        return (
                          <button
                            type="button"
                            key={analysis.id || analysis.created_at || index}
                            className={`debate-history-item ${isSelected ? 'selected' : ''}`}
                            onClick={() => setActiveAnalysis(analysis)}
                            aria-pressed={Boolean(isSelected)}
                            aria-label={`Load ${signal} Strategy Desk analysis from ${dateLabel}`}
                          >
                            <span>{dateLabel}</span>
                            <b className={`history-signal signal-${signal.toLowerCase()}`}>
                              {signal}
                            </b>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </section>

              <aside className="verdict-panel">
                <div className="war-panel-heading">
                  <div>
                    <span className="war-section-index">02 / DESK SIGNAL & RISK SYNTHESIS</span>
                    <h3>Executive Synthesis</h3>
                  </div>
                  <span className="verdict-shield">◆</span>
                </div>

                {activeAnalysis?.verdict ? (
                  <>
                    <div className={`trade-signal signal-${activeAnalysis.verdict.signal.toLowerCase()}`}>
                      <span className="signal-label">DESK ACTION</span>
                      <strong>{activeAnalysis.verdict.signal}</strong>
                      <span className="signal-confidence">{activeAnalysis.verdict.conviction}% conviction</span>
                    </div>
                    <div className="verdict-price">
                      <div><span>BRENT / BZ=F</span><strong>${Number(activeAnalysis.market_price).toFixed(2)}</strong></div>
                      <span>{activeAnalysis.market_context?.price_basis === 'intraday' ? 'LIVE SNAPSHOT' : 'LAST CLOSE'}</span>
                    </div>
                    {activeAnalysis.market_context?.market_is_closed && (
                      <p className="market-closed-note">
                        Market closed for the weekend · using the last close
                        {activeAnalysis.market_context.price_as_of
                          ? ` from ${activeAnalysis.market_context.price_as_of.slice(0, 10)}`
                          : ''}
                      </p>
                    )}
                    <div className="direction-grid">
                      <div><span>SHORT-TERM</span><b className={`trend-${activeAnalysis.verdict.short_term_trend.toLowerCase()}`}>{activeAnalysis.verdict.short_term_trend}</b></div>
                      <div><span>LONG-TERM</span><b className={`trend-${activeAnalysis.verdict.long_term_trend.toLowerCase()}`}>{activeAnalysis.verdict.long_term_trend}</b></div>
                    </div>
                    <div className="price-levels">
                      <div className="level-row">
                        <span><i className="level-dot support-dot" /> SUPPORT FLOOR</span>
                        <strong>${Number(activeAnalysis.verdict.support).toFixed(2)}</strong>
                      </div>
                      <div className="level-track"><span className="level-marker support-marker" /></div>
                      <div className="level-row">
                        <span><i className="level-dot resistance-dot" /> RESISTANCE CEILING</span>
                        <strong>${Number(activeAnalysis.verdict.resistance).toFixed(2)}</strong>
                      </div>
                      <div className="level-track"><span className="level-marker resistance-marker" /></div>
                    </div>
                    {(activeAnalysis.verdict.entry || activeAnalysis.verdict.stop_loss || activeAnalysis.verdict.take_profit) && (
                      <div className="risk-parameters">
                        {[
                          ['ENTRY', activeAnalysis.verdict.entry],
                          ['STOP LOSS', activeAnalysis.verdict.stop_loss],
                          ['TAKE PROFIT', activeAnalysis.verdict.take_profit],
                        ].filter(([, value]) => value !== null && value !== undefined).map(([label, value]) => (
                          <div key={label}><span>{label}</span><b>${Number(value).toFixed(2)}</b></div>
                        ))}
                      </div>
                    )}
                    {activeAnalysis.verdict.risk_factors?.length > 0 && (
                      <div className="risk-factors">
                        <span className="war-section-index">SUPPLY CHAIN VOLATILITY WATCH</span>
                        {activeAnalysis.verdict.risk_factors.map((factor, index) => <p key={index}>! {factor}</p>)}
                      </div>
                    )}
                    <div className="verdict-footer">
                      <span>DATA: {activeAnalysis.market_context?.telemetry_source || 'TELEMETRY'} + {activeAnalysis.market_context?.news_source || 'NEWS'}</span>
                      <span>{new Date(activeAnalysis.created_at).toLocaleString()}</span>
                    </div>
                  </>
                ) : (
                  <div className="verdict-placeholder">
                    <div>◆</div>
                    <p>Awaiting Strategy Desk synthesis.</p>
                    <span>The desk synthesizes technical evidence with the supply and demand theses.</span>
                  </div>
                )}
              </aside>
            </div>
            <div className="war-room-disclaimer">For energy-market intelligence and research only. Not investment advice. Market data and model conclusions can be incomplete or delayed.</div>
          </section>
        )}
      </main>

      {/* Modal for All Stored RSS Headlines */}
      {showAllModal && (
        <div className="modal-overlay">
          <div className="modal-content">
            <div className="modal-header">
              <h3>Latest RSS and TankerMap Headlines</h3>
              <button onClick={() => setShowAllModal(false)} className="modal-close-btn">&times;</button>
            </div>
            <div className="modal-body">
              {articles.map((art, idx) => (
                <div key={idx} className="news-item modal-item">
                  <div className="news-meta">
                    <span className="news-source">{art.source}</span>
                    <span className="news-time">{art.published_at ? new Date(art.published_at).toLocaleString() : art.created_at ? new Date(art.created_at).toLocaleString() : 'Recent'}</span>
                  </div>
                  <h4 className="news-headline">
                    <a href={art.link} target="_blank" rel="noopener noreferrer" className="news-link">
                      {art.title}
                    </a>
                  </h4>
                  <span className={`sentiment-badge ${art.sentiment?.toLowerCase() || 'neutral'}`}>
                    {art.sentiment || 'Neutral'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Modal for Full Chokepoint History */}
      {showFullChokepointModal && (
        <div className="modal-overlay">
          <div className="modal-content modal-large">
            <div className="modal-header">
              <h3>Full Chokepoint History ({chokepointTab.toUpperCase()}) - Total {sortedCPData.length} Days</h3>
              <button onClick={() => setShowFullChokepointModal(false)} className="modal-close-btn">&times;</button>
            </div>
            <div className="modal-body">
              <div className="chokepoint-bars-grid modal-grid-full">
                {sortedCPData.map((rec, i) => {
                  const maxTankers = Math.max(...sortedCPData.map(d => d.tankers ?? d.vessel_count_tanker ?? 0), 1);
                  const tCount = rec.tankers ?? rec.vessel_count_tanker ?? 0;
                  const heightPct = (tCount / maxTankers) * 100;

                  return (
                    <div key={i} className="chokepoint-bar-col" title={`Date: ${rec.date}\nTankers: ${tCount}`}>
                      <div className="bar-tooltip-val">{tCount}</div>
                      <div className="bar-fill-track">
                        <div className="bar-fill-tankers" style={{ height: `${heightPct}%` }}></div>
                      </div>
                      <span className="bar-date-label">{rec.date}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
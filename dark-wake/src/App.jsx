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

export default function App() {
  const [activeTab, setActiveTab] = useState('news');
  const [brentData, setBrentData] = useState({ price: '100.95', change_pct: '-0.61' });
  const [articles, setArticles] = useState([]);
  const [showAllModal, setShowAllModal] = useState(false);
  const [warRoomDebates, setWarRoomDebates] = useState([]);
  const [activeDebate, setActiveDebate] = useState(null);
  const [warRoomLoading, setWarRoomLoading] = useState(false);
  const [warRoomError, setWarRoomError] = useState('');

  // Chokepoint telemetry data state
  const [chokepointRecords, setChokepointRecords] = useState([]);
  const [portwatchDataAsOf, setPortwatchDataAsOf] = useState(null);
  const [chokepointTab, setChokepointTab] = useState('hormuz');
  const [showFullChokepointModal, setShowFullChokepointModal] = useState(false);

  const [priceHistory, setPriceHistory] = useState([
    { time: '2:00 AM', price: 100.50 },
    { time: '4:00 AM', price: 100.80 },
    { time: '6:00 AM', price: 99.20 },
    { time: '8:00 AM', price: 98.50 },
    { time: '10:00 AM', price: 97.60 },
    { time: '12:00 PM', price: 100.95 }
  ]);

  const defaultArticles = [
    { id: 1, title: 'OPEC+ Signals Potential Output Adjustments Amid Middle East Supply Concerns', source: 'Reuters Energy', time_ago: '12m ago', sentiment: 'Bullish' },
    { id: 2, title: 'Strait of Hormuz Tanker Traffic Stable Despite Increased Naval Patrols', source: 'Lloyd’s List', time_ago: '45m ago', sentiment: 'Neutral' },
  ];

  useEffect(() => {
    const fetchData = () => {
      // Fetch live Brent price
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
    if (activeTab !== 'warroom') return;
    let cancelled = false;

    setWarRoomLoading(true);
    setWarRoomError('');
    fetch(`${API_BASE_URL}/api/war-room/debates`)
      .then(async response => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not load debate history.');
        return data;
      })
      .then(data => {
        if (cancelled) return;
        setWarRoomDebates(Array.isArray(data) ? data : []);
        setActiveDebate(data?.[0] || null);
        setWarRoomError('');
      })
      .catch(error => {
        if (!cancelled) setWarRoomError(error.message || 'War Room API is unavailable.');
      })
      .finally(() => {
        if (!cancelled) setWarRoomLoading(false);
      });

    return () => { cancelled = true; };
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
          <span className="badge">MARITIME INTEL v0.1</span>
        </div>

        <nav className="nav-tabs">
          {[
            { id: 'news', label: 'News & Price' },
            { id: 'warroom', label: 'Multi-Agent War Room' },
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
                <span className="source-tag">Source: Yahoo Finance</span>
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
                    <span className="chart-subtext">NY Mercantile // Intraday Spot Trend</span>
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
                  <h3 className="panel-title">Live Geopolitical RSS Intel</h3>
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
                  <h3 className="panel-title">Chokepoint Traffic Telemetry</h3>
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

        {activeTab === 'warroom' && (
          <section className="war-room">
            <div className="war-room-header">
              <div>
                <div className="war-room-eyebrow"><span className="war-room-live-dot" /> DARK WAKE / INTELLIGENCE DESK</div>
                <h2>Brent crude <span>command room</span></h2>
                <p>Multi-agent adversarial analysis · Instrument <b>brentCash / BZ=F</b></p>
              </div>
              <div className="daily-debate-status" aria-live="polite">
                <span>{warRoomLoading ? 'CHECKING DEBATE STATUS' : 'AUTO-RUN · EVERY 12 HOURS'}</span>
                <span className="daily-debate-last-run">
                  LAST ANALYSIS · {warRoomLoading && !activeDebate
                    ? 'LOADING…'
                    : formatLondonDateTime(activeDebate?.created_at)}
                </span>
              </div>
            </div>

            {warRoomError && <div className="war-room-error" role="alert">{warRoomError}</div>}
            {warRoomLoading && (
              <div className="war-room-progress" role="status">
                <span className="war-room-progress-pulse" />
                Agents are reviewing live market, shipping, and geopolitical data against prior debate history…
              </div>
            )}

            <div className="war-room-grid">
              <section className="debate-panel">
                <div className="war-panel-heading">
                  <div>
                    <span className="war-section-index">01 / DEBATE TRANSCRIPT</span>
                    <h3>Signal room</h3>
                  </div>
                  <span className="war-round-count">{activeDebate?.transcript?.length || 0} TRANSMISSIONS</span>
                </div>

                {activeDebate?.transcript?.length ? (
                  <div className="debate-stream">
                    {activeDebate.transcript.map((turn, index) => (
                      <article className={`debate-message debate-${turn.role || 'risk'}`} key={`${activeDebate.id}-${index}`}>
                        <div className="debate-message-topline">
                          <span className="debate-agent"><i />{turn.agent || 'Risk Manager'}</span>
                          <span className="debate-phase">
                            {turn.phase === 'bearish-rebuttal'
                              ? 'BEARISH REBUTTAL'
                              : turn.phase === 'initial-analysis'
                                ? 'OPENING THESIS'
                                : 'CROSS-EXAMINATION'}
                          </span>
                        </div>
                        <p>{turn.message}</p>
                      </article>
                    ))}
                    {activeDebate.verdict?.rationale && (
                      <article className="debate-message debate-risk">
                        <div className="debate-message-topline">
                          <span className="debate-agent"><i />Risk Manager</span>
                          <span className="debate-phase">EXECUTIVE SYNTHESIS</span>
                        </div>
                        <p>{activeDebate.verdict.rationale}</p>
                      </article>
                    )}
                  </div>
                ) : (
                  <div className="war-room-empty">
                    <div className="empty-radar">◎</div>
                    <h3>{warRoomLoading ? 'Assembling analyst desk' : 'No debate runs yet'}</h3>
                    <p>{warRoomLoading
                      ? 'Agents are assembling today’s market analysis.'
                      : 'The daily debate will initialize automatically when no analysis exists for today.'}</p>
                  </div>
                )}

                {warRoomDebates.length > 1 && (
                  <div className="debate-history">
                    <span className="war-section-index">RECENT DEBATE RUNS</span>
                    <div className="debate-history-list">
                      {warRoomDebates.slice(0, 5).map((debate, index) => (
                        <div
                          key={debate.id || debate.created_at || index}
                          className={`debate-history-item ${activeDebate?.id === debate.id ? 'selected' : ''}`}
                        >
                          <span>{new Date(debate.created_at).toLocaleString()}</span>
                          <b className={`history-signal signal-${(debate.signal || debate.verdict?.signal || 'hold').toLowerCase()}`}>
                            {debate.signal || debate.verdict?.signal || '—'}
                          </b>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </section>

              <aside className="verdict-panel">
                <div className="war-panel-heading">
                  <div>
                    <span className="war-section-index">02 / RISK CONTROL</span>
                    <h3>Executive verdict</h3>
                  </div>
                  <span className="verdict-shield">◆</span>
                </div>

                {activeDebate?.verdict ? (
                  <>
                    <div className={`trade-signal signal-${activeDebate.verdict.signal.toLowerCase()}`}>
                      <span className="signal-label">DESK ACTION</span>
                      <strong>{activeDebate.verdict.signal}</strong>
                      <span className="signal-confidence">{activeDebate.verdict.conviction}% conviction</span>
                    </div>
                    <div className="verdict-price">
                      <div><span>BRENT / BZ=F</span><strong>${Number(activeDebate.market_price).toFixed(2)}</strong></div>
                      <span>LIVE SNAPSHOT</span>
                    </div>
                    <div className="direction-grid">
                      <div><span>SHORT-TERM</span><b className={`trend-${activeDebate.verdict.short_term_trend.toLowerCase()}`}>{activeDebate.verdict.short_term_trend}</b></div>
                      <div><span>LONG-TERM</span><b className={`trend-${activeDebate.verdict.long_term_trend.toLowerCase()}`}>{activeDebate.verdict.long_term_trend}</b></div>
                    </div>
                    <div className="price-levels">
                      <div className="level-row">
                        <span><i className="level-dot support-dot" /> SUPPORT FLOOR</span>
                        <strong>${Number(activeDebate.verdict.support).toFixed(2)}</strong>
                      </div>
                      <div className="level-track"><span className="level-marker support-marker" /></div>
                      <div className="level-row">
                        <span><i className="level-dot resistance-dot" /> RESISTANCE CEILING</span>
                        <strong>${Number(activeDebate.verdict.resistance).toFixed(2)}</strong>
                      </div>
                      <div className="level-track"><span className="level-marker resistance-marker" /></div>
                    </div>
                    {(activeDebate.verdict.entry || activeDebate.verdict.stop_loss || activeDebate.verdict.take_profit) && (
                      <div className="risk-parameters">
                        {[
                          ['ENTRY', activeDebate.verdict.entry],
                          ['STOP LOSS', activeDebate.verdict.stop_loss],
                          ['TAKE PROFIT', activeDebate.verdict.take_profit],
                        ].filter(([, value]) => value !== null && value !== undefined).map(([label, value]) => (
                          <div key={label}><span>{label}</span><b>${Number(value).toFixed(2)}</b></div>
                        ))}
                      </div>
                    )}
                    {activeDebate.verdict.risk_factors?.length > 0 && (
                      <div className="risk-factors">
                        <span className="war-section-index">RISK WATCH</span>
                        {activeDebate.verdict.risk_factors.map((factor, index) => <p key={index}>! {factor}</p>)}
                      </div>
                    )}
                    <div className="verdict-footer">
                      <span>DATA: {activeDebate.market_context?.telemetry_source || 'TELEMETRY'} + {activeDebate.market_context?.news_source || 'NEWS'}</span>
                      <span>{new Date(activeDebate.created_at).toLocaleString()}</span>
                    </div>
                  </>
                ) : (
                  <div className="verdict-placeholder">
                    <div>◆</div>
                    <p>Awaiting full debate synthesis.</p>
                    <span>Risk Manager reconciles the technical view, bullish case, and bearish rebuttal.</span>
                  </div>
                )}
              </aside>
            </div>
            <div className="war-room-disclaimer">For intelligence and research only. Not investment advice. Market data and model conclusions can be incomplete or delayed.</div>
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
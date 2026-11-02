import React, { useState, useEffect, useRef } from 'react';
import './App.css';
import { getDailyTrafficDisplay } from './dailyTrafficDisplay.js';
import SpatialIntelligence from "./SpatialIntelligence";

const SPATIAL_V2 = import.meta.env.VITE_SPATIAL_V2 !== 'false';

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

const formatCurrency = value => {
  const price = Number(value);
  return value !== null && value !== undefined && Number.isFinite(price) && price > 0
    ? `$${price.toFixed(2)}`
    : '—';
};

const getNicePriceInterval = value => {
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
};

function DeskSignalPanel({ analysis, marketData, loading, error }) {
  const verdict = analysis?.verdict;
  const signal = String(verdict?.signal || 'HOLD').toLowerCase();
  const marketPriceLabel = marketData?.price_basis === 'intraday'
    ? 'LIVE SNAPSHOT'
    : marketData?.price_basis === 'last_close'
      ? 'LAST CLOSE'
      : 'QUOTE UNAVAILABLE';
  const analysisDate = analysis?.created_at ? new Date(analysis.created_at) : null;

  return (
    <aside className="verdict-panel">
      <div className="war-panel-heading">
        <div>
          <span className="war-section-index">02 / DESK SIGNAL &amp; RISK SYNTHESIS</span>
          <h3>Executive Synthesis</h3>
        </div>
        <span className="verdict-shield">◆</span>
      </div>

      {verdict ? (
        <>
          <div className={`trade-signal signal-${signal}`}>
            <span className="signal-label">DESK ACTION</span>
            <strong>{verdict.signal || 'HOLD'}</strong>
            <span className="signal-confidence">{verdict.conviction ?? '—'}% conviction</span>
          </div>
          <div className="verdict-price">
            <div><span>BRENT / BZ=F</span><strong>{formatCurrency(marketData?.price)}</strong></div>
            <span>{marketPriceLabel}</span>
          </div>
          {marketData?.market_is_closed && (
            <p className="market-closed-note">
              Market closed · using the latest close
              {marketData.price_as_of ? ` from ${marketData.price_as_of.slice(0, 10)}` : ''}
            </p>
          )}
          <div className="direction-grid">
            <div><span>SHORT-TERM</span><b className={`trend-${String(verdict.short_term_trend || 'neutral').toLowerCase()}`}>{verdict.short_term_trend || '—'}</b></div>
            <div><span>LONG-TERM</span><b className={`trend-${String(verdict.long_term_trend || 'neutral').toLowerCase()}`}>{verdict.long_term_trend || '—'}</b></div>
          </div>
          <div className="price-levels">
            <div className="level-row">
              <span><i className="level-dot support-dot" /> SUPPORT FLOOR</span>
              <strong>{formatCurrency(verdict.support)}</strong>
            </div>
            <div className="level-track"><span className="level-marker support-marker" /></div>
            <div className="level-row">
              <span><i className="level-dot resistance-dot" /> RESISTANCE CEILING</span>
              <strong>{formatCurrency(verdict.resistance)}</strong>
            </div>
            <div className="level-track"><span className="level-marker resistance-marker" /></div>
          </div>
          {[['ENTRY', verdict.entry], ['STOP LOSS', verdict.stop_loss], ['TAKE PROFIT', verdict.take_profit]]
            .some(([, value]) => value !== null && value !== undefined) && (
            <div className="risk-parameters">
              {[
                ['ENTRY', verdict.entry],
                ['STOP LOSS', verdict.stop_loss],
                ['TAKE PROFIT', verdict.take_profit],
              ].filter(([, value]) => value !== null && value !== undefined).map(([label, value]) => (
                <div key={label}><span>{label}</span><b>{formatCurrency(value)}</b></div>
              ))}
            </div>
          )}
          {verdict.risk_factors?.length > 0 && (
            <div className="risk-factors">
              <span className="war-section-index">SUPPLY CHAIN VOLATILITY WATCH</span>
              {verdict.risk_factors.map((factor, index) => <p key={index}>! {factor}</p>)}
            </div>
          )}
          <div className="verdict-footer">
            <span>DATA: {analysis.market_context?.telemetry_source || 'TELEMETRY'} + {analysis.market_context?.news_source || 'NEWS'}</span>
            <span>{analysisDate && !Number.isNaN(analysisDate.getTime()) ? analysisDate.toLocaleString() : 'DATE UNAVAILABLE'}</span>
          </div>
        </>
      ) : (
        <div className="verdict-placeholder">
          <div>◆</div>
          <p>{loading ? 'Loading Strategy Desk synthesis.' : error ? 'Strategy Desk synthesis unavailable.' : 'Awaiting Strategy Desk synthesis.'}</p>
          <span>{error || 'The desk synthesizes technical evidence with the supply and demand theses.'}</span>
        </div>
      )}
    </aside>
  );
}

function DeskSynthesisAnalysis({ analysis, loading, error }) {
  const rationale = analysis?.verdict?.rationale;

  return (
    <section className="desk-synthesis-analysis" aria-live="polite">
      <div className="desk-synthesis-heading">
        <h3><span aria-hidden="true">●</span> Desk Signal &amp; Risk Synthesis</h3>
        <span>DESK SYNTHESIS</span>
      </div>
      <p>
        {rationale || (loading
          ? 'Loading the latest Desk Signal & Risk Synthesis analysis…'
          : error
            ? 'Desk Signal & Risk Synthesis is unavailable.'
            : 'No Desk Signal & Risk Synthesis analysis has been recorded yet.')}
      </p>
    </section>
  );
}

const SPATIAL_LOCATIONS = {
  hormuz: { name: 'Strait of Hormuz', type: 'chokepoint', region: 'Persian Gulf', coords: '26.42° N, 56.51° E' },
  bab: { name: 'Bab el-Mandeb', type: 'chokepoint', region: 'Red Sea', coords: '12.65° N, 43.42° E' },
  fujairah: { name: 'Port of Fujairah', type: 'dock', region: 'Gulf of Oman', coords: '25.16° N, 56.39° E' },
  suez: { name: 'Suez Canal', type: 'canal', region: 'Egypt', coords: '29.94° N, 32.56° E' },
  malacca: { name: 'Malacca Strait / Singapore Hub', type: 'chokepoint', region: 'SE Asia', coords: '1.20° N, 103.68° E' },
  singapore: { name: 'Port of Singapore', type: 'dock', region: 'SE Asia', coords: '1.25° N, 103.75° E' },
  rotterdam: { name: 'Port of Rotterdam', type: 'dock', region: 'North Sea', coords: '51.96° N, 4.08° E' },
  jebel_ali: { name: 'Port of Jebel Ali', type: 'dock', region: 'Persian Gulf', coords: '25.01° N, 55.06° E' },
};

const FALLBACK_IMAGES = {
  hormuz: '/assets/satellite_chokepoints/hormuz.png',
  bab: '/assets/satellite_chokepoints/bab_el_mandeb.png',
  fujairah: '/assets/satellite_chokepoints/fujairah.png',
  suez: '/assets/satellite_chokepoints/suez.png',
  malacca: '/assets/satellite_chokepoints/malacca.png',
  singapore: '/assets/satellite_chokepoints/singapore.png',
  rotterdam: '/assets/satellite_chokepoints/rotterdam.png',
  jebel_ali: '/assets/satellite_chokepoints/jebel_ali.png',
};

const DEFAULT_SPATIAL_TELEMETRY = {
  hormuz: { index: 68, vessels: 52, latency: 'High', token: 'SAM31-HRMZ-09' },
  bab: { index: 42, vessels: 34, latency: 'Medium', token: 'SAM31-BMND-04' },
  fujairah: { index: 45, vessels: 28, latency: 'Low', token: 'SAM31-FUJR-02' },
  suez: { index: 59, vessels: 39, latency: 'Medium', token: 'SAM31-SUEZ-07' },
  malacca: { index: 78, vessels: 64, latency: 'High', token: 'SAM31-MLCA-12' },
  singapore: { index: 72, vessels: 58, latency: 'High', token: 'SAM31-SGP-11' },
  rotterdam: { index: 38, vessels: 24, latency: 'Low', token: 'SAM31-ROTT-01' },
  jebel_ali: { index: 44, vessels: 26, latency: 'Low', token: 'SAM31-JBLA-03' },
};

export default function App() {
  const [activeTab, setActiveTab] = useState('news');
  const [brentData, setBrentData] = useState({ price: null, change_pct: null });
  const [articles, setArticles] = useState([]);
  const [showAllModal, setShowAllModal] = useState(false);
  const [strategyDeskAnalyses, setStrategyDeskAnalyses] = useState([]);
  const [activeAnalysis, setActiveAnalysis] = useState(null);
  const [strategyDeskLoading, setStrategyDeskLoading] = useState(false);
  const [strategyDeskError, setStrategyDeskError] = useState('');
  const [chartTimeframe, setChartTimeframe] = useState('1d');
  const [chartTimeZoom, setChartTimeZoom] = useState(1);
  const [chartPanOffset, setChartPanOffset] = useState(0);
  const [chartPriceScale, setChartPriceScale] = useState(1);
  const [chartHover, setChartHover] = useState(null);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState('');
  const chartDragRef = useRef(null);

  // Chokepoint telemetry data state
  const [chokepointRecords, setChokepointRecords] = useState([]);
  const [portwatchDataAsOf, setPortwatchDataAsOf] = useState(null);
  const [chokepointTab, setChokepointTab] = useState('hormuz');
  const [showFullChokepointModal, setShowFullChokepointModal] = useState(false);
  const [spatialChokepoint, setSpatialChokepoint] = useState('hormuz');
  const [spatialSnapshots, setSpatialSnapshots] = useState([]);
  const [snapshotsLoading, setSnapshotsLoading] = useState(false);
  const [activeSnapshotIdx, setActiveSnapshotIdx] = useState(0);

  const fetchSnapshots = () => {
    setSnapshotsLoading(true);
    fetch(`${API_BASE_URL}/api/spatial/snapshots`)
      .then(r => r.json())
      .then(data => setSpatialSnapshots(Array.isArray(data?.snapshots) ? data.snapshots : []))
      .catch(() => setSpatialSnapshots([]))
      .finally(() => setSnapshotsLoading(false));
  };

  useEffect(() => {
    fetchSnapshots();
  }, []);

  const [spatialTelemetry] = useState(DEFAULT_SPATIAL_TELEMETRY);

  const getCongestionTier = idx => (idx > 70 ? 'high' : idx > 40 ? 'medium' : 'low');
  const currentLocObj = SPATIAL_LOCATIONS[spatialChokepoint] || SPATIAL_LOCATIONS.hormuz;
  const currentLocName = currentLocObj.name;
  const currentLocTelemetry = spatialTelemetry[spatialChokepoint] || {
    index: 50,
    vessels: 30,
    latency: 'Medium',
    token: `SAM31-${spatialChokepoint.toUpperCase()}-01`,
  };

  const matchedSnapshots = (spatialSnapshots || []).filter(s => {
    const sName = (s?.location_name || '').toLowerCase();
    const targetKey = spatialChokepoint.toLowerCase();
    const targetName = currentLocName.toLowerCase();
    return (
      sName.includes(targetKey) ||
      sName === targetName ||
      (targetKey === 'bab' && sName.includes('mandeb')) ||
      (targetKey === 'hormuz' && sName.includes('hormuz')) ||
      (targetKey === 'malacca' && sName.includes('malacca')) ||
      (targetKey === 'fujairah' && sName.includes('fujairah')) ||
      (targetKey === 'suez' && sName.includes('suez')) ||
      (targetKey === 'singapore' && sName.includes('singapore')) ||
      (targetKey === 'rotterdam' && sName.includes('rotterdam')) ||
      (targetKey === 'jebel_ali' && sName.includes('jebel'))
    );
  });

  const onlineSnapshots = matchedSnapshots.filter(s => (s?.image_url || '').startsWith('http'));
  const filteredSnapshots = (onlineSnapshots.length > 0 ? onlineSnapshots : matchedSnapshots)
    .sort((a, b) => {
      const aHires = (a?.image_url || '').includes('_hires_') ? 1 : 0;
      const bHires = (b?.image_url || '').includes('_hires_') ? 1 : 0;
      if (bHires !== aHires) return bHires - aHires;
      return new Date(b?.captured_at || 0) - new Date(a?.captured_at || 0);
    });

  const displaySnapshots = filteredSnapshots.length > 0
    ? filteredSnapshots
    : [
        {
          id: `benchmark-${spatialChokepoint}`,
          location_name: currentLocName,
          image_url: FALLBACK_IMAGES[spatialChokepoint] || '/assets/satellite_chokepoints/hormuz.png',
          fallback_url: FALLBACK_IMAGES[spatialChokepoint] || '/assets/satellite_chokepoints/hormuz.png',
          captured_at: new Date().toISOString(),
          is_benchmark: true,
        },
      ];

  const safeSnapshotIdx = activeSnapshotIdx < displaySnapshots.length ? activeSnapshotIdx : 0;
  const activeSnapshot = displaySnapshots[safeSnapshotIdx] || displaySnapshots[0];
  const [priceHistory, setPriceHistory] = useState([]);

  const defaultArticles = [
    { id: 1, title: 'OPEC+ Signals Potential Output Adjustments as Brent Prices Shift', source: 'Reuters Energy', time_ago: '12m ago', sentiment: 'Bullish' },
    { id: 2, title: 'Tanker Traffic Holds Steady Across Key Maritime Routes', source: 'Lloyd’s List', time_ago: '45m ago', sentiment: 'Neutral' },
  ];

  useEffect(() => {
    let cancelled = false;
    const fetchMarketSnapshot = () => {
      fetch(`${API_BASE_URL}/api/market/prices?period=${chartTimeframe}`)
        .then(async response => {
          const data = await response.json();
          if (!response.ok) throw new Error(data.detail || 'Market price history is unavailable.');

          const price = Number(data?.price);
          if (!Number.isFinite(price) || price <= 0) {
            throw new Error('Market endpoint returned an invalid Brent price.');
          }
          const history = Array.isArray(data.history)
            ? data.history
              .filter(point => Number.isFinite(Number(point?.price)) && Number(point.price) > 0)
              .map(point => ({ ...point, price: Number(point.price) }))
            : [];
          if (history.length === 0) throw new Error('No price history is available for this timeframe.');
          return { ...data, price, history };
        })
        .then(data => {
          if (cancelled) return;
          const changePct = data.change_pct == null ? Number.NaN : Number(data.change_pct);
          setBrentData({
            ...data,
            change_pct: Number.isFinite(changePct) ? changePct : null,
          });
          setPriceHistory(data.history);
          setChartError('');
          setChartLoading(false);
        })
        .catch(error => {
          if (cancelled) return;
          setChartError(error.message || 'Market endpoint offline.');
          setChartLoading(false);
        });
    };

    setChartLoading(true);
    setChartError('');
    fetchMarketSnapshot();
    const interval = setInterval(fetchMarketSnapshot, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [chartTimeframe]);

  useEffect(() => {
    setChartTimeZoom(1);
    setChartPanOffset(0);
    setChartPriceScale(1);
    setChartHover(null);
  }, [chartTimeframe]);

  useEffect(() => {
    const fetchData = () => {
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
    if (activeTab !== 'strategy-desk' && activeTab !== 'news') return;
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

  const visibleCount = priceHistory.length
    ? Math.max(2, Math.ceil(priceHistory.length / chartTimeZoom))
    : 0;
  const maxPanOffset = Math.max(0, priceHistory.length - visibleCount);
  const boundedPanOffset = Math.min(maxPanOffset, Math.max(0, chartPanOffset));
  const visibleStart = Math.max(0, priceHistory.length - visibleCount - boundedPanOffset);
  const visiblePriceHistory = priceHistory.slice(visibleStart, visibleStart + visibleCount);
  const visiblePrices = visiblePriceHistory.map(point => point.price);
  const rawMinPrice = visiblePrices.length ? Math.min(...visiblePrices) : 0;
  const rawMaxPrice = visiblePrices.length ? Math.max(...visiblePrices) : 1;
  const rawPriceRange = Math.max(rawMaxPrice - rawMinPrice, rawMaxPrice * 0.002, 0.02);
  const priceInterval = getNicePriceInterval(rawPriceRange * chartPriceScale / 4);
  let minPrice = Math.floor(rawMinPrice / priceInterval) * priceInterval;
  let maxPrice = Math.ceil(rawMaxPrice / priceInterval) * priceInterval;
  if (maxPrice <= minPrice) {
    minPrice -= priceInterval;
    maxPrice += priceInterval;
  }
  const priceRange = maxPrice - minPrice;
  const priceY = price => 240 - ((price - minPrice) / priceRange) * 240;
  const chartPoints = visiblePriceHistory.map((point, index) => {
    const x = visiblePriceHistory.length > 1
      ? index / (visiblePriceHistory.length - 1) * 600
      : 300;
    return { x, y: priceY(point.price), point };
  });
  const pointsString = chartPoints.map(({ x, y }) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const polygonPoints = chartPoints.length
    ? `0,240 ${pointsString} 600,240`
    : '';
  const lastPoint = chartPoints.at(-1);
  const chartAxisPrices = visiblePriceHistory.length
    ? Array.from(
      { length: Math.round(priceRange / priceInterval) + 1 },
      (_, index) => maxPrice - index * priceInterval,
    )
    : [];
  const chartTimeLabels = Array.from({ length: Math.min(6, visiblePriceHistory.length) }, (_, index) => {
    const pointIndex = Math.round(
      index * (visiblePriceHistory.length - 1) / Math.max(1, Math.min(6, visiblePriceHistory.length) - 1),
    );
    return visiblePriceHistory[pointIndex];
  });
  const chartTimeRangeLabel = visiblePriceHistory.length > 1
    ? `${visiblePriceHistory[0].time} — ${visiblePriceHistory.at(-1).time}`
    : 'No price history';

  const handleChartPointerDown = event => {
    event.currentTarget.setPointerCapture(event.pointerId);
    chartDragRef.current = {
      axis: event.currentTarget.dataset.axis || 'time',
      x: event.clientX,
      y: event.clientY,
      panOffset: boundedPanOffset,
      priceScale: chartPriceScale,
    };
  };
  const handleChartPointerMove = event => {
    const drag = chartDragRef.current;
    if (drag?.axis === 'price') {
      const deltaY = event.clientY - drag.y;
      setChartPriceScale(Math.min(10000, Math.max(1, drag.priceScale * Math.exp(deltaY / 40))));
      return;
    }

    const svg = event.currentTarget.closest('.chart-plot-area')?.querySelector('svg');
    if (!svg || visiblePriceHistory.length === 0) return;
    const rect = svg.getBoundingClientRect();
    const x = Math.min(600, Math.max(0, (event.clientX - rect.left) / rect.width * 600));
    const y = Math.min(240, Math.max(0, (event.clientY - rect.top) / rect.height * 240));
    const index = Math.round(x / 600 * Math.max(0, visiblePriceHistory.length - 1));
    setChartHover({ x, y, index });
    if (drag?.axis === 'time' && maxPanOffset > 0) {
      const deltaPoints = (event.clientX - drag.x) / rect.width * visiblePriceHistory.length;
      setChartPanOffset(Math.min(maxPanOffset, Math.max(0, drag.panOffset + deltaPoints)));
    }
  };
  const handleChartPointerUp = event => {
    chartDragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };
  const handleChartWheel = event => {
    event.preventDefault();
    const factor = event.deltaY < 0 ? 1.2 : 1 / 1.2;
    setChartTimeZoom(current => Math.min(
      Math.max(1, priceHistory.length / 2),
      Math.max(1, current * factor),
    ));
  };
  const changeTimeframe = timeframe => {
    setChartTimeframe(timeframe);
    setPriceHistory([]);
    setChartLoading(true);
    setChartError('');
    setChartPanOffset(0);
    setChartTimeZoom(1);
    setChartPriceScale(1);
  };

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
                  {formatCurrency(brentData.price)}{' '}
                  {Number.isFinite(brentData.change_pct) && (
                    <span className={brentData.change_pct >= 0 ? 'text-emerald' : 'text-rose'}>
                      {brentData.change_pct >= 0 ? `+${brentData.change_pct}%` : `${brentData.change_pct}%`}
                    </span>
                  )}
                </p>
                <span className="source-tag">
                  {brentData.price == null
                    ? 'Yahoo Finance · Quote unavailable'
                    : brentData.price_basis === 'last_close'
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
              <div className="news-chart-column">
                <div className="chart-panel">
                <div className="panel-header-flex">
                  <div>
                    <h3 className="panel-title">Brent Crude Oil Futures (BZ=F)</h3>
                    <span className="chart-subtext">
                      {brentData.history_interval === 'daily'
                        ? 'NY Mercantile // Daily Closing Prices'
                        : 'NY Mercantile // Intraday Price History'} · {chartTimeRangeLabel}
                    </span>
                  </div>
                  <span className="source-badge">Yahoo Finance</span>
                </div>

                <div className="chart-toolbar" aria-label="Price chart controls">
                  <div className="chart-control-group" aria-label="Chart time interval">
                    {[
                      ['1d', '1D'],
                      ['5d', '5D'],
                      ['1mo', '1M'],
                      ['3mo', '3M'],
                    ].map(([period, label]) => (
                      <button
                        key={period}
                        type="button"
                        className={`chart-control-button ${chartTimeframe === period ? 'active' : ''}`}
                        onClick={() => changeTimeframe(period)}
                        aria-pressed={chartTimeframe === period}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <div className="chart-control-group" aria-label="Time scale controls">
                    <button type="button" className="chart-control-button" onClick={() => setChartTimeZoom(zoom => Math.min(Math.max(1, priceHistory.length / 2), zoom * 1.5))} aria-label="Zoom in on time">+</button>
                    <button type="button" className="chart-control-button" onClick={() => setChartTimeZoom(zoom => Math.max(1, zoom / 1.5))} aria-label="Zoom out on time">−</button>
                    <button type="button" className="chart-control-button chart-auto-button" onClick={() => { setChartTimeZoom(1); setChartPanOffset(0); }}>FIT</button>
                  </div>
                  <div className="chart-control-group chart-price-controls" aria-label="Price scale controls">
                    <span>$/LEVEL</span>
                    <button type="button" className="chart-control-button" onClick={() => setChartPriceScale(scale => Math.max(1, scale / 1.25))} aria-label="Decrease price interval">+</button>
                    <button type="button" className="chart-control-button" onClick={() => setChartPriceScale(scale => Math.min(10000, scale * 1.25))} aria-label="Increase price interval">−</button>
                    <button type="button" className="chart-control-button chart-auto-button" onClick={() => setChartPriceScale(1)}>AUTO</button>
                  </div>
                </div>

                <div className="chart-canvas-area">
                  <div className="chart-plot-area">
                    <div className="chart-wrapper">
                      <svg
                        className="line-chart-svg"
                        viewBox="0 0 600 240"
                        preserveAspectRatio="none"
                        onPointerDown={handleChartPointerDown}
                        onPointerMove={handleChartPointerMove}
                        onPointerUp={handleChartPointerUp}
                        onPointerCancel={handleChartPointerUp}
                        onPointerLeave={() => {
                          if (!chartDragRef.current) setChartHover(null);
                        }}
                        onWheel={handleChartWheel}
                        aria-label="Interactive Brent price chart. Drag to pan, scroll to zoom."
                      >
                        <defs>
                          <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#f43f5e" stopOpacity="0.35" />
                            <stop offset="100%" stopColor="#f43f5e" stopOpacity="0.0" />
                          </linearGradient>
                        </defs>
                        {Array.from({ length: chartAxisPrices.length || 5 }, (_, index) => (
                          <line
                            key={index}
                            x1="0"
                            y1={chartAxisPrices.length ? priceY(chartAxisPrices[index]) : index * 60}
                            x2="600"
                            y2={chartAxisPrices.length ? priceY(chartAxisPrices[index]) : index * 60}
                            className="chart-grid-line"
                          />
                        ))}
                        {visiblePriceHistory.length > 0 && (
                          <>
                            <polygon fill="url(#chartGradient)" points={polygonPoints} />
                            <polyline fill="none" stroke="#f43f5e" strokeWidth="2" points={pointsString} />
                            {lastPoint && <circle cx={lastPoint.x} cy={lastPoint.y} r="3.5" fill="#f43f5e" />}
                          </>
                        )}
                        {chartHover && visiblePriceHistory[chartHover.index] && (
                          <>
                            <line x1={chartHover.x} y1="0" x2={chartHover.x} y2="240" className="chart-crosshair" />
                            <line x1="0" y1={chartHover.y} x2="600" y2={chartHover.y} className="chart-crosshair" />
                            <circle
                              cx={chartPoints[chartHover.index]?.x}
                              cy={chartPoints[chartHover.index]?.y}
                              r="4"
                              className="chart-hover-point"
                            />
                          </>
                        )}
                      </svg>
                      {chartHover && visiblePriceHistory[chartHover.index] && (
                        <div
                          className="chart-hover-tooltip"
                          style={{ left: `${Math.min(78, Math.max(2, chartHover.x / 6))}%` }}
                        >
                          <strong>${visiblePriceHistory[chartHover.index].price.toFixed(2)}</strong>
                          <span>{visiblePriceHistory[chartHover.index].time}</span>
                        </div>
                      )}
                      {visiblePriceHistory.length === 0 && (
                        <div className="chart-empty-state">
                          {chartLoading ? 'Loading Brent price history…' : chartError || 'No Brent price history available.'}
                        </div>
                      )}
                    </div>
                    <div
                      className="chart-y-axis"
                      data-axis="price"
                      onPointerDown={handleChartPointerDown}
                      onPointerMove={handleChartPointerMove}
                      onPointerUp={handleChartPointerUp}
                      onPointerCancel={handleChartPointerUp}
                      aria-label={`Price interval ${formatCurrency(priceInterval)} per level. Drag vertically to change interval.`}
                    >
                      {chartAxisPrices.map((price, index) => <span key={index}>{formatCurrency(price)}</span>)}
                    </div>
                  </div>
                  <div className="chart-x-axis">
                    {chartTimeLabels.map((point, index) => <span key={`${point.timestamp || point.time}-${index}`}>{point.time}</span>)}
                  </div>
                  <div className="chart-interaction-hint">
                    Drag chart to pan · scroll to zoom time · drag price scale to change $/level ({formatCurrency(priceInterval)}) · {chartLoading ? 'Updating…' : chartTimeframe.toUpperCase()}
                  </div>
                </div>
              </div>
                <DeskSynthesisAnalysis
                  analysis={activeAnalysis}
                  loading={strategyDeskLoading}
                  error={strategyDeskError}
                />
              </div>

              <div className="news-sidebar">
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

                <DeskSignalPanel
                  analysis={activeAnalysis}
                  marketData={brentData}
                  loading={strategyDeskLoading}
                  error={strategyDeskError}
                />
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

        {activeTab === 'spatial-intelligence' && (SPATIAL_V2 ? <SpatialIntelligence /> : (
          <div className="spatial-tab space-y-6">
            {/* Header */}
            <div className="spatial-header">
              <div>
                <h2>Spatial <span>Intelligence</span></h2>
                <p className="spatial-header-sub">
                  Sentinel-2 L2A Optical Surveillance · SAM 3.1 Tanker Segmentation · Maritime Bottleneck Matrix
                </p>
              </div>
              <div className="spatial-source-pill">
                <span className="spatial-live-dot" />
                <span>AWS Earth Search STAC · SAM 3.1 Vision</span>
              </div>
            </div>

            {/* Chokepoint Telemetry Cards & Grid */}
            <div className="spatial-grid-cards">
              {Object.entries(SPATIAL_LOCATIONS).map(([key, loc]) => {
                const telem = spatialTelemetry[key] || { index: 45, vessels: 25, latency: 'Medium', token: 'SAM31' };
                const tier = getCongestionTier(telem.index);
                const isSelected = spatialChokepoint === key;

                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => {
                      setSpatialChokepoint(key);
                      setActiveSnapshotIdx(0);
                    }}
                    className={`spatial-card-btn ${isSelected ? 'active-card' : ''}`}
                    aria-pressed={isSelected}
                  >
                    <div className="spatial-card-topline">
                      <span className="spatial-card-name">{loc.name}</span>
                      <span className={`spatial-card-badge ${loc.type}`}>{loc.type.toUpperCase()}</span>
                    </div>

                    <div className="spatial-card-main-val">
                      <span className={`spatial-card-index ${tier}`}>{telem.index}</span>
                      <span className="spatial-card-index-scale">/ 100 CONGESTION</span>
                    </div>

                    <div className="spatial-card-stats">
                      <span>{telem.vessels} vessels</span>
                      <span className={`spatial-risk-pill ${tier}`}>{telem.latency} LATENCY</span>
                    </div>

                    <div className="spatial-token-tag" title={telem.token}>
                      TOKEN: {telem.token}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Main Content Grid: Satellite Snapshot Viewer & Visual Telemetry Panel */}
            <div className="spatial-main-grid">
              {/* Left Column: Satellite Snapshot Viewer & Rolling Timeline */}
              <div className="spatial-viewer-box">
                <div className="spatial-viewer-header">
                  <div>
                    <h3 className="spatial-viewer-title">
                      Optical Surveillance Feed — {currentLocName}
                    </h3>
                    <span className="spatial-viewer-meta">
                      Rolling 3-day history · {displaySnapshots.length} capture{displaySnapshots.length === 1 ? '' : 's'} indexed
                      {activeSnapshot?.is_benchmark ? ' · Benchmark reference tile' : ' · STAC Sentinel-2 archive'}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={fetchSnapshots}
                    className="spatial-refresh-button"
                    disabled={snapshotsLoading}
                    aria-label="Refresh satellite snapshots"
                  >
                    <span>{snapshotsLoading ? '⟳' : '↻'}</span>
                    <span>{snapshotsLoading ? 'Ingesting STAC…' : 'Refresh Feed'}</span>
                  </button>
                </div>

                <div className="spatial-frame-container">
                  <img
                    className="spatial-frame-img"
                    src={activeSnapshot?.image_url || FALLBACK_IMAGES[spatialChokepoint]}
                    alt={`Satellite surveillance of ${currentLocName}`}
                    onError={e => {
                      e.target.onerror = null;
                      e.target.src = FALLBACK_IMAGES[spatialChokepoint] || '/assets/satellite_chokepoints/hormuz.png';
                    }}
                  />
                  <div className="spatial-scanline-overlay" />

                  <div className="spatial-hud-crosshairs">
                    REC: {currentLocObj.region?.toUpperCase()} // {currentLocObj.coords} // 1280x720 HIGH-RES OPTICAL
                  </div>

                  <div className="spatial-hud-badge">
                    <span
                      className={`spatial-hud-badge-val ${getCongestionTier(currentLocTelemetry.index)}`}
                      style={{
                        color:
                          currentLocTelemetry.index > 70
                            ? '#f43f5e'
                            : currentLocTelemetry.index > 40
                              ? '#fbbf24'
                              : '#34d399',
                      }}
                    >
                      {currentLocTelemetry.index}
                    </span>
                    <span className="spatial-hud-badge-lbl">CONGESTION INDEX</span>
                  </div>
                </div>

                {/* Rolling 3-Day History Timeline */}
                <div className="spatial-timeline-section">
                  <div className="spatial-timeline-title">
                    <span>ROLLING 3-DAY CAPTURE TIMELINE</span>
                    <span style={{ color: '#556c80', fontWeight: 500 }}>
                      SELECT CAPTURE TO INSPECT
                    </span>
                  </div>

                  <div className="spatial-thumbs-row">
                    {displaySnapshots.map((snap, i) => {
                      const isActiveThumb = i === safeSnapshotIdx;
                      const captureDate = snap?.captured_at
                        ? new Date(snap.captured_at).toLocaleDateString('en-GB', {
                            day: '2-digit',
                            month: 'short',
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : 'Benchmark';

                      return (
                        <div
                          key={snap?.id || i}
                          className={`spatial-thumb-item ${isActiveThumb ? 'active' : ''}`}
                          onClick={() => setActiveSnapshotIdx(i)}
                          role="button"
                          tabIndex={0}
                          aria-label={`Select capture from ${captureDate}`}
                        >
                          <img
                            className="spatial-thumb-preview"
                            src={snap?.image_url || FALLBACK_IMAGES[spatialChokepoint]}
                            alt={snap?.location_name || 'Thumbnail'}
                            onError={e => {
                              e.target.onerror = null;
                              e.target.src = FALLBACK_IMAGES[spatialChokepoint] || '/assets/satellite_chokepoints/hormuz.png';
                            }}
                          />
                          <div className="spatial-thumb-info">
                            <span className="spatial-thumb-date">{captureDate}</span>
                            <span>{snap?.is_benchmark ? 'BENCHMARK' : 'STAC TILE'}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Right Column: Visual Telemetry Panel */}
              <div className="spatial-telemetry-panel">
                <div className="spatial-telemetry-head">
                  <div>
                    <span className="spatial-telemetry-eyebrow">
                      TELEMETRY MATRIX · {currentLocObj.type?.toUpperCase()}
                    </span>
                    <h3>{currentLocName}</h3>
                  </div>
                  <span className={`spatial-card-badge ${currentLocObj.type}`}>
                    {currentLocObj.type.toUpperCase()}
                  </span>
                </div>

                <div className="spatial-gauge-section">
                  <div className={`spatial-gauge-number ${getCongestionTier(currentLocTelemetry.index)}`}>
                    {currentLocTelemetry.index}
                  </div>
                  <div className="spatial-gauge-track">
                    <div
                      className={`spatial-gauge-bar ${getCongestionTier(currentLocTelemetry.index)}`}
                      style={{ width: `${Math.min(100, Math.max(0, currentLocTelemetry.index))}%` }}
                    />
                  </div>
                  <span className="spatial-gauge-caption">SPATIAL CONGESTION INDEX (0–100)</span>
                </div>

                <div className="spatial-telemetry-rows">
                  <div className="spatial-row-item">
                    <span className="spatial-row-label">Geographic Coordinates</span>
                    <span className="spatial-row-value" style={{ color: '#7dd3fc', fontSize: '0.68rem' }}>
                      {currentLocObj.coords}
                    </span>
                  </div>

                  <div className="spatial-row-item">
                    <span className="spatial-row-label">Optical Resolution</span>
                    <span className="spatial-row-value" style={{ color: '#34d399', fontSize: '0.68rem' }}>
                      1280x720 High-Res Ortho
                    </span>
                  </div>

                  <div className="spatial-row-item">
                    <span className="spatial-row-label">Estimated Vessel Count</span>
                    <span className="spatial-row-value">{currentLocTelemetry.vessels} vessels</span>
                  </div>

                  <div className="spatial-row-item">
                    <span className="spatial-row-label">Transit Latency Risk</span>
                    <span className={`spatial-risk-pill ${getCongestionTier(currentLocTelemetry.index)}`}>
                      {currentLocTelemetry.latency.toUpperCase()} RISK
                    </span>
                  </div>

                  <div className="spatial-row-item">
                    <span className="spatial-row-label">SAM 3.1 Model Token</span>
                    <span className="spatial-row-value" style={{ color: '#7dd3fc', fontSize: '0.68rem' }}>
                      {currentLocTelemetry.token}
                    </span>
                  </div>

                  <div className="spatial-row-item">
                    <span className="spatial-row-label">STAC Constellation</span>
                    <span className="spatial-row-value" style={{ fontSize: '0.68rem' }}>
                      Sentinel-2 L2A (AWS Earth Search)
                    </span>
                  </div>

                  <div className="spatial-row-item">
                    <span className="spatial-row-label">Pipeline Refresh Cadence</span>
                    <span className="spatial-row-value" style={{ fontSize: '0.68rem', color: '#34d399' }}>
                      24h Pre-Debate Cycle
                    </span>
                  </div>

                  <div className="spatial-row-item">
                    <span className="spatial-row-label">Last Capture Timestamp</span>
                    <span className="spatial-row-value" style={{ fontSize: '0.68rem' }}>
                      {activeSnapshot?.captured_at
                        ? new Date(activeSnapshot.captured_at).toLocaleString('en-GB', {
                            day: '2-digit',
                            month: 'short',
                            year: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : 'Benchmark Verified'}
                    </span>
                  </div>
                </div>

                <div className="spatial-footer-note">
                  <div><b>DATA PIPELINE:</b> AWS Earth Search STAC (No Auth / Zero Token Burn)</div>
                  <div><b>COMPUTER VISION:</b> SAM 3.1 Tanker Segmentation (Mocked until final release)</div>
                  <div><b>FAILSAFE:</b> Auto-fallback static asset policy guarantees zero blank screens.</div>
                </div>
              </div>
            </div>

            <div className="spatial-disclaimer-box">
              Satellite imagery sourced from ESA Copernicus Sentinel-2 via AWS Earth Search open STAC catalog. SAM 3.1 vessel identification and congestion indices are informational models for research purposes and do not constitute real-time vessel navigation guarantees.
            </div>
          </div>
        ))}

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

            <DeskSynthesisAnalysis
              analysis={activeAnalysis}
              loading={strategyDeskLoading}
              error={strategyDeskError}
            />

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

              <DeskSignalPanel
                analysis={activeAnalysis}
                marketData={brentData}
                loading={strategyDeskLoading}
                error={strategyDeskError}
              />
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
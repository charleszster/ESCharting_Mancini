import { useState, useRef, useEffect } from 'react'
import './App.css'
import Chart from './components/Chart'
import TradeList from './components/TradeList'
import TimeframeSelector from './components/TimeframeSelector'
import LevelsPanel from './components/LevelsPanel'
import ChartSettings from './components/ChartSettings'
import DownloadModal from './components/DownloadModal'

const DEFAULT_SETTINGS = {
  // Candles — TradingView default palette
  upColor:       '#26a69a',
  downColor:     '#ef5350',
  upBorder:      '#26a69a',
  downBorder:    '#ef5350',
  upWick:        '#26a69a',
  downWick:      '#ef5350',
  wickVisible:   true,
  borderVisible: true,
  // Background / text
  backgroundColor: '#ffffff',
  textColor:       '#131722',
  // Grid — very subtle, TV style
  gridHorzVisible: true,
  gridHorzColor:   '#f0f3fa',
  gridVertVisible: true,
  gridVertColor:   '#f0f3fa',
  // Session shading
  session: {
    enabled: true,
    mode:    'eth',
    color:   '#131722',
    opacity: 0.03,
  },
  // Volume histogram
  showVolume:   false,
  volUpColor:   '#26a69a',
  volDownColor: '#ef5350',
  volHeightPct: 0.15,
  // Crosshair
  crosshairMode:  3,
  crosshairColor: '#9598a1',
  crosshairWidth: 1,
  // Markers
  markerFontSize: 11,
  // Level labels
  levelFontSize:    9,
  levelShowBox:     false,
  levelShowZones:   true,
  levelZoneOpacity: 0.10,
  // Price scale
  logScale:          false,
  invertScale:       false,
  scaleMarginTop:    0.1,
  scaleMarginBottom: 0.1,
}

const API_BASE = 'http://localhost:8000'

export default function App() {
  const chartRef = useRef(null)
  const [leftOpen,      setLeftOpen]      = useState(true)
  const [rightOpen,     setRightOpen]     = useState(true)
  const [leftWidth,     setLeftWidth]     = useState(220)
  const [rightWidth,    setRightWidth]    = useState(270)
  const [timeframe,     setTimeframe]     = useState('5m')
  const [adjMode,       setAdjMode]       = useState('non-adj')
  const [selectedTrade,     setSelectedTrade]     = useState(null)
  const [selectedTradeData, setSelectedTradeData] = useState(null)
  const [focusDate,         setFocusDate]         = useState(null)
  const [settings,      setSettings]      = useState(DEFAULT_SETTINGS)
  const [showSettings,  setShowSettings]  = useState(false)
  const [showDownload,  setShowDownload]  = useState(false)

  // Data bounds — fetched from backend on mount so they reflect the actual parquet.
  // Hardcoded fallback used only until the fetch completes.
  const DATA_START = '2016-03-29'
  const [dataEnd,   setDataEnd]  = useState('2026-03-25')
  const [dateRange, setDateRange] = useState(() => {
    const end   = new Date('2026-03-25T12:00:00Z')
    const start = new Date(end)
    start.setUTCMonth(start.getUTCMonth() - 6)
    return { start: start.toISOString().slice(0, 10), end: '2026-03-25' }
  })

  // On mount, fetch actual data bounds and update the default view
  useEffect(() => {
    fetch(`${API_BASE}/candles/bounds`)
      .then(r => r.json())
      .then(({ end }) => {
        setDataEnd(end)
        setDateRange(r => {
          const endDate   = new Date(end + 'T12:00:00Z')
          const startDate = new Date(endDate)
          startDate.setUTCMonth(startDate.getUTCMonth() - 6)
          return { start: startDate.toISOString().slice(0, 10), end }
        })
      })
      .catch(() => {})
  }, [])

  const [levelsData,    setLevelsData]    = useState(null)   // {date, supports, resistances}
  const [levelsDate,    setLevelsDate]    = useState(null)   // null = use latest
  const [levelsVisible, setLevelsVisible] = useState(true)

  // ── Fetch levels whenever levelsDate changes ─────────────────────────────
  // null means "latest available", but cap at dataEnd so we don't show
  // levels for dates beyond the chart data we actually have.
  useEffect(() => {
    const date = levelsDate ?? dataEnd
    fetch(`${API_BASE}/levels?date=${date}`)
      .then(r => r.json())
      .then(data => setLevelsData(data.date ? data : null))
      .catch(() => setLevelsData(null))
  }, [levelsDate])

  // If a trade is entered at or after 18:00 ET, Mancini's levels for that
  // session belong to the NEXT trading day (e.g. Sunday 7 PM → Monday levels).
  function getTradeSessionDate(entryDate, entryTime) {
    if (!entryTime || entryTime < '18:00:00') return entryDate
    const d = new Date(entryDate + 'T12:00:00Z')
    d.setUTCDate(d.getUTCDate() + 1)
    if (d.getUTCDay() === 6) d.setUTCDate(d.getUTCDate() + 2) // Fri+1=Sat → Mon
    return d.toISOString().slice(0, 10)
  }

  function handleTradeSelect(trade) {
    if (selectedTrade === trade.id) {
      setSelectedTrade(null)
      setSelectedTradeData(null)
      setFocusDate(null)
      return
    }
    setSelectedTrade(trade.id)
    setSelectedTradeData(trade)
    setFocusDate(trade.entry_date)
    setLevelsDate(getTradeSessionDate(trade.entry_date, trade.entry_time))
    setAdjMode('non-adj')             // levels are non-adjusted; switch mode to match

    // ±6 months around the trade date, clamped to available data
    const base  = new Date(trade.entry_date + 'T12:00:00Z')
    const start = new Date(base)
    start.setUTCMonth(start.getUTCMonth() - 6)
    const end = new Date(base)
    end.setUTCMonth(end.getUTCMonth() + 6)

    const clamp = (d, lo, hi) => d < lo ? lo : d > hi ? hi : d
    const lo = new Date(DATA_START + 'T00:00:00Z')
    const hi = new Date(dataEnd    + 'T00:00:00Z')

    setDateRange({
      start: clamp(start, lo, hi).toISOString().slice(0, 10),
      end:   clamp(end,   lo, hi).toISOString().slice(0, 10),
    })
  }

  function startDrag(e, getCurrent, setter, minW = 120, maxW = 600) {
    e.preventDefault()
    const startX = e.clientX
    const startW = getCurrent()
    const onMove = mv => setter(Math.max(minW, Math.min(maxW, startW + mv.clientX - startX)))
    const onUp   = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup',   onUp)
  }

  return (
    <div className="app-shell">
      {/* Top bar */}
      <div className="topbar">
        <span className="topbar-title">ES Trade Analyzer</span>
        <div className="topbar-actions">
          <button onClick={() => setShowDownload(true)}>Download data</button>
          <button>Settings</button>
        </div>
      </div>

      {/* Main body */}
      <div className="app-body">
        {/* Left panel */}
        <div
          className={`left-panel${leftOpen ? '' : ' collapsed'}`}
          style={leftOpen ? { width: leftWidth } : undefined}
        >
          {leftOpen && <TradeList selectedId={selectedTrade} onSelect={handleTradeSelect} />}
          <button
            className="left-panel-toggle"
            onClick={() => setLeftOpen(o => !o)}
            title={leftOpen ? 'Collapse' : 'Expand'}
            style={{ writingMode: 'horizontal-tb', width: '100%', flexShrink: 0, height: leftOpen ? 'auto' : '100%', borderTop: leftOpen ? '1px solid var(--border)' : 'none' }}
          >
            {leftOpen ? '◀ collapse' : '▶'}
          </button>
        </div>

        {/* Left resize handle */}
        {leftOpen && (
          <div
            className="panel-resize-handle"
            onMouseDown={e => startDrag(e, () => leftWidth, setLeftWidth)}
          />
        )}

        {/* Center: toolbar + chart */}
        <div className="center-panel">
          <div className="toolbar">
            <TimeframeSelector value={timeframe} onChange={setTimeframe} />
            <div className="toolbar-sep" />

            {/* Date range picker */}
            <div className="date-range">
              <input
                type="date"
                value={dateRange.start}
                onChange={e => { setDateRange(r => ({ ...r, start: e.target.value })); setFocusDate(null) }}
                className="date-input"
              />
              <span className="date-sep">–</span>
              <input
                type="date"
                value={dateRange.end}
                onChange={e => { setDateRange(r => ({ ...r, end: e.target.value })); setFocusDate(null) }}
                className="date-input"
              />
            </div>
            <div className="toolbar-sep" />

            {/* Reset view */}
            <button className="tf-btn" title="Reset view (fit all)" onClick={() => { chartRef.current?.resetView(); setLevelsDate(null) }}>
              ⊡
            </button>
            <div className="toolbar-sep" />

            {/* Chart settings button */}
            <button className="tf-btn" title="Chart settings" onClick={() => setShowSettings(true)}>
              ⚙
            </button>
            <div className="toolbar-sep" />

            <div className="adj-toggle-group">
              <button className={adjMode === 'adj'     ? 'active' : ''} onClick={() => setAdjMode('adj')}>Adjusted</button>
              <button className={adjMode === 'non-adj' ? 'active' : ''} onClick={() => setAdjMode('non-adj')}>Non-Adj</button>
            </div>
          </div>

          <div className="chart-container">
            <Chart ref={chartRef} timeframe={timeframe} settings={settings} dateRange={dateRange} focusDate={focusDate} tradeData={selectedTradeData} adjMode={adjMode} levels={levelsVisible ? levelsData : null} />
          </div>
        </div>

        {/* Right resize handle */}
        {rightOpen && (
          <div
            className="panel-resize-handle"
            onMouseDown={e => startDrag(e, () => rightWidth, w => setRightWidth(w), 150, 600)}
          />
        )}

        {/* Right panel */}
        <div
          className={`right-panel${rightOpen ? '' : ' collapsed'}`}
          style={rightOpen ? { width: rightWidth } : undefined}
        >
          {rightOpen && <LevelsPanel selectedTrade={selectedTrade} selectedDate={dateRange.start} tradeData={selectedTradeData} levelsData={levelsData} levelsDate={levelsDate} onLevelsDateChange={setLevelsDate} onLevelsSaved={setLevelsData} levelsVisible={levelsVisible} onLevelsVisibleChange={setLevelsVisible} />}
          <button
            className="right-panel-toggle"
            onClick={() => setRightOpen(o => !o)}
            title={rightOpen ? 'Collapse' : 'Expand'}
            style={{ height: rightOpen ? 'auto' : '100%' }}
          >
            {rightOpen ? '▶ collapse' : '◀'}
          </button>
        </div>
      </div>

      {/* Status bar */}
      <div className="statusbar">
        <div className="status-item">
          <span className="status-dot" />
          <span>Backend: connected</span>
        </div>
        <div className="status-item">
          <span>Mode: {adjMode === 'adj' ? 'Adjusted' : 'Non-Adjusted'}</span>
        </div>
        <div className="status-item">
          <span>Levels: {levelsData?.date ?? '—'}</span>
        </div>
        <div className="status-item">
          <span>Timeframe: {timeframe}</span>
        </div>
      </div>

      {/* Chart settings modal */}
      {showSettings && (
        <ChartSettings value={settings} onChange={setSettings} onClose={() => setShowSettings(false)} />
      )}

      {/* Databento download modal */}
      {showDownload && (
        <DownloadModal
          dataEnd={dataEnd}
          onClose={() => setShowDownload(false)}
          onSuccess={newEnd => {
            setDataEnd(newEnd)
            setDateRange(r => ({ ...r, end: newEnd }))
          }}
        />
      )}
    </div>
  )
}

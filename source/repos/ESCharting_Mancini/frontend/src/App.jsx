import { useState } from 'react'
import './App.css'
import Chart from './components/Chart'
import TradeList from './components/TradeList'
import TimeframeSelector from './components/TimeframeSelector'
import LevelsPanel from './components/LevelsPanel'

export default function App() {
  const [leftOpen, setLeftOpen] = useState(true)
  const [timeframe, setTimeframe] = useState('5m')
  const [adjMode, setAdjMode] = useState('non-adj')
  const [selectedTrade, setSelectedTrade] = useState(null)

  function handleSelectTrade(id) {
    setSelectedTrade(prev => (prev === id ? null : id))
  }

  return (
    <div className="app-shell">
      {/* Top bar */}
      <div className="topbar">
        <span className="topbar-title">ES Trade Analyzer</span>
        <div className="topbar-actions">
          <button>Download data</button>
          <button>Settings</button>
        </div>
      </div>

      {/* Main body */}
      <div className="app-body">
        {/* Left panel */}
        <div className={`left-panel${leftOpen ? '' : ' collapsed'}`}>
          {leftOpen && <TradeList selectedId={selectedTrade} onSelect={handleSelectTrade} />}
          <button
            className="left-panel-toggle"
            onClick={() => setLeftOpen(o => !o)}
            title={leftOpen ? 'Collapse' : 'Expand'}
            style={{ writingMode: 'horizontal-tb', width: '100%', flexShrink: 0, height: leftOpen ? 'auto' : '100%', borderTop: leftOpen ? '1px solid var(--border)' : 'none' }}
          >
            {leftOpen ? '◀ collapse' : '▶'}
          </button>
        </div>

        {/* Center: toolbar + chart */}
        <div className="center-panel">
          <div className="toolbar">
            <TimeframeSelector value={timeframe} onChange={setTimeframe} />
            <div className="toolbar-sep" />
            <div className="adj-toggle-group">
              <button
                className={adjMode === 'adj' ? 'active' : ''}
                onClick={() => setAdjMode('adj')}
              >Adjusted</button>
              <button
                className={adjMode === 'non-adj' ? 'active' : ''}
                onClick={() => setAdjMode('non-adj')}
              >Non-Adj</button>
            </div>
          </div>
          <div className="chart-container">
            <Chart />
          </div>
        </div>

        {/* Right panel */}
        <div className="right-panel">
          <LevelsPanel
            selectedTrade={selectedTrade}
            selectedDate="03/20/24"
          />
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
          <span>Timeframe: {timeframe}</span>
        </div>
        <div className="status-item">
          <span>10 trades loaded</span>
        </div>
      </div>
    </div>
  )
}

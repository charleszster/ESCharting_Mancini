/**
 * StudyTrades.jsx — Research study trade overlay panel.
 *
 * Shows historical study trade setups on the chart as hollow markers.
 * Completely self-contained: remove this file + the two lines in App.jsx
 * and Chart.jsx (marked with "// STUDY TRADES") to disable entirely.
 *
 * Props:
 *   dateRange       { start: 'YYYY-MM-DD', end: 'YYYY-MM-DD' }
 *   onTradesChange  (trades: Array) => void   — feed markers to Chart
 *   onSelectTrade   (trade) => void           — zoom chart to bar
 */

import { useState, useEffect, useCallback } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export const STUDY_SETUP_META = {
  afternoon_ft: { label: 'Afternoon First Touch', short: 'AFT', winColor: '#7C3AED', lossColor: '#EA580C' },
  fb_afternoon: { label: 'FB — Afternoon',        short: 'FBA', winColor: '#0891B2', lossColor: '#EA580C' },
  fb_opening:   { label: 'FB — Opening (9:30)',   short: 'FBO', winColor: '#059669', lossColor: '#EA580C' },
}

function formatET(touchTime) {
  try {
    const d = new Date(touchTime)
    const date = d.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', timeZone: 'America/New_York' })
    const time = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/New_York' })
    return `${date} ${time}`
  } catch {
    return touchTime
  }
}

export default function StudyTrades({ dateRange, onTradesChange, onSelectTrade }) {
  const [enabled,  setEnabled]  = useState(false)
  const [setups,   setSetups]   = useState({ afternoon_ft: true, fb_afternoon: true, fb_opening: false })
  const [result,   setResult]   = useState('all')   // 'all' | 'win' | 'loss'
  const [trades,   setTrades]   = useState([])
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  const fetchTrades = useCallback(() => {
    const activeSetups = Object.entries(setups)
      .filter(([, v]) => v)
      .map(([k]) => k)

    if (!enabled || activeSetups.length === 0) {
      setTrades([])
      onTradesChange([])
      return
    }

    setLoading(true)
    setError(null)

    const params = new URLSearchParams({ setup: activeSetups.join(','), result })
    if (dateRange?.start) params.set('date_from', dateRange.start)
    if (dateRange?.end)   params.set('date_to',   dateRange.end)

    fetch(`${API_BASE}/study-trades?${params}`)
      .then(r => r.json())
      .then(data => {
        if (data.error) { setError(data.error); setTrades([]); onTradesChange([]); }
        else { setTrades(data.trades ?? []); onTradesChange(data.trades ?? []) }
        setLoading(false)
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [enabled, setups, result, dateRange?.start, dateRange?.end, onTradesChange])

  useEffect(() => { fetchTrades() }, [fetchTrades])

  const toggleSetup = key => setSetups(s => ({ ...s, [key]: !s[key] }))

  const wins   = trades.filter(t => t.outcome === 1).length
  const losses = trades.filter(t => t.outcome === 0).length

  return (
    <div className="study-trades-panel">
      {/* Header row — click to enable/disable */}
      <div className="study-trades-header" onClick={() => setEnabled(e => !e)}>
        <span className={`study-dot${enabled ? ' on' : ''}`} />
        <span className="study-title">Study Trades</span>
        {enabled && !loading && trades.length > 0 && (
          <span className="study-count">
            {trades.length} &nbsp;
            <span className="study-w">{wins}W</span>
            <span className="study-l">{losses}L</span>
          </span>
        )}
        {loading && <span className="study-count">...</span>}
      </div>

      {enabled && (
        <div className="study-controls">
          {/* Setup toggles */}
          <div className="study-setups">
            {Object.entries(STUDY_SETUP_META).map(([key, meta]) => (
              <label key={key} className={`study-setup-row${setups[key] ? ' active' : ''}`}>
                <input type="checkbox" checked={setups[key]} onChange={() => toggleSetup(key)} />
                <span className="study-setup-dot" style={{ background: meta.winColor }} />
                <span>{meta.label}</span>
              </label>
            ))}
          </div>

          {/* Result filter */}
          <div className="study-result-filter">
            {['all', 'win', 'loss'].map(r => (
              <button
                key={r}
                className={`study-rf-btn${result === r ? ' active' : ''}`}
                onClick={() => setResult(r)}
              >
                {r[0].toUpperCase() + r.slice(1)}
              </button>
            ))}
          </div>

          {error && <div className="study-error">{error}</div>}

          {/* Trade list */}
          <div className="study-list">
            {trades.length === 0 && !loading && (
              <div className="study-empty">No trades in date range</div>
            )}
            {trades.map((t, i) => {
              const meta = STUDY_SETUP_META[t.setup_type] ?? STUDY_SETUP_META.afternoon_ft
              const color = t.outcome === 1 ? meta.winColor : t.outcome === 0 ? meta.lossColor : '#888'
              return (
                <div
                  key={i}
                  className="study-row"
                  style={{ borderLeft: `3px solid ${color}` }}
                  onClick={() => onSelectTrade?.(t)}
                  title={`${meta.label} | Level ${t.level_price} | ${t.is_support ? 'Long' : 'Short'} | ${t.sr_flip ? 'SR flip' : ''} ${t.is_major ? 'Major' : 'Minor'}`}
                >
                  <span className="st-time">{formatET(t.touch_time)}</span>
                  <span className="st-price">{t.level_price}</span>
                  <span className="st-dir" style={{ color }}>{t.is_support ? 'L' : 'S'}</span>
                  <span className="st-tag">{meta.short}</span>
                  <span className="st-result" style={{ color }}>
                    {t.outcome === 1 ? 'W' : t.outcome === 0 ? 'L' : '?'}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

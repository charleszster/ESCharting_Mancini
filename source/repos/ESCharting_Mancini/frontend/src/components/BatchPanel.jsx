import { useState, useEffect } from 'react'

function addDays(dateStr, n) {
  const d = new Date(dateStr + 'T12:00:00Z')
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

function clampDate(d, lo, hi) {
  if (d < lo) return lo
  if (d > hi) return hi
  return d
}

export default function BatchPanel({ trades, dataStart, dataEnd, active, onShow, onClear }) {
  const [collapsed, setCollapsed] = useState(false)
  const [filter,    setFilter]    = useState('all')   // 'all' | 'winners' | 'losers'
  const [fromDate,  setFromDate]  = useState('')
  const [toDate,    setToDate]    = useState('')
  const [noResults, setNoResults] = useState(false)

  // Default date range = full span of loaded trades (trades are newest-first)
  useEffect(() => {
    if (!trades.length) return
    const dates = trades.map(t => t.entry_date)
    setFromDate(dates[dates.length - 1])   // oldest
    setToDate(dates[0])                    // newest
  }, [trades.length])

  function handleShow() {
    const filtered = trades
      .filter(t => t.entry_date >= fromDate && t.entry_date <= toDate)
      .filter(t => {
        if (filter === 'winners') return t.net_pnl > 0
        if (filter === 'losers')  return t.net_pnl < 0
        return true
      })

    if (!filtered.length) { setNoResults(true); return }
    setNoResults(false)

    // Chart window: first entry − 28 cal days → last exit + 28 cal days, clamped
    const entryDates = filtered.map(t => t.entry_date)
    const exitDates  = filtered.flatMap(t => t.exits.map(e => e.date))
    const allDates   = [...entryDates, ...exitDates]
    const firstDate  = allDates.reduce((a, b) => a < b ? a : b)
    const lastDate   = allDates.reduce((a, b) => a > b ? a : b)

    const chartStart = clampDate(addDays(firstDate, -28), dataStart, dataEnd)
    const chartEnd   = clampDate(addDays(lastDate,  +28), dataStart, dataEnd)

    onShow(filtered, chartStart, chartEnd)
  }

  function handleClear() {
    setNoResults(false)
    onClear()
  }

  const canShow = fromDate && toDate && fromDate <= toDate

  return (
    <div className={`batch-panel${active ? ' batch-active' : ''}`}>
      <div className="batch-header" onClick={() => setCollapsed(c => !c)}>
        <span className="batch-title">
          Batch View{active ? ' ●' : ''}
        </span>
        <span className="batch-toggle-arrow">{collapsed ? '▼' : '▲'}</span>
      </div>

      {!collapsed && (
        <div className="batch-body">
          <div className="batch-date-row">
            <span className="batch-label">From</span>
            <input type="date" className="date-input batch-date-input" value={fromDate}
              onChange={e => { setFromDate(e.target.value); setNoResults(false) }} />
          </div>
          <div className="batch-date-row">
            <span className="batch-label">To</span>
            <input type="date" className="date-input batch-date-input" value={toDate}
              onChange={e => { setToDate(e.target.value); setNoResults(false) }} />
          </div>

          <div className="batch-filter-row">
            {['all', 'winners', 'losers'].map(f => (
              <button key={f}
                className={`batch-filter-btn${filter === f ? ' active' : ''}`}
                onClick={() => { setFilter(f); setNoResults(false) }}
              >
                {f[0].toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>

          {noResults && <div className="batch-no-results">No trades match</div>}

          <div className="batch-action-row">
            <button className="batch-show-btn" onClick={handleShow} disabled={!canShow}>
              Show on chart
            </button>
            <button className="batch-clear-btn" onClick={handleClear}>
              Clear
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

import { useState, useEffect } from 'react'

const API_BASE = 'http://localhost:8000'

// ── helpers ──────────────────────────────────────────────────────────────────

function fmtTime(hms) {
  return hms ? hms.slice(0, 5) : '—'
}

function fmtDuration(seconds) {
  if (seconds == null || seconds < 0) return null
  const s = Math.round(seconds)
  if (s < 60)   return `${s}s`
  const m = Math.floor(s / 60), rs = s % 60
  if (m < 60)   return rs ? `${m}m ${rs}s` : `${m}m`
  const h = Math.floor(m / 60), rm = m % 60
  return rm ? `${h}h ${rm}m` : `${h}h`
}

function fmtPnl(val) {
  const abs = Math.abs(val).toLocaleString('en-US', {
    style: 'currency', currency: 'USD', minimumFractionDigits: 2,
  })
  return val >= 0 ? `+${abs}` : `−${abs.slice(1)}`
}

function Toggle({ checked, onChange }) {
  return (
    <label className="toggle-switch">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      <span className="toggle-slider" />
    </label>
  )
}

// ── trade detail ─────────────────────────────────────────────────────────────

function TradeDetail({ trade }) {
  if (!trade) {
    return <div className="trade-detail-placeholder">No trade selected — Planning Mode</div>
  }

  const isLong   = trade.direction === 'long'
  const grossPnl = trade.net_pnl + trade.commission
  const lastExit = trade.exits.length
    ? trade.exits.reduce((a, b) => ((b.ts ?? 0) > (a.ts ?? 0) ? b : a))
    : null
  const duration = lastExit?.ts != null && trade.entry_ts != null
    ? fmtDuration(lastExit.ts - trade.entry_ts)
    : null

  return (
    <div className="td">
      <div className="td-header">
        <span className={`td-badge ${isLong ? 'long' : 'short'}`}>
          {isLong ? 'Long' : 'Short'}
        </span>
        <span className="td-meta">{Math.abs(trade.entry_qty)} contracts</span>
        <span className="td-meta">{trade.entry_date}</span>
      </div>

      <div className="td-section-title">Entry</div>
      <div className="td-row">
        <span className="td-time">{fmtTime(trade.entry_time)} ET</span>
        <span className="td-price">{trade.entry_price.toFixed(2)}</span>
        <span className="td-qty">×{Math.abs(trade.entry_qty)}</span>
      </div>

      {trade.exits.length > 0 && (
        <>
          <div className="td-section-title">Exit{trade.exits.length > 1 ? 's' : ''}</div>
          {trade.exits.map((ex, i) => (
            <div className="td-row" key={i}>
              <span className="td-time">
                {ex.date !== trade.entry_date && <span className="td-diff-date">{ex.date} </span>}
                {fmtTime(ex.time)} ET
              </span>
              <span className="td-price">{ex.price.toFixed(2)}</span>
              <span className="td-qty">×{Math.abs(ex.qty)}</span>
            </div>
          ))}
        </>
      )}

      <div className="td-section-title">P&amp;L</div>
      <div className="td-pnl-row">
        <span className="td-pnl-label">Gross</span>
        <span className={`td-pnl-val ${grossPnl >= 0 ? 'pos' : 'neg'}`}>{fmtPnl(grossPnl)}</span>
      </div>
      <div className="td-pnl-row">
        <span className="td-pnl-label">Commission</span>
        <span className="td-pnl-val neg">−${trade.commission.toFixed(2)}</span>
      </div>
      <div className="td-pnl-row td-pnl-net">
        <span className="td-pnl-label">Net</span>
        <span className={`td-pnl-val ${trade.net_pnl >= 0 ? 'pos' : 'neg'}`}>{fmtPnl(trade.net_pnl)}</span>
      </div>

      {duration && <div className="td-duration">Duration: {duration}</div>}
    </div>
  )
}

// ── main component ────────────────────────────────────────────────────────────

export default function LevelsPanel({
  selectedTrade, selectedDate, tradeData,
  levelsData, levelsDate, onLevelsDateChange, onLevelsSaved,
  manualVisible, onManualVisibleChange,
  autoVisible, onAutoVisibleChange,
  autoLevelsData, onGenerateAutoLevels,
  autoLevelsLoading, autoLevelsError,
}) {
  const [tradeOpen,    setTradeOpen]    = useState(true)
  const [detailHeight, setDetailHeight] = useState(180)
  const [autoGenDate,  setAutoGenDate]  = useState('')   // '' = most recent 4pm
  const [autoOpen,     setAutoOpen]     = useState(false)

  // Auto-open the Auto Levels section when data arrives
  useEffect(() => {
    if (autoLevelsData) setAutoOpen(true)
  }, [autoLevelsData])

  // Edit buffers
  const [resRaw,    setResRaw]    = useState('')
  const [supRaw,    setSupRaw]    = useState('')
  // "Save to" date — user can change this to create a new entry
  const [saveDate,  setSaveDate]  = useState('')
  const [saving,    setSaving]    = useState(false)
  const [saveMsg,   setSaveMsg]   = useState('')

  // Reimport state
  const [reimporting, setReimporting] = useState(false)
  const [reimportMsg, setReimportMsg] = useState('')

  // Sync edit buffers when loaded levels change.
  // Only populate if the returned date exactly matches what was requested —
  // otherwise leave textareas blank (user is entering a new date).
  useEffect(() => {
    const exactMatch = !levelsDate || levelsData?.date === levelsDate
if (exactMatch) {
      setResRaw(levelsData?.resistances_raw ?? '')
      setSupRaw(levelsData?.supports_raw    ?? '')
      setSaveDate(levelsDate ?? levelsData?.date ?? '')
    } else {
      setSaveDate(levelsDate ?? '')
    }
    setSaveMsg('')
  }, [levelsData, levelsDate])

  function startDragDetail(e) {
    e.preventDefault()
    const startY = e.clientY
    const startH = detailHeight
    const onMove = mv => setDetailHeight(Math.max(60, Math.min(600, startH + mv.clientY - startY)))
    const onUp   = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup',   onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup',   onUp)
  }

  async function handleSave() {
    if (!saveDate) return
    setSaving(true)
    setSaveMsg('')
    try {
      const res = await fetch(`${API_BASE}/levels`, {
        method:  'PUT',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ date: saveDate, supports_raw: supRaw, resistances_raw: resRaw }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const updated = await res.json()
      onLevelsSaved(updated)
      onLevelsDateChange(saveDate)  // switch view to the saved date
      setSaveMsg('Saved')
    } catch {
      setSaveMsg('Error saving')
    } finally {
      setSaving(false)
    }
  }

  async function handleReimport() {
    setReimporting(true)
    setReimportMsg('')
    try {
      const res = await fetch(`${API_BASE}/levels/reimport`, { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setReimportMsg(`${data.imported} rows imported (latest: ${data.latest_date})`)
      // Refresh the currently viewed levels
      onLevelsDateChange(levelsDate)
    } catch {
      setReimportMsg('Import failed')
    } finally {
      setReimporting(false)
    }
  }

  return (
    <div className="levels-panel">

      {/* ── Trade detail ── */}
      <div
        className="right-section levels-panel-top"
        style={tradeOpen ? { height: detailHeight } : undefined}
      >
        <div
          className="right-section-title right-section-title--toggle"
          onClick={() => setTradeOpen(o => !o)}
        >
          Trade Detail
          <span className="section-chevron">{tradeOpen ? '▾' : '▸'}</span>
        </div>
        {tradeOpen && <TradeDetail trade={tradeData} />}
      </div>

      {tradeOpen && (
        <div className="section-resize-handle" onMouseDown={startDragDetail} />
      )}

      {/* ── Scrollable lower area ── */}
      <div className="levels-panel-bottom">
        <div className="right-section">
          <div className="right-section-title">Layers</div>
          <div className="layer-row">
            <span className="layer-label">Manual levels</span>
            <Toggle checked={manualVisible} onChange={onManualVisibleChange} />
          </div>
          <div className="layer-row">
            <span className="layer-label">Auto levels</span>
            <Toggle checked={autoVisible} onChange={onAutoVisibleChange} />
          </div>
          <div className="levels-date-row" style={{ marginTop: 6 }}>
            <input
              type="date"
              className="date-input levels-date-input"
              value={autoGenDate}
              onChange={e => setAutoGenDate(e.target.value)}
              title="Leave blank to use most recent 4pm ET bar"
            />
            <button
              className="copy-btn"
              onClick={() => setAutoGenDate('')}
              title="Clear — use most recent 4pm"
            >latest</button>
          </div>
          <button
            className="gen-levels-btn"
            onClick={() => onGenerateAutoLevels(autoGenDate || null)}
            disabled={autoLevelsLoading}
          >
            {autoLevelsLoading ? 'Generating…' : 'Generate auto levels'}
          </button>
          {autoLevelsData && !autoLevelsLoading && (
            <div className="levels-date-matched">
              Auto: {autoLevelsData.date} · 4pm {autoLevelsData.close4pm}
            </div>
          )}
          {autoLevelsError && (
            <div className="levels-date-matched err-text">{autoLevelsError}</div>
          )}

          {/* Levels date picker */}
          <div className="levels-date-row" style={{ marginTop: 10 }}>
            <span className="layer-label">Levels date</span>
          </div>
          <div className="levels-date-row">
            <input
              type="date"
              className="date-input levels-date-input"
              value={levelsDate ?? ''}
              onChange={e => {
                const d = e.target.value || null
                if (d) { setResRaw(''); setSupRaw(''); setSaveDate(d); setSaveMsg('') }
                onLevelsDateChange(d)
              }}
            />
            <button
              className="copy-btn"
              title="Use latest available levels"
              onClick={() => onLevelsDateChange(null)}
            >latest</button>
          </div>
          {levelsData?.date && (
            <div className="levels-date-matched">
              Showing: {levelsData.date}
            </div>
          )}

          {/* Batch reimport */}
          <div className="levels-date-row" style={{ marginTop: 8 }}>
            <button
              className="gen-levels-btn"
              onClick={handleReimport}
              disabled={reimporting}
              title="Re-read the Excel file and upsert all rows into the database"
            >
              {reimporting ? 'Importing…' : 'Re-import from Excel'}
            </button>
          </div>
          {reimportMsg && (
            <div className={`levels-date-matched ${reimportMsg.includes('failed') ? 'err-text' : ''}`}>
              {reimportMsg}
            </div>
          )}
        </div>

        {/* ── Auto levels read-only view ── */}
        {autoLevelsData && (
          <div className="right-section">
            <div
              className="right-section-title right-section-title--toggle"
              onClick={() => setAutoOpen(o => !o)}
            >
              Auto Levels (read-only)
              <span className="section-chevron">{autoOpen ? '▾' : '▸'}</span>
            </div>
            {autoOpen && (
              <>
                <div className="level-label-row">
                  <span className="level-label-text">Resistances</span>
                </div>
                <textarea
                  className="level-textarea"
                  readOnly
                  value={autoLevelsData.resistances_raw ?? ''}
                />
                <div className="level-label-row">
                  <span className="level-label-text">Supports</span>
                </div>
                <textarea
                  className="level-textarea"
                  readOnly
                  value={autoLevelsData.supports_raw ?? ''}
                />
              </>
            )}
          </div>
        )}

        <div className="right-section">
          <div className="right-section-title">Levels</div>

          <div className="level-label-row">
            <span className="level-label-text">Resistances</span>
          </div>
          <textarea
            className="level-textarea"
            placeholder="e.g. 5270, 5280 (major), 5295"
            value={resRaw}
            onChange={e => { setResRaw(e.target.value); setSaveMsg('') }}
          />

          <div className="level-label-row">
            <span className="level-label-text">Supports</span>
          </div>
          <textarea
            className="level-textarea"
            placeholder="e.g. 5240, 5228 (major), 5210"
            value={supRaw}
            onChange={e => { setSupRaw(e.target.value); setSaveMsg('') }}
          />

          {/* Save-to date — editable so user can create a new entry */}
          <div className="levels-save-date-row">
            <span className="layer-label" style={{ flexShrink: 0 }}>Save to date</span>
            <input
              type="date"
              className="date-input levels-date-input"
              value={saveDate}
              onChange={e => { setSaveDate(e.target.value); setSaveMsg('') }}
            />
          </div>

          <div className="levels-save-row">
            <button
              className="save-btn"
              onClick={handleSave}
              disabled={saving || !saveDate}
            >
              {saving ? 'Saving…' : 'Save levels'}
            </button>
            {saveMsg && (
              <span className={`save-msg ${saveMsg === 'Saved' ? 'ok' : 'err'}`}>
                {saveMsg}
              </span>
            )}
          </div>
        </div>
      </div>

    </div>
  )
}

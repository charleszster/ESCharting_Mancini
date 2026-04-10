import { useState, useRef, useEffect } from 'react'

const API_BASE = 'http://localhost:8000'

function nextDay(dateStr) {
  const d = new Date(dateStr + 'T12:00:00Z')
  d.setUTCDate(d.getUTCDate() + 1)
  return d.toISOString().slice(0, 10)
}

function fmtBytes(b) {
  if (b < 1024 * 1024)           return `${(b / 1024).toFixed(1)} KB`
  if (b < 1024 * 1024 * 1024)   return `${(b / 1024 / 1024).toFixed(1)} MB`
  return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`
}

// ── Databento tab ─────────────────────────────────────────────────────────────

// Format a UTC ISO timestamp (2026-04-09T23:00:00Z) for display in ET.
function fmtEndTs(endTs) {
  if (!endTs) return null
  const d = new Date(endTs)
  return d.toLocaleString('en-US', {
    timeZone: 'America/New_York',
    month: 'numeric', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true,
  }) + ' ET'
}

function DatabentoTab({ dataEnd, endTs, onSuccess }) {
  const today = new Date().toISOString().slice(0, 10)

  // startParam: exact UTC timestamp of last bar, or nextDay(dataEnd) as fallback.
  // Read-only — user never changes it; only "To" is editable.
  const [startParam,  setStartParam]  = useState(null)
  const [endDate,     setEndDate]     = useState(today)
  const [phase,         setPhase]         = useState('idle')
  const [estimate,      setEstimate]      = useState(null)
  const [messages,      setMessages]      = useState([])
  const [error,         setError]         = useState(null)
  const [newEndDate,    setNewEndDate]     = useState(null)
  const [newEndTs,      setNewEndTs]       = useState(null)

  const esRef   = useRef(null)
  const doneRef = useRef(false)

  // Sync startParam from endTs once /candles/bounds resolves.
  // useEffect (not useState initializer) avoids the race where the modal
  // mounts before the fetch completes.
  useEffect(() => {
    if (phase !== 'idle') return
    setStartParam(endTs ?? nextDay(dataEnd))
  }, [endTs, dataEnd])  // eslint-disable-line react-hooks/exhaustive-deps

  function resetToIdle() {
    setPhase('idle'); setEstimate(null); setError(null)
    setMessages([]); doneRef.current = false
  }

  const effectiveStart = startParam ?? nextDay(dataEnd)

  async function handleEstimate() {
    setPhase('estimating'); setError(null)
    try {
      const res = await fetch(`${API_BASE}/download/estimate?start=${encodeURIComponent(effectiveStart)}&end=${endDate}`)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail ?? `HTTP ${res.status}`)
      }
      setEstimate(await res.json())
      setPhase('confirm')
    } catch (e) { setError(e.message); setPhase('error') }
  }

  function handleConfirm() {
    setPhase('downloading'); setMessages([]); doneRef.current = false
    const es = new EventSource(`${API_BASE}/download/stream?start=${encodeURIComponent(effectiveStart)}&end=${endDate}`)
    esRef.current = es
    es.onmessage = (e) => {
      const data = JSON.parse(e.data)
      if (data.type === 'progress') {
        setMessages(m => [...m, data.msg])
      } else if (data.type === 'done') {
        doneRef.current = true
        setMessages(m => [...m, data.msg])
        setNewEndDate(data.end_date)
        setNewEndTs(data.end_ts ?? null)
        setPhase('done')
        es.close(); esRef.current = null
        if (data.end_date) onSuccess(data.end_date)
      } else if (data.type === 'error') {
        doneRef.current = true
        setError(data.msg); setPhase('error')
        es.close(); esRef.current = null
      }
    }
    es.onerror = () => {
      if (!doneRef.current) { setError('Connection to server lost'); setPhase('error') }
      es.close(); esRef.current = null
    }
  }

  const canEstimate = effectiveStart && endDate && effectiveStart <= endDate

  return (
    <>
      <div className="dl-body">
        <div className="dl-current-range">
          Current data: <strong>2016-03-29 → {fmtEndTs(endTs) ?? dataEnd}</strong>
        </div>

        {(phase === 'idle' || phase === 'estimating' || phase === 'confirm') && (
          <div className="dl-date-section">
            <div className="dl-row">
              <span className="dl-label">From</span>
              <span className="dl-readonly">{fmtEndTs(endTs) ?? effectiveStart}</span>
            </div>
            <div className="dl-row">
              <span className="dl-label">To</span>
              <input type="date" className="date-input" value={endDate}
                disabled={phase !== 'idle'}
                onChange={e => { setEndDate(e.target.value); resetToIdle() }} />
            </div>
          </div>
        )}

        {phase === 'confirm' && estimate && (
          <div className="dl-estimate">
            Estimated download: <strong>{fmtBytes(estimate.size_bytes)}</strong>
            {' — '}approx. <strong>${estimate.cost_usd.toFixed(4)}</strong>
          </div>
        )}

        {(phase === 'downloading' || phase === 'done') && (
          <div className="dl-log">
            {messages.map((m, i) => (
              <div key={i} className={`dl-log-line${i === messages.length - 1 && phase === 'done' ? ' dl-log-done' : ''}`}>
                {m}
              </div>
            ))}
            {phase === 'downloading' && <div className="dl-log-line dl-log-active">Working…</div>}
          </div>
        )}

        {phase === 'error' && error && <div className="dl-error">{error}</div>}
      </div>

      <div className="dl-footer">
        {phase === 'idle' && (
          <>
            <button className="save-btn dl-btn" onClick={handleEstimate} disabled={!canEstimate}>Get estimate</button>
            <button className="dl-cancel-btn" onClick={() => esRef.current?.close()}>Cancel</button>
          </>
        )}
        {phase === 'estimating' && <button className="save-btn dl-btn" disabled>Estimating…</button>}
        {phase === 'confirm' && (
          <>
            <button className="save-btn dl-btn" onClick={handleConfirm}>Confirm &amp; Download</button>
            <button className="dl-cancel-btn" onClick={resetToIdle}>Back</button>
          </>
        )}
        {phase === 'downloading' && (
          <button className="dl-cancel-btn" onClick={() => { esRef.current?.close(); esRef.current = null }}>Cancel</button>
        )}
        {phase === 'done' && (
          <div className="dl-log-line dl-log-done" style={{ padding: '6px 0' }}>
            Done{newEndTs ? ` — data through ${fmtEndTs(newEndTs)}` : newEndDate ? ` — data through ${newEndDate}` : ''}
          </div>
        )}
        {phase === 'error' && (
          <>
            <button className="save-btn dl-btn" onClick={resetToIdle}>Try again</button>
            <button className="dl-cancel-btn" onClick={() => {}}>Close</button>
          </>
        )}
      </div>
    </>
  )
}

// ── TradingView CSV import tab ────────────────────────────────────────────────

function TradingViewTab({ onSuccess }) {
  const [file,    setFile]    = useState(null)
  const [phase,   setPhase]   = useState('idle')   // idle|importing|done|error
  const [result,  setResult]  = useState(null)
  const [error,   setError]   = useState(null)
  const fileRef = useRef(null)

  async function handleImport() {
    if (!file) return
    setPhase('importing'); setError(null); setResult(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(`${API_BASE}/import/tv`, { method: 'POST', body: form })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail ?? `HTTP ${res.status}`)
      }
      const data = await res.json()
      setResult(data)
      setPhase('done')
      onSuccess(data.end_date)
    } catch (e) { setError(e.message); setPhase('error') }
  }

  return (
    <>
      <div className="dl-body">
        <div className="dl-current-range">
          Export 1-minute OHLC from TradingView (MES1! or ES1!) and import here.
          Volume is not required — it will be set to 0.
        </div>

        <div className="dl-row">
          <input
            ref={fileRef}
            type="file"
            accept=".csv"
            style={{ display: 'none' }}
            onChange={e => { setFile(e.target.files[0] || null); setPhase('idle'); setResult(null); setError(null) }}
          />
          <button className="dl-cancel-btn" style={{ flex: 'none', width: 'auto', padding: '5px 10px' }}
            onClick={() => fileRef.current?.click()}>
            Choose CSV…
          </button>
          <span style={{ fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {file ? file.name : 'No file selected'}
          </span>
        </div>

        {phase === 'importing' && (
          <div className="dl-log">
            <div className="dl-log-line dl-log-active">Importing and rebuilding cache (~30s)…</div>
          </div>
        )}

        {phase === 'done' && result && (
          <div className="dl-estimate">
            Imported <strong>{result.new_rows.toLocaleString()}</strong> new rows
            ({result.csv_rows.toLocaleString()} in CSV) through <strong>{result.end_date}</strong>
          </div>
        )}

        {phase === 'error' && error && <div className="dl-error">{error}</div>}
      </div>

      <div className="dl-footer">
        {(phase === 'idle' || phase === 'error') && (
          <button className="save-btn dl-btn" onClick={handleImport} disabled={!file}>
            Import CSV
          </button>
        )}
        {phase === 'importing' && (
          <button className="save-btn dl-btn" disabled>Importing…</button>
        )}
        {phase === 'done' && (
          <div className="dl-log-line dl-log-done" style={{ padding: '6px 0' }}>Done</div>
        )}
      </div>
    </>
  )
}

// ── Modal shell ───────────────────────────────────────────────────────────────

export default function DownloadModal({ dataEnd, endTs, onClose, onSuccess }) {
  const [tab, setTab] = useState('databento')

  function handleSuccess(newEnd) {
    onSuccess(newEnd)
  }

  return (
    <div className="cs-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="cs-modal dl-modal">

        <div className="cs-header">
          <span className="cs-title">Import ES Data</span>
          <button className="cs-close" onClick={onClose}>×</button>
        </div>

        {/* Tab bar */}
        <div className="dl-tabs">
          <button className={`dl-tab${tab === 'databento'  ? ' active' : ''}`} onClick={() => setTab('databento')}>Databento</button>
          <button className={`dl-tab${tab === 'tradingview' ? ' active' : ''}`} onClick={() => setTab('tradingview')}>TradingView CSV</button>
        </div>

        {tab === 'databento'   && <DatabentoTab   dataEnd={dataEnd} endTs={endTs} onSuccess={handleSuccess} />}
        {tab === 'tradingview' && <TradingViewTab               onSuccess={handleSuccess} />}

      </div>
    </div>
  )
}

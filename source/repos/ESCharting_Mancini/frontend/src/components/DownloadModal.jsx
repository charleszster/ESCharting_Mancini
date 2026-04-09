import { useState, useRef } from 'react'

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

export default function DownloadModal({ dataEnd, onClose, onSuccess }) {
  const today = new Date().toISOString().slice(0, 10)

  const [startDate,  setStartDate]  = useState(nextDay(dataEnd))
  const [endDate,    setEndDate]    = useState(today)
  const [phase,      setPhase]      = useState('idle')   // idle|estimating|confirm|downloading|done|error
  const [estimate,   setEstimate]   = useState(null)
  const [messages,   setMessages]   = useState([])
  const [error,      setError]      = useState(null)
  const [newEndDate, setNewEndDate] = useState(null)

  const esRef   = useRef(null)
  const doneRef = useRef(false)   // prevents onerror false-positive on clean stream close

  function resetToIdle() {
    setPhase('idle')
    setEstimate(null)
    setError(null)
    setMessages([])
    doneRef.current = false
  }

  async function handleEstimate() {
    setPhase('estimating')
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/download/estimate?start=${startDate}&end=${endDate}`)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail ?? `HTTP ${res.status}`)
      }
      setEstimate(await res.json())
      setPhase('confirm')
    } catch (e) {
      setError(e.message)
      setPhase('error')
    }
  }

  function handleConfirm() {
    setPhase('downloading')
    setMessages([])
    doneRef.current = false

    const es = new EventSource(`${API_BASE}/download/stream?start=${startDate}&end=${endDate}`)
    esRef.current = es

    es.onmessage = (e) => {
      const data = JSON.parse(e.data)
      if (data.type === 'progress') {
        setMessages(m => [...m, data.msg])
      } else if (data.type === 'done') {
        doneRef.current = true
        setMessages(m => [...m, data.msg])
        setNewEndDate(data.end_date)
        setPhase('done')
        es.close()
        esRef.current = null
      } else if (data.type === 'error') {
        doneRef.current = true
        setError(data.msg)
        setPhase('error')
        es.close()
        esRef.current = null
      }
    }

    es.onerror = () => {
      // EventSource fires onerror when the server closes the stream normally;
      // doneRef guards against treating that as a real failure.
      if (!doneRef.current) {
        setError('Connection to server lost')
        setPhase('error')
      }
      es.close()
      esRef.current = null
    }
  }

  function handleCancel() {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    onClose()
  }

  function handleClose() {
    if (newEndDate) onSuccess(newEndDate)
    onClose()
  }

  const canEstimate = startDate && endDate && startDate <= endDate

  return (
    <div className="cs-backdrop" onClick={e => { if (e.target === e.currentTarget) handleCancel() }}>
      <div className="cs-modal dl-modal">

        {/* Header */}
        <div className="cs-header">
          <span className="cs-title">Download ES Data from Databento</span>
          <button className="cs-close" onClick={handleCancel}>×</button>
        </div>

        {/* Body */}
        <div className="dl-body">
          <div className="dl-current-range">
            Current data: <strong>2016-03-29 → {dataEnd}</strong>
          </div>

          {/* Date inputs — shown until download starts */}
          {(phase === 'idle' || phase === 'estimating' || phase === 'confirm') && (
            <div className="dl-date-section">
              <div className="dl-row">
                <span className="dl-label">From</span>
                <input
                  type="date"
                  className="date-input"
                  value={startDate}
                  disabled={phase !== 'idle'}
                  onChange={e => { setStartDate(e.target.value); resetToIdle() }}
                />
              </div>
              <div className="dl-row">
                <span className="dl-label">To</span>
                <input
                  type="date"
                  className="date-input"
                  value={endDate}
                  disabled={phase !== 'idle'}
                  onChange={e => { setEndDate(e.target.value); resetToIdle() }}
                />
              </div>
            </div>
          )}

          {/* Cost estimate */}
          {phase === 'confirm' && estimate && (
            <div className="dl-estimate">
              Estimated download: <strong>{fmtBytes(estimate.size_bytes)}</strong>
              {' — '}approx. <strong>${estimate.cost_usd.toFixed(4)}</strong>
            </div>
          )}

          {/* Progress log */}
          {(phase === 'downloading' || phase === 'done') && (
            <div className="dl-log">
              {messages.map((m, i) => (
                <div
                  key={i}
                  className={`dl-log-line${i === messages.length - 1 && phase === 'done' ? ' dl-log-done' : ''}`}
                >
                  {m}
                </div>
              ))}
              {phase === 'downloading' && (
                <div className="dl-log-line dl-log-active">Working…</div>
              )}
            </div>
          )}

          {/* Error */}
          {phase === 'error' && error && (
            <div className="dl-error">{error}</div>
          )}
        </div>

        {/* Footer */}
        <div className="dl-footer">
          {phase === 'idle' && (
            <>
              <button className="save-btn dl-btn" onClick={handleEstimate} disabled={!canEstimate}>
                Get estimate
              </button>
              <button className="dl-cancel-btn" onClick={handleCancel}>Cancel</button>
            </>
          )}
          {phase === 'estimating' && (
            <button className="save-btn dl-btn" disabled>Estimating…</button>
          )}
          {phase === 'confirm' && (
            <>
              <button className="save-btn dl-btn" onClick={handleConfirm}>
                Confirm &amp; Download
              </button>
              <button className="dl-cancel-btn" onClick={handleCancel}>Cancel</button>
            </>
          )}
          {phase === 'downloading' && (
            <button className="dl-cancel-btn" onClick={handleCancel}>Cancel</button>
          )}
          {phase === 'done' && (
            <button className="save-btn dl-btn" onClick={handleClose}>Close</button>
          )}
          {phase === 'error' && (
            <>
              <button className="save-btn dl-btn" onClick={resetToIdle}>Try again</button>
              <button className="dl-cancel-btn" onClick={handleCancel}>Close</button>
            </>
          )}
        </div>

      </div>
    </div>
  )
}

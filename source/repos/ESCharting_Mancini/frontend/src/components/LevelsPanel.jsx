import { useState } from 'react'

function Toggle({ checked, onChange }) {
  return (
    <label className="toggle-switch">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      <span className="toggle-slider" />
    </label>
  )
}

export default function LevelsPanel({ selectedTrade, selectedDate }) {
  const [manualOn, setManualOn] = useState(true)
  const [autoOn, setAutoOn] = useState(false)
  const [resistance, setResistance] = useState('')
  const [support, setSupport] = useState('')

  function copyToClipboard(text) {
    if (text.trim()) navigator.clipboard.writeText(text)
  }

  const dateLabel = selectedDate || 'no date selected'

  return (
    <>
      {/* Trade detail */}
      <div className="right-section">
        <div className="right-section-title">Trade Detail</div>
        {selectedTrade
          ? <div style={{ fontSize: 12 }}>Trade #{selectedTrade} selected<br /><em style={{ color: 'var(--text-muted)' }}>Full detail in Step 6</em></div>
          : <div className="trade-detail-placeholder">No trade selected — Planning Mode</div>
        }
      </div>

      {/* Layer toggles */}
      <div className="right-section">
        <div className="right-section-title">Layers</div>
        <div className="layer-row">
          <span className="layer-label">Manual levels</span>
          <Toggle checked={manualOn} onChange={setManualOn} />
        </div>
        <div className="layer-row">
          <span className="layer-label">Auto levels</span>
          <Toggle checked={autoOn} onChange={setAutoOn} />
        </div>
        <button className="gen-levels-btn">Generate auto levels for {dateLabel}</button>
      </div>

      {/* Level inputs */}
      <div className="right-section">
        <div className="right-section-title">Levels</div>

        <div className="level-label-row">
          <span className="level-label-text">Resistances</span>
          <button className="copy-btn" onClick={() => copyToClipboard(resistance)}>Copy</button>
        </div>
        <textarea
          className="level-textarea"
          placeholder="e.g. 5270, 5280 (major), 5295"
          value={resistance}
          onChange={e => setResistance(e.target.value)}
        />

        <div className="level-label-row">
          <span className="level-label-text">Supports</span>
          <button className="copy-btn" onClick={() => copyToClipboard(support)}>Copy</button>
        </div>
        <textarea
          className="level-textarea"
          placeholder="e.g. 5240, 5228 (major), 5210"
          value={support}
          onChange={e => setSupport(e.target.value)}
        />

        <button className="save-btn">Save levels for {dateLabel}</button>
      </div>
    </>
  )
}

import { useState } from 'react'

const PRESETS = ['1m', '5m', '15m', '30m', '1h', '4h', 'D']

export default function TimeframeSelector({ value, onChange }) {
  const [customN, setCustomN] = useState('3')
  const [customUnit, setCustomUnit] = useState('min')

  function applyCustom() {
    const n = parseInt(customN, 10)
    if (!n || n < 1) return
    onChange(`${n}${customUnit}`)
  }

  return (
    <>
      {PRESETS.map(tf => (
        <button
          key={tf}
          className={`tf-btn${value === tf ? ' active' : ''}`}
          onClick={() => onChange(tf)}
        >
          {tf}
        </button>
      ))}
      <div className="toolbar-sep" />
      <div className="tf-custom">
        <input
          type="number"
          min="1"
          value={customN}
          onChange={e => setCustomN(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && applyCustom()}
        />
        <select value={customUnit} onChange={e => setCustomUnit(e.target.value)}>
          <option value="min">min</option>
          <option value="h">hour</option>
        </select>
        <button className="tf-btn" onClick={applyCustom}>Go</button>
      </div>
    </>
  )
}

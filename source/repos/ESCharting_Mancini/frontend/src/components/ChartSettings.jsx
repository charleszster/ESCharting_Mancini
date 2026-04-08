import { useState } from 'react'

const CROSSHAIR_MODES = [
  { value: 1, label: 'Normal' },
  { value: 2, label: 'Magnet' },
  { value: 0, label: 'Hidden' },
]

function Row({ label, children }) {
  return (
    <div className="cs-row">
      <span className="cs-label">{label}</span>
      <span className="cs-control">{children}</span>
    </div>
  )
}

function ColorRow({ label, value, onChange }) {
  return (
    <Row label={label}>
      <input type="color" value={value} onChange={e => onChange(e.target.value)} />
    </Row>
  )
}

function CheckRow({ label, value, onChange }) {
  return (
    <Row label={label}>
      <label className="toggle-switch">
        <input type="checkbox" checked={value} onChange={e => onChange(e.target.checked)} />
        <span className="toggle-slider" />
      </label>
    </Row>
  )
}

function SliderRow({ label, value, onChange, min = 0, max = 1, step = 0.01, fmt }) {
  return (
    <Row label={<>{label} <span className="cs-val">{fmt ? fmt(value) : value}</span></>}>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        style={{ width: 110 }}
      />
    </Row>
  )
}

function SelectRow({ label, value, onChange, options }) {
  return (
    <Row label={label}>
      <select value={value} onChange={e => onChange(Number(e.target.value))}>
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </Row>
  )
}

function Section({ title, children }) {
  return (
    <div className="cs-section">
      <div className="cs-section-title">{title}</div>
      {children}
    </div>
  )
}

export default function ChartSettings({ value, onChange, onClose }) {
  const [tab, setTab] = useState('candles')

  function set(path, val) {
    const keys = path.split('.')
    onChange(prev => {
      const next = { ...prev }
      let obj = next
      for (let i = 0; i < keys.length - 1; i++) {
        obj[keys[i]] = { ...obj[keys[i]] }
        obj = obj[keys[i]]
      }
      obj[keys[keys.length - 1]] = val
      return next
    })
  }

  const tabs = ['candles', 'grid', 'sessions', 'volume', 'scales', 'crosshair']

  return (
    <div className="cs-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="cs-modal">
        <div className="cs-header">
          <span className="cs-title">Chart Settings</span>
          <button className="cs-close" onClick={onClose}>✕</button>
        </div>

        <div className="cs-tabs">
          {tabs.map(t => (
            <button key={t} className={`cs-tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>

        <div className="cs-body">
          {tab === 'candles' && (
            <>
              <Section title="Candle colors">
                <ColorRow label="Up color"   value={value.upColor}   onChange={v => set('upColor', v)} />
                <ColorRow label="Down color" value={value.downColor} onChange={v => set('downColor', v)} />
                <ColorRow label="Up wick"    value={value.upWick}    onChange={v => set('upWick', v)} />
                <ColorRow label="Down wick"  value={value.downWick}  onChange={v => set('downWick', v)} />
                <ColorRow label="Up border"   value={value.upBorder}   onChange={v => set('upBorder', v)} />
                <ColorRow label="Down border" value={value.downBorder} onChange={v => set('downBorder', v)} />
              </Section>
              <Section title="Visibility">
                <CheckRow label="Show wicks"   value={value.wickVisible}   onChange={v => set('wickVisible', v)} />
                <CheckRow label="Show borders" value={value.borderVisible} onChange={v => set('borderVisible', v)} />
              </Section>
              <Section title="Background">
                <ColorRow label="Background color" value={value.backgroundColor} onChange={v => set('backgroundColor', v)} />
              </Section>
            </>
          )}

          {tab === 'grid' && (
            <>
              <Section title="Grid lines">
                <CheckRow label="Horizontal lines" value={value.gridHorzVisible} onChange={v => set('gridHorzVisible', v)} />
                <ColorRow label="Horizontal color" value={value.gridHorzColor}   onChange={v => set('gridHorzColor', v)} />
                <CheckRow label="Vertical lines"   value={value.gridVertVisible} onChange={v => set('gridVertVisible', v)} />
                <ColorRow label="Vertical color"   value={value.gridVertColor}   onChange={v => set('gridVertColor', v)} />
              </Section>
            </>
          )}

          {tab === 'sessions' && (
            <>
              <Section title="Session shading">
                <CheckRow label="Enabled" value={value.session.enabled} onChange={v => set('session.enabled', v)} />
                <Row label="Mode">
                  <select
                    value={value.session.mode}
                    onChange={e => set('session.mode', e.target.value)}
                  >
                    <option value="eth">ETH (shade off-hours)</option>
                    <option value="rth">RTH (shade trading hours)</option>
                  </select>
                </Row>
                <ColorRow label="Color" value={value.session.color} onChange={v => set('session.color', v)} />
                <SliderRow
                  label="Opacity"
                  value={value.session.opacity}
                  onChange={v => set('session.opacity', v)}
                  max={0.5} step={0.01}
                  fmt={v => `${Math.round(v * 100)}%`}
                />
              </Section>
            </>
          )}

          {tab === 'volume' && (
            <>
              <Section title="Volume histogram">
                <CheckRow label="Show volume" value={value.showVolume} onChange={v => set('showVolume', v)} />
                <ColorRow label="Up bar color"   value={value.volUpColor}   onChange={v => set('volUpColor', v)} />
                <ColorRow label="Down bar color" value={value.volDownColor} onChange={v => set('volDownColor', v)} />
                <SliderRow
                  label="Height"
                  value={value.volHeightPct}
                  onChange={v => set('volHeightPct', v)}
                  min={0.05} max={0.4} step={0.01}
                  fmt={v => `${Math.round(v * 100)}%`}
                />
              </Section>
            </>
          )}

          {tab === 'scales' && (
            <>
              <Section title="Price scale">
                <CheckRow label="Log scale"    value={value.logScale}    onChange={v => set('logScale', v)} />
                <CheckRow label="Invert scale" value={value.invertScale} onChange={v => set('invertScale', v)} />
                <SliderRow
                  label="Top margin"
                  value={value.scaleMarginTop}
                  onChange={v => set('scaleMarginTop', v)}
                  max={0.4} step={0.01}
                  fmt={v => `${Math.round(v * 100)}%`}
                />
                <SliderRow
                  label="Bottom margin"
                  value={value.scaleMarginBottom}
                  onChange={v => set('scaleMarginBottom', v)}
                  max={0.4} step={0.01}
                  fmt={v => `${Math.round(v * 100)}%`}
                />
              </Section>
              <Section title="Text">
                <ColorRow label="Axis text color" value={value.textColor} onChange={v => set('textColor', v)} />
              </Section>
            </>
          )}

          {tab === 'crosshair' && (
            <>
              <Section title="Crosshair">
                <SelectRow
                  label="Mode"
                  value={value.crosshairMode}
                  onChange={v => set('crosshairMode', v)}
                  options={CROSSHAIR_MODES}
                />
                <ColorRow label="Line color"  value={value.crosshairColor} onChange={v => set('crosshairColor', v)} />
                <SliderRow
                  label="Line width"
                  value={value.crosshairWidth}
                  onChange={v => set('crosshairWidth', v)}
                  min={1} max={4} step={1}
                  fmt={v => `${v}px`}
                />
              </Section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export default function TradeList({ trades, loading, error, selectedId, onSelect }) {
  return (
    <>
      <div className="left-panel-header">
        Trades{!loading && !error ? ` (${trades.length})` : ''}
      </div>
      <div className="trade-list">
        {loading && (
          <div style={{ padding: '12px', fontSize: 12, color: 'var(--text-muted)' }}>Loading…</div>
        )}
        {error && (
          <div style={{ padding: '12px', fontSize: 12, color: 'var(--red)' }}>Error: {error}</div>
        )}
        {trades.map(t => {
          const entryTime    = t.entry_time ? t.entry_time.slice(0, 5) : '—'
          const lastExit     = t.exits.length
            ? t.exits.reduce((a, b) => (b.time > a.time ? b : a))
            : null
          const lastExitTime = lastExit ? lastExit.time.slice(0, 5) : '—'
          const qty          = Math.abs(t.entry_qty)

          return (
            <div
              key={t.id}
              className={`trade-row${selectedId === t.id ? ' selected' : ''}`}
              onClick={() => onSelect(t)}
            >
              <div className="trade-row-main">
                <span className="trade-date">{t.entry_date}</span>
                <span className={`trade-dir ${t.direction}`}>
                  {t.direction === 'long' ? 'L' : 'S'}
                </span>
                <span className={`trade-pnl ${t.net_pnl >= 0 ? 'pos' : 'neg'}`}>
                  {t.net_pnl >= 0 ? '+' : ''}
                  {t.net_pnl.toLocaleString('en-US', {
                    style: 'currency', currency: 'USD', minimumFractionDigits: 0,
                  })}
                </span>
              </div>
              <div className="trade-row-sub">
                <span>{entryTime} → {lastExitTime}</span>
                <span>×{qty}</span>
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}

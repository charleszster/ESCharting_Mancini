// Hardcoded trades — will be replaced with real Excel data in Step 5
const SAMPLE_TRADES = [
  { id: 1, date: '03/20/24', dir: 'Long',  pnl:  812.50 },
  { id: 2, date: '03/19/24', dir: 'Short', pnl: -375.00 },
  { id: 3, date: '03/18/24', dir: 'Long',  pnl: 1250.00 },
  { id: 4, date: '03/15/24', dir: 'Long',  pnl:  625.00 },
  { id: 5, date: '03/14/24', dir: 'Short', pnl: -187.50 },
  { id: 6, date: '03/13/24', dir: 'Long',  pnl: 2187.50 },
  { id: 7, date: '03/12/24', dir: 'Short', pnl:  437.50 },
  { id: 8, date: '03/11/24', dir: 'Long',  pnl: -250.00 },
  { id: 9, date: '03/08/24', dir: 'Long',  pnl:  937.50 },
  { id: 10, date: '03/07/24', dir: 'Short', pnl: 1562.50 },
]

export default function TradeList({ selectedId, onSelect }) {
  return (
    <>
      <div className="left-panel-header">Trades</div>
      <div className="trade-list">
        {SAMPLE_TRADES.map(t => (
          <div
            key={t.id}
            className={`trade-row${selectedId === t.id ? ' selected' : ''}`}
            onClick={() => onSelect(t.id)}
          >
            <span className="trade-date">{t.date}</span>
            <span className={`trade-dir ${t.dir === 'Long' ? 'long' : 'short'}`}>
              {t.dir === 'Long' ? 'L' : 'S'}
            </span>
            <span className={`trade-pnl ${t.pnl >= 0 ? 'pos' : 'neg'}`}>
              {t.pnl >= 0 ? '+' : ''}{t.pnl.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })}
            </span>
          </div>
        ))}
      </div>
    </>
  )
}

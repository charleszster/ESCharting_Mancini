/**
 * Lightweight Charts v5 series primitive.
 * mode: 'eth' → shade off-hours (pre/post-market + weekends)  [default]
 * mode: 'rth' → shade regular trading hours only
 * RTH = 09:30–16:00 ET, handles EDT/EST automatically.
 */

function nthSundayOfMonth(year, month, n) {
  const d = new Date(Date.UTC(year, month, 1))
  const daysToSunday = (7 - d.getUTCDay()) % 7
  return new Date(Date.UTC(year, month, 1 + daysToSunday + (n - 1) * 7))
}

function isEDT(utcDate) {
  const year = utcDate.getUTCFullYear()
  const dstStart = nthSundayOfMonth(year, 2, 2)   // 2nd Sunday March
  const dstEnd   = nthSundayOfMonth(year, 10, 1)  // 1st Sunday November
  return utcDate >= dstStart && utcDate < dstEnd
}

/** Return RTH start/end as Unix seconds for the given UTC day. */
function rthBounds(dayMidnightUtc) {
  const edt = isEDT(dayMidnightUtc)
  const base = dayMidnightUtc.getTime() / 1000
  return {
    start: base + (edt ? 13.5 : 14.5) * 3600,   // 09:30 ET in UTC
    end:   base + (edt ? 20.0 : 21.0) * 3600,   // 16:00 ET in UTC
  }
}

class SessionHighlightRenderer {
  constructor(chart, options) {
    this._chart   = chart
    this._options = options
  }

  draw(target) {
    const { color, mode } = this._options
    target.useBitmapCoordinateSpace(({ context, bitmapSize, horizontalPixelRatio }) => {
      const timeScale    = this._chart.timeScale()
      const visibleRange = timeScale.getVisibleRange()
      if (!visibleRange) return

      context.fillStyle = color

      let day = new Date(visibleRange.from * 1000)
      day.setUTCHours(0, 0, 0, 0)
      const toMs = visibleRange.to * 1000

      const fillBand = (t1, t2) => {
        const x1 = timeScale.timeToCoordinate(t1)
        const x2 = timeScale.timeToCoordinate(t2)
        if (x1 === null || x2 === null) return
        const bx1 = Math.round(x1 * horizontalPixelRatio)
        const bx2 = Math.round(x2 * horizontalPixelRatio)
        if (bx2 > bx1) context.fillRect(bx1, 0, bx2 - bx1, bitmapSize.height)
      }

      while (day.getTime() <= toMs) {
        const dayStart = day.getTime() / 1000
        const dayEnd   = dayStart + 86400
        const dow      = day.getUTCDay()
        const weekend  = dow === 0 || dow === 6
        const { start: rthStart, end: rthEnd } = rthBounds(day)

        if (mode === 'rth') {
          if (!weekend) fillBand(rthStart, rthEnd)
        } else {
          // ETH mode: shade everything outside RTH
          if (weekend) {
            fillBand(dayStart, dayEnd)
          } else {
            fillBand(dayStart, rthStart)   // pre-market
            fillBand(rthEnd,   dayEnd)     // post-market
          }
        }

        day.setUTCDate(day.getUTCDate() + 1)
      }
    })
  }
}

class SessionHighlightView {
  constructor(chart, options) {
    this._chart   = chart
    this._options = options
  }
  zOrder()    { return 'bottom' }
  renderer()  { return new SessionHighlightRenderer(this._chart, this._options) }
}

export class SessionHighlight {
  constructor(options = {}) {
    this._options = { color: 'rgba(0,0,0,0.04)', mode: 'eth', ...options }
    this._chart          = null
    this._requestUpdate  = null
  }

  updateOptions(options) {
    this._options = { ...this._options, ...options }
    this._requestUpdate?.()
  }

  attached({ chart, requestUpdate }) {
    this._chart         = chart
    this._requestUpdate = requestUpdate
  }

  detached() {
    this._chart         = null
    this._requestUpdate = null
  }

  updateAllViews() {}

  paneViews() {
    if (!this._chart) return []
    return [new SessionHighlightView(this._chart, this._options)]
  }
}

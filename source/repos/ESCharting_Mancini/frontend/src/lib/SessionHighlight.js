/**
 * Lightweight Charts v5 series primitive.
 * mode: 'eth' → shade off-hours (pre/post-market + weekends)  [default]
 * mode: 'rth' → shade regular trading hours only
 * RTH = 09:30–16:00 ET, handles EDT/EST automatically.
 *
 * ETH mode iterates gaps *between* RTH windows rather than shading UTC calendar
 * days.  The original UTC-day approach silently failed when timeToCoordinate()
 * returned null for timestamps inside trading gaps (e.g. Saturday), causing the
 * Sunday 6–8 PM ET window to go unshaded.
 */

function nthSundayOfMonth(year, month, n) {
  const d = new Date(Date.UTC(year, month, 1))
  const daysToSunday = (7 - d.getUTCDay()) % 7
  return new Date(Date.UTC(year, month, 1 + daysToSunday + (n - 1) * 7))
}

function isEDT(utcDate) {
  const year     = utcDate.getUTCFullYear()
  const dstStart = nthSundayOfMonth(year, 2,  2)   // 2nd Sunday of March
  const dstEnd   = nthSundayOfMonth(year, 10, 1)   // 1st Sunday of November
  return utcDate >= dstStart && utcDate < dstEnd
}

/** RTH start/end as Unix seconds for the UTC-midnight date given. */
function rthBounds(dayMidnightUtc) {
  const edt  = isEDT(dayMidnightUtc)
  const base = dayMidnightUtc.getTime() / 1000
  return {
    start: base + (edt ? 13.5 : 14.5) * 3600,  // 09:30 ET
    end:   base + (edt ? 20.0 : 21.0) * 3600,  // 16:00 ET
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

      const fillBand = (t1, t2) => {
        if (t2 <= t1) return
        const x1  = timeScale.timeToCoordinate(t1)
        const x2  = timeScale.timeToCoordinate(t2)
        // Clamp to chart edges when the timestamp has no bar (gap / outside data).
        // Use <= / >= so that prevEnd === visibleRange.from still maps to x=0.
        const bx1 = x1 !== null
          ? Math.round(x1 * horizontalPixelRatio)
          : (t1 <= visibleRange.from ? 0 : null)
        const bx2 = x2 !== null
          ? Math.round(x2 * horizontalPixelRatio)
          : (t2 >= visibleRange.to ? bitmapSize.width : null)
        if (bx1 === null || bx2 === null || bx2 <= bx1) return
        context.fillRect(bx1, 0, bx2 - bx1, bitmapSize.height)
      }

      // Snap loop start to UTC midnight of the first visible day.
      let day = new Date(visibleRange.from * 1000)
      day.setUTCHours(0, 0, 0, 0)
      const toMs = visibleRange.to * 1000

      if (mode === 'rth') {
        // RTH mode: fill only the 09:30–16:00 ET bands on weekdays.
        while (day.getTime() <= toMs) {
          const dow = day.getUTCDay()
          if (dow >= 1 && dow <= 5) {
            const { start: rthStart, end: rthEnd } = rthBounds(day)
            fillBand(rthStart, rthEnd)
          }
          day.setUTCDate(day.getUTCDate() + 1)
        }
      } else {
        // ETH mode: shade the *gaps* between RTH windows.
        //
        // By anchoring bands to RTH open/close times (real bar boundaries)
        // instead of UTC midnight, timeToCoordinate() always has valid data to
        // work with — even across weekends when the UTC-day approach produced
        // null coordinates for Saturday/Sunday gap timestamps.
        //
        // Example: the band "Friday 16:00 → Monday 09:30" covers the entire
        // weekend as one contiguous block with no null-coordinate risk.
        let prevEnd = visibleRange.from

        while (day.getTime() <= toMs) {
          const dow = day.getUTCDay()
          if (dow >= 1 && dow <= 5) {    // Mon–Fri in UTC
            const { start: rthStart, end: rthEnd } = rthBounds(day)
            // Shade from end of last RTH (or visible start) to this RTH open.
            if (rthStart > prevEnd) {
              fillBand(prevEnd, rthStart)
            }
            prevEnd = Math.max(prevEnd, rthEnd)
          }
          day.setUTCDate(day.getUTCDate() + 1)
        }

        // Shade post-market tail: last RTH close to end of visible range.
        if (prevEnd < visibleRange.to) {
          fillBand(prevEnd, visibleRange.to)
        }
      }
    })
  }
}

class SessionHighlightView {
  constructor(chart, options) {
    this._chart   = chart
    this._options = options
  }
  zOrder()   { return 'bottom' }
  renderer() { return new SessionHighlightRenderer(this._chart, this._options) }
}

export class SessionHighlight {
  constructor(options = {}) {
    this._options        = { color: 'rgba(0,0,0,0.04)', mode: 'eth', ...options }
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

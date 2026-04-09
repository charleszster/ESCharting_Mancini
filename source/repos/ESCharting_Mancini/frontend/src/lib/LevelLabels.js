/**
 * LWC v5 series primitive.
 * Draws support/resistance labels + translucent zone fills at the right edge
 * of the chart pane, with the horizontal price line running through the label.
 */

class LevelLabelsRenderer {
  constructor(series, levels, options) {
    this._series  = series
    this._levels  = levels  // [{price, price_lo, price_hi, color, text}]
    this._options = options
  }

  draw(target) {
    if (!this._levels.length || !this._series) return

    target.useBitmapCoordinateSpace(({
      context, bitmapSize, verticalPixelRatio, horizontalPixelRatio,
    }) => {
      const { fontSize, showBox, showZones, zoneOpacity } = this._options
      const PAD_X     = 4
      const PAD_Y     = 2
      const RIGHT_GAP = 4

      // ── Pass 1: zone fills (range levels only) ───────────────────────────
      if (showZones) {
        const prevAlpha = context.globalAlpha
        context.globalAlpha = zoneOpacity
        for (const lvl of this._levels) {
          if (lvl.price_lo === lvl.price_hi) continue  // point level — no zone
          const y_hi = this._series.priceToCoordinate(lvl.price_hi)
          const y_lo = this._series.priceToCoordinate(lvl.price_lo)
          if (y_hi === null || y_lo === null) continue
          const by_hi = Math.round(y_hi * verticalPixelRatio)
          const by_lo = Math.round(y_lo * verticalPixelRatio)
          context.fillStyle = lvl.color
          context.fillRect(0, by_hi, bitmapSize.width, by_lo - by_hi)
        }
        context.globalAlpha = prevAlpha
      }

      // ── Pass 2: labels ───────────────────────────────────────────────────
      context.font         = `${Math.round(fontSize * verticalPixelRatio)}px system-ui, -apple-system, sans-serif`
      context.textBaseline = 'middle'

      for (const lvl of this._levels) {
        const y = this._series.priceToCoordinate(lvl.price)
        if (y === null) continue

        const by        = Math.round(y * verticalPixelRatio)
        const textWidth = context.measureText(lvl.text).width
        const rectW     = textWidth + PAD_X * 2 * horizontalPixelRatio
        const rectH     = (fontSize + PAD_Y * 2) * verticalPixelRatio
        const rectX     = bitmapSize.width - rectW - RIGHT_GAP * horizontalPixelRatio
        const textX     = rectX + PAD_X * horizontalPixelRatio

        if (showBox) {
          context.fillStyle = lvl.color
          context.fillRect(rectX, by - rectH / 2, rectW, rectH)
          context.fillStyle = '#ffffff'
          context.fillText(lvl.text, textX, by)
        } else {
          context.fillStyle = lvl.color
          context.fillText(lvl.text, textX, by)
        }
      }
    })
  }
}

class LevelLabelsView {
  constructor(series, levels, options) {
    this._renderer = new LevelLabelsRenderer(series, levels, options)
  }
  zOrder()   { return 'top' }
  renderer() { return this._renderer }
}

export class LevelLabelsPrimitive {
  constructor() {
    this._series  = null
    this._levels  = []
    this._options = { fontSize: 9, showBox: false, showZones: true, zoneOpacity: 0.10 }
    this._update  = null
  }

  attached({ series, requestUpdate }) {
    this._series = series
    this._update = requestUpdate
  }

  detached() {
    this._series = null
    this._update = null
  }

  updateAllViews() {}

  paneViews() {
    if (!this._series) return []
    return [new LevelLabelsView(this._series, this._levels, { ...this._options })]
  }

  setLevels(levels) {
    this._levels = levels
    this._update?.()
  }

  updateOptions(opts) {
    this._options = { ...this._options, ...opts }
    this._update?.()
  }
}

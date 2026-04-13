/**
 * LWC v5 series primitive that draws trade entry/exit arrows
 * at exact price coordinates using series.priceToCoordinate().
 *
 * Each marker: { time, price, direction: 'up'|'down', color, label }
 */

class TradeMarkersRenderer {
  constructor(chart, series, markers, options) {
    this._chart   = chart
    this._series  = series
    this._markers = markers
    this._options = options
  }

  draw(target) {
    target.useBitmapCoordinateSpace(({ context: ctx, horizontalPixelRatio: hpr, verticalPixelRatio: vpr }) => {
      const timeScale = this._chart.timeScale()

      for (const m of this._markers) {
        const x = timeScale.timeToCoordinate(m.time)
        const y = this._series.priceToCoordinate(m.price)
        if (x === null || y === null) continue

        const bx = Math.round(x * hpr)
        const by = Math.round(y * vpr)
        const h  = Math.round(10 * vpr)   // arrow height
        const w  = Math.round(6  * hpr)   // arrow half-width

        // Build arrow path (tip at exact price coordinate)
        const drawArrowPath = () => {
          ctx.beginPath()
          if (m.direction === 'up') {
            ctx.moveTo(bx,     by)
            ctx.lineTo(bx - w, by + h)
            ctx.lineTo(bx + w, by + h)
          } else {
            ctx.moveTo(bx,     by)
            ctx.lineTo(bx - w, by - h)
            ctx.lineTo(bx + w, by - h)
          }
          ctx.closePath()
        }

        if (m.hollow) {
          // Hollow style: white fill + colored border (for study trade markers)
          ctx.save()
          ctx.fillStyle = 'rgba(255,255,255,0.92)'
          drawArrowPath()
          ctx.fill()
          ctx.strokeStyle = m.color
          ctx.lineWidth   = Math.round(2 * Math.min(hpr, vpr))
          ctx.lineJoin    = 'round'
          drawArrowPath()
          ctx.stroke()
          ctx.restore()
        } else {
          // Solid style: white halo then colored fill (for personal trade markers)
          ctx.save()
          ctx.strokeStyle = 'rgba(255,255,255,0.9)'
          ctx.lineWidth   = Math.round(3 * Math.min(hpr, vpr))
          ctx.lineJoin    = 'round'
          drawArrowPath()
          ctx.stroke()

          ctx.fillStyle = m.color
          drawArrowPath()
          ctx.fill()
          ctx.restore()
        }

        // Price label with background box
        const fontSize  = Math.round((this._options.fontSize ?? 11) * vpr)
        const font      = `600 ${fontSize}px -apple-system,BlinkMacSystemFont,"Trebuchet MS",sans-serif`
        ctx.font        = font
        ctx.textBaseline = 'middle'
        const labelText = String(m.label ?? m.price)
        const tw        = ctx.measureText(labelText).width
        const labelX    = bx + w + Math.round(5 * hpr)
        const labelY    = m.direction === 'up' ? by + h : by - h
        const padX      = Math.round(3 * hpr)
        const padY      = Math.round(2 * vpr)

        // Background rect
        ctx.fillStyle = 'rgba(255,255,255,0.88)'
        ctx.fillRect(labelX - padX, labelY - fontSize / 2 - padY, tw + padX * 2, fontSize + padY * 2)

        // Label text
        ctx.fillStyle = m.color
        ctx.fillText(labelText, labelX, labelY)
      }
    })
  }
}

class TradeMarkersView {
  constructor(chart, series, markers, options) {
    this._chart   = chart
    this._series  = series
    this._markers = markers
    this._options = options
  }
  zOrder()   { return 'top' }
  renderer() { return new TradeMarkersRenderer(this._chart, this._series, this._markers, this._options) }
}

export class TradeMarkersPrimitive {
  constructor() {
    this._chart         = null
    this._series        = null
    this._requestUpdate = null
    this._markers       = []
    this._options       = { fontSize: 11 }
  }

  setMarkers(markers) {
    this._markers = markers
    this._requestUpdate?.()
  }

  clearMarkers() {
    this.setMarkers([])
  }

  updateOptions(opts) {
    this._options = { ...this._options, ...opts }
    this._requestUpdate?.()
  }

  attached({ chart, series, requestUpdate }) {
    this._chart         = chart
    // LWC v5 may or may not pass series in attached; capture via constructor if needed
    if (series) this._series = series
    this._requestUpdate = requestUpdate
  }

  // Called by Chart.jsx after attaching, to supply the series reference
  setSeries(series) {
    this._series = series
  }

  detached() {
    this._chart         = null
    this._requestUpdate = null
  }

  updateAllViews() {}

  paneViews() {
    if (!this._chart || !this._series) return []
    return [new TradeMarkersView(this._chart, this._series, this._markers, this._options)]
  }
}

import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from 'react'
import { createChart, CandlestickSeries, HistogramSeries } from 'lightweight-charts'
import { SessionHighlight } from '../lib/SessionHighlight'
import { TradeMarkersPrimitive } from '../lib/TradeMarkers'

const API_BASE = 'http://localhost:8000'
const ET_ZONE  = 'America/New_York'

// ── ET timezone formatters for Lightweight Charts ────────────────────────────

function fmtET(unixSecs, opts) {
  return new Intl.DateTimeFormat('en-US', { timeZone: ET_ZONE, ...opts })
    .format(new Date(unixSecs * 1000))
}

// Called by LWC for axis tick labels.
// tickMarkType: 0=Year, 1=Month, 2=DayOfMonth, 3=Time, 4=TimeWithSeconds
function etTickMarkFormatter(time, tickMarkType) {
  if (tickMarkType === 0) return fmtET(time, { year: 'numeric' })
  if (tickMarkType === 1) return fmtET(time, { month: 'short', year: 'numeric' })
  if (tickMarkType === 2) return fmtET(time, { month: 'short', day: 'numeric' })
  // Time ticks — show HH:MM in 24h
  return fmtET(time, { hour: '2-digit', minute: '2-digit', hour12: false })
}

// Called by LWC for the crosshair time label
function etTimeFormatter(time) {
  return fmtET(time, {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }) + ' ET'
}

// Format a UTC unix timestamp as a short ET time string for the OHLCV tooltip
function fmtTooltipTime(unixSecs) {
  return fmtET(unixSecs, {
    weekday: 'short', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }) + ' ET'
}

function hexToRgba(hex, opacity) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${opacity})`
}

// ── Trade markers ────────────────────────────────────────────────────────────

/** Find the candle bar whose open time is <= targetTs and is the closest. */
function findNearestBarTime(candles, targetTs) {
  let best = candles[0]?.time ?? null
  for (const c of candles) {
    if (c.time <= targetTs) best = c.time
    else break
  }
  return best
}

function buildMarkers(trade, candles) {
  if (!candles.length) return []
  const isLong = trade.direction === 'long'

  const ENTRY_COLOR = isLong ? '#26a69a' : '#ef5350'
  const EXIT_COLOR  = isLong ? '#ef5350' : '#26a69a'

  const markers = []

  if (trade.entry_ts != null) {
    const t = findNearestBarTime(candles, trade.entry_ts)
    if (t !== null) markers.push({
      time:     t,
      position: isLong ? 'belowBar' : 'aboveBar',
      color:    ENTRY_COLOR,
      shape:    isLong ? 'arrowUp' : 'arrowDown',
      text:     String(trade.entry_price),
      size:     2,
    })
  }

  for (const exit of trade.exits) {
    if (exit.ts != null) {
      const t = findNearestBarTime(candles, exit.ts)
      if (t !== null) markers.push({
        time:     t,
        position: isLong ? 'aboveBar' : 'belowBar',
        color:    EXIT_COLOR,
        shape:    isLong ? 'arrowDown' : 'arrowUp',
        text:     String(exit.price),
        size:     2,
      })
    }
  }

  // LWC requires ascending time order; deduplicate same-time same-shape markers
  markers.sort((a, b) => a.time - b.time)
  return markers
}

function applyMarkers(primitive, series, trade) {
  if (!primitive) return
  if (!trade) { primitive.clearMarkers(); return }
  const candles = series?.data?.() ?? []
  const raw = buildMarkers(trade, candles)   // [{time, price, ...}] from the old builder

  // Convert to TradeMarkersPrimitive format
  const isLong = trade.direction === 'long'
  const markers = raw.map(m => ({
    time:      m.time,
    price:     parseFloat(m.text),           // text held the price string
    direction: m.shape === 'arrowUp' ? 'up' : 'down',
    color:     m.color,
    label:     m.text,
  }))
  primitive.setMarkers(markers)
}

function toBackendTf(tf) {
  if (tf.toUpperCase() === 'D') return 'D'
  const h = tf.match(/^(\d+)h$/i)
  if (h) return String(parseInt(h[1], 10) * 60)
  const m = tf.match(/^(\d+)m(?:in)?$/i)
  if (m) return m[1]
  return tf
}

const Chart = forwardRef(function Chart({ timeframe = '5m', settings, dateRange, focusDate, tradeData }, ref) {
  const containerRef   = useRef(null)
  const chartRef         = useRef(null)
  const candleRef        = useRef(null)   // candlestick series
  const volRef           = useRef(null)   // volume histogram series
  const markersRef       = useRef(null)   // TradeMarkersPrimitive
  const snapLineRef      = useRef(null)   // price line for OHLC snap mode
  const crosshairModeRef = useRef(settings.crosshairMode)
  const shadingRef       = useRef(null)   // SessionHighlight primitive
  const shadingOnRef     = useRef(false)

  const [chartReady, setChartReady] = useState(false)
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [hoverBar, setHoverBar]     = useState(null)

  const tf = toBackendTf(timeframe)

  // ── Expose reset to parent ───────────────────────────────────────────────
  useImperativeHandle(ref, () => ({
    resetView() {
      if (!chartRef.current) return
      chartRef.current.timeScale().fitContent()
      chartRef.current.priceScale('right').applyOptions({ autoScale: true })
    }
  }))

  // ── Create chart (runs once) ─────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return
    const s = settings  // capture initial settings for chart creation

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: s.backgroundColor },
        textColor: s.textColor,
        fontFamily: "system-ui, 'Segoe UI', Roboto, sans-serif",
        fontSize: 11,
      },
      localization: {
        timeFormatter: etTimeFormatter,
      },
      grid: {
        vertLines: { color: s.gridVertColor, visible: s.gridVertVisible },
        horzLines: { color: s.gridHorzColor, visible: s.gridHorzVisible },
      },
      crosshair: {
        mode: s.crosshairMode,
        vertLine: { color: s.crosshairColor, width: s.crosshairWidth },
        horzLine: { color: s.crosshairColor, width: s.crosshairWidth },
      },
      rightPriceScale: {
        borderColor: '#e0e0e0',
        scaleMargins: { top: s.scaleMarginTop, bottom: s.scaleMarginBottom },
        mode: s.logScale ? 1 : 0,
        invertScale: s.invertScale,
      },
      timeScale: {
        borderColor: '#e0e0e0',
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: etTickMarkFormatter,
      },
      width:  containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    })

    const candle = chart.addSeries(CandlestickSeries, {
      upColor:         s.upColor,
      downColor:       s.downColor,
      borderUpColor:   s.upBorder,
      borderDownColor: s.downBorder,
      wickUpColor:     s.upWick,
      wickDownColor:   s.downWick,
      wickVisible:     s.wickVisible,
      borderVisible:   s.borderVisible,
    })

    const tradeMarkers = new TradeMarkersPrimitive()
    tradeMarkers.setSeries(candle)
    candle.attachPrimitive(tradeMarkers)

    chartRef.current   = chart
    candleRef.current  = candle
    markersRef.current = tradeMarkers
    shadingRef.current = new SessionHighlight()

    chart.subscribeCrosshairMove(param => {
      const bar = param.seriesData?.get(candle) ?? null
      setHoverBar(bar)

      // OHLC snap: update price line to nearest of O/H/L/C
      if (crosshairModeRef.current === 3 && snapLineRef.current) {
        if (bar && param.point) {
          const cursorPrice = candle.coordinateToPrice(param.point.y)
          if (cursorPrice !== null) {
            const prices  = [bar.open, bar.high, bar.low, bar.close]
            const nearest = prices.reduce((a, b) =>
              Math.abs(b - cursorPrice) < Math.abs(a - cursorPrice) ? b : a
            )
            snapLineRef.current.applyOptions({ price: nearest, axisLabelVisible: true })
          }
        } else {
          snapLineRef.current.applyOptions({ price: -1e9, axisLabelVisible: false })
        }
      }
    })

    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      chart.resize(width, height)
    })
    ro.observe(containerRef.current)

    setChartReady(true)

    return () => {
      setChartReady(false)
      ro.disconnect()
      chart.remove()        // removes all attached primitives automatically
      chartRef.current     = null
      candleRef.current    = null
      markersRef.current   = null
      snapLineRef.current  = null
      volRef.current       = null
      shadingRef.current   = null
      shadingOnRef.current = false
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Apply appearance settings ────────────────────────────────────────────
  useEffect(() => {
    if (!chartReady || !chartRef.current || !candleRef.current) return
    const chart  = chartRef.current
    const candle = candleRef.current
    const s      = settings

    // Keep ref current so the subscribe handler always reads the latest mode
    crosshairModeRef.current = s.crosshairMode

    // Mode 3 = custom OHLC snap: use LWC Normal + hide native horzLine + use price line
    const lwcMode    = s.crosshairMode === 3 ? 0 : s.crosshairMode
    const horzActive = s.crosshairMode !== 2 && s.crosshairMode !== 3

    // Create or remove the OHLC snap price line
    if (s.crosshairMode === 3 && !snapLineRef.current) {
      snapLineRef.current = candle.createPriceLine({
        price: -1e9, color: s.crosshairColor,
        lineWidth: s.crosshairWidth, lineStyle: 0, axisLabelVisible: false,
      })
    } else if (s.crosshairMode !== 3 && snapLineRef.current) {
      candle.removePriceLine(snapLineRef.current)
      snapLineRef.current = null
    }
    if (s.crosshairMode === 3 && snapLineRef.current) {
      snapLineRef.current.applyOptions({ color: s.crosshairColor, lineWidth: s.crosshairWidth })
    }

    chart.applyOptions({
      layout: { background: { color: s.backgroundColor }, textColor: s.textColor },
      grid: {
        vertLines: { color: s.gridVertColor, visible: s.gridVertVisible },
        horzLines: { color: s.gridHorzColor, visible: s.gridHorzVisible },
      },
      crosshair: {
        mode: lwcMode,
        vertLine: { color: s.crosshairColor, width: s.crosshairWidth, visible: s.crosshairMode !== 2 },
        horzLine: { color: s.crosshairColor, width: s.crosshairWidth, visible: horzActive, labelVisible: horzActive },
      },
      rightPriceScale: {
        scaleMargins: { top: s.scaleMarginTop, bottom: s.showVolume ? s.volHeightPct + 0.02 : s.scaleMarginBottom },
        mode: s.logScale ? 1 : 0,
        invertScale: s.invertScale,
      },
    })

    candle.applyOptions({
      upColor:         s.upColor,
      downColor:       s.downColor,
      borderUpColor:   s.upBorder,
      borderDownColor: s.downBorder,
      wickUpColor:     s.upWick,
      wickDownColor:   s.downWick,
      wickVisible:     s.wickVisible,
      borderVisible:   s.borderVisible,
    })
  }, [chartReady, settings])

  // ── Session shading ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!chartReady || !candleRef.current || !shadingRef.current) return
    const primitive = shadingRef.current
    const series    = candleRef.current
    const { enabled, color, opacity, mode } = settings.session

    if (enabled) {
      primitive.updateOptions({ color: hexToRgba(color, opacity), mode })
      if (!shadingOnRef.current) {
        series.attachPrimitive(primitive)
        shadingOnRef.current = true
      }
    } else {
      if (shadingOnRef.current) {
        series.detachPrimitive(primitive)
        shadingOnRef.current = false
      }
    }
  }, [chartReady, settings.session])

  // ── Volume histogram ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!chartReady || !chartRef.current || !candleRef.current) return
    const chart  = chartRef.current
    const candle = candleRef.current
    const s      = settings

    if (s.showVolume && !volRef.current) {
      const vol = chart.addSeries(HistogramSeries, {
        priceFormat:    { type: 'volume' },
        priceScaleId:   'vol',
        color:          s.volUpColor,
        lastValueVisible: false,
        priceLineVisible: false,
      })
      chart.priceScale('vol').applyOptions({
        scaleMargins: { top: 1 - s.volHeightPct, bottom: 0 },
      })
      volRef.current = vol

      // Re-colour volume bars from existing candle data
      const candleData = candle.data?.() ?? []
      if (candleData.length) {
        vol.setData(candleData.map(c => ({
          time:  c.time,
          value: c.volume ?? 0,
          color: c.close >= c.open ? s.volUpColor : s.volDownColor,
        })))
      }
    } else if (!s.showVolume && volRef.current) {
      chart.removeSeries(volRef.current)
      volRef.current = null
    }

    // Update vol series colors when settings change
    if (s.showVolume && volRef.current) {
      chart.priceScale('vol').applyOptions({
        scaleMargins: { top: 1 - s.volHeightPct, bottom: 0 },
      })
    }
  }, [chartReady, settings.showVolume, settings.volUpColor, settings.volDownColor, settings.volHeightPct])

  // ── Marker appearance options ────────────────────────────────────────────
  useEffect(() => {
    if (!chartReady || !markersRef.current) return
    markersRef.current.updateOptions({ fontSize: settings.markerFontSize })
  }, [chartReady, settings.markerFontSize])

  // ── Trade markers (handles deselect / trade switch without re-fetch) ─────
  useEffect(() => {
    if (!chartReady) return
    applyMarkers(markersRef.current, candleRef.current, tradeData)
  }, [chartReady, tradeData])

  // ── Fetch candles ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!chartReady || !candleRef.current) return

    const controller = new AbortController()
    setLoading(true)
    setError(null)

    fetch(
      `${API_BASE}/candles?timeframe=${tf}&start=${dateRange.start}&end=${dateRange.end}`,
      { signal: controller.signal }
    )
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => {
        const candles = data.candles
        candleRef.current.setData(candles)

        if (focusDate) {
          // Zoom to show 7 days before → 3 days after the trade date
          const tradeTs = new Date(focusDate + 'T12:00:00Z').getTime() / 1000
          chartRef.current.timeScale().setVisibleRange({
            from: tradeTs - 7  * 86400,
            to:   tradeTs + 3  * 86400,
          })
        } else {
          chartRef.current.timeScale().fitContent()
        }

        // Apply trade markers (or clear if none selected)
        applyMarkers(markersRef.current, candleRef.current, tradeData)

        // Populate volume histogram if visible
        if (volRef.current && settings.showVolume) {
          volRef.current.setData(candles.map(c => ({
            time:  c.time,
            value: c.volume ?? 0,
            color: c.close >= c.open ? settings.volUpColor : settings.volDownColor,
          })))
        }

        setLoading(false)
      })
      .catch(err => {
        if (err.name !== 'AbortError') { setError(err.message); setLoading(false) }
      })

    return () => controller.abort()
  }, [chartReady, tf, dateRange, focusDate]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />

      {hoverBar && !loading && (
        <div className="ohlcv-tooltip">
          <span className="ohlcv-item ohlcv-time">{fmtTooltipTime(hoverBar.time)}</span>
          <span className="ohlcv-item">O <strong>{Number(hoverBar.open).toFixed(2)}</strong></span>
          <span className="ohlcv-item">H <strong>{Number(hoverBar.high).toFixed(2)}</strong></span>
          <span className="ohlcv-item">L <strong>{Number(hoverBar.low).toFixed(2)}</strong></span>
          <span className="ohlcv-item">C <strong>{Number(hoverBar.close).toFixed(2)}</strong></span>
          <span className="ohlcv-item ohlcv-vol">V <strong>{Number(hoverBar.volume).toLocaleString()}</strong></span>
        </div>
      )}

      {loading && <div className="chart-overlay">Loading…</div>}
      {error   && <div className="chart-overlay chart-overlay--error">Error: {error}</div>}
    </div>
  )
})

export default Chart

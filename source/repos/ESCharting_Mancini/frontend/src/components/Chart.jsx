import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from 'react'
import { createChart, CandlestickSeries, HistogramSeries } from 'lightweight-charts'
import { SessionHighlight } from '../lib/SessionHighlight'

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

function toBackendTf(tf) {
  if (tf.toUpperCase() === 'D') return 'D'
  const h = tf.match(/^(\d+)h$/i)
  if (h) return String(parseInt(h[1], 10) * 60)
  const m = tf.match(/^(\d+)m(?:in)?$/i)
  if (m) return m[1]
  return tf
}

const Chart = forwardRef(function Chart({ timeframe = '5m', settings, dateRange, focusDate }, ref) {
  const containerRef   = useRef(null)
  const chartRef       = useRef(null)
  const candleRef      = useRef(null)   // candlestick series
  const volRef         = useRef(null)   // volume histogram series
  const shadingRef     = useRef(null)   // SessionHighlight primitive
  const shadingOnRef   = useRef(false)

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

    chartRef.current  = chart
    candleRef.current = candle
    shadingRef.current = new SessionHighlight()

    chart.subscribeCrosshairMove(param => {
      if (param.seriesData && param.seriesData.has(candle)) {
        setHoverBar(param.seriesData.get(candle))
      } else {
        setHoverBar(null)
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
      chart.remove()
      chartRef.current    = null
      candleRef.current   = null
      volRef.current      = null
      shadingRef.current  = null
      shadingOnRef.current = false
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Apply appearance settings ────────────────────────────────────────────
  useEffect(() => {
    if (!chartReady || !chartRef.current || !candleRef.current) return
    const chart  = chartRef.current
    const candle = candleRef.current
    const s      = settings

    chart.applyOptions({
      layout: { background: { color: s.backgroundColor }, textColor: s.textColor },
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

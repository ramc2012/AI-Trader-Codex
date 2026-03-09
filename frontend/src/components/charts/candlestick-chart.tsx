'use client';

import { useEffect, useRef, memo } from 'react';
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type UTCTimestamp,
} from 'lightweight-charts';

interface CandleBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface TradeMarkerInput {
  time: number;
  side?: 'BUY' | 'SELL';
  type?: 'entry' | 'exit';
  pnl?: number;
  text?: string;
}

interface CandlestickChartProps {
  data: CandleBar[];
  height?: number;
  /** Lock viewport to data range so chart doesn't scroll past the last candle */
  lockViewport?: boolean;
  /** Optional trade markers rendered on top of OHLC candles */
  tradeMarkers?: TradeMarkerInput[];
}

function CandlestickChart({
  data,
  height = 400,
  lockViewport = true,
  tradeMarkers = [],
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const markerSeriesRef = useRef<{ setMarkers: (markers: SeriesMarker<UTCTimestamp>[]) => void } | null>(null);

  // ── Create chart instance once ─────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: {
        vertLine: {
          color: '#64748b',
          labelBackgroundColor: '#475569',
        },
        horzLine: {
          color: '#64748b',
          labelBackgroundColor: '#475569',
        },
      },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: UTCTimestamp) => {
          const d = new Date((time as number) * 1000);
          const ist = new Date(d.getTime() + 5.5 * 60 * 60 * 1000);
          return `${String(ist.getUTCHours()).padStart(2, '0')}:${String(ist.getUTCMinutes()).padStart(2, '0')}`;
        },
        // Prevent the chart from auto-scrolling to future empty space
        fixRightEdge: lockViewport,
        fixLeftEdge: lockViewport,
        lockVisibleTimeRangeOnResize: true,
        rightOffset: 2,
      },
      rightPriceScale: {
        borderColor: '#334155',
        scaleMargins: { top: 0.08, bottom: 0.22 },
      },
      localization: {
        timeFormatter: (time: UTCTimestamp) => {
          const d = new Date((time as number) * 1000);
          const ist = new Date(d.getTime() + 5.5 * 60 * 60 * 1000);
          return ist.toLocaleString('en-IN', { timeZone: 'UTC', hour12: false });
        },
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: { time: true, price: true },
        mouseWheel: true,
        pinch: true,
      },
    });

    chartRef.current = chart;

    candleSeriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderUpColor: '#10b981',
      borderDownColor: '#ef4444',
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });
    markerSeriesRef.current = createSeriesMarkers(candleSeriesRef.current, []);

    volumeSeriesRef.current = chart.addSeries(HistogramSeries, {
      color: '#64748b',
      priceFormat: { type: 'volume' },
      priceScaleId: 'vol',
    });
    chart.priceScale('vol').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    // Responsive width via ResizeObserver (faster than window resize event)
    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      markerSeriesRef.current = null;
    };
    // height and lockViewport are stable props; intentionally excluded from deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Push data into existing series (no chart recreation) ──────────────────
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || data.length === 0) return;

    // Sort ascending by time (required by lightweight-charts)
    const sorted = [...data].sort((a, b) => a.time - b.time);

    candleSeriesRef.current.setData(
      sorted.map(({ time, open, high, low, close }) => ({
        time: time as UTCTimestamp,
        open,
        high,
        low,
        close,
      }))
    );

    const volData = sorted
      .filter((d) => d.volume !== undefined && d.volume > 0)
      .map((d) => ({
        time: d.time as UTCTimestamp,
        value: d.volume!,
        color: d.close >= d.open ? '#10b98150' : '#ef444450',
      }));
    if (volData.length > 0) {
      volumeSeriesRef.current.setData(volData);
    }

    if (markerSeriesRef.current) {
      const firstTs = sorted[0]?.time ?? 0;
      const lastTs = sorted[sorted.length - 1]?.time ?? 0;
      const markers: SeriesMarker<UTCTimestamp>[] = tradeMarkers
        .filter((m) => Number.isFinite(m.time) && m.time >= firstTs && m.time <= (lastTs + 86400))
        .map((m) => {
          const side = String(m.side ?? '').toUpperCase();
          const isBuy = side !== 'SELL';
          const isExit = m.type === 'exit' || (m.type !== 'entry' && !side && m.pnl !== undefined);
          if (isExit) {
            const pnl = Number(m.pnl ?? 0);
            const position: SeriesMarker<UTCTimestamp>['position'] =
              pnl >= 0 ? 'aboveBar' : 'belowBar';
            return {
              time: m.time as UTCTimestamp,
              position,
              shape: 'circle' as const,
              color: pnl >= 0 ? '#22c55e' : '#f97316',
              text: m.text ?? 'EXIT',
            };
          }
          const position: SeriesMarker<UTCTimestamp>['position'] =
            isBuy ? 'belowBar' : 'aboveBar';
          const shape: SeriesMarker<UTCTimestamp>['shape'] =
            isBuy ? 'arrowUp' : 'arrowDown';
          return {
            time: m.time as UTCTimestamp,
            position,
            shape,
            color: isBuy ? '#10b981' : '#ef4444',
            text: m.text ?? (isBuy ? 'BUY' : 'SELL'),
          };
        });
      markerSeriesRef.current.setMarkers(markers.slice(-150));
    }

    // Fit content then lock the right edge so we don't scroll into empty future
    chartRef.current?.timeScale().fitContent();
  }, [data, tradeMarkers]);

  return <div ref={containerRef} className="w-full" style={{ height: `${height}px` }} />;
}

export default memo(CandlestickChart);

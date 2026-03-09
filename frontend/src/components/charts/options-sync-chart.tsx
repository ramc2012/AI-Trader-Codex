'use client';

import { useCallback, useEffect, useMemo, useRef } from 'react';
import {
  CandlestickSeries,
  createChart,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type LogicalRange,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts';

import type { OptionCandle } from '@/hooks/use-options';

type ChartPoint = {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ema9: number | null;
  ema50: number | null;
  bbMid: number | null;
  bbUpper: number | null;
  bbLower: number | null;
  rsi: number | null;
  macd: number | null;
  signal: number | null;
  hist: number | null;
};

interface OptionsSyncChartProps {
  candles: OptionCandle[];
  compact?: boolean;
}

function ema(values: number[], period: number): Array<number | null> {
  const out: Array<number | null> = new Array(values.length).fill(null);
  if (values.length < period) return out;

  const k = 2 / (period + 1);
  let prev = 0;
  for (let i = 0; i < period; i += 1) prev += values[i];
  prev /= period;
  out[period - 1] = prev;

  for (let i = period; i < values.length; i += 1) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

function sma(values: number[], period: number): Array<number | null> {
  const out: Array<number | null> = new Array(values.length).fill(null);
  if (values.length < period) return out;
  let sum = 0;
  for (let i = 0; i < values.length; i += 1) {
    sum += values[i];
    if (i >= period) {
      sum -= values[i - period];
    }
    if (i >= period - 1) {
      out[i] = sum / period;
    }
  }
  return out;
}

function stddev(values: number[], period: number, means: Array<number | null>): Array<number | null> {
  const out: Array<number | null> = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i += 1) {
    const mean = means[i];
    if (mean === null) continue;
    let variance = 0;
    for (let j = i - period + 1; j <= i; j += 1) {
      const d = values[j] - mean;
      variance += d * d;
    }
    out[i] = Math.sqrt(variance / period);
  }
  return out;
}

function rsi(values: number[], period = 14): Array<number | null> {
  const out: Array<number | null> = new Array(values.length).fill(null);
  if (values.length <= period) return out;

  let gains = 0;
  let losses = 0;
  for (let i = 1; i <= period; i += 1) {
    const delta = values[i] - values[i - 1];
    if (delta >= 0) gains += delta;
    else losses += Math.abs(delta);
  }

  let avgGain = gains / period;
  let avgLoss = losses / period;
  out[period] = avgLoss === 0 ? 100 : 100 - (100 / (1 + avgGain / avgLoss));

  for (let i = period + 1; i < values.length; i += 1) {
    const delta = values[i] - values[i - 1];
    const gain = delta > 0 ? delta : 0;
    const loss = delta < 0 ? Math.abs(delta) : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - (100 / (1 + avgGain / avgLoss));
  }
  return out;
}

function macd(values: number[]): {
  macdLine: Array<number | null>;
  signalLine: Array<number | null>;
  histogram: Array<number | null>;
} {
  const ema12 = ema(values, 12);
  const ema26 = ema(values, 26);
  const macdLine: Array<number | null> = values.map((_, idx) => {
    if (ema12[idx] === null || ema26[idx] === null) return null;
    return (ema12[idx] as number) - (ema26[idx] as number);
  });

  const compactMacd = macdLine.map((v) => v ?? 0);
  const signalRaw = ema(compactMacd, 9);
  const signalLine = macdLine.map((v, idx) => (v === null ? null : signalRaw[idx]));
  const histogram = macdLine.map((v, idx) => {
    if (v === null || signalLine[idx] === null) return null;
    return v - (signalLine[idx] as number);
  });
  return { macdLine, signalLine, histogram };
}

function applySyncedRange(source: IChartApi, targets: IChartApi[], guard: { syncing: boolean }) {
  const onRange = (range: LogicalRange | null) => {
    if (!range || guard.syncing) return;
    guard.syncing = true;
    for (const target of targets) {
      target.timeScale().setVisibleLogicalRange(range);
    }
    guard.syncing = false;
  };
  source.timeScale().subscribeVisibleLogicalRangeChange(onRange);
  return () => source.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
}

export function OptionsSyncChart({ candles, compact = false }: OptionsSyncChartProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const pricePaneRef = useRef<HTMLDivElement>(null);
  const rsiPaneRef = useRef<HTMLDivElement>(null);
  const macdPaneRef = useRef<HTMLDivElement>(null);

  const priceChartRef = useRef<IChartApi | null>(null);
  const rsiChartRef = useRef<IChartApi | null>(null);
  const macdChartRef = useRef<IChartApi | null>(null);
  const didFitRef = useRef(false);

  const candleSeriesRef = useRef<any>(null);
  const volumeSeriesRef = useRef<any>(null);
  const ema9SeriesRef = useRef<any>(null);
  const ema50SeriesRef = useRef<any>(null);
  const bbUpperSeriesRef = useRef<any>(null);
  const bbMidSeriesRef = useRef<any>(null);
  const bbLowerSeriesRef = useRef<any>(null);

  const rsiSeriesRef = useRef<any>(null);
  const rsiObSeriesRef = useRef<any>(null);
  const rsiOsSeriesRef = useRef<any>(null);

  const macdSeriesRef = useRef<any>(null);
  const signalSeriesRef = useRef<any>(null);
  const histSeriesRef = useRef<any>(null);
  const macdZeroSeriesRef = useRef<any>(null);

  const points = useMemo<ChartPoint[]>(() => {
    if (!candles.length) return [];

    const bySecond = new Map<number, OptionCandle>();
    for (const candle of candles) {
      const ts = Math.floor(new Date(candle.timestamp).getTime() / 1000);
      if (!Number.isFinite(ts)) continue;
      bySecond.set(ts, candle);
    }

    const sorted = Array.from(bySecond.entries())
      .sort((a, b) => a[0] - b[0])
      .map(([ts, candle]) => ({ ts, candle }));
    if (!sorted.length) return [];

    const closes = sorted.map((entry) => entry.candle.close);
    const ema9 = ema(closes, 9);
    const ema50 = ema(closes, 50);
    const bbMid = sma(closes, 20);
    const sigma = stddev(closes, 20, bbMid);
    const bbUpper = bbMid.map((m, i) => (m === null || sigma[i] === null ? null : m + 2 * (sigma[i] as number)));
    const bbLower = bbMid.map((m, i) => (m === null || sigma[i] === null ? null : m - 2 * (sigma[i] as number)));
    const rsi14 = rsi(closes, 14);
    const macdOut = macd(closes);

    return sorted.map((entry, idx) => ({
      time: entry.ts as UTCTimestamp,
      open: entry.candle.open,
      high: entry.candle.high,
      low: entry.candle.low,
      close: entry.candle.close,
      volume: entry.candle.volume,
      ema9: ema9[idx],
      ema50: ema50[idx],
      bbMid: bbMid[idx],
      bbUpper: bbUpper[idx],
      bbLower: bbLower[idx],
      rsi: rsi14[idx],
      macd: macdOut.macdLine[idx],
      signal: macdOut.signalLine[idx],
      hist: macdOut.histogram[idx],
    }));
  }, [candles]);

  const priceHeight = compact ? 220 : 300;
  const rsiHeight = compact ? 92 : 130;
  const macdHeight = compact ? 96 : 130;

  useEffect(() => {
    if (!pricePaneRef.current || !rsiPaneRef.current || !macdPaneRef.current || priceChartRef.current) {
      return;
    }

    const width = pricePaneRef.current.clientWidth || 900;
    const baseOptions = {
      width,
      layout: {
        background: { color: '#020617' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      rightPriceScale: {
        borderColor: '#1e293b',
      },
      timeScale: {
        borderColor: '#1e293b',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 1,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
      crosshair: {
        vertLine: { color: '#64748b' },
        horzLine: { color: '#64748b' },
      },
    } as const;

    const priceChart = createChart(pricePaneRef.current, {
      ...baseOptions,
      height: priceHeight,
    });
    const rsiChart = createChart(rsiPaneRef.current, {
      ...baseOptions,
      height: rsiHeight,
    });
    const macdChart = createChart(macdPaneRef.current, {
      ...baseOptions,
      height: macdHeight,
    });

    priceChartRef.current = priceChart;
    rsiChartRef.current = rsiChart;
    macdChartRef.current = macdChart;

    candleSeriesRef.current = priceChart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });
    volumeSeriesRef.current = priceChart.addSeries(HistogramSeries, {
      color: '#334155',
      priceScaleId: '',
      priceFormat: { type: 'volume' },
    });
    priceChart.priceScale('').applyOptions({
      scaleMargins: {
        top: 0.82,
        bottom: 0,
      },
    });

    const overlayStyle = {
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    } as const;
    ema9SeriesRef.current = priceChart.addSeries(LineSeries, {
      ...overlayStyle,
      color: '#f59e0b',
    } as any);
    ema50SeriesRef.current = priceChart.addSeries(LineSeries, {
      ...overlayStyle,
      color: '#38bdf8',
    } as any);
    bbUpperSeriesRef.current = priceChart.addSeries(LineSeries, {
      ...overlayStyle,
      lineWidth: 1,
      color: '#a78bfa',
    } as any);
    bbMidSeriesRef.current = priceChart.addSeries(LineSeries, {
      ...overlayStyle,
      lineWidth: 1,
      color: '#94a3b8',
    } as any);
    bbLowerSeriesRef.current = priceChart.addSeries(LineSeries, {
      ...overlayStyle,
      lineWidth: 1,
      color: '#a78bfa',
    } as any);

    rsiSeriesRef.current = rsiChart.addSeries(LineSeries, {
      color: '#818cf8',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    } as any);
    rsiObSeriesRef.current = rsiChart.addSeries(LineSeries, {
      color: '#ef4444',
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    } as any);
    rsiOsSeriesRef.current = rsiChart.addSeries(LineSeries, {
      color: '#10b981',
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    } as any);
    rsiChart.priceScale('right').applyOptions({
      autoScale: false,
      mode: 0,
    });

    macdSeriesRef.current = macdChart.addSeries(LineSeries, {
      color: '#3b82f6',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    } as any);
    signalSeriesRef.current = macdChart.addSeries(LineSeries, {
      color: '#f59e0b',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    } as any);
    histSeriesRef.current = macdChart.addSeries(HistogramSeries, {
      color: '#22d3ee',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    macdZeroSeriesRef.current = macdChart.addSeries(LineSeries, {
      color: '#334155',
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    } as any);

    const syncGuard = { syncing: false };
    const unsubA = applySyncedRange(priceChart, [rsiChart, macdChart], syncGuard);
    const unsubB = applySyncedRange(rsiChart, [priceChart, macdChart], syncGuard);
    const unsubC = applySyncedRange(macdChart, [priceChart, rsiChart], syncGuard);

    const handleResize = () => {
      const nextWidth = rootRef.current?.clientWidth || width;
      priceChart.applyOptions({ width: nextWidth });
      rsiChart.applyOptions({ width: nextWidth });
      macdChart.applyOptions({ width: nextWidth });
    };

    const observer = rootRef.current ? new ResizeObserver(handleResize) : null;
    if (observer && rootRef.current) observer.observe(rootRef.current);
    window.addEventListener('resize', handleResize);

    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', handleResize);
      unsubA();
      unsubB();
      unsubC();
      didFitRef.current = false;
      priceChart.remove();
      rsiChart.remove();
      macdChart.remove();
      priceChartRef.current = null;
      rsiChartRef.current = null;
      macdChartRef.current = null;
    };
  }, [priceHeight, rsiHeight, macdHeight]);

  useEffect(() => {
    if (!priceChartRef.current || !rsiChartRef.current || !macdChartRef.current) return;
    priceChartRef.current.applyOptions({ height: priceHeight });
    rsiChartRef.current.applyOptions({ height: rsiHeight });
    macdChartRef.current.applyOptions({ height: macdHeight });
  }, [priceHeight, rsiHeight, macdHeight]);

  const resetZoom = useCallback(() => {
    const priceChart = priceChartRef.current;
    const rsiChart = rsiChartRef.current;
    const macdChart = macdChartRef.current;
    if (!priceChart || !rsiChart || !macdChart) return;
    priceChart.timeScale().fitContent();
    const range = priceChart.timeScale().getVisibleLogicalRange();
    if (range) {
      rsiChart.timeScale().setVisibleLogicalRange(range);
      macdChart.timeScale().setVisibleLogicalRange(range);
    }
  }, []);

  useEffect(() => {
    if (!points.length) return;
    if (!candleSeriesRef.current || !rsiSeriesRef.current || !macdSeriesRef.current) return;
    const priceChart = priceChartRef.current;
    const rsiChart = rsiChartRef.current;
    const macdChart = macdChartRef.current;
    if (!priceChart || !rsiChart || !macdChart) return;

    // Save user's current zoom/pan before updating data so it is preserved after setData()
    const savedRange: LogicalRange | null = didFitRef.current
      ? priceChart.timeScale().getVisibleLogicalRange()
      : null;

    candleSeriesRef.current.setData(
      points.map((p) => ({
        time: p.time,
        open: p.open,
        high: p.high,
        low: p.low,
        close: p.close,
      }))
    );
    volumeSeriesRef.current?.setData(
      points.map((p) => ({
        time: p.time,
        value: p.volume,
        color: p.close >= p.open ? '#10b98166' : '#ef444466',
      }))
    );

    const toLine = (getter: (p: ChartPoint) => number | null) =>
      points
        .map((p) => {
          const value = getter(p);
          return value === null ? null : { time: p.time as Time, value };
        })
        .filter((p): p is { time: Time; value: number } => p !== null);

    ema9SeriesRef.current?.setData(toLine((p) => p.ema9));
    ema50SeriesRef.current?.setData(toLine((p) => p.ema50));
    bbUpperSeriesRef.current?.setData(toLine((p) => p.bbUpper));
    bbMidSeriesRef.current?.setData(toLine((p) => p.bbMid));
    bbLowerSeriesRef.current?.setData(toLine((p) => p.bbLower));

    rsiSeriesRef.current.setData(toLine((p) => p.rsi));
    rsiObSeriesRef.current?.setData(points.map((p) => ({ time: p.time, value: 60 })));
    rsiOsSeriesRef.current?.setData(points.map((p) => ({ time: p.time, value: 40 })));
    rsiChartRef.current?.priceScale('right').applyOptions({
      autoScale: false,
      mode: 0,
      visible: true,
      alignLabels: true,
      scaleMargins: { top: 0.1, bottom: 0.1 },
    });

    macdSeriesRef.current.setData(toLine((p) => p.macd));
    signalSeriesRef.current?.setData(toLine((p) => p.signal));
    const histData = points.flatMap((p) =>
      p.hist === null
        ? []
        : [
            {
              time: p.time,
              value: p.hist,
              color: p.hist >= 0 ? '#2dd4bf' : '#f87171',
            },
          ]
    );
    histSeriesRef.current?.setData(histData);
    macdZeroSeriesRef.current?.setData(points.map((p) => ({ time: p.time, value: 0 })));

    if (!didFitRef.current) {
      // First load — fit all content
      priceChart.timeScale().fitContent();
      const range = priceChart.timeScale().getVisibleLogicalRange();
      if (range) {
        rsiChart.timeScale().setVisibleLogicalRange(range);
        macdChart.timeScale().setVisibleLogicalRange(range);
      }
      didFitRef.current = true;
    } else if (savedRange) {
      // Subsequent updates — restore user's zoom/pan so it doesn't reset
      priceChart.timeScale().setVisibleLogicalRange(savedRange);
      rsiChart.timeScale().setVisibleLogicalRange(savedRange);
      macdChart.timeScale().setVisibleLogicalRange(savedRange);
    }
  }, [points]);

  if (!points.length) {
    return (
      <div className="flex h-80 items-center justify-center rounded-lg border border-slate-800 bg-slate-900/60 text-sm text-slate-500">
        No chart data
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-wide text-slate-500">
          EMA(9,50) · BB(20,2) · RSI OB:60 OS:40 · MACD(12,26,9)
        </div>
        <button
          onClick={resetZoom}
          className="rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
          title="Reset zoom to show all candles"
        >
          Reset Zoom
        </button>
      </div>
      <div ref={rootRef} className="space-y-2 overflow-hidden rounded-lg border border-slate-800 bg-slate-950/60 p-2">
        <div ref={pricePaneRef} className="w-full" style={{ height: `${priceHeight}px` }} />
        <div ref={rsiPaneRef} className="w-full" style={{ height: `${rsiHeight}px` }} />
        <div ref={macdPaneRef} className="w-full" style={{ height: `${macdHeight}px` }} />
      </div>
    </div>
  );
}

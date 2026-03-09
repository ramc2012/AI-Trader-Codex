'use client';

import { useState, useMemo, useEffect, useRef, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  CandlestickChart,
  PieChart,
  Activity,
  BarChart3,
  DollarSign,
  TrendingUp,
  TrendingDown,
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw,
  Eye,
  Wifi,
  WifiOff,
  Zap,
} from 'lucide-react';
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useOHLC } from '@/hooks/use-ohlc';
import { useOIQuadrants, useATMWatchlist } from '@/hooks/use-oi';
import type { QuadrantSymbol, ATMOption } from '@/hooks/use-oi';
import { useOrderflowWS } from '@/hooks/use-orderflow-ws';
import type { RtFootprintBar, RtPriceLevel } from '@/hooks/use-orderflow-ws';
import { useFootprint } from '@/hooks/use-orderflow';
import type { FootprintBar, PriceLevel } from '@/hooks/use-orderflow';
import { FootprintChart } from '@/components/charts/FootprintChart';
import MarketProfileWorkspace from '@/components/charts/market-profile-workspace';
import { MoneyFlowDashboard } from '@/components/MoneyFlowDashboard';
import { useGlobalContinuousWatchlist, useWatchlistUniverse } from '@/hooks/use-watchlist';
import { useAgentEvents } from '@/hooks/use-agent';
import { formatINR, formatNumber } from '@/lib/formatters';
import {
  buildInstrumentOptions,
  defaultSymbolForMarket,
  filterInstrumentOptions,
  type InstrumentOption,
} from '@/lib/instrument-universe';
import { cn } from '@/lib/utils';
import {
  calculateATR,
  calculateBollingerBands,
  calculateEMA,
  calculateMACD,
  calculateRSI,
  calculateVWAP,
} from '@/lib/indicators';

// ─── Tab config ────────────────────────────────────────────────────────────────

type Tab = 'charts' | 'oi' | 'orderflow' | 'profile' | 'moneyflow';

const TABS: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'charts',    label: 'Charts',         icon: CandlestickChart },
  { id: 'oi',        label: 'OI Dashboard',   icon: PieChart },
  { id: 'orderflow', label: 'Order Flow',     icon: Activity },
  { id: 'profile',   label: 'Market Profile', icon: BarChart3 },
  { id: 'moneyflow', label: 'Money Flow',     icon: DollarSign },
];

// ══════════════════════════════════════════════════════════════════════════════
// Charts View — fixed lifecycle: create chart once, update series on data change
// ══════════════════════════════════════════════════════════════════════════════

const CHART_TIMEFRAMES = [
  { label: '1m', value: '1' },
  { label: '5m', value: '5' },
  { label: '15m', value: '15' },
  { label: '1h', value: '60' },
  { label: '1D', value: 'D' },
];

const CHART_INDICATORS = [
  { key: 'ema20', label: 'EMA 20' },
  { key: 'ema50', label: 'EMA 50' },
  { key: 'ema200', label: 'EMA 200' },
  { key: 'vwap', label: 'VWAP' },
  { key: 'bbands', label: 'BB(20,2)' },
] as const;

const MARKET_FILTERS = ['ALL', 'NSE', 'BSE', 'US', 'CRYPTO'] as const;

function ChartsView({ options, initialSymbol }: { options: InstrumentOption[]; initialSymbol?: string | null }) {
  const [market, setMarket] = useState<string>('ALL');
  const filteredOptions = useMemo(() => filterInstrumentOptions(options, market), [market, options]);
  const [requestedSymbol, setRequestedSymbol] = useState(() =>
    defaultSymbolForMarket(options, 'ALL', initialSymbol ?? 'NSE:NIFTY50-INDEX'),
  );
  const symbol = useMemo(() => {
    if (filteredOptions.some((item) => item.value === requestedSymbol)) {
      return requestedSymbol;
    }
    return defaultSymbolForMarket(options, market, initialSymbol ?? requestedSymbol);
  }, [filteredOptions, initialSymbol, market, options, requestedSymbol]);
  const [timeframe, setTimeframe] = useState('5');
  const [enabledIndicators, setEnabledIndicators] = useState<Record<string, boolean>>({
    ema20: true,
    ema50: true,
    ema200: false,
    vwap: true,
    bbands: false,
  });
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const ema20Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const ema50Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const ema200Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const vwapRef = useRef<ISeriesApi<'Line'> | null>(null);
  const bbUpperRef = useRef<ISeriesApi<'Line'> | null>(null);
  const bbLowerRef = useRef<ISeriesApi<'Line'> | null>(null);
  const markersRef = useRef<{ setMarkers: (markers: SeriesMarker<UTCTimestamp>[]) => void } | null>(null);

  const { data: ohlcData, isFetching } = useOHLC(symbol, timeframe);
  const { data: agentEvents } = useAgentEvents(500, 1500);

  const parseTs = (ts: string) => {
    const hasTz = /Z$|[+-]\d{2}:\d{2}$/.test(ts);
    return new Date(hasTz ? ts : `${ts}Z`);
  };

  const tradeMarkers = useMemo<SeriesMarker<UTCTimestamp>[]>(() => {
    const candles = ohlcData?.candles ?? [];
    if (!candles.length || !agentEvents?.length) return [];

    const tfSec = timeframe === 'D' ? 86400 : Math.max(parseInt(timeframe || '5', 10), 1) * 60;
    const firstTs = Math.floor(new Date(candles[0].timestamp).getTime() / 1000);
    const lastTs = Math.floor(new Date(candles[candles.length - 1].timestamp).getTime() / 1000);

    const alignToTf = (epochSec: number) =>
      (Math.floor(epochSec / tfSec) * tfSec) as UTCTimestamp;

    const markers: SeriesMarker<UTCTimestamp>[] = [];
    for (const event of agentEvents) {
      if (
        event.event_type !== 'order_placed' &&
        event.event_type !== 'order_filled' &&
        event.event_type !== 'position_closed'
      ) {
        continue;
      }
      const meta = event.metadata ?? {};
      const underlying = String(meta.underlying_symbol ?? '').trim();
      const directSymbol = String(meta.symbol ?? '').trim();
      if (underlying !== symbol && directSymbol !== symbol) {
        continue;
      }

      const epoch = Math.floor(new Date(event.timestamp).getTime() / 1000);
      const t = alignToTf(epoch);
      if (t < firstTs || t > (lastTs + tfSec)) {
        continue;
      }

      if (event.event_type === 'order_placed' || event.event_type === 'order_filled') {
        const side = String(meta.side ?? '').toUpperCase();
        const isBuy = side !== 'SELL';
        markers.push({
          time: t,
          position: isBuy ? 'belowBar' : 'aboveBar',
          shape: isBuy ? 'arrowUp' : 'arrowDown',
          color: isBuy ? '#10b981' : '#ef4444',
          text: side || 'TRADE',
        });
      } else {
        const pnl = Number(meta.pnl ?? 0);
        markers.push({
          time: t,
          position: pnl >= 0 ? 'aboveBar' : 'belowBar',
          shape: 'circle',
          color: pnl >= 0 ? '#22c55e' : '#f97316',
          text: 'EXIT',
        });
      }
    }
    return markers.slice(-120);
  }, [agentEvents, ohlcData?.candles, symbol, timeframe]);

  const indicatorSnapshot = useMemo(() => {
    const candles = ohlcData?.candles ?? [];
    if (!candles.length) {
      return {
        ema20: null as number | null,
        ema50: null as number | null,
        ema200: null as number | null,
        vwap: null as number | null,
        bbUpper: null as number | null,
        bbLower: null as number | null,
        rsi14: null as number | null,
        macd: null as number | null,
        macdSignal: null as number | null,
        atr14: null as number | null,
      };
    }

    const closes = candles.map((c) => c.close);
    const ema20 = calculateEMA(closes, 20);
    const ema50 = calculateEMA(closes, 50);
    const ema200 = calculateEMA(closes, 200);
    const vwap = calculateVWAP(candles.map((c) => ({ ...c, timestamp: c.timestamp })));
    const bb = calculateBollingerBands(closes, 20, 2);
    const rsi = calculateRSI(closes, 14);
    const macdResult = calculateMACD(closes, 12, 26, 9);
    const atr = calculateATR(candles.map((c) => ({ ...c, timestamp: c.timestamp })), 14);

    const lastValue = (arr: Array<number | null>) => {
      for (let i = arr.length - 1; i >= 0; i -= 1) {
        if (arr[i] !== null) return arr[i] as number;
      }
      return null;
    };

    return {
      ema20: lastValue(ema20),
      ema50: lastValue(ema50),
      ema200: lastValue(ema200),
      vwap: vwap.length ? vwap[vwap.length - 1] : null,
      bbUpper: lastValue(bb.upper),
      bbLower: lastValue(bb.lower),
      rsi14: lastValue(rsi),
      macd: lastValue(macdResult.macd),
      macdSignal: lastValue(macdResult.signal),
      atr14: lastValue(atr),
    };
  }, [ohlcData?.candles]);

  // ── Create chart ONCE on mount ──────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#0f172a' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      width: containerRef.current.clientWidth,
      height: 480,
      crosshair: {
        vertLine: { color: '#475569', labelBackgroundColor: '#334155' },
        horzLine: { color: '#475569', labelBackgroundColor: '#334155' },
      },
      timeScale: {
        borderColor: '#1e293b',
        timeVisible: true,
        secondsVisible: false,
        // Display times in IST (UTC+5:30)
        tickMarkFormatter: (time: UTCTimestamp) => {
          const d = new Date((time as number) * 1000);
          const ist = new Date(d.getTime() + 5.5 * 60 * 60 * 1000);
          return `${String(ist.getUTCHours()).padStart(2, '0')}:${String(ist.getUTCMinutes()).padStart(2, '0')}`;
        },
      },
      rightPriceScale: { borderColor: '#1e293b' },
      localization: {
        timeFormatter: (time: UTCTimestamp) => {
          const d = new Date((time as number) * 1000);
          const ist = new Date(d.getTime() + 5.5 * 60 * 60 * 1000);
          return ist.toLocaleString('en-IN', { timeZone: 'UTC', hour12: false });
        },
      },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981', downColor: '#ef4444',
      borderDownColor: '#ef4444', borderUpColor: '#10b981',
      wickDownColor: '#ef4444', wickUpColor: '#10b981',
    });
    const ema20Series = chart.addSeries(LineSeries, {
      color: '#22d3ee',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ema50Series = chart.addSeries(LineSeries, {
      color: '#a78bfa',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ema200Series = chart.addSeries(LineSeries, {
      color: '#f59e0b',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const vwapSeries = chart.addSeries(LineSeries, {
      color: '#34d399',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const bbUpperSeries = chart.addSeries(LineSeries, {
      color: '#fb7185',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      lineStyle: 2,
    });
    const bbLowerSeries = chart.addSeries(LineSeries, {
      color: '#60a5fa',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      lineStyle: 2,
    });
    const markersApi = createSeriesMarkers(series, []);

    chartRef.current = chart;
    seriesRef.current = series;
    ema20Ref.current = ema20Series;
    ema50Ref.current = ema50Series;
    ema200Ref.current = ema200Series;
    vwapRef.current = vwapSeries;
    bbUpperRef.current = bbUpperSeries;
    bbLowerRef.current = bbLowerSeries;
    markersRef.current = markersApi;

    const handleResize = () => {
      if (containerRef.current)
        chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    const ro = new ResizeObserver(handleResize);
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      ema20Ref.current = null;
      ema50Ref.current = null;
      ema200Ref.current = null;
      vwapRef.current = null;
      bbUpperRef.current = null;
      bbLowerRef.current = null;
      markersRef.current = null;
    };
  }, []); // only once

  // ── Update data whenever symbol/timeframe/data changes ───────────────────────
  useEffect(() => {
    if (!seriesRef.current || !chartRef.current) return;

    const candles = (ohlcData?.candles ?? [])
      .map((c) => ({
        time: Math.floor(parseTs(c.timestamp).getTime() / 1000) as UTCTimestamp,
        open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume,
      }))
      .sort((a, b) => (a.time as number) - (b.time as number));
    const formatted = candles.map(({ time, open, high, low, close }) => ({
      time,
      open,
      high,
      low,
      close,
    }));

    const setLineData = (
      target: ISeriesApi<'Line'> | null,
      values: Array<number | null>,
      enabled: boolean,
    ) => {
      if (!target) return;
      if (!enabled || !formatted.length) {
        target.setData([]);
        return;
      }
      target.setData(
        formatted
          .map((bar, idx) => {
            const value = values[idx];
            if (value === null || value === undefined) return null;
            return { time: bar.time, value };
          })
          .filter((row): row is { time: UTCTimestamp; value: number } => row !== null),
      );
    };

    try {
      seriesRef.current.setData(formatted);
      if (formatted.length) {
        const closes = candles.map((bar) => bar.close);
        const barsForCalc = candles.map((bar) => ({
          timestamp: bar.time,
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
          volume: Math.max(bar.volume, 1),
        }));
        const ema20 = calculateEMA(closes, 20);
        const ema50 = calculateEMA(closes, 50);
        const ema200 = calculateEMA(closes, 200);
        const vwap = calculateVWAP(barsForCalc);
        const bb = calculateBollingerBands(closes, 20, 2);

        setLineData(ema20Ref.current, ema20, Boolean(enabledIndicators.ema20));
        setLineData(ema50Ref.current, ema50, Boolean(enabledIndicators.ema50));
        setLineData(ema200Ref.current, ema200, Boolean(enabledIndicators.ema200));
        setLineData(vwapRef.current, vwap, Boolean(enabledIndicators.vwap));
        setLineData(bbUpperRef.current, bb.upper, Boolean(enabledIndicators.bbands));
        setLineData(bbLowerRef.current, bb.lower, Boolean(enabledIndicators.bbands));
      } else {
        setLineData(ema20Ref.current, [], false);
        setLineData(ema50Ref.current, [], false);
        setLineData(ema200Ref.current, [], false);
        setLineData(vwapRef.current, [], false);
        setLineData(bbUpperRef.current, [], false);
        setLineData(bbLowerRef.current, [], false);
      }

      if (formatted.length) {
        chartRef.current.timeScale().fitContent();
      }
    } catch {
      // series may have been removed during navigation; ignore
    }
  }, [enabledIndicators, ohlcData]);

  useEffect(() => {
    markersRef.current?.setMarkers(tradeMarkers);
  }, [tradeMarkers]);

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={market}
          onChange={(e) => setMarket(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
        >
          {MARKET_FILTERS.map((item) => (
            <option key={item} value={item}>
              {item === 'ALL' ? 'All Markets' : item}
            </option>
          ))}
        </select>
        <select
          value={symbol}
          onChange={(e) => setRequestedSymbol(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
        >
          {filteredOptions.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>

        <div className="flex gap-1">
          {CHART_TIMEFRAMES.map((tf) => (
            <button
              key={tf.value}
              onClick={() => setTimeframe(tf.value)}
              className={cn(
                'rounded-md px-3 py-2 text-sm font-medium transition-colors',
                timeframe === tf.value
                  ? 'bg-emerald-500/20 text-emerald-400'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-700',
              )}
            >
              {tf.label}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap gap-1">
          {CHART_INDICATORS.map((ind) => {
            const enabled = Boolean(enabledIndicators[ind.key]);
            return (
              <button
                key={ind.key}
                onClick={() =>
                  setEnabledIndicators((prev) => ({
                    ...prev,
                    [ind.key]: !prev[ind.key],
                  }))
                }
                className={cn(
                  'rounded-md border px-2 py-1 text-xs font-medium transition-colors',
                  enabled
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                    : 'border-slate-700 bg-slate-800 text-slate-400 hover:text-slate-300'
                )}
              >
                {ind.label}
              </button>
            );
          })}
        </div>

        {isFetching && (
          <RefreshCw className="h-3.5 w-3.5 animate-spin text-slate-500" />
        )}
      </div>

      {/* Chart container — always visible so clientWidth is correct */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 relative">
        <div ref={containerRef} style={{ height: 480 }} />
        {!ohlcData?.candles?.length && !isFetching && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
            <p className="text-sm text-slate-400">No data yet for {symbol} ({timeframe})</p>
            <p className="text-xs text-slate-500">Data loads in IST and falls back across configured providers. Check Settings if the selected market feed is not configured.</p>
            <a href="/settings" className="text-xs text-emerald-400 hover:underline">→ Go to Settings to authenticate</a>
          </div>
        )}
      </div>

      {/* Info row */}
      {ohlcData?.candles?.length && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
            <span className="rounded border border-slate-700 bg-slate-900 px-2 py-1">
              RSI(14): {indicatorSnapshot.rsi14 !== null ? indicatorSnapshot.rsi14.toFixed(1) : '—'}
            </span>
            <span className="rounded border border-slate-700 bg-slate-900 px-2 py-1">
              MACD: {indicatorSnapshot.macd !== null ? indicatorSnapshot.macd.toFixed(2) : '—'}
            </span>
            <span className="rounded border border-slate-700 bg-slate-900 px-2 py-1">
              Signal: {indicatorSnapshot.macdSignal !== null ? indicatorSnapshot.macdSignal.toFixed(2) : '—'}
            </span>
            <span className="rounded border border-slate-700 bg-slate-900 px-2 py-1">
              ATR(14): {indicatorSnapshot.atr14 !== null ? indicatorSnapshot.atr14.toFixed(2) : '—'}
            </span>
            <span className="rounded border border-slate-700 bg-slate-900 px-2 py-1">
              EMA20: {indicatorSnapshot.ema20 !== null ? indicatorSnapshot.ema20.toFixed(2) : '—'}
            </span>
            <span className="rounded border border-slate-700 bg-slate-900 px-2 py-1">
              EMA50: {indicatorSnapshot.ema50 !== null ? indicatorSnapshot.ema50.toFixed(2) : '—'}
            </span>
            <span className="rounded border border-slate-700 bg-slate-900 px-2 py-1">
              VWAP: {indicatorSnapshot.vwap !== null ? indicatorSnapshot.vwap.toFixed(2) : '—'}
            </span>
          </div>

          <div className="flex items-center justify-between text-[10px] text-slate-500">
            <span>{tradeMarkers.length} AI trade markers</span>
            <span>
              {ohlcData.count} candles · last {parseTs(ohlcData.candles[ohlcData.candles.length - 1].timestamp).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false })} IST
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// OI Dashboard View
// ══════════════════════════════════════════════════════════════════════════════

const OI_QUADRANTS = [
  { key: 'long_buildup'   as const, label: 'Long Buildup',   description: 'Price ↑ + OI ↑', colorClass: 'text-emerald-400', bgClass: 'bg-emerald-500/5', borderClass: 'border-emerald-500/20', badgeClass: 'bg-emerald-500/10 text-emerald-400', icon: TrendingUp },
  { key: 'short_buildup'  as const, label: 'Short Buildup',  description: 'Price ↓ + OI ↑', colorClass: 'text-red-400',     bgClass: 'bg-red-500/5',     borderClass: 'border-red-500/20',     badgeClass: 'bg-red-500/10 text-red-400',         icon: TrendingDown },
  { key: 'short_covering' as const, label: 'Short Covering', description: 'Price ↑ + OI ↓', colorClass: 'text-cyan-400',    bgClass: 'bg-cyan-500/5',    borderClass: 'border-cyan-500/20',    badgeClass: 'bg-cyan-500/10 text-cyan-400',       icon: ArrowUpRight },
  { key: 'long_unwinding' as const, label: 'Long Unwinding', description: 'Price ↓ + OI ↓', colorClass: 'text-amber-400',  bgClass: 'bg-amber-500/5',   borderClass: 'border-amber-500/20',   badgeClass: 'bg-amber-500/10 text-amber-400',     icon: ArrowDownRight },
];

function QuadrantCard({ config, symbols }: { config: typeof OI_QUADRANTS[number]; symbols: QuadrantSymbol[] }) {
  const Icon = config.icon;
  return (
    <div className={cn('flex flex-col rounded-xl border', config.borderClass, config.bgClass)}>
      <div className="flex items-center justify-between border-b border-slate-800/50 px-4 py-3">
        <div className="flex items-center gap-2">
          <Icon className={cn('h-4 w-4', config.colorClass)} />
          <div>
            <div className={cn('text-sm font-semibold', config.colorClass)}>{config.label}</div>
            <div className="text-[10px] text-slate-500">{config.description}</div>
          </div>
        </div>
        <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-semibold', config.badgeClass)}>
          {symbols.length}
        </span>
      </div>
      <div className="max-h-[260px] overflow-y-auto">
        <table className="w-full">
          <thead>
            <tr className="text-left text-[10px] font-medium uppercase tracking-wider text-slate-500">
              <th className="px-3 py-2">Symbol</th>
              <th className="px-3 py-2 text-right">LTP</th>
              <th className="px-3 py-2 text-right">Price Chg%</th>
              <th className="px-3 py-2 text-right">OI Chg%</th>
            </tr>
          </thead>
          <tbody>
            {symbols.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-6 text-center text-xs text-slate-500">No symbols</td></tr>
            )}
            {symbols.map((sym) => (
              <tr key={sym.symbol} className="border-t border-slate-800/30 hover:bg-slate-800/20">
                <td className="px-3 py-1.5 text-xs font-medium text-slate-200">{sym.symbol}</td>
                <td className="px-3 py-1.5 text-right font-mono text-xs text-slate-300">
                  {sym.ltp > 0 ? formatINR(sym.ltp) : '—'}
                </td>
                <td className="px-3 py-1.5 text-right">
                  <span className={cn('font-mono text-xs font-semibold', sym.price_change_pct >= 0 ? 'text-emerald-400' : 'text-red-400')}>
                    {sym.price_change_pct >= 0 ? '+' : ''}{sym.price_change_pct.toFixed(2)}%
                  </span>
                </td>
                <td className="px-3 py-1.5 text-right">
                  <span className={cn('font-mono text-xs font-semibold', sym.oi_change_pct >= 0 ? 'text-emerald-400' : 'text-red-400')}>
                    {sym.oi_change_pct >= 0 ? '+' : ''}{sym.oi_change_pct.toFixed(2)}%
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ATMSidebar({ entries }: { entries: ATMOption[] }) {
  if (entries.length === 0) {
    return (
      <div className="flex h-full items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-12">
        <div className="text-center"><Eye className="mx-auto mb-2 h-6 w-6 text-slate-600" /><p className="text-xs text-slate-500">No ATM data</p></div>
      </div>
    );
  }
  return (
    <div className="flex flex-col rounded-xl border border-slate-800 bg-slate-900/60">
      <div className="border-b border-slate-800 px-4 py-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-200"><Eye className="h-4 w-4 text-blue-400" />ATM Watchlist</h3>
      </div>
      <div className="max-h-[600px] overflow-y-auto">
        {entries.map((entry) => {
          const pcrColor = entry.pcr > 1.2 ? 'text-emerald-400' : entry.pcr < 0.8 ? 'text-red-400' : 'text-slate-300';
          return (
            <div key={entry.symbol} className="border-b border-slate-800/30 px-4 py-3 hover:bg-slate-800/20">
              <div className="mb-2 flex items-baseline justify-between">
                <div>
                  <span className="text-sm font-semibold text-slate-100">{entry.display_name}</span>
                  <span className="ml-2 font-mono text-xs text-slate-400">Spot {formatINR(entry.spot)}</span>
                </div>
                <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">ATM {entry.atm_strike}</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-emerald-500/10 bg-emerald-500/5 px-2.5 py-1.5">
                  <div className="mb-1 text-[10px] font-medium uppercase text-emerald-500/70">CE</div>
                  <div className="font-mono text-xs font-semibold text-emerald-300">{formatINR(entry.ce_ltp)}</div>
                  <div className="mt-0.5 flex justify-between font-mono text-[10px] text-slate-500">
                    <span>OI {formatNumber(entry.ce_oi)}</span><span>IV {entry.ce_iv.toFixed(1)}%</span>
                  </div>
                </div>
                <div className="rounded-lg border border-red-500/10 bg-red-500/5 px-2.5 py-1.5">
                  <div className="mb-1 text-[10px] font-medium uppercase text-red-500/70">PE</div>
                  <div className="font-mono text-xs font-semibold text-red-300">{formatINR(entry.pe_ltp)}</div>
                  <div className="mt-0.5 flex justify-between font-mono text-[10px] text-slate-500">
                    <span>OI {formatNumber(entry.pe_oi)}</span><span>IV {entry.pe_iv.toFixed(1)}%</span>
                  </div>
                </div>
              </div>
              <div className="mt-2 flex items-center justify-between text-[10px]">
                <span className="text-slate-500">PCR <span className={cn('font-mono font-semibold', pcrColor)}>{entry.pcr.toFixed(2)}</span></span>
                <span className="text-slate-500">Straddle <span className="font-mono font-semibold text-slate-300">{formatINR(entry.straddle_price)}</span></span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function OIView() {
  const { data: quadrants, isLoading: qLoading, isError: qError, isFetching } = useOIQuadrants();
  const { data: atm, isLoading: aLoading } = useATMWatchlist();

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center gap-2 text-xs text-slate-500">
        {(qLoading || aLoading) && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
        {isFetching && !qLoading && <RefreshCw className="h-3 w-3 animate-spin opacity-50" />}
        {quadrants?.timestamp && (
          <span>Updated: {new Date(quadrants.timestamp).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false })} IST</span>
        )}
        {quadrants?.source === 'fyers_live' && (
          <span className="ml-auto rounded-full bg-emerald-500/10 px-2 py-0.5 text-emerald-400">● Live Fyers Data</span>
        )}
      </div>

      {qError && (
        <div className="rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-400">
          Failed to load OI data. Check backend connection.
        </div>
      )}

      <div className="flex gap-4">
        <div className="flex-1 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {OI_QUADRANTS.map((config) => (
            <QuadrantCard key={config.key} config={config} symbols={quadrants?.[config.key] ?? []} />
          ))}
        </div>
        <div className="hidden w-[320px] flex-shrink-0 xl:block">
          <ATMSidebar entries={atm?.entries ?? []} />
        </div>
      </div>
      <div className="xl:hidden"><ATMSidebar entries={atm?.entries ?? []} /></div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Order Flow View — real-time footprint via WebSocket
// ══════════════════════════════════════════════════════════════════════════════

const OF_BAR_OPTS = [{ value: 5, label: '5m' }, { value: 15, label: '15m' }, { value: 30, label: '30m' }];

function formatUSD(v: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(v);
}

/** Convert a real-time RtFootprintBar to the FootprintChart-compatible FootprintBar. */
function toFootprintBar(rt: RtFootprintBar, cvdAcc: number): FootprintBar {
  const levels: PriceLevel[] = Object.entries(rt.levels).map(([priceStr, lvl]: [string, RtPriceLevel]) => {
    const price = parseFloat(priceStr);
    // imbalance: one side is 3× the other
    const imbalance =
      lvl.bid > 0 && lvl.ask > 0
        ? lvl.bid / lvl.ask > 3 || lvl.ask / lvl.bid > 3
        : false;
    return { price, bid: lvl.bid, ask: lvl.ask, delta: lvl.delta, imbalance };
  });
  return {
    time: rt.open_time,
    open: rt.open ?? 0,
    high: rt.high ?? 0,
    low: rt.low ?? 0,
    close: rt.close ?? 0,
    volume: rt.volume,
    delta: rt.delta,
    vwap: rt.close ?? 0,    // approximate; not tracked per-tick
    cvd: cvdAcc,
    levels,
    imbalance_count: levels.filter((l) => l.imbalance).length,
  };
}

function OrderFlowView({ options, initialSymbol }: { options: InstrumentOption[]; initialSymbol?: string | null }) {
  const [market, setMarket] = useState<string>('ALL');
  const filteredOptions = useMemo(() => filterInstrumentOptions(options, market), [market, options]);
  const [requestedSymbol, setRequestedSymbol] = useState(() =>
    defaultSymbolForMarket(options, 'ALL', initialSymbol ?? 'NSE:NIFTY50-INDEX'),
  );
  const symbol = useMemo(() => {
    if (filteredOptions.some((item) => item.value === requestedSymbol)) {
      return requestedSymbol;
    }
    return defaultSymbolForMarket(options, market, initialSymbol ?? requestedSymbol);
  }, [filteredOptions, initialSymbol, market, options, requestedSymbol]);
  const [barMinutes, setBarMinutes] = useState(15);

  const { bars, currentBar, latencyMs, isConnected } = useOrderflowWS(symbol, barMinutes);
  const { data: restFootprint, isLoading: restLoading } = useFootprint(symbol, barMinutes, 3);

  // Build FootprintBar[] for chart: archived bars + live current bar (at the end)
  const wsBars = useMemo<FootprintBar[]>(() => {
    let cvd = 0;
    const allRt = currentBar ? [...bars, currentBar] : [...bars];
    return allRt.map((rt) => {
      cvd += rt.delta;
      return toFootprintBar(rt, cvd);
    });
  }, [bars, currentBar]);

  const hasMeaningfulFootprint = (bar: FootprintBar) =>
    bar.volume > 0 ||
    Math.abs(bar.delta) > 0 ||
    bar.levels.some((level) => level.bid > 0 || level.ask > 0);

  const hasWsData = useMemo(
    () => wsBars.length > 0 && wsBars.some((b) => hasMeaningfulFootprint(b)),
    [wsBars],
  );

  const footprintBars = useMemo(
    () => {
      const fallback = restFootprint?.footprints ?? [];
      const wsMeaningful = wsBars.filter((bar) => hasMeaningfulFootprint(bar));
      if (!wsMeaningful.length) {
        return fallback;
      }
      if (!fallback.length || wsMeaningful.length >= 3) {
        return wsMeaningful;
      }

      const merged = new Map<string, FootprintBar>();
      for (const bar of fallback) merged.set(bar.time, bar);
      for (const bar of wsMeaningful) merged.set(bar.time, bar);
      return Array.from(merged.values()).sort(
        (a, b) => new Date(a.time).getTime() - new Date(b.time).getTime(),
      );
    },
    [restFootprint?.footprints, wsBars],
  );

  const stats = useMemo(() => {
    if (!footprintBars.length) return { totalDelta: 0, totalVolume: 0, barCount: 0, imbalances: 0 };
    return {
      totalDelta: footprintBars.reduce((s, b) => s + b.delta, 0),
      totalVolume: footprintBars.reduce((s, b) => s + b.volume, 0),
      barCount: footprintBars.length,
      imbalances: footprintBars.reduce((s, b) => s + b.imbalance_count, 0),
    };
  }, [footprintBars]);

  return (
    <div className="flex flex-col gap-4">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={market}
          onChange={(e) => setMarket(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 focus:border-emerald-500 focus:outline-none"
        >
          {MARKET_FILTERS.map((item) => (
            <option key={item} value={item}>
              {item === 'ALL' ? 'All Markets' : item}
            </option>
          ))}
        </select>
        <select value={symbol} onChange={(e) => setRequestedSymbol(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 focus:border-emerald-500 focus:outline-none">
          {filteredOptions.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>

        {/* Bar size */}
        <div className="flex gap-0.5 rounded-lg border border-slate-700 bg-slate-800 p-0.5">
          {OF_BAR_OPTS.map((opt) => (
            <button key={opt.value} onClick={() => setBarMinutes(opt.value)}
              className={cn('rounded-md px-3 py-1 text-xs font-medium transition-colors', barMinutes === opt.value ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200')}>
              {opt.label}
            </button>
          ))}
        </div>

        {/* WS status badge */}
        <div className={cn(
          'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-mono font-medium',
          isConnected
            ? 'border-emerald-700/50 bg-emerald-500/10 text-emerald-400'
            : 'border-slate-700 bg-slate-800 text-slate-500'
        )}>
          {isConnected
            ? <Wifi className="h-3 w-3" />
            : <WifiOff className="h-3 w-3" />}
          {isConnected ? 'LIVE' : 'Connecting…'}
          {isConnected && latencyMs != null && (
            <span className="ml-1 text-[10px] text-emerald-600">{latencyMs}ms</span>
          )}
        </div>

        {/* Tick indicator */}
        {isConnected && currentBar && (
          <div className="flex items-center gap-1 rounded border border-blue-700/30 bg-blue-500/10 px-2 py-1 text-[10px] font-mono text-blue-400">
            <Zap className="h-2.5 w-2.5" />
            Live bar updating
          </div>
        )}
        {!hasWsData && restFootprint?.source && (
          <div className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-[10px] font-mono text-slate-300">
            Source: {restFootprint.source}
          </div>
        )}
      </div>

      {/* Chart */}
      {footprintBars.length === 0 ? (
        <div className="flex h-[520px] flex-col items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60">
          {restLoading ? (
            <>
              <RefreshCw className="mb-3 h-6 w-6 animate-spin text-slate-600" />
              <p className="text-sm text-slate-400">Loading order flow…</p>
            </>
          ) : (
            <>
              <WifiOff className="mb-3 h-8 w-8 text-slate-600" />
              <p className="text-sm text-slate-400">No order flow data yet</p>
              <p className="mt-1 text-xs text-slate-500">WS reconnecting and historical fallback unavailable</p>
            </>
          )}
        </div>
      ) : (
        <FootprintChart data={footprintBars} height="520px" />
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: 'Total Delta', value: `${stats.totalDelta >= 0 ? '+' : ''}${formatNumber(stats.totalDelta)}`, color: stats.totalDelta >= 0 ? 'text-emerald-400' : 'text-red-400' },
          { label: 'Total Volume', value: formatNumber(stats.totalVolume), color: 'text-slate-100' },
          { label: 'Bars', value: String(stats.barCount), color: 'text-slate-100' },
          { label: 'Imbalances', value: String(stats.imbalances), color: stats.imbalances > 0 ? 'text-amber-400' : 'text-slate-400' },
        ].map((s) => (
          <div key={s.label} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-slate-500">{s.label}</div>
            <div className={cn('font-mono text-lg font-bold', s.color)}>{s.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Market Profile View — horizontal stacking for multi-day comparison
// ══════════════════════════════════════════════════════════════════════════════

function MarketProfileView({ options, initialSymbol }: { options: InstrumentOption[]; initialSymbol?: string | null }) {
  return (
    <div className="space-y-4">
      <MarketProfileWorkspace options={options} initialSymbol={initialSymbol} />
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Money Flow View
// ══════════════════════════════════════════════════════════════════════════════

function MoneyFlowView() {
  const { data, isLoading, isFetching } = useGlobalContinuousWatchlist(true);
  const usOptions = data?.us_options ?? [];
  const crypto = data?.crypto_top10 ?? [];

  return (
    <div className="space-y-4">
      <MoneyFlowDashboard />

      <div className="rounded-xl border border-slate-800 bg-slate-900/60">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2.5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Global Watch</p>
            <p className="text-[11px] text-slate-500">US options + Top 10 crypto</p>
          </div>
          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            {isFetching && <RefreshCw className="h-3 w-3 animate-spin" />}
            <span>{data?.timestamp ? new Date(data.timestamp).toLocaleTimeString('en-IN') : '—'}</span>
          </div>
        </div>

        {isLoading ? (
          <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-2">
            <div className="h-28 animate-pulse rounded-lg bg-slate-800/50" />
            <div className="h-28 animate-pulse rounded-lg bg-slate-800/50" />
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-2">
            <div className="overflow-hidden rounded-lg border border-slate-800">
              <div className="border-b border-slate-800 bg-slate-900/70 px-3 py-2 text-xs font-semibold text-slate-300">
                US Option Underlyings (ATM)
              </div>
              <div className="max-h-56 overflow-auto">
                <table className="w-full min-w-[420px] text-xs">
                  <thead className="sticky top-0 bg-slate-900 text-slate-500">
                    <tr>
                      <th className="px-3 py-2 text-left">Symbol</th>
                      <th className="px-3 py-2 text-right">Spot</th>
                      <th className="px-3 py-2 text-right">Call</th>
                      <th className="px-3 py-2 text-right">Put</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usOptions.map((row) => (
                      <tr key={row.symbol} className="border-t border-slate-800/70">
                        <td className="px-3 py-2 font-semibold text-slate-200">{row.symbol}</td>
                        <td className="px-3 py-2 text-right font-mono text-slate-300">
                          {row.spot ? formatUSD(row.spot) : '—'}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-emerald-400">
                          {row.call_last ? formatUSD(row.call_last) : '—'}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-red-400">
                          {row.put_last ? formatUSD(row.put_last) : '—'}
                        </td>
                      </tr>
                    ))}
                    {!usOptions.length && (
                      <tr><td colSpan={4} className="px-3 py-4 text-center text-slate-500">US feed unavailable</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="overflow-hidden rounded-lg border border-slate-800">
              <div className="border-b border-slate-800 bg-slate-900/70 px-3 py-2 text-xs font-semibold text-slate-300">
                Crypto Top 10
              </div>
              <div className="max-h-56 overflow-auto">
                <table className="w-full min-w-[360px] text-xs">
                  <thead className="sticky top-0 bg-slate-900 text-slate-500">
                    <tr>
                      <th className="px-3 py-2 text-left">Asset</th>
                      <th className="px-3 py-2 text-right">Price (USD)</th>
                      <th className="px-3 py-2 text-right">24h %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {crypto.map((row) => (
                      <tr key={row.symbol} className="border-t border-slate-800/70">
                        <td className="px-3 py-2">
                          <div className="font-semibold text-slate-200">{row.symbol}</div>
                          <div className="text-[10px] text-slate-500">{row.name}</div>
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-slate-300">${row.price_usd.toFixed(2)}</td>
                        <td className={cn(
                          'px-3 py-2 text-right font-mono',
                          row.change_pct_24h >= 0 ? 'text-emerald-400' : 'text-red-400',
                        )}>
                          {row.change_pct_24h >= 0 ? '+' : ''}{row.change_pct_24h.toFixed(2)}%
                        </td>
                      </tr>
                    ))}
                    {!crypto.length && (
                      <tr><td colSpan={3} className="px-3 py-4 text-center text-slate-500">Crypto feed unavailable</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Analytics Page (tabbed container)
// ══════════════════════════════════════════════════════════════════════════════

function AnalyticsPageInner() {
  const searchParams = useSearchParams();
  const { data: universe } = useWatchlistUniverse();
  const instrumentOptions = useMemo(() => buildInstrumentOptions(universe), [universe]);
  const initialSymbol = searchParams.get('symbol');
  const [tab, setTab] = useState<Tab>(() => {
    const t = searchParams.get('tab');
    return (TABS.some((x) => x.id === t) ? t : 'charts') as Tab;
  });

  return (
    <div className="flex flex-col gap-0">
      {/* Tab bar */}
      <div className="mb-6 flex gap-0 border-b border-slate-800">
        {TABS.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                'flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors -mb-px',
                tab === t.id
                  ? 'border-emerald-500 text-emerald-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-600',
              )}
            >
              <Icon className="h-4 w-4" />
              <span className="hidden sm:inline">{t.label}</span>
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      {tab === 'charts'    && <ChartsView options={instrumentOptions} initialSymbol={initialSymbol} />}
      {tab === 'oi'        && <OIView />}
      {tab === 'orderflow' && <OrderFlowView options={instrumentOptions} initialSymbol={initialSymbol} />}
      {tab === 'profile'   && <MarketProfileView options={instrumentOptions} initialSymbol={initialSymbol} />}
      {tab === 'moneyflow' && <MoneyFlowView />}
    </div>
  );
}

export default function AnalyticsPage() {
  return (
    <Suspense fallback={null}>
      <AnalyticsPageInner />
    </Suspense>
  );
}

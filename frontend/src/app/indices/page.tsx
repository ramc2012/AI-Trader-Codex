'use client';

import { useState, useMemo, useCallback, useEffect } from 'react';
import Link from 'next/link';
import {
  TrendingUp,
  TrendingDown,
  Clock,
  Activity,
  RefreshCw,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { useWatchlistSummary, useHistoricalData } from '@/hooks/use-watchlist';
import { useAgentEvents } from '@/hooks/use-agent';
import { useIndicesWS } from '@/hooks/use-indices-ws';
import { formatINR, formatNumber } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import { APP_DISPLAY_NAME } from '@/lib/app-brand';
import CandlestickChart from '@/components/charts/candlestick-chart';
import { buildTradeMarkersFromEvents } from '@/lib/trade-markers';
import type { AgentEvent } from '@/types/api';

// ── Constants ─────────────────────────────────────────────────────────────────

const INDICES_META: Record<string, { displayName: string; slug: string; sector: string }> = {
  NIFTY:      { displayName: 'Nifty 50',     slug: 'nifty',      sector: 'Broad Market'  },
  BANKNIFTY:  { displayName: 'Bank Nifty',   slug: 'banknifty',  sector: 'Banking'       },
  FINNIFTY:   { displayName: 'Fin Nifty',    slug: 'finnifty',   sector: 'Financials'    },
  MIDCPNIFTY: { displayName: 'Midcap Nifty', slug: 'midcpnifty', sector: 'Midcap'        },
  SENSEX:     { displayName: 'BSE Sensex',   slug: 'sensex',     sector: 'Broad Market'  },
};

const TIMEFRAMES = [
  { label: '1W', days: 7,  resolution: 'D'  },
  { label: '1M', days: 30, resolution: 'D'  },
  { label: '3M', days: 90, resolution: 'D'  },
];

// ── Indicator helpers (stable — computed from historical data) ─────────────────

function calcEMA(values: number[], period: number): number[] {
  const k = 2 / (period + 1);
  const out: number[] = [];
  let ema = values[0];
  for (const v of values) {
    ema = v * k + ema * (1 - k);
    out.push(ema);
  }
  return out;
}

function calcRSI(closes: number[], period = 14): number {
  if (closes.length < period + 1) return 50;
  let gains = 0, losses = 0;
  for (let i = closes.length - period; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff > 0) gains += diff; else losses -= diff;
  }
  const rs = gains / (losses || 1);
  return 100 - 100 / (1 + rs);
}

function calcMACD(closes: number[]): { macd: number; signal: number; hist: number } {
  if (closes.length < 26) return { macd: 0, signal: 0, hist: 0 };
  const ema12 = calcEMA(closes, 12);
  const ema26 = calcEMA(closes, 26);
  const macdLine = ema12.map((v, i) => v - ema26[i]);
  const signalLine = calcEMA(macdLine.slice(-9), 9);
  const last = macdLine[macdLine.length - 1];
  const sig = signalLine[signalLine.length - 1];
  return { macd: last, signal: sig, hist: last - sig };
}

function calcATR(data: { high: number; low: number; close: number }[], period = 14): number {
  if (data.length < period + 1) return 0;
  const trs = data.slice(1).map((d, i) => {
    const prev = data[i].close;
    return Math.max(d.high - d.low, Math.abs(d.high - prev), Math.abs(d.low - prev));
  });
  return trs.slice(-period).reduce((s, v) => s + v, 0) / period;
}

// ── Sub-components ────────────────────────────────────────────────────────────

interface ChartWithIndicatorsProps {
  symbol: string;
  days: number;
  resolution: string;
  liveLtp?: number;   // overlay from WS — used for today's partial candle
  agentEvents?: AgentEvent[];
}

function ChartWithIndicators({
  symbol,
  days,
  resolution,
  liveLtp,
  agentEvents = [],
}: ChartWithIndicatorsProps) {
  const { data, isLoading, isFetching } = useHistoricalData(symbol, days, resolution);

  const { chartData, indicators } = useMemo(() => {
    if (!data?.data || data.data.length === 0) {
      return { chartData: [], indicators: null };
    }

    const ohlc = data.data;
    const closes = ohlc.map((d) => d.close);

    const rsi = calcRSI(closes);
    const { macd, signal, hist } = calcMACD(closes);
    const atr = calcATR(ohlc);

    return {
      chartData: ohlc.map((d) => ({
        time: Math.floor(new Date(d.timestamp).getTime() / 1000),
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
        volume: d.volume,
      })),
      indicators: { rsi, macd, signal, hist, atr },
    };
  }, [data]);

  // Patch the last candle with live LTP so the chart feels real-time
  const liveChartData = useMemo(() => {
    if (!liveLtp || chartData.length === 0) return chartData;
    const last = chartData[chartData.length - 1];
    const patched = {
      ...last,
      close: liveLtp,
      high: Math.max(last.high, liveLtp),
      low:  Math.min(last.low,  liveLtp),
    };
    return [...chartData.slice(0, -1), patched];
  }, [chartData, liveLtp]);
  const tradeMarkers = useMemo(() => {
    if (!liveChartData.length) return [];
    return buildTradeMarkersFromEvents(
      agentEvents,
      symbol,
      resolution,
      liveChartData[0].time,
      liveChartData[liveChartData.length - 1].time,
    );
  }, [agentEvents, liveChartData, symbol, resolution]);

  const rsiSignal =
    indicators && indicators.rsi > 70 ? 'overbought'
    : indicators && indicators.rsi < 30 ? 'oversold'
    : 'neutral';

  const macdSignal = indicators ? (indicators.macd > indicators.signal ? 'bullish' : 'bearish') : 'neutral';

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-600">
        <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
        Loading chart…
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-3">
      {/* Indicator pills */}
      <div className="flex flex-wrap items-center gap-3 text-xs">
        {indicators && (
          <>
            <span className="text-slate-500">RSI(14)</span>
            <span
              className={cn(
                'font-mono font-semibold',
                rsiSignal === 'overbought' ? 'text-red-400' :
                rsiSignal === 'oversold'   ? 'text-emerald-400' :
                'text-slate-300'
              )}
            >
              {indicators.rsi.toFixed(1)}
              <span className="ml-1 font-normal text-slate-500">
                ({rsiSignal === 'overbought' ? '↓ Overbought' : rsiSignal === 'oversold' ? '↑ Oversold' : '→ Neutral'})
              </span>
            </span>

            <span className="text-slate-700">|</span>

            <span className="text-slate-500">MACD</span>
            <span className={cn('font-mono font-semibold', macdSignal === 'bullish' ? 'text-emerald-400' : 'text-red-400')}>
              {indicators.macd.toFixed(2)}
              <span className="ml-1 font-normal text-slate-500">
                ({macdSignal === 'bullish' ? '↑ Bull' : '↓ Bear'})
              </span>
            </span>

            <span className="text-slate-700">|</span>

            <span className="text-slate-500">ATR(14)</span>
            <span className="font-mono font-semibold text-slate-300">{indicators.atr.toFixed(1)}</span>

            {isFetching && (
              <RefreshCw className="ml-auto h-3 w-3 animate-spin text-slate-600" />
            )}
          </>
        )}
      </div>

      {/* Chart */}
      <div className="min-h-0 flex-1">
        <CandlestickChart data={liveChartData} height={380} lockViewport tradeMarkers={tradeMarkers} />
      </div>
    </div>
  );
}

// ── Watchlist row ─────────────────────────────────────────────────────────────

interface WatchlistRowProps {
  name: string;
  isSelected: boolean;
  /** HTTP-polled baseline — used for OHLC, volume, OI */
  spot:    { ltp: number; change?: number; change_pct?: number; volume?: number } | null;
  futures: { ltp: number; oi?: number } | null;
  /** WS live price — overrides spot.ltp for display when available */
  liveLtp?: number;
  liveChangePct?: number;
  liveChange?: number;
  onClick: () => void;
}

function WatchlistRow({ name, isSelected, spot, futures, liveLtp, liveChangePct, liveChange, onClick }: WatchlistRowProps) {
  const meta = INDICES_META[name];

  // Prefer WS values, fall back to HTTP baseline
  const displayLtp       = liveLtp       ?? spot?.ltp ?? 0;
  const displayChangePct = liveChangePct ?? spot?.change_pct ?? 0;
  const displayChange    = liveChange    ?? spot?.change ?? 0;
  const isUp = displayChangePct >= 0;

  const flash = '';

  return (
    <tr
      onClick={onClick}
      className={cn(
        'cursor-pointer border-b border-slate-800/60 transition-colors',
        isSelected
          ? 'bg-emerald-500/5'
          : 'hover:bg-slate-800/40'
      )}
    >
      {/* Index name */}
      <td className="py-3 pl-4 pr-2">
        <div className="flex items-center gap-2">
          {isSelected && <div className="h-3 w-0.5 rounded-full bg-emerald-500" />}
          <div>
            <div className={cn('text-sm font-semibold', isSelected ? 'text-emerald-300' : 'text-slate-200')}>
              {meta?.displayName ?? name}
            </div>
            <div className="text-xs text-slate-600">{meta?.sector}</div>
          </div>
        </div>
      </td>

      {/* LTP — live from WS */}
      <td className={cn('px-3 py-3 text-right', flash)}>
        <span className="font-mono text-sm font-semibold text-slate-100">
          {displayLtp ? formatINR(displayLtp) : '—'}
        </span>
      </td>

      {/* Change */}
      <td className="px-3 py-3 text-right">
        <div className={cn('text-xs font-medium', isUp ? 'text-emerald-400' : 'text-red-400')}>
          {displayChangePct !== 0 ? (
            <>
              {isUp ? '▲' : '▼'} {Math.abs(displayChangePct).toFixed(2)}%
            </>
          ) : '—'}
        </div>
        <div className={cn('font-mono text-xs', isUp ? 'text-emerald-500/70' : 'text-red-500/70')}>
          {displayChange !== 0 ? `${isUp ? '+' : ''}${displayChange.toFixed(1)}` : ''}
        </div>
      </td>

      {/* Volume — from HTTP (not in every tick) */}
      <td className="px-3 py-3 text-right">
        <span className="font-mono text-xs text-slate-400">
          {spot?.volume ? formatNumber(spot.volume) : '—'}
        </span>
      </td>

      {/* Futures */}
      <td className="px-3 py-3 text-right">
        <span className="font-mono text-xs text-slate-400">
          {futures?.ltp ? formatINR(futures.ltp) : '—'}
        </span>
      </td>

      {/* OI */}
      <td className="py-3 pl-3 pr-4 text-right">
        <span className="font-mono text-xs text-slate-400">
          {futures?.oi ? formatNumber(futures.oi) : '—'}
        </span>
      </td>
    </tr>
  );
}

// ── IST clock (isolated — only this sub-tree re-renders every second) ─────────

function ISTClock() {
  const fmt = () =>
    new Date().toLocaleTimeString('en-IN', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false, timeZone: 'Asia/Kolkata',
    });

  const [time, setTime] = useState(fmt);

  useEffect(() => {
    const id = setInterval(() => setTime(fmt()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex items-center gap-2 font-mono text-sm text-slate-300">
      <Clock className="h-4 w-4" />
      IST {time}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const TIMEFRAME_DEFAULT = TIMEFRAMES[0];

export default function IndicesPage() {
  const [selectedIndex, setSelectedIndex] = useState('NIFTY');
  const [tf, setTf] = useState(TIMEFRAME_DEFAULT);

  // HTTP baseline — refreshes every 15 s for OHLC/OI context (not LTP)
  const { data: summary, isLoading } = useWatchlistSummary();
  const { data: agentEvents } = useAgentEvents(300, 3000);

  // WebSocket — real-time LTP for all indices, reconnects every 3 s on drop
  const { prices: wsPrices, isConnected: wsConnected } = useIndicesWS(true);

  const selectedMeta       = INDICES_META[selectedIndex] ?? INDICES_META.NIFTY;
  const selectedIndexData  = summary?.indices?.find((i) => i.name === selectedIndex);
  const spotQuote          = selectedIndexData?.spot    ?? null;
  const futuresQuote       = selectedIndexData?.futures ?? null;

  // For the detail panel: prefer WS LTP, fall back to HTTP
  const liveLtpForSelected  = wsPrices[selectedIndex]?.ltp ?? spotQuote?.ltp ?? 0;
  const liveChangePctSelected =
    wsPrices[selectedIndex]?.change_pct ?? spotQuote?.change_pct ?? 0;

  const spotLtpForPremium = liveLtpForSelected ?? 0;
  const futuresLtpForPremium = futuresQuote?.ltp ?? 0;
  const premium =
    futuresLtpForPremium > 0 && spotLtpForPremium > 0 ? futuresLtpForPremium - spotLtpForPremium : 0;
  const premiumPct =
    spotLtpForPremium > 0 && premium !== 0 ? (premium / spotLtpForPremium) * 100 : 0;

  // Stats bar — derived from HTTP summary (gainers/losers based on day change)
  const { gainers, losers, avgChange } = useMemo(() => {
    const indices = summary?.indices ?? [];
    const g = indices.filter((i) => (i.spot?.change_pct ?? 0) > 0).length;
    const l = indices.filter((i) => (i.spot?.change_pct ?? 0) < 0).length;
    const avg = indices.length > 0
      ? indices.reduce((s, i) => s + (i.spot?.change_pct ?? 0), 0) / indices.length
      : 0;
    return { gainers: g, losers: l, avgChange: avg };
  }, [summary?.indices]);

  const handleSelectIndex = useCallback((name: string) => setSelectedIndex(name), []);

  return (
    <div className="flex h-screen flex-col bg-slate-950 text-slate-100">

      {/* ── Top Nav ─────────────────────────────────────────────────────────── */}
      <header className="flex items-center justify-between border-b border-slate-800 bg-slate-900 px-5 py-2.5">
        <div className="flex items-center gap-5">
          <h1 className="text-base font-bold tracking-tight text-slate-100">{APP_DISPLAY_NAME}</h1>
          <nav className="flex gap-0.5">
            {[
              { label: 'Indices',    href: '/indices',    active: true },
              { label: 'Positions',  href: '/positions'               },
              { label: 'Strategies', href: '/strategies'              },
              { label: 'Risk',       href: '/risk'                    },
              { label: 'Monitoring', href: '/monitoring'              },
              { label: 'Settings',   href: '/settings'                },
            ].map((t) => (
              <Link
                key={t.href}
                href={t.href}
                className={cn(
                  'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                  t.active
                    ? 'bg-emerald-500/10 text-emerald-400'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                )}
              >
                {t.label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          {/* WS connectivity badge */}
          <div className={cn(
            'flex items-center gap-1.5 text-xs',
            wsConnected ? 'text-emerald-400' : 'text-amber-400'
          )}>
            {wsConnected
              ? <Wifi className="h-3.5 w-3.5" />
              : <WifiOff className="h-3.5 w-3.5 animate-pulse" />}
            {wsConnected ? 'Live' : 'Reconnecting…'}
          </div>

          <div className="h-3.5 w-px bg-slate-700" />

          <div className="rounded bg-yellow-500/10 px-2 py-1 text-xs font-medium text-yellow-500">
            PAPER
          </div>
          <ISTClock />
        </div>
      </header>

      {/* ── Stats bar ───────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-5 gap-px border-b border-slate-800 bg-slate-800">
        {[
          { label: 'Indices',  value: summary?.indices?.length ?? 5,                                            color: 'text-slate-100' },
          { label: 'Gainers',  value: gainers,                                                                   color: 'text-emerald-400' },
          { label: 'Losers',   value: losers,                                                                    color: 'text-red-400'    },
          { label: 'Avg Chg',  value: `${avgChange >= 0 ? '+' : ''}${avgChange.toFixed(2)}%`,                   color: avgChange >= 0 ? 'text-emerald-400' : 'text-red-400' },
          { label: 'Market',   value: 'OPEN',                                                                    color: 'text-emerald-400' },
        ].map((s) => (
          <div key={s.label} className="bg-slate-950 px-4 py-2.5">
            <div className="text-xs text-slate-500">{s.label}</div>
            <div className={cn('text-base font-semibold tabular-nums', s.color)}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* ── Main layout: left watchlist table | right detail panel ──────────── */}
      <div className="flex min-h-0 flex-1 overflow-hidden">

        {/* Left: watchlist table */}
        <div className="flex w-72 flex-shrink-0 flex-col border-r border-slate-800 bg-slate-900">
          <div className="flex items-center justify-between px-4 py-2 text-xs font-medium uppercase tracking-wider text-slate-500">
            <span>Watchlist</span>
            {isLoading && <RefreshCw className="h-3 w-3 animate-spin" />}
          </div>

          <div className="flex-1 overflow-y-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-800/60 text-right text-xs text-slate-600">
                  <th className="pb-2 pl-4 pr-2 text-left font-normal">Name</th>
                  <th className="px-3 pb-2 font-normal">LTP</th>
                  <th className="px-3 pb-2 font-normal">Chg %</th>
                  <th className="px-3 pb-2 font-normal">Vol</th>
                  <th className="px-3 pb-2 font-normal">Fut</th>
                  <th className="py-2 pl-3 pr-4 font-normal">OI</th>
                </tr>
              </thead>
              <tbody>
                {isLoading
                  ? Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i} className="border-b border-slate-800/60">
                      {Array.from({ length: 6 }).map((_, j) => (
                        <td key={j} className="px-3 py-3">
                          <div className="h-3 animate-pulse rounded bg-slate-800" />
                        </td>
                      ))}
                    </tr>
                  ))
                  : Object.keys(INDICES_META).map((name) => {
                      const idxData = summary?.indices?.find((i) => i.name === name);
                      const ws = wsPrices[name];
                      return (
                        <WatchlistRow
                          key={name}
                          name={name}
                          isSelected={selectedIndex === name}
                          spot={idxData?.spot ?? null}
                          futures={idxData?.futures ?? null}
                          liveLtp={ws?.ltp}
                          liveChangePct={ws?.change_pct}
                          liveChange={ws?.change}
                          onClick={() => handleSelectIndex(name)}
                        />
                      );
                    })}
              </tbody>
            </table>
          </div>

          {/* Options workspace shortcut */}
          <div className="border-t border-slate-800 p-3">
            <Link
              href={`/indices/${selectedMeta.slug}/options`}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-emerald-600/20 px-3 py-2 text-xs font-semibold text-emerald-400 transition-colors hover:bg-emerald-600/30"
            >
              <Activity className="h-3.5 w-3.5" />
              {selectedMeta.displayName} Options
            </Link>
          </div>
        </div>

        {/* Right: detail panel */}
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">

          {/* Index header */}
          <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
            <div className="flex items-center gap-4">
              <div>
                <h2 className="text-lg font-bold text-slate-100">{selectedMeta.displayName}</h2>
                <p className="text-xs text-slate-500">{selectedMeta.sector}</p>
              </div>

              {liveLtpForSelected > 0 && (
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-2xl font-bold text-slate-100">
                    {formatINR(liveLtpForSelected)}
                  </span>
                  <span
                    className={cn(
                      'flex items-center gap-1 text-sm font-medium',
                      liveChangePctSelected >= 0 ? 'text-emerald-400' : 'text-red-400'
                    )}
                  >
                    {liveChangePctSelected >= 0
                      ? <TrendingUp className="h-4 w-4" />
                      : <TrendingDown className="h-4 w-4" />}
                    {liveChangePctSelected >= 0 ? '+' : ''}
                    {liveChangePctSelected.toFixed(2)}%
                  </span>
                </div>
              )}
            </div>

            <div className="flex items-center gap-3">
              {/* Timeframe selector */}
              <div className="flex gap-1 rounded-lg border border-slate-700 bg-slate-800 p-0.5">
                {TIMEFRAMES.map((t) => (
                  <button
                    key={t.label}
                    onClick={() => setTf(t)}
                    className={cn(
                      'rounded-md px-3 py-1 text-xs font-medium transition-colors',
                      tf.label === t.label
                        ? 'bg-slate-700 text-slate-100'
                        : 'text-slate-400 hover:text-slate-200'
                    )}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              <Link
                href={`/indices/${selectedMeta.slug}/options`}
                className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-emerald-500"
              >
                Options Workspace →
              </Link>
            </div>
          </div>

          {/* Body: chart + info cards */}
          <div className="flex min-h-0 flex-1 overflow-hidden">

            {/* Chart (takes most of the space) */}
            <div className="flex min-w-0 flex-1 flex-col p-4">
              {selectedIndexData?.spot?.symbol ? (
                <ChartWithIndicators
                  symbol={selectedIndexData.spot.symbol}
                  days={tf.days}
                  resolution={tf.resolution}
                  liveLtp={wsPrices[selectedIndex]?.ltp}
                  agentEvents={agentEvents ?? []}
                />
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-slate-600">
                  {isLoading ? <RefreshCw className="h-4 w-4 animate-spin" /> : 'No data'}
                </div>
              )}
            </div>

            {/* Right sidebar info cards */}
            <div className="flex w-56 flex-shrink-0 flex-col gap-3 overflow-y-auto border-l border-slate-800 p-3">

              {/* OHLC */}
              <InfoCard title="SPOT OHLC">
                {spotQuote ? (
                  <div className="grid grid-cols-2 gap-x-2 gap-y-1 font-mono text-xs">
                    {(['open','high','low','close'] as const).map((k) => {
                      const spotNum = spotQuote as unknown as Record<string, number>;
                      const val = spotNum[k];
                      return (
                        <div key={k} className="flex justify-between gap-1">
                          <span className="text-slate-500 uppercase">{k[0]}</span>
                          <span className="text-slate-300">
                            {val > 0
                              ? formatINR(val)
                              : k === 'close' && liveLtpForSelected > 0
                                ? formatINR(liveLtpForSelected)
                                : '—'}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : <Placeholder />}
              </InfoCard>

              {/* Futures */}
              <InfoCard title="FUTURES">
                <div className="space-y-1.5 text-xs">
                  <Row label="LTP"     value={futuresQuote?.ltp ? formatINR(futuresQuote.ltp) : '—'} />
                  <Row
                    label="Premium"
                    value={premium !== 0 ? `${premium > 0 ? '+' : ''}${formatINR(premium)}` : '—'}
                    valueClass={premium > 0 ? 'text-emerald-400' : premium < 0 ? 'text-red-400' : 'text-slate-400'}
                  />
                  <Row
                    label="Prem %"
                    value={premiumPct !== 0 ? `${premiumPct.toFixed(3)}%` : '—'}
                    valueClass={premiumPct > 0 ? 'text-emerald-400' : premiumPct < 0 ? 'text-red-400' : 'text-slate-400'}
                  />
                </div>
              </InfoCard>

              {/* Volume / OI */}
              <InfoCard title="VOLUME & OI">
                <div className="space-y-1.5 text-xs">
                  <Row label="Volume"  value={spotQuote?.volume   ? formatNumber(spotQuote.volume)   : '—'} />
                  <Row label="Spot OI" value="—" />
                  <Row label="Fut OI"  value={futuresQuote?.oi    ? formatNumber(futuresQuote.oi)    : '—'} />
                </div>
              </InfoCard>

              {/* Market Depth */}
              <InfoCard title="DEPTH">
                <div className="space-y-1.5 text-xs">
                  <Row
                    label="Bid"
                    value={
                      (spotQuote?.bid ?? 0) > 0
                        ? formatINR(spotQuote!.bid!)
                        : wsPrices[selectedIndex]?.bid
                          ? formatINR(wsPrices[selectedIndex].bid!)
                          : '—'
                    }
                    valueClass="text-emerald-400"
                  />
                  <Row label="Spread" value="—" />
                  <Row
                    label="Ask"
                    value={
                      (spotQuote?.ask ?? 0) > 0
                        ? formatINR(spotQuote!.ask!)
                        : wsPrices[selectedIndex]?.ask
                          ? formatINR(wsPrices[selectedIndex].ask!)
                          : '—'
                    }
                    valueClass="text-red-400"
                  />
                </div>
              </InfoCard>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Tiny helpers ──────────────────────────────────────────────────────────────

function InfoCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">{title}</div>
      {children}
    </div>
  );
}

function Row({
  label,
  value,
  valueClass = 'text-slate-300',
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-slate-500">{label}</span>
      <span className={cn('font-mono', valueClass)}>{value}</span>
    </div>
  );
}

function Placeholder() {
  return <div className="h-4 animate-pulse rounded bg-slate-800" />;
}

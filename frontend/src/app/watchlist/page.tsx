'use client';

/**
 * Watchlist — live market data table.
 *
 * - WebSocket for real-time LTP via /ws/ticks/all
 * - /watchlist/quote/{symbol} per row for full OHLC (10 s)
 * - /watchlist/summary for futures LTP + OI
 * - Click any row → right-side chart drawer (candlestick + RSI/MACD)
 * - Data Sync panel collapsed by default
 */

import { useState, useCallback, useMemo, useId } from 'react';
import Link from 'next/link';
import {
  TrendingUp, TrendingDown, BarChart3, Activity,
  X, RefreshCw, Wifi, WifiOff, Download,
  ChevronDown, ChevronUp, ExternalLink,
} from 'lucide-react';
import { AreaChart, Area, ResponsiveContainer } from 'recharts';
import {
  useWatchlistSummary,
  useIndexQuote,
  useHistoricalData,
  useCollectionStatus,
  useStartCollection,
  useGlobalContinuousWatchlist,
  useWatchlistUniverse,
} from '@/hooks/use-watchlist';
import { useAgentEvents } from '@/hooks/use-agent';
import { useIndicesWS } from '@/hooks/use-indices-ws';
import { formatINR, formatNumber } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import CandlestickChart from '@/components/charts/candlestick-chart';
import FractalWatchlistBoard from '@/components/charts/fractal-watchlist-board';
import { buildTradeMarkersFromEvents } from '@/lib/trade-markers';
import { buildInstrumentOptions } from '@/lib/instrument-universe';
import { useAuth } from '@/contexts/auth-context';
import type { AgentEvent } from '@/types/api';

// ── Constants ─────────────────────────────────────────────────────────────────

const INDICES_ORDER = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX'];

const META: Record<string, { display: string; slug: string; sector: string; symbol: string }> = {
  NIFTY:      { display: 'Nifty 50',     slug: 'nifty',      sector: 'Broad Market', symbol: 'NSE:NIFTY50-INDEX'       },
  BANKNIFTY:  { display: 'Bank Nifty',   slug: 'banknifty',  sector: 'Banking',      symbol: 'NSE:NIFTYBANK-INDEX'     },
  FINNIFTY:   { display: 'Fin Nifty',    slug: 'finnifty',   sector: 'Financials',   symbol: 'NSE:FINNIFTY-INDEX'      },
  MIDCPNIFTY: { display: 'Midcap Nifty', slug: 'midcpnifty', sector: 'Midcap',       symbol: 'NSE:NIFTYMIDCAP50-INDEX' },
  SENSEX:     { display: 'Sensex',       slug: 'sensex',     sector: 'Broad Market', symbol: 'BSE:SENSEX-INDEX'        },
};
const SYMBOL_TO_NAME = Object.fromEntries(
  Object.entries(META).map(([name, meta]) => [meta.symbol, name]),
) as Record<string, string>;

const TF_OPTIONS = [
  { label: '1W', days: 7,  res: 'D' },
  { label: '1M', days: 30, res: 'D' },
  { label: '3M', days: 90, res: 'D' },
];

// ── Indicator helpers ─────────────────────────────────────────────────────────

function calcEMA(v: number[], p: number): number[] {
  const k = 2 / (p + 1);
  let ema = v[0];
  return v.map((x) => { ema = x * k + ema * (1 - k); return ema; });
}

function calcRSI(c: number[], p = 14): number {
  if (c.length < p + 1) return 50;
  let g = 0, l = 0;
  for (let i = c.length - p; i < c.length; i++) {
    const d = c[i] - c[i - 1];
    if (d > 0) g += d; else l -= d;
  }
  return 100 - 100 / (1 + g / (l || 1));
}

function calcMACD(c: number[]): { macd: number; signal: number } {
  if (c.length < 26) return { macd: 0, signal: 0 };
  const e12 = calcEMA(c, 12);
  const e26 = calcEMA(c, 26);
  const line = e12.map((v, i) => v - e26[i]);
  const sig = calcEMA(line.slice(-9), 9);
  return { macd: line[line.length - 1], signal: sig[sig.length - 1] };
}

function formatUSD(v: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(v);
}

// ── Spark chart ───────────────────────────────────────────────────────────────

function SparkChart({ symbol }: { symbol: string }) {
  const { data } = useHistoricalData(symbol, 30, 'D', !!symbol);
  const closes = useMemo(
    () => (data?.data ?? []).slice(-30).map((d) => d.close),
    [data],
  );
  const isUp    = closes.length >= 2 ? closes[closes.length - 1] >= closes[0] : true;
  const color   = isUp ? '#10b981' : '#ef4444';
  const rows    = closes.map((close) => ({ close }));
  const gradId  = `sg-${useId().replace(/:/g, '')}`;

  if (closes.length < 2) return <div className="h-10 w-24 rounded bg-slate-800/30" />;

  return (
    <div className="h-10 w-24">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={color} stopOpacity={0.4} />
              <stop offset="95%" stopColor={color} stopOpacity={0}   />
            </linearGradient>
          </defs>
          <Area
            type="monotone" dataKey="close"
            stroke={color} strokeWidth={1.5}
            fill={`url(#${gradId})`}
            dot={false} isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Chart drawer ──────────────────────────────────────────────────────────────

interface DrawerProps {
  name: string;
  symbol: string;    // always a valid Fyers symbol from META
  ltp: number;
  changePct: number;
  agentEvents: AgentEvent[];
  onClose: () => void;
}

function ChartDrawer({ name, symbol, ltp, changePct, agentEvents, onClose }: DrawerProps) {
  const [tf, setTf]           = useState(TF_OPTIONS[1]);
  const { data, isLoading }   = useHistoricalData(symbol, tf.days, tf.res, true);
  const meta                  = META[name];
  const isUp                  = changePct >= 0;

  const { chartData, rsi, macdVal, macdSig } = useMemo(() => {
    if (!data?.data?.length) return { chartData: [], rsi: 50, macdVal: 0, macdSig: 0 };
    const ohlc   = data.data;
    const closes = ohlc.map((d) => d.close);
    const { macd, signal } = calcMACD(closes);
    return {
      chartData: ohlc.map((d) => ({
        time: Math.floor(new Date(d.timestamp).getTime() / 1000),
        open: d.open, high: d.high, low: d.low, close: d.close, volume: d.volume,
      })),
      rsi:     calcRSI(closes),
      macdVal: macd,
      macdSig: signal,
    };
  }, [data]);

  // Patch last candle with live WS price so chart is truly real-time
  const liveData = useMemo(() => {
    if (!ltp || chartData.length === 0) return chartData;
    const last = chartData[chartData.length - 1];
    return [...chartData.slice(0, -1), {
      ...last,
      close: ltp,
      high: Math.max(last.high, ltp),
      low:  Math.min(last.low,  ltp),
    }];
  }, [chartData, ltp]);

  const tradeMarkers = useMemo(() => {
    if (!liveData.length) return [];
    return buildTradeMarkersFromEvents(
      agentEvents,
      symbol,
      tf.res,
      liveData[0].time,
      liveData[liveData.length - 1].time,
    );
  }, [agentEvents, liveData, symbol, tf.res]);

  const rsiColor = rsi > 70 ? 'text-red-400' : rsi < 30 ? 'text-emerald-400' : 'text-slate-300';
  const rsiLabel = rsi > 70 ? 'Overbought'   : rsi < 30 ? 'Oversold'          : 'Neutral';

  return (
    <div className="flex h-full flex-col bg-slate-950">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <div className="flex items-center gap-3">
          <div>
            <div className="text-sm font-bold text-slate-100">{meta?.display ?? name}</div>
            <div className="font-mono text-[11px] text-slate-500">{symbol}</div>
          </div>
          {ltp > 0 && (
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono text-xl font-bold text-slate-100">{formatINR(ltp)}</span>
              <span className={cn('text-xs font-semibold', isUp ? 'text-emerald-400' : 'text-red-400')}>
                {isUp ? '▲' : '▼'} {Math.abs(changePct).toFixed(2)}%
              </span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/indices"
            className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          >
            <ExternalLink className="h-3 w-3" /> Full View
          </Link>
          {meta && (
            <Link
              href={`/indices/${meta.slug}/options`}
              className="rounded-md bg-emerald-600/20 px-2 py-1 text-xs font-semibold text-emerald-400 hover:bg-emerald-600/30"
            >
              Options
            </Link>
          )}
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Timeframe + indicators */}
      <div className="flex items-center justify-between border-b border-slate-800/60 px-4 py-2">
        <div className="flex gap-0.5 rounded-lg border border-slate-700 bg-slate-800 p-0.5">
          {TF_OPTIONS.map((t) => (
            <button
              key={t.label}
              onClick={() => setTf(t)}
              className={cn(
                'rounded-md px-3 py-1 text-xs font-medium transition-colors',
                tf.label === t.label ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200',
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">RSI</span>
          <span className={cn('font-mono font-semibold', rsiColor)}>{rsi.toFixed(1)}</span>
          <span className="text-[10px] text-slate-600">({rsiLabel})</span>
          <span className="mx-1 text-slate-700">|</span>
          <span className="text-slate-500">MACD</span>
          <span className={cn('font-mono font-semibold', macdVal > macdSig ? 'text-emerald-400' : 'text-red-400')}>
            {macdVal.toFixed(1)}
          </span>
        </div>
      </div>

      {/* Chart body */}
      <div className="flex-1 overflow-hidden p-4">
        {isLoading ? (
          <div className="flex h-full items-center justify-center gap-2">
            <RefreshCw className="h-5 w-5 animate-spin text-slate-600" />
            <span className="text-sm text-slate-500">Loading chart…</span>
          </div>
        ) : liveData.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2">
            <BarChart3 className="h-8 w-8 text-slate-700" />
            <p className="text-sm text-slate-500">No historical data</p>
            <p className="text-xs text-slate-600">Use Data Sync below to collect</p>
          </div>
        ) : (
          <CandlestickChart
            data={liveData}
            height={320}
            lockViewport
            tradeMarkers={tradeMarkers}
          />
        )}
      </div>
    </div>
  );
}

// ── Table row — each row fetches its own full OHLC quote ──────────────────────

import type { MarketData } from '@/hooks/use-watchlist';

interface IndexRowProps {
  name: string;
  isSelected: boolean;
  onClick: () => void;
  spotData?: MarketData;
  futuresData?: MarketData;
  wsLtp?: number;
  wsChange?: number;
  wsChangePct?: number;
  isSummaryLoading?: boolean;
}

function IndexRow({
  name,
  isSelected,
  onClick,
  spotData,
  futuresData,
  wsLtp,
  wsChange,
  wsChangePct,
  isSummaryLoading,
}: IndexRowProps) {
  const meta = META[name];

  // Prefer WS for LTP/change (real-time), fall back to REST summary
  const ltp       = wsLtp       ?? spotData?.ltp       ?? 0;
  const change    = wsChange    ?? spotData?.change     ?? 0;
  const changePct = wsChangePct ?? spotData?.change_pct ?? 0;

  // Static OHLC from summary
  const open      = spotData?.open     ?? 0;
  const high      = spotData?.high     ?? 0;
  const low       = spotData?.low      ?? 0;
  const volume    = spotData?.volume   ?? 0;

  const futLtp    = futuresData?.ltp   ?? 0;
  const futOI     = futuresData?.oi    ?? 0;

  const isUp      = changePct >= 0;
  const premium   = futLtp > 0 && ltp > 0 ? futLtp - ltp : 0;

  return (
    <tr
      onClick={onClick}
      className={cn(
        'group cursor-pointer border-b border-slate-800/50 transition-colors',
        isSelected ? 'bg-emerald-500/5' : 'hover:bg-slate-800/30',
      )}
    >
      {/* Index name */}
      <td className="py-3 pl-4 pr-3">
        <div className="flex items-center gap-2">
          {isSelected && <div className="h-3.5 w-0.5 flex-shrink-0 rounded-full bg-emerald-500" />}
          <div>
            <div className={cn('text-sm font-semibold', isSelected ? 'text-emerald-300' : 'text-slate-200')}>
              {meta.display}
            </div>
            <div className="text-[11px] text-slate-500">{meta.sector}</div>
          </div>
        </div>
      </td>

      {/* LTP — flashes on tick */}
      <td className="px-3 py-3 text-right tabular-nums">
        <span className="font-mono text-sm font-semibold text-slate-100">
          {ltp > 0 ? formatINR(ltp) : '—'}
        </span>
      </td>

      {/* Change */}
      <td className="px-3 py-3 text-right">
        <span className={cn('font-mono text-xs', isUp ? 'text-emerald-400' : 'text-red-400')}>
          {change !== 0 ? `${isUp ? '+' : ''}${change.toFixed(1)}` : '—'}
        </span>
      </td>

      {/* Chg% badge */}
      <td className="px-3 py-3 text-right">
        <span className={cn(
          'inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs font-semibold',
          isUp ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400',
        )}>
          {isUp ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
          {Math.abs(changePct).toFixed(2)}%
        </span>
      </td>

      {/* Open */}
      <td className="px-3 py-3 text-right">
        <span className="font-mono text-xs text-slate-400">
          {open > 0 ? formatINR(open) : isSummaryLoading ? <RefreshCw className="inline h-3 w-3 animate-spin opacity-40" /> : '—'}
        </span>
      </td>

      {/* High */}
      <td className="px-3 py-3 text-right">
        <span className="font-mono text-xs text-emerald-500/80">
          {high > 0 ? formatINR(high) : '—'}
        </span>
      </td>

      {/* Low */}
      <td className="px-3 py-3 text-right">
        <span className="font-mono text-xs text-red-500/80">
          {low > 0 ? formatINR(low) : '—'}
        </span>
      </td>

      {/* Volume */}
      <td className="px-3 py-3 text-right">
        <span className="font-mono text-xs text-slate-400">
          {volume > 0 ? formatNumber(volume) : '—'}
        </span>
      </td>

      {/* Futures LTP + premium */}
      <td className="px-3 py-3 text-right">
        <div className="font-mono text-xs text-slate-300">
          {futLtp > 0 ? formatINR(futLtp) : '—'}
        </div>
        {premium !== 0 && (
          <div className={cn('text-[10px]', premium > 0 ? 'text-emerald-500/70' : 'text-red-500/70')}>
            {premium > 0 ? '+' : ''}{premium.toFixed(1)}
          </div>
        )}
      </td>

      {/* Futures OI */}
      <td className="px-3 py-3 text-right">
        <span className="font-mono text-xs text-slate-400">
          {futOI > 0 ? formatNumber(futOI) : '—'}
        </span>
      </td>

      {/* 30-day spark */}
      <td className="px-3 py-3">
        <SparkChart symbol={meta.symbol} />
      </td>

      {/* Hover actions */}
      <td className="py-3 pl-3 pr-4">
        <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
          <button
            onClick={(e) => { e.stopPropagation(); onClick(); }}
            className="rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
            title="Open chart"
          >
            <BarChart3 className="h-3.5 w-3.5" />
          </button>
          <Link
            href={`/indices/${meta.slug}/options`}
            onClick={(e) => e.stopPropagation()}
            className="rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
            title="Options workspace"
          >
            <Activity className="h-3.5 w-3.5" />
          </Link>
        </div>
      </td>
    </tr>
  );
}

// ── Data-sync panel (collapsed) ───────────────────────────────────────────────

function DataSyncPanel() {
  const { isAuthenticated }   = useAuth();
  const [open, setOpen]       = useState(false);
  const [sym, setSym]         = useState('NSE:NIFTY50-INDEX');
  const [tf, setTf]           = useState('D');
  const [days, setDays]       = useState(90);
  const { data: universe }    = useWatchlistUniverse();
  const instrumentOptions     = useMemo(() => buildInstrumentOptions(universe), [universe]);
  const { data: statuses }    = useCollectionStatus();
  const startCol              = useStartCollection();
  const active                = statuses?.find((s) => s.status === 'collecting');

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-xs font-medium text-slate-400 hover:text-slate-200"
      >
        <span className="flex items-center gap-2">
          <Download className="h-3.5 w-3.5" />
          Data Sync
          {active && (
            <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] text-emerald-400">
              Collecting…
            </span>
          )}
        </span>
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>

      {open && (
        <div className="border-t border-slate-800 px-4 pb-4 pt-3">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="mb-1 block text-xs text-slate-500">Symbol</label>
              <select
                value={sym}
                onChange={(e) => setSym(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-200 focus:border-emerald-500 focus:outline-none"
              >
                {instrumentOptions.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">Timeframe</label>
              <div className="flex gap-1">
                {['1', '5', '15', '60', 'D', 'W'].map((t) => (
                  <button
                    key={t}
                    onClick={() => setTf(t)}
                    className={cn(
                      'rounded px-2 py-1 text-xs font-medium transition-colors',
                      tf === t ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700',
                    )}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">Days</label>
              <input
                type="number" min={1} max={730} value={days}
                onChange={(e) => setDays(Math.max(1, Math.min(730, +e.target.value || 90)))}
                className="w-20 rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-xs text-slate-200 focus:border-emerald-500 focus:outline-none"
              />
            </div>
            <button
              onClick={() => startCol.mutate({ symbol: sym, timeframe: tf, days_back: days })}
              disabled={!isAuthenticated || startCol.isPending}
              className="flex items-center gap-2 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
            >
              {startCol.isPending
                ? <RefreshCw className="h-3 w-3 animate-spin" />
                : <Download className="h-3 w-3" />}
              Collect
            </button>
          </div>

          {active && (
            <div className="mt-3">
              <div className="mb-1 flex justify-between text-xs text-slate-400">
                <span>{active.symbol}</span>
                <span className="text-emerald-400">{active.progress.toFixed(0)}%</span>
              </div>
              <div className="h-1 w-full rounded-full bg-slate-700">
                <div
                  className="h-1 rounded-full bg-emerald-500 transition-all"
                  style={{ width: `${active.progress}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function GlobalEvaluationPanel() {
  const { data, isLoading, isFetching } = useGlobalContinuousWatchlist(true);
  const usOptions = data?.us_options ?? [];
  const crypto = data?.crypto_top10 ?? [];

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2.5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Global Evaluation Feed
          </p>
          <p className="text-[11px] text-slate-500">
            US options focus + top 10 crypto for continuous system validation
          </p>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-slate-500">
          {isFetching && <RefreshCw className="h-3 w-3 animate-spin" />}
          <span>{data?.timestamp ? new Date(data.timestamp).toLocaleTimeString('en-IN') : '—'}</span>
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-2">
          <div className="h-32 animate-pulse rounded-lg bg-slate-800/50" />
          <div className="h-32 animate-pulse rounded-lg bg-slate-800/50" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-2">
          <div className="overflow-hidden rounded-lg border border-slate-800">
            <div className="border-b border-slate-800 bg-slate-900/70 px-3 py-2 text-xs font-semibold text-slate-300">
              US Option Underlyings (ATM)
            </div>
            <div className="max-h-56 overflow-auto">
              <table className="w-full min-w-[460px] text-xs">
                <thead className="sticky top-0 bg-slate-900 text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left">Symbol</th>
                    <th className="px-3 py-2 text-right">Spot</th>
                    <th className="px-3 py-2 text-right">ATM Strike</th>
                    <th className="px-3 py-2 text-right">Call</th>
                    <th className="px-3 py-2 text-right">Put</th>
                  </tr>
                </thead>
                <tbody>
                  {usOptions.map((row) => (
                    <tr key={row.symbol} className="border-t border-slate-800/70">
                      <td className="px-3 py-2">
                        <div className="font-semibold text-slate-200">{row.symbol}</div>
                        <div className="text-[10px] text-slate-500">{row.expiry ?? '—'}</div>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-slate-300">
                        {row.spot ? formatUSD(row.spot) : '—'}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-slate-300">
                        {row.atm_strike ? row.atm_strike.toFixed(2) : '—'}
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
                    <tr>
                      <td colSpan={5} className="px-3 py-4 text-center text-slate-500">
                        US options feed unavailable
                      </td>
                    </tr>
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
              <table className="w-full min-w-[420px] text-xs">
                <thead className="sticky top-0 bg-slate-900 text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left">Asset</th>
                    <th className="px-3 py-2 text-right">Price</th>
                    <th className="px-3 py-2 text-right">24h %</th>
                    <th className="px-3 py-2 text-right">Mkt Cap</th>
                  </tr>
                </thead>
                <tbody>
                  {crypto.map((row) => {
                    const up = row.change_pct_24h >= 0;
                    return (
                      <tr key={row.symbol} className="border-t border-slate-800/70">
                        <td className="px-3 py-2">
                          <div className="font-semibold text-slate-200">{row.symbol}</div>
                          <div className="text-[10px] text-slate-500">{row.name}</div>
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-slate-300">
                          {formatUSD(row.price_usd)}
                        </td>
                        <td className={cn(
                          'px-3 py-2 text-right font-mono',
                          up ? 'text-emerald-400' : 'text-red-400',
                        )}>
                          {up ? '+' : ''}{row.change_pct_24h.toFixed(2)}%
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-slate-400">
                          {formatUSD(row.market_cap)}
                        </td>
                      </tr>
                    );
                  })}
                  {!crypto.length && (
                    <tr>
                      <td colSpan={4} className="px-3 py-4 text-center text-slate-500">
                        Crypto feed unavailable
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WatchlistPage() {
  const [selectedName, setSelectedName] = useState<string | null>(null);

  // Summary provides futures LTP + OI only (spot OHLC is incomplete there)
  const { data: summary, isLoading } = useWatchlistSummary();
  const { data: agentEvents } = useAgentEvents(300, 3000);

  // Real-time LTP via WebSocket
  const {
    prices: ws,
    isConnected: wsOk,
    lastTickAt,
    tickCount,
  } = useIndicesWS(true);

  const handleSelect  = useCallback((name: string) => setSelectedName((p) => (p === name ? null : name)), []);
  const handleSelectSymbol = useCallback((symbol: string) => {
    const name = SYMBOL_TO_NAME[symbol];
    if (!name) return;
    setSelectedName((prev) => (prev === name ? null : name));
  }, []);
  const closeDrawer   = useCallback(() => setSelectedName(null), []);

  // Baseline data from summary (spot + futures)
  const baselineData = useMemo(() => {
    const out: Record<string, { spot?: MarketData; futures?: MarketData }> = {};
    for (const idx of summary?.indices ?? []) {
      out[idx.name] = {
        spot: idx.spot,
        futures: idx.futures,
      };
    }
    return out;
  }, [summary]);

  // Header stats
  const gainers = INDICES_ORDER.filter((n) => (ws[n]?.change_pct ?? 0) > 0).length;
  const losers  = INDICES_ORDER.filter((n) => (ws[n]?.change_pct ?? 0) < 0).length;
  const lastTickLabel = lastTickAt
    ? new Date(lastTickAt).toLocaleTimeString('en-IN', {
        timeZone: 'Asia/Kolkata',
        hour12: false,
      })
    : '--';

  const selectedMeta = selectedName ? META[selectedName] : null;
  const selectedWs   = selectedName ? ws[selectedName]  : null;

  return (
    <div className="flex h-full flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-100">Watchlist</h2>
          <p className="text-xs text-slate-500">Live market data · Click any row to open chart</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-2 text-xs sm:flex">
            <span className="rounded-full bg-emerald-500/10 px-2.5 py-1 text-emerald-400">{gainers} ▲ Up</span>
            <span className="rounded-full bg-red-500/10 px-2.5 py-1 text-red-400">{losers} ▼ Down</span>
            <span className="rounded-full bg-slate-800 px-2.5 py-1 text-slate-400">
              Ticks {tickCount}
            </span>
            <span className="rounded-full bg-slate-800 px-2.5 py-1 text-slate-400">
              Last {lastTickLabel} IST
            </span>
          </div>
          <div className={cn('flex items-center gap-1 text-xs', wsOk ? 'text-emerald-400' : 'text-amber-400')}>
            {wsOk ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5 animate-pulse" />}
            {wsOk ? `Live · ${lastTickLabel}` : 'Reconnecting…'}
          </div>
        </div>
      </div>

      {/* Data sync (collapsed) */}
      <DataSyncPanel />
      <GlobalEvaluationPanel />
      <FractalWatchlistBoard onSelectSymbol={handleSelectSymbol} />

      {/* Table + optional chart drawer */}
      <div className="flex min-h-0 flex-1 gap-4 overflow-hidden">

        {/* Market data table */}
        <div className={cn(
          'flex min-w-0 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-900',
          selectedName ? 'flex-1' : 'w-full',
        )}>
          <div className="overflow-auto">
            <table className="w-full min-w-[860px]">
              <thead>
                <tr className="sticky top-0 z-10 border-b border-slate-800 bg-slate-900 text-right text-[11px] font-medium uppercase tracking-wider text-slate-500">
                  <th className="py-2.5 pl-4 pr-3 text-left">Index</th>
                  <th className="px-3 py-2.5">LTP</th>
                  <th className="px-3 py-2.5">Change</th>
                  <th className="px-3 py-2.5">Chg %</th>
                  <th className="px-3 py-2.5">Open</th>
                  <th className="px-3 py-2.5 text-emerald-600/80">High</th>
                  <th className="px-3 py-2.5 text-red-600/80">Low</th>
                  <th className="px-3 py-2.5">Volume</th>
                  <th className="px-3 py-2.5">Futures</th>
                  <th className="px-3 py-2.5">OI</th>
                  <th className="px-3 py-2.5 text-left">30D Trend</th>
                  <th className="py-2.5 pl-3 pr-4" />
                </tr>
              </thead>
              <tbody>
                {isLoading
                  ? Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i} className="border-b border-slate-800/50">
                      {Array.from({ length: 12 }).map((_, j) => (
                        <td key={j} className="px-3 py-4">
                          <div className="h-3 animate-pulse rounded bg-slate-800" />
                        </td>
                      ))}
                    </tr>
                  ))
                  : INDICES_ORDER.map((name) => {
                    const baseline = baselineData[name];
                    const w        = ws[name];
                    return (
                      <IndexRow
                        key={name}
                        name={name}
                        isSelected={selectedName === name}
                        onClick={() => handleSelect(name)}
                        spotData={baseline?.spot}
                        futuresData={baseline?.futures}
                        wsLtp={w?.ltp}
                        wsChange={w?.change}
                        wsChangePct={w?.change_pct}
                        isSummaryLoading={isLoading}
                      />
                    );
                  })}
              </tbody>
            </table>
          </div>

          {!isLoading && !summary?.indices?.length && (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 py-16 text-center">
              <BarChart3 className="h-10 w-10 text-slate-700" />
              <p className="text-sm text-slate-500">No market data available</p>
              <p className="text-xs text-slate-600">
                Connect to Fyers in{' '}
                <Link href="/settings" className="text-emerald-500 hover:underline">
                  Settings
                </Link>
              </p>
            </div>
          )}
        </div>

        {/* Chart drawer (opens when row is clicked) */}
        {selectedName && selectedMeta && (
          <div className="w-[500px] flex-shrink-0 overflow-hidden rounded-xl border border-slate-800">
            <ChartDrawer
              name={selectedName}
              symbol={selectedMeta.symbol}
              ltp={selectedWs?.ltp ?? 0}
              changePct={selectedWs?.change_pct ?? 0}
              agentEvents={agentEvents ?? []}
              onClose={closeDrawer}
            />
          </div>
        )}
      </div>
    </div>
  );
}

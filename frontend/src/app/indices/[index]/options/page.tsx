'use client';

import { use, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  Loader2,
  Minimize2,
  Maximize2,
  RefreshCw,
  CandlestickChart as CandlestickIcon,
  X,
} from 'lucide-react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import {
  type OptionExpiryBlock,
  type OptionStrikeRow,
  useCanonicalOptionChain,
  useOptionChart,
  useOptionsAnalytics,
  useStraddleChart,
} from '@/hooks/use-options';
import CandlestickChart from '@/components/charts/candlestick-chart';
import { formatINR, formatNumber } from '@/lib/formatters';
import { cn } from '@/lib/utils';

interface PageProps {
  params: Promise<{ index: string }>;
}

const INDEX_META: Record<string, { label: string; underlying: string }> = {
  nifty: { label: 'NIFTY', underlying: 'NSE:NIFTY50-INDEX' },
  banknifty: { label: 'BANKNIFTY', underlying: 'NSE:NIFTYBANK-INDEX' },
  finnifty: { label: 'FINNIFTY', underlying: 'NSE:FINNIFTY-INDEX' },
  midcpnifty: { label: 'MIDCPNIFTY', underlying: 'NSE:NIFTYMIDCAP50-INDEX' },
  sensex: { label: 'SENSEX', underlying: 'BSE:SENSEX-INDEX' },
};

type ChartTab = 'CE' | 'PE' | 'STRADDLE';
type WorkspaceTab = 'CHAIN' | 'CHARTS' | 'ANALYTICS' | 'STRATEGY';
type StrategyPreset =
  | 'LONG_CALL'
  | 'LONG_PUT'
  | 'LONG_STRADDLE'
  | 'SHORT_STRADDLE'
  | 'BULL_CALL_SPREAD'
  | 'BEAR_PUT_SPREAD';

function expiryLabel(idx: number): string {
  if (idx === 0) return 'Nearest';
  if (idx === 1) return 'Next';
  if (idx === 2) return 'Far';
  return `E${idx + 1}`;
}

function OIBar({ ratio }: { ratio: number }) {
  const width = `${Math.max(0, Math.min(1, ratio)) * 100}%`;
  return (
    <div className="mt-1 h-1.5 w-full rounded bg-slate-800/80">
      <div className="h-1.5 rounded bg-emerald-400/90" style={{ width }} />
    </div>
  );
}

function OptionChainRow({
  row,
  isAtm,
  isSelected,
  onSelect,
  compact,
}: {
  row: OptionStrikeRow;
  isAtm: boolean;
  isSelected: boolean;
  onSelect: (strike: number) => void;
  compact: boolean;
}) {
  return (
    <tr
      className={cn(
        'border-t border-slate-800/80 transition-colors hover:bg-slate-800/30',
        isAtm && 'bg-amber-500/8',
        isSelected && 'bg-emerald-500/10'
      )}
      onClick={() => onSelect(row.strike)}
    >
      <td className={cn('px-2 text-right text-cyan-300', compact ? 'py-1.5 text-xs' : 'py-2 text-sm')}>
        {formatNumber(row.ce.oi)}
        <OIBar ratio={row.oi_bar?.ce_ratio ?? 0} />
      </td>
      <td className={cn('px-2 text-right text-emerald-300', compact ? 'py-1.5 text-xs' : 'py-2 text-sm')}>
        {formatNumber(row.ce.oich)}
      </td>
      <td className={cn('px-2 text-right text-slate-200', compact ? 'py-1.5 text-xs' : 'py-2 text-sm')}>
        {row.ce.iv > 0 ? `${(row.ce.iv * 100).toFixed(1)}%` : '—'}
      </td>
      <td className={cn('px-2 text-right text-emerald-400', compact ? 'py-1.5 text-xs' : 'py-2 text-sm')}>
        {row.ce.delta !== null ? row.ce.delta.toFixed(3) : '—'}
      </td>
      <td className={cn('px-2 text-right text-emerald-400', compact ? 'py-1.5 text-xs' : 'py-2 text-sm')}>
        {row.ce.gamma !== null ? row.ce.gamma.toFixed(5) : '—'}
      </td>
      <td className={cn('px-2 text-right font-semibold text-emerald-300', compact ? 'py-1.5 text-xs' : 'py-2 text-sm')}>
        {row.ce.ltp > 0 ? row.ce.ltp.toFixed(2) : '0.00'}
      </td>

      <td className={cn('px-2 text-center font-bold', compact ? 'py-1.5 text-xs' : 'py-2 text-sm', isAtm ? 'text-amber-300' : 'text-slate-100')}>
        {Math.round(row.strike)}
      </td>

      <td className={cn('px-2 text-right font-semibold text-rose-300', compact ? 'py-1.5 text-xs' : 'py-2 text-sm')}>
        {row.pe.ltp > 0 ? row.pe.ltp.toFixed(2) : '0.00'}
      </td>
      <td className={cn('px-2 text-right text-rose-400', compact ? 'py-1.5 text-xs' : 'py-2 text-sm')}>
        {row.pe.gamma !== null ? row.pe.gamma.toFixed(5) : '—'}
      </td>
      <td className={cn('px-2 text-right text-rose-400', compact ? 'py-1.5 text-xs' : 'py-2 text-sm')}>
        {row.pe.delta !== null ? row.pe.delta.toFixed(3) : '—'}
      </td>
      <td className={cn('px-2 text-right text-slate-200', compact ? 'py-1.5 text-xs' : 'py-2 text-sm')}>
        {row.pe.iv > 0 ? `${(row.pe.iv * 100).toFixed(1)}%` : '—'}
      </td>
      <td className={cn('px-2 text-right text-rose-300', compact ? 'py-1.5 text-xs' : 'py-2 text-sm')}>
        {formatNumber(row.pe.oich)}
      </td>
      <td className={cn('px-2 text-right text-cyan-300', compact ? 'py-1.5 text-xs' : 'py-2 text-sm')}>
        {formatNumber(row.pe.oi)}
        <OIBar ratio={row.oi_bar?.pe_ratio ?? 0} />
      </td>
    </tr>
  );
}

function GammaConvexityTile({
  points,
  minimized,
  onToggle,
  onExpand,
}: {
  points: Array<{ strike: number; gamma_convexity: number }>;
  minimized: boolean;
  onToggle: () => void;
  onExpand: () => void;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Gamma Convexity</h3>
        <div className="flex gap-1">
          <button
            className="rounded border border-slate-700 p-1 text-slate-300 hover:bg-slate-800"
            title="Expand full-screen"
            onClick={onExpand}
          >
            <Maximize2 className="h-3 w-3" />
          </button>
          <button
            className="rounded border border-slate-700 p-1 text-slate-300 hover:bg-slate-800"
            onClick={onToggle}
          >
            {minimized ? <Maximize2 className="h-3 w-3 text-slate-500" /> : <Minimize2 className="h-3 w-3" />}
          </button>
        </div>
      </div>
      {minimized ? null : points.length ? (
        <div className="h-40">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
              <XAxis dataKey="strike" tick={{ fontSize: 10 }} stroke="#64748b" />
              <YAxis tick={{ fontSize: 10 }} width={58} stroke="#64748b" />
              <Tooltip
                formatter={(v: number | string | undefined) => [
                  Number(v ?? 0).toFixed(4),
                  'Convexity',
                ]}
              />
              <Line dataKey="gamma_convexity" type="monotone" dot={false} stroke="#a78bfa" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="flex h-24 items-center justify-center text-sm text-slate-500">No convexity points</div>
      )}
    </div>
  );
}

function strikeKey(v: number): string {
  return v.toFixed(2);
}

function callPnL(spot: number, strike: number, premium: number): number {
  return Math.max(spot - strike, 0) - premium;
}

function putPnL(spot: number, strike: number, premium: number): number {
  return Math.max(strike - spot, 0) - premium;
}

export default function OptionsChainPage({ params }: PageProps) {
  const { index: indexParam } = use(params);
  const indexKey = indexParam.toLowerCase();
  const meta = INDEX_META[indexKey];

  const [interval, setInterval] = useState('15');
  const [chartDays, setChartDays] = useState(3);
  const [userSelectedExpiryTs, setUserSelectedExpiryTs] = useState<number | null>(null);
  const [userSelectedStrike, setUserSelectedStrike] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<ChartTab>('CE');
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>('CHAIN');
  const [chartsCompact, setChartsCompact] = useState(true);
  const [strategyPreset, setStrategyPreset] = useState<StrategyPreset>('LONG_STRADDLE');
  const [lots, setLots] = useState(1);
  const [chainMinimized, setChainMinimized] = useState(false);
  const [gammaMinimized, setGammaMinimized] = useState(false);
  const [oiMapMinimized, setOiMapMinimized] = useState(false);
  const [ivSmileMinimized, setIvSmileMinimized] = useState(false);
  const [termMinimized, setTermMinimized] = useState(false);
  const [chainHeight, setChainHeight] = useState(460);
  const [analyticsHeight, setAnalyticsHeight] = useState(240);
  const [expandedChart, setExpandedChart] = useState<'oi' | 'iv' | 'term' | 'gex' | 'gamma' | null>(null);

  // Full chain: 25 strikes per side (~51 total for NIFTY at 50pt intervals = ±1250pt coverage)
  const chainQuery = useCanonicalOptionChain(
    meta?.underlying ?? '',
    userSelectedExpiryTs,
    25,
    userSelectedExpiryTs ? 1 : 3,
    Boolean(meta)
  );

  const expiryBlocks = useMemo(
    () => chainQuery.data?.data.expiryData ?? [],
    [chainQuery.data]
  );
  const selectedExpiryTs = userSelectedExpiryTs ?? expiryBlocks[0]?.expiry_ts ?? null;

  const activeExpiry: OptionExpiryBlock | null = useMemo(() => {
    if (!expiryBlocks.length) return null;
    if (!selectedExpiryTs) return expiryBlocks[0];
    return expiryBlocks.find((e) => e.expiry_ts === selectedExpiryTs) ?? expiryBlocks[0];
  }, [expiryBlocks, selectedExpiryTs]);

  const atmRow = useMemo(() => {
    if (!activeExpiry?.strikes.length) return null;
    const spot = activeExpiry.spot || 0;
    return [...activeExpiry.strikes].sort(
      (a, b) => Math.abs(a.strike - spot) - Math.abs(b.strike - spot)
    )[0];
  }, [activeExpiry]);

  const selectedStrike = useMemo(() => {
    if (!activeExpiry?.strikes.length) return null;
    if (
      userSelectedStrike !== null &&
      activeExpiry.strikes.some((row) => row.strike === userSelectedStrike)
    ) {
      return userSelectedStrike;
    }
    return atmRow?.strike ?? activeExpiry.strikes[0].strike;
  }, [activeExpiry, atmRow, userSelectedStrike]);

  const selectedRow = useMemo(() => {
    if (!activeExpiry?.strikes.length) return null;
    return (
      activeExpiry.strikes.find((row) => row.strike === selectedStrike) ?? atmRow ?? activeExpiry.strikes[0]
    );
  }, [activeExpiry, selectedStrike, atmRow]);

  const ceSymbol = selectedRow?.ce.symbol ?? null;
  const peSymbol = selectedRow?.pe.symbol ?? null;

  const ceChartQuery = useOptionChart(ceSymbol, interval, chartDays, Boolean(ceSymbol));
  const peChartQuery = useOptionChart(peSymbol, interval, chartDays, Boolean(peSymbol));
  const straddleQuery = useStraddleChart(
    meta?.underlying ?? '',
    activeExpiry?.expiry_ts,
    selectedRow?.strike,
    interval,
    chartDays,
    Boolean(meta && activeExpiry && selectedRow)
  );
  const analyticsQuery = useOptionsAnalytics(meta?.underlying ?? '', activeExpiry?.expiry_ts, Boolean(meta));

  const currentChart = activeTab === 'CE'
    ? ceChartQuery.data?.candles ?? []
    : activeTab === 'PE'
      ? peChartQuery.data?.candles ?? []
      : straddleQuery.data?.candles ?? [];
  const oiBuildup = analyticsQuery.data?.oi_buildup ?? [];
  const ivSmile = (analyticsQuery.data?.iv_smile ?? []).filter(
    (point) => point.ce_iv_pct > 0 || point.pe_iv_pct > 0
  );
  const termStructure = analyticsQuery.data?.term_structure ?? [];
  const gexDex = (analyticsQuery.data?.exposures_by_strike ?? []).map((row) => ({
    strike: row.strike,
    gex: row.net_gamma_exposure,
    dex: row.net_delta_exposure,
  }));
  const chartCandles = useMemo(
    () =>
      currentChart
        .map((c) => ({
          time: Math.floor(new Date(c.timestamp).getTime() / 1000),
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
          volume: c.volume,
        }))
        .filter((c) => Number.isFinite(c.time)),
    [currentChart]
  );

  const strikeStep = useMemo(() => {
    const strikes = activeExpiry?.strikes ?? [];
    if (strikes.length < 2) return 50;
    const sorted = [...strikes].map((s) => s.strike).sort((a, b) => a - b);
    let minStep = Number.POSITIVE_INFINITY;
    for (let i = 1; i < sorted.length; i += 1) {
      const diff = sorted[i] - sorted[i - 1];
      if (diff > 0 && diff < minStep) minStep = diff;
    }
    return Number.isFinite(minStep) ? minStep : 50;
  }, [activeExpiry]);

  const strikeMap = useMemo(() => {
    const map = new Map<string, OptionStrikeRow>();
    for (const row of activeExpiry?.strikes ?? []) {
      map.set(strikeKey(row.strike), row);
    }
    return map;
  }, [activeExpiry]);

  const strategyPoints = useMemo(() => {
    if (!selectedRow || !activeExpiry) return [];

    const lotSize = Math.max(analyticsQuery.data?.lot_size ?? 1, 1);
    const qty = Math.max(lots, 1) * lotSize;
    const k = selectedRow.strike;
    const spotRef = activeExpiry.spot || k;
    const kUp = k + strikeStep;
    const kDown = k - strikeStep;
    const ceAtm = Math.max(selectedRow.ce.ltp, 0.01);
    const peAtm = Math.max(selectedRow.pe.ltp, 0.01);
    const ceUp = Math.max(strikeMap.get(strikeKey(kUp))?.ce.ltp ?? ceAtm * 0.6, 0.01);
    const peDown = Math.max(strikeMap.get(strikeKey(kDown))?.pe.ltp ?? peAtm * 0.6, 0.01);

    const minSpot = Math.max(1, spotRef * 0.9);
    const maxSpot = spotRef * 1.1;
    const step = (maxSpot - minSpot) / 80;
    const points: Array<{ spot: number; pnl: number; zero: number }> = [];

    for (let s = minSpot; s <= maxSpot + step / 2; s += step) {
      let pnl = 0;
      if (strategyPreset === 'LONG_CALL') {
        pnl = callPnL(s, k, ceAtm);
      } else if (strategyPreset === 'LONG_PUT') {
        pnl = putPnL(s, k, peAtm);
      } else if (strategyPreset === 'LONG_STRADDLE') {
        pnl = callPnL(s, k, ceAtm) + putPnL(s, k, peAtm);
      } else if (strategyPreset === 'SHORT_STRADDLE') {
        pnl = -(callPnL(s, k, ceAtm) + putPnL(s, k, peAtm));
      } else if (strategyPreset === 'BULL_CALL_SPREAD') {
        pnl = callPnL(s, k, ceAtm) - callPnL(s, kUp, ceUp);
      } else if (strategyPreset === 'BEAR_PUT_SPREAD') {
        pnl = putPnL(s, k, peAtm) - putPnL(s, kDown, peDown);
      }
      points.push({
        spot: Number(s.toFixed(2)),
        pnl: Number((pnl * qty).toFixed(2)),
        zero: 0,
      });
    }
    return points;
  }, [activeExpiry, analyticsQuery.data?.lot_size, lots, selectedRow, strategyPreset, strikeMap, strikeStep]);

  const strategyStats = useMemo(() => {
    if (!strategyPoints.length) return { maxProfit: 0, maxLoss: 0, breakEven: [] as number[] };
    const pnl = strategyPoints.map((p) => p.pnl);
    const maxProfit = Math.max(...pnl);
    const maxLoss = Math.min(...pnl);
    const breakEven: number[] = [];
    for (let i = 1; i < strategyPoints.length; i += 1) {
      const prev = strategyPoints[i - 1];
      const curr = strategyPoints[i];
      if ((prev.pnl <= 0 && curr.pnl >= 0) || (prev.pnl >= 0 && curr.pnl <= 0)) {
        breakEven.push(Number(((prev.spot + curr.spot) / 2).toFixed(2)));
      }
    }
    return { maxProfit, maxLoss, breakEven };
  }, [strategyPoints]);

  const loading = chainQuery.isLoading;

  if (!meta) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-slate-100">Index Not Found</h2>
          <p className="mt-2 text-slate-400">The index &quot;{indexParam}&quot; is not available.</p>
          <Link href="/indices" className="mt-4 inline-flex items-center gap-2 text-emerald-400 hover:text-emerald-300">
            <ArrowLeft className="h-4 w-4" /> Back to Indices
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800 bg-slate-900/90 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Link href={`/indices/${indexKey}`} className="rounded-lg border border-slate-800 p-2 hover:border-slate-600">
              <ArrowLeft className="h-4 w-4 text-slate-400" />
            </Link>
            <div>
              <h2 className="text-2xl font-bold text-slate-100">{meta.label} - Options Detail</h2>
              <p className="text-xs text-slate-500">Accuracy-first chain + OHLC + OI history pipeline</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Data freshness */}
            {chainQuery.data?.fetched_at && (
              <span className="text-[11px] text-emerald-400">
                ● Live · {new Date(chainQuery.data.fetched_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </span>
            )}

            {/* Chart period */}
            <div className="flex rounded-md border border-slate-700 overflow-hidden">
              {([1, 3, 7, 14] as const).map((d) => (
                <button
                  key={d}
                  className={cn(
                    'px-2 py-1.5 text-xs',
                    chartDays === d
                      ? 'bg-slate-600 text-white'
                      : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                  )}
                  onClick={() => setChartDays(d)}
                >
                  {d === 1 ? '1D' : d === 3 ? '3D' : d === 7 ? '1W' : '2W'}
                </button>
              ))}
            </div>

            <select
              className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200"
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
            >
              <option value="1">1m</option>
              <option value="5">5m</option>
              <option value="15">15m</option>
              <option value="30">30m</option>
              <option value="60">60m</option>
            </select>

            <button
              className="rounded-md border border-slate-700 px-2 py-1.5 text-slate-300 hover:bg-slate-800"
              onClick={() => { chainQuery.refetch(); }}
            >
              <RefreshCw className={cn('h-4 w-4', chainQuery.isFetching && 'animate-spin')} />
            </button>
          </div>
        </div>

        <div className="mt-3 grid gap-2 md:grid-cols-7">
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
            <div className="text-[11px] uppercase text-slate-500">Spot</div>
            <div className="text-xl font-bold text-slate-100">{activeExpiry ? activeExpiry.spot.toFixed(2) : '—'}</div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
            <div className="text-[11px] uppercase text-slate-500">ATM Strike</div>
            <div className="text-xl font-bold text-amber-300">{selectedRow ? Math.round(selectedRow.strike) : '—'}</div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
            <div className="text-[11px] uppercase text-slate-500">Total CE OI</div>
            <div className="text-xl font-semibold text-cyan-300">{activeExpiry ? formatNumber(activeExpiry.total_call_oi) : '—'}</div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
            <div className="text-[11px] uppercase text-slate-500">Total PE OI</div>
            <div className="text-xl font-semibold text-cyan-300">{activeExpiry ? formatNumber(activeExpiry.total_put_oi) : '—'}</div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
            <div className="text-[11px] uppercase text-slate-500">PCR</div>
            <div className="text-xl font-semibold text-violet-300">{activeExpiry ? activeExpiry.pcr.toFixed(2) : '—'}</div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
            <div className="text-[11px] uppercase text-slate-500">Integrity</div>
            <div className="text-xl font-semibold text-emerald-300">
              {activeExpiry ? `${(activeExpiry.quality.integrity_score * 100).toFixed(1)}%` : '—'}
            </div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
            <div className="text-[11px] uppercase text-slate-500">Source Latency</div>
            <div className="text-xl font-semibold text-slate-200">
              {activeExpiry?.quality.source_latency_ms !== undefined
                ? `${activeExpiry.quality.source_latency_ms}ms`
                : '—'}
            </div>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {expiryBlocks.map((exp, idx) => (
            <button
              key={exp.expiry_ts}
              className={cn(
                'rounded-md border px-2.5 py-1 text-xs',
                selectedExpiryTs === exp.expiry_ts
                  ? 'border-emerald-500 bg-emerald-500/10 text-emerald-300'
                  : 'border-slate-700 bg-slate-900 text-slate-400 hover:border-slate-600'
              )}
                  onClick={() => {
                    setUserSelectedExpiryTs(exp.expiry_ts);
                    setUserSelectedStrike(null);
                  }}
            >
              {expiryLabel(idx)} · {new Date(exp.expiry).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
            </button>
          ))}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-1 rounded-lg border border-slate-800 bg-slate-950/60 p-1">
          {([
            { key: 'CHAIN', label: 'Option Chain' },
            { key: 'CHARTS', label: 'Charts' },
            { key: 'ANALYTICS', label: 'Option Analytics' },
            { key: 'STRATEGY', label: 'Strategy Builder' },
          ] as Array<{ key: WorkspaceTab; label: string }>).map((tab) => (
            <button
              key={tab.key}
              className={cn(
                'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                workspaceTab === tab.key
                  ? 'bg-emerald-500/20 text-emerald-300'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              )}
              onClick={() => setWorkspaceTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {workspaceTab === 'CHARTS' && (
      <div className="grid gap-3 lg:grid-cols-[1fr_300px]">
        <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CandlestickIcon className="h-4 w-4 text-cyan-300" />
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Charts (main chart behavior)</h3>
            </div>
            <div className="flex items-center gap-1">
              {(['CE', 'PE', 'STRADDLE'] as ChartTab[]).map((tab) => (
                <button
                  key={tab}
                  className={cn(
                    'rounded border px-2 py-1 text-xs',
                    activeTab === tab
                      ? 'border-cyan-500 bg-cyan-500/10 text-cyan-300'
                      : 'border-slate-700 text-slate-400 hover:bg-slate-800'
                  )}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab === 'STRADDLE' ? 'ATM Straddle' : `${tab} Chart`}
                </button>
              ))}
              <button
                className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
                onClick={() => setChartsCompact((v) => !v)}
              >
                {chartsCompact ? 'Expand' : 'Compact'}
              </button>
            </div>
          </div>

          {ceChartQuery.isLoading || peChartQuery.isLoading || straddleQuery.isLoading ? (
            <div className="flex h-[360px] items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
            </div>
          ) : chartCandles.length === 0 ? (
            <div className="flex h-[360px] items-center justify-center text-sm text-slate-500">
              No chart candles available for selected contract
            </div>
          ) : (
            <div className="space-y-2">
              <div className="text-[11px] uppercase tracking-wide text-slate-500">
                Stable viewport · same engine as main chart page
              </div>
              <CandlestickChart
                data={chartCandles}
                height={chartsCompact ? 360 : 520}
                lockViewport
              />
            </div>
          )}
        </div>

        <div className="space-y-3">
          <GammaConvexityTile
            points={analyticsQuery.data?.gamma_convexity ?? []}
            minimized={gammaMinimized}
            onToggle={() => setGammaMinimized((v) => !v)}
            onExpand={() => setExpandedChart('gamma')}
          />

          <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Exposure Snapshot</h3>
            <div className="space-y-1 text-sm">
              <div className="flex justify-between text-slate-400"><span>Net GEX</span><span className="text-cyan-300">{analyticsQuery.data ? analyticsQuery.data.total_net_gex.toFixed(2) : '—'}</span></div>
              <div className="flex justify-between text-slate-400"><span>Net DEX</span><span className="text-cyan-300">{analyticsQuery.data ? analyticsQuery.data.total_net_dex.toFixed(2) : '—'}</span></div>
              <div className="flex justify-between text-slate-400"><span>Net Theta</span><span className="text-cyan-300">{analyticsQuery.data ? analyticsQuery.data.total_net_theta_exposure.toFixed(2) : '—'}</span></div>
              <div className="flex justify-between text-slate-400"><span>Net Vega</span><span className="text-cyan-300">{analyticsQuery.data ? analyticsQuery.data.total_net_vega_exposure.toFixed(2) : '—'}</span></div>
              <div className="flex justify-between text-slate-400"><span>Net Vanna</span><span className="text-cyan-300">{analyticsQuery.data ? analyticsQuery.data.total_net_vanna_exposure.toFixed(2) : '—'}</span></div>
              <div className="flex justify-between text-slate-400"><span>Net Charm</span><span className="text-cyan-300">{analyticsQuery.data ? analyticsQuery.data.total_net_charm_exposure.toFixed(2) : '—'}</span></div>
              <div className="flex justify-between text-slate-400"><span>Net Vomma</span><span className="text-cyan-300">{analyticsQuery.data ? analyticsQuery.data.total_net_vomma_exposure.toFixed(2) : '—'}</span></div>
              <div className="flex justify-between text-slate-400"><span>Net Speed</span><span className="text-cyan-300">{analyticsQuery.data ? analyticsQuery.data.total_net_speed_exposure.toFixed(4) : '—'}</span></div>
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Selected Strike</h3>
            <div className="space-y-1 text-sm">
              <div className="flex justify-between text-slate-400"><span>Strike</span><span className="text-slate-200">{selectedRow ? Math.round(selectedRow.strike) : '—'}</span></div>
              <div className="flex justify-between text-slate-400"><span>CE Symbol</span><span className="max-w-[170px] truncate text-emerald-300">{ceSymbol ?? '—'}</span></div>
              <div className="flex justify-between text-slate-400"><span>PE Symbol</span><span className="max-w-[170px] truncate text-rose-300">{peSymbol ?? '—'}</span></div>
              <div className="flex justify-between text-slate-400"><span>CE LTP</span><span className="text-emerald-300">{selectedRow ? selectedRow.ce.ltp.toFixed(2) : '—'}</span></div>
              <div className="flex justify-between text-slate-400"><span>PE LTP</span><span className="text-rose-300">{selectedRow ? selectedRow.pe.ltp.toFixed(2) : '—'}</span></div>
              <div className="flex justify-between text-slate-400"><span>ATM Straddle</span><span className="text-violet-300">{selectedRow ? formatINR(selectedRow.ce.ltp + selectedRow.pe.ltp) : '—'}</span></div>
            </div>
          </div>
        </div>
      </div>
      )}

      {workspaceTab === 'CHAIN' && (
      <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
        <div className="mb-2 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-amber-300">Option Chain Matrix</h3>
            <p className="text-xs text-slate-500">Inline OI bars under each strike side. No separate OI chart column.</p>
          </div>
          <div className="flex items-center gap-1">
            <button
              className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
              onClick={() => setChainHeight((h) => Math.max(300, h - 80))}
            >
              H-
            </button>
            <button
              className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
              onClick={() => setChainHeight((h) => Math.min(760, h + 80))}
            >
              H+
            </button>
            <button
              className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
              onClick={() => setChainMinimized((v) => !v)}
            >
              {chainMinimized ? 'Show' : 'Min'}
            </button>
          </div>
        </div>

        {chainMinimized ? null : loading ? (
          <div className="flex h-44 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
          </div>
        ) : activeExpiry ? (
          <div className="resize-y overflow-auto rounded-lg border border-slate-800" style={{ height: chainHeight }}>
            <table className="min-w-full text-xs">
              <thead className="sticky top-0 z-10 bg-slate-900">
                <tr className="border-b border-slate-800 bg-slate-800/60 text-[11px] uppercase tracking-wide text-slate-400">
                  <th className="px-2 py-2 text-right text-cyan-300">CE OI</th>
                  <th className="px-2 py-2 text-right text-cyan-300">CE COI</th>
                  <th className="px-2 py-2 text-right">CE IV</th>
                  <th className="px-2 py-2 text-right">CE Δ</th>
                  <th className="px-2 py-2 text-right">CE Γ</th>
                  <th className="px-2 py-2 text-right">CE LTP</th>
                  <th className="px-2 py-2 text-center text-amber-300">Strike</th>
                  <th className="px-2 py-2 text-right">PE LTP</th>
                  <th className="px-2 py-2 text-right">PE Γ</th>
                  <th className="px-2 py-2 text-right">PE Δ</th>
                  <th className="px-2 py-2 text-right">PE IV</th>
                  <th className="px-2 py-2 text-right text-cyan-300">PE COI</th>
                  <th className="px-2 py-2 text-right text-cyan-300">PE OI</th>
                </tr>
              </thead>
              <tbody>
                {activeExpiry.strikes.map((row) => (
                  <OptionChainRow
                    key={row.strike}
                    row={row}
                    isAtm={atmRow?.strike === row.strike}
                    isSelected={selectedRow?.strike === row.strike}
                    onSelect={(strike) => setUserSelectedStrike(strike)}
                    compact
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex h-44 items-center justify-center text-sm text-slate-500">No option chain data available.</div>
        )}
      </div>
      )}

      {workspaceTab === 'ANALYTICS' && (
      <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
        <div className="mb-2 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-cyan-300">Advanced Analytics</h3>
            <p className="text-xs text-slate-500">OI build-up, IV smile, and expiry term structure. Click ⤢ to expand full-screen.</p>
          </div>
          <div className="flex items-center gap-1">
            <button
              className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
              onClick={() => setAnalyticsHeight((h) => Math.max(180, h - 40))}
            >
              H-
            </button>
            <button
              className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
              onClick={() => setAnalyticsHeight((h) => Math.min(420, h + 40))}
            >
              H+
            </button>
          </div>
        </div>

        <div className="grid gap-3 lg:grid-cols-4">
          {/* OI Build-up */}
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-2">
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">OI Build-up Map</h4>
              <div className="flex gap-1">
                <button
                  className="rounded border border-slate-700 p-1 text-slate-300 hover:bg-slate-800"
                  title="Expand full-screen"
                  onClick={() => setExpandedChart('oi')}
                >
                  <Maximize2 className="h-3 w-3" />
                </button>
                <button
                  className="rounded border border-slate-700 p-1 text-slate-300 hover:bg-slate-800"
                  onClick={() => setOiMapMinimized((v) => !v)}
                >
                  {oiMapMinimized ? <Maximize2 className="h-3 w-3 text-slate-500" /> : <Minimize2 className="h-3 w-3" />}
                </button>
              </div>
            </div>
            {oiMapMinimized ? null : oiBuildup.length ? (
              <div style={{ height: analyticsHeight }}>
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={oiBuildup} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                    <XAxis dataKey="strike" tick={{ fontSize: 10 }} stroke="#64748b" />
                    <YAxis tick={{ fontSize: 10 }} stroke="#64748b" />
                    <Tooltip />
                    <Bar dataKey="ce_oich" fill="#10b981" name="CE COI" />
                    <Bar dataKey="pe_oich" fill="#f43f5e" name="PE COI" />
                    <Line dataKey="net_oich" stroke="#22d3ee" dot={false} strokeWidth={1.3} name="Net COI" />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="flex h-24 items-center justify-center text-sm text-slate-500">No OI build-up data</div>
            )}
          </div>

          {/* IV Smile */}
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-2">
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">IV Smile</h4>
              <div className="flex gap-1">
                <button
                  className="rounded border border-slate-700 p-1 text-slate-300 hover:bg-slate-800"
                  title="Expand full-screen"
                  onClick={() => setExpandedChart('iv')}
                >
                  <Maximize2 className="h-3 w-3" />
                </button>
                <button
                  className="rounded border border-slate-700 p-1 text-slate-300 hover:bg-slate-800"
                  onClick={() => setIvSmileMinimized((v) => !v)}
                >
                  {ivSmileMinimized ? <Maximize2 className="h-3 w-3 text-slate-500" /> : <Minimize2 className="h-3 w-3" />}
                </button>
              </div>
            </div>
            {ivSmileMinimized ? null : ivSmile.length ? (
              <div style={{ height: analyticsHeight }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={ivSmile} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                    <XAxis dataKey="strike" tick={{ fontSize: 10 }} stroke="#64748b" />
                    <YAxis tick={{ fontSize: 10 }} stroke="#64748b" />
                    <Tooltip formatter={(v: number | string | undefined) => [`${Number(v ?? 0).toFixed(2)}%`, 'IV']} />
                    <Line dataKey="ce_iv_pct" stroke="#10b981" dot={false} strokeWidth={1.7} name="CE IV%" />
                    <Line dataKey="pe_iv_pct" stroke="#f43f5e" dot={false} strokeWidth={1.7} name="PE IV%" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="flex h-24 items-center justify-center text-sm text-slate-500">No IV smile data</div>
            )}
          </div>

          {/* Term Structure */}
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-2">
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Expiry Term Structure</h4>
              <div className="flex gap-1">
                <button
                  className="rounded border border-slate-700 p-1 text-slate-300 hover:bg-slate-800"
                  title="Expand full-screen"
                  onClick={() => setExpandedChart('term')}
                >
                  <Maximize2 className="h-3 w-3" />
                </button>
                <button
                  className="rounded border border-slate-700 p-1 text-slate-300 hover:bg-slate-800"
                  onClick={() => setTermMinimized((v) => !v)}
                >
                  {termMinimized ? <Maximize2 className="h-3 w-3 text-slate-500" /> : <Minimize2 className="h-3 w-3" />}
                </button>
              </div>
            </div>
            {termMinimized ? null : termStructure.length ? (
              <div style={{ height: analyticsHeight }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={termStructure} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                    <XAxis
                      dataKey="expiry"
                      tick={{ fontSize: 10 }}
                      stroke="#64748b"
                      tickFormatter={(value) => new Date(value).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
                    />
                    <YAxis yAxisId="left" tick={{ fontSize: 10 }} stroke="#64748b" />
                    <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} stroke="#475569" />
                    <Tooltip />
                    <Line yAxisId="left" dataKey="pcr" stroke="#a78bfa" dot={false} strokeWidth={1.6} name="PCR" />
                    <Line yAxisId="right" dataKey="atm_straddle" stroke="#22d3ee" dot={false} strokeWidth={1.6} name="ATM Straddle" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="flex h-24 items-center justify-center text-sm text-slate-500">No term-structure data</div>
            )}
          </div>

          {/* GEX / DEX */}
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-2">
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">GEX / DEX</h4>
              <button
                className="rounded border border-slate-700 p-1 text-slate-300 hover:bg-slate-800"
                title="Expand full-screen"
                onClick={() => setExpandedChart('gex')}
              >
                <Maximize2 className="h-3 w-3" />
              </button>
            </div>
            {gexDex.length ? (
              <div style={{ height: analyticsHeight }}>
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={gexDex} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                    <XAxis dataKey="strike" tick={{ fontSize: 10 }} stroke="#64748b" />
                    <YAxis yAxisId="left" tick={{ fontSize: 10 }} stroke="#64748b" />
                    <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} stroke="#475569" />
                    <Tooltip />
                    <Bar yAxisId="left" dataKey="gex" fill="#22d3ee" name="GEX" />
                    <Line yAxisId="right" dataKey="dex" stroke="#f59e0b" dot={false} strokeWidth={1.4} name="DEX" />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="flex h-24 items-center justify-center text-sm text-slate-500">No GEX/DEX data</div>
            )}
          </div>
        </div>
      </div>
      )}

      {workspaceTab === 'STRATEGY' && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-emerald-300">Options Strategy Builder</h3>
              <p className="text-xs text-slate-500">Build payoff profiles from live chain premiums for the selected expiry.</p>
            </div>
            <div className="flex items-center gap-2">
              <select
                value={strategyPreset}
                onChange={(e) => setStrategyPreset(e.target.value as StrategyPreset)}
                className="rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-xs text-slate-200"
              >
                <option value="LONG_CALL">Long Call</option>
                <option value="LONG_PUT">Long Put</option>
                <option value="LONG_STRADDLE">Long Straddle</option>
                <option value="SHORT_STRADDLE">Short Straddle</option>
                <option value="BULL_CALL_SPREAD">Bull Call Spread</option>
                <option value="BEAR_PUT_SPREAD">Bear Put Spread</option>
              </select>
              <input
                type="number"
                min={1}
                max={50}
                value={lots}
                onChange={(e) => setLots(Math.max(1, Number(e.target.value) || 1))}
                className="w-20 rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-xs text-slate-200"
              />
            </div>
          </div>

          <div className="mb-3 grid gap-2 md:grid-cols-4">
            <div className="rounded border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs">
              <div className="text-slate-500">ATM Strike</div>
              <div className="font-mono text-slate-100">{selectedRow ? Math.round(selectedRow.strike) : '—'}</div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs">
              <div className="text-slate-500">Max Profit</div>
              <div className="font-mono text-emerald-300">{formatINR(strategyStats.maxProfit)}</div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs">
              <div className="text-slate-500">Max Loss</div>
              <div className="font-mono text-rose-300">{formatINR(strategyStats.maxLoss)}</div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs">
              <div className="text-slate-500">Break-even</div>
              <div className="font-mono text-slate-200">
                {strategyStats.breakEven.length ? strategyStats.breakEven.map((v) => v.toFixed(0)).join(', ') : '—'}
              </div>
            </div>
          </div>

          {strategyPoints.length ? (
            <div className="h-[360px] rounded border border-slate-800 bg-slate-950/60 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={strategyPoints} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                  <XAxis dataKey="spot" tick={{ fontSize: 10 }} stroke="#64748b" />
                  <YAxis tick={{ fontSize: 10 }} stroke="#64748b" />
                  <Tooltip
                    formatter={(v: number | string | undefined) => [formatINR(Number(v ?? 0)), 'P&L']}
                    labelFormatter={(label) => `Spot ${formatINR(Number(label ?? 0))}`}
                  />
                  <Line dataKey="pnl" type="monotone" dot={false} stroke="#22d3ee" strokeWidth={2} />
                  <Line
                    dataKey="zero"
                    type="linear"
                    dot={false}
                    stroke="#475569"
                    strokeWidth={1}
                    strokeDasharray="4 3"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="flex h-44 items-center justify-center text-sm text-slate-500">
              Strategy payoff unavailable for current selection
            </div>
          )}
        </div>
      )}

      {/* ── Full-screen chart modal ─────────────────────────────── */}
      {expandedChart && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
          onClick={() => setExpandedChart(null)}
        >
          <div
            className="flex max-h-[95vh] w-full max-w-[98vw] flex-col rounded-xl border border-slate-700 bg-slate-900 p-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal header */}
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-cyan-300">
                {expandedChart === 'oi' && 'OI Build-up Map — Full Spectrum'}
                {expandedChart === 'iv' && 'IV Smile — Full Spectrum'}
                {expandedChart === 'term' && 'Expiry Term Structure'}
                {expandedChart === 'gex' && 'Gamma Exposure (GEX) / Delta Exposure (DEX)'}
                {expandedChart === 'gamma' && 'Gamma Convexity — Full Spectrum'}
              </h3>
              <button
                className="rounded-md border border-slate-700 p-1.5 text-slate-300 hover:bg-slate-800"
                onClick={() => setExpandedChart(null)}
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Modal chart body */}
            <div className="min-h-0 flex-1" style={{ height: 'calc(85vh - 80px)' }}>
              <ResponsiveContainer width="100%" height="100%">
                {expandedChart === 'oi' ? (
                  <ComposedChart data={oiBuildup} margin={{ top: 12, right: 24, left: 8, bottom: 16 }}>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                    <XAxis dataKey="strike" tick={{ fontSize: 11 }} stroke="#64748b" interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 11 }} stroke="#64748b" width={64} />
                    <Tooltip />
                    <Bar dataKey="ce_oich" fill="#10b981" name="CE Change OI" />
                    <Bar dataKey="pe_oich" fill="#f43f5e" name="PE Change OI" />
                    <Line dataKey="net_oich" stroke="#22d3ee" dot={false} strokeWidth={2} name="Net COI" />
                  </ComposedChart>
                ) : expandedChart === 'iv' ? (
                  <LineChart data={ivSmile} margin={{ top: 12, right: 24, left: 8, bottom: 16 }}>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                    <XAxis dataKey="strike" tick={{ fontSize: 11 }} stroke="#64748b" interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 11 }} stroke="#64748b" width={48} />
                    <Tooltip formatter={(v: number | string | undefined) => [`${Number(v ?? 0).toFixed(2)}%`, 'IV']} />
                    <Line dataKey="ce_iv_pct" stroke="#10b981" dot={false} strokeWidth={2} name="CE IV%" />
                    <Line dataKey="pe_iv_pct" stroke="#f43f5e" dot={false} strokeWidth={2} name="PE IV%" />
                  </LineChart>
                ) : expandedChart === 'term' ? (
                  <LineChart data={termStructure} margin={{ top: 12, right: 24, left: 8, bottom: 16 }}>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                    <XAxis
                      dataKey="expiry"
                      tick={{ fontSize: 11 }}
                      stroke="#64748b"
                      tickFormatter={(value) => new Date(value).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
                    />
                    <YAxis yAxisId="left" tick={{ fontSize: 11 }} stroke="#64748b" width={48} />
                    <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} stroke="#475569" width={64} />
                    <Tooltip />
                    <Line yAxisId="left" dataKey="pcr" stroke="#a78bfa" dot strokeWidth={2} name="PCR" />
                    <Line yAxisId="right" dataKey="atm_straddle" stroke="#22d3ee" dot strokeWidth={2} name="ATM Straddle" />
                  </LineChart>
                ) : expandedChart === 'gex' ? (
                  <ComposedChart data={gexDex} margin={{ top: 12, right: 24, left: 8, bottom: 16 }}>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                    <XAxis dataKey="strike" tick={{ fontSize: 11 }} stroke="#64748b" interval="preserveStartEnd" />
                    <YAxis yAxisId="left" tick={{ fontSize: 11 }} stroke="#64748b" width={64} />
                    <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} stroke="#475569" width={64} />
                    <Tooltip />
                    <Bar yAxisId="left" dataKey="gex" fill="#22d3ee" name="GEX" />
                    <Line yAxisId="right" dataKey="dex" stroke="#f59e0b" dot={false} strokeWidth={2} name="DEX" />
                  </ComposedChart>
                ) : (
                  <LineChart data={analyticsQuery.data?.gamma_convexity ?? []} margin={{ top: 12, right: 24, left: 8, bottom: 16 }}>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                    <XAxis dataKey="strike" tick={{ fontSize: 11 }} stroke="#64748b" interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 11 }} stroke="#64748b" width={64} />
                    <Tooltip formatter={(v: number | string | undefined) => [Number(v ?? 0).toFixed(4), 'Convexity']} />
                    <Line dataKey="gamma_convexity" stroke="#a78bfa" dot={false} strokeWidth={2} name="Gamma Convexity" />
                  </LineChart>
                )}
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {chainQuery.error ? (
        <div className="rounded-lg border border-rose-900/60 bg-rose-950/20 px-3 py-2 text-xs text-rose-300">
          Failed to load options chain: {(chainQuery.error as Error).message}
        </div>
      ) : null}

      {(ceChartQuery.error || peChartQuery.error || straddleQuery.error) ? (
        <div className="rounded-lg border border-rose-900/60 bg-rose-950/20 px-3 py-2 text-xs text-rose-300">
          One or more charts could not be loaded. Verify symbol availability or wait for chart backfill to complete.
        </div>
      ) : null}

      {analyticsQuery.error ? (
        <div className="rounded-lg border border-rose-900/60 bg-rose-950/20 px-3 py-2 text-xs text-rose-300">
          Analytics runtime error: {(analyticsQuery.error as Error).message}
        </div>
      ) : null}

      <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 text-[11px] text-slate-500">
        Runtime notes: charts are interval-resampled server-side, RSI thresholds fixed at OB=60 / OS=40, EMA(9,50), BB(20,2), and updates are patch-ready through websocket channels.
      </div>
    </div>
  );
}

'use client';

import { useState, useMemo } from 'react';
import {
  Radar,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Zap,
  BarChart3,
  ArrowUpRight,
  ArrowDownRight,
  AlertCircle,
  Activity,
  Search,
} from 'lucide-react';
import { useScannerResults } from '@/hooks/use-scanner';
import { formatINR, formatNumber } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import type { ScanResult } from '@/hooks/use-scanner';

// ─── Signal badge ─────────────────────────────────────────────────────────────

const SIGNAL_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  strong_breakout:  { bg: 'bg-emerald-500/15', text: 'text-emerald-300', border: 'border-emerald-500/30' },
  breakout:         { bg: 'bg-green-500/10',   text: 'text-green-400',   border: 'border-green-500/20' },
  strong_breakdown: { bg: 'bg-red-500/15',     text: 'text-red-300',     border: 'border-red-500/30' },
  breakdown:        { bg: 'bg-orange-500/10',  text: 'text-orange-400',  border: 'border-orange-500/20' },
  long_buildup:     { bg: 'bg-blue-500/10',    text: 'text-blue-400',    border: 'border-blue-500/20' },
  short_buildup:    { bg: 'bg-purple-500/10',  text: 'text-purple-400',  border: 'border-purple-500/20' },
  volume_spike:     { bg: 'bg-yellow-500/10',  text: 'text-yellow-400',  border: 'border-yellow-500/20' },
  bullish:          { bg: 'bg-teal-500/10',    text: 'text-teal-400',    border: 'border-teal-500/20' },
  bearish:          { bg: 'bg-rose-500/10',    text: 'text-rose-400',    border: 'border-rose-500/20' },
  neutral:          { bg: 'bg-slate-500/10',   text: 'text-slate-400',   border: 'border-slate-500/20' },
};

const SIGNAL_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  strong_breakout:  TrendingUp,
  breakout:         TrendingUp,
  strong_breakdown: TrendingDown,
  breakdown:        TrendingDown,
  long_buildup:     ArrowUpRight,
  short_buildup:    ArrowDownRight,
  volume_spike:     Zap,
  bullish:          TrendingUp,
  bearish:          TrendingDown,
  neutral:          Activity,
};

function SignalBadge({ signal }: { signal: string }) {
  const style = SIGNAL_STYLES[signal] ?? SIGNAL_STYLES['neutral'];
  const Icon = SIGNAL_ICONS[signal] ?? Activity;
  const label = signal.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium', style.bg, style.text, style.border)}>
      <Icon className="h-2.5 w-2.5" />
      {label}
    </span>
  );
}

// ─── Stats bar ────────────────────────────────────────────────────────────────

function StatsBar({ results }: { results: ScanResult[] }) {
  const stats = [
    { label: 'Breakouts',  value: results.filter((r) => r.signal.includes('breakout')).length,  color: 'text-emerald-400' },
    { label: 'Breakdowns', value: results.filter((r) => r.signal.includes('breakdown')).length, color: 'text-red-400' },
    { label: 'Vol Spikes', value: results.filter((r) => r.signal === 'volume_spike').length,    color: 'text-yellow-400' },
    { label: 'OI Buildup', value: results.filter((r) => r.signal.includes('buildup')).length,   color: 'text-blue-400' },
  ];
  return (
    <div className="grid grid-cols-4 gap-3">
      {stats.map((s) => (
        <div key={s.label} className="rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-center">
          <div className={cn('text-2xl font-bold', s.color)}>{s.value}</div>
          <div className="text-[11px] text-slate-500 mt-0.5">{s.label}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Table row ────────────────────────────────────────────────────────────────

function ScannerRow({ result }: { result: ScanResult }) {
  const isUp = result.change_pct >= 0;
  return (
    <tr className="hover:bg-slate-800/30 transition-colors border-b border-slate-800/50">
      <td className="px-4 py-3">
        <div className="font-semibold text-slate-100 text-sm">{result.display_name}</div>
        <div className="text-[10px] text-slate-500 mt-0.5">{result.symbol}</div>
      </td>
      <td className="px-4 py-3 text-right font-mono font-bold text-slate-100">{formatINR(result.ltp)}</td>
      <td className="px-4 py-3 text-right">
        <div className={cn('font-semibold text-sm', isUp ? 'text-emerald-400' : 'text-red-400')}>
          {isUp ? '+' : ''}{result.change_pct.toFixed(2)}%
        </div>
        <div className={cn('text-[10px]', isUp ? 'text-emerald-500' : 'text-red-500')}>
          {isUp ? '+' : ''}{formatINR(result.change)}
        </div>
      </td>
      <td className="px-4 py-3 text-right">
        <div className="text-slate-300 text-sm">{formatNumber(result.volume)}</div>
        {result.volume_ratio !== 1 && (
          <div className={cn('text-[10px]', result.volume_ratio >= 2 ? 'text-yellow-400' : result.volume_ratio >= 1.2 ? 'text-teal-400' : 'text-slate-500')}>
            {result.volume_ratio.toFixed(1)}× avg
          </div>
        )}
      </td>
      <td className="px-4 py-3 text-right">
        {result.oi > 0 ? (
          <>
            <div className="text-slate-300 text-sm">{formatNumber(result.oi)}</div>
            {result.oi_change !== 0 && (
              <div className={cn('text-[10px]', result.oi_change > 0 ? 'text-blue-400' : 'text-rose-400')}>
                {result.oi_change > 0 ? '+' : ''}{result.oi_change_pct.toFixed(1)}%
              </div>
            )}
          </>
        ) : (
          <span className="text-slate-600 text-xs">—</span>
        )}
      </td>
      <td className="px-4 py-3"><SignalBadge signal={result.signal} /></td>
    </tr>
  );
}

// ─── Filter tabs ──────────────────────────────────────────────────────────────

const FILTER_TABS = [
  { id: 'all',       label: 'All',        icon: BarChart3 },
  { id: 'breakout',  label: 'Breakouts',  icon: TrendingUp },
  { id: 'breakdown', label: 'Breakdowns', icon: TrendingDown },
  { id: 'volume',    label: 'Volume',     icon: Zap },
  { id: 'oi',        label: 'OI Buildup', icon: Activity },
  { id: 'indices',   label: 'Indices',    icon: Radar },
];

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ScannerPage() {
  const [filterType, setFilterType] = useState('all');
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState<'signal' | 'change' | 'volume'>('signal');

  const { data, isLoading, isError, refetch, isFetching } = useScannerResults(filterType);

  const results = useMemo(() => {
    let list = data?.results ?? [];
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter((r) => r.display_name.toLowerCase().includes(q) || r.symbol.toLowerCase().includes(q));
    }
    if (sortBy === 'change') list = [...list].sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct));
    else if (sortBy === 'volume') list = [...list].sort((a, b) => b.volume_ratio - a.volume_ratio);
    return list;
  }, [data, search, sortBy]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Radar className="h-6 w-6 text-emerald-400" />
          <div>
            <h1 className="text-xl font-bold text-slate-100">Market Scanner</h1>
            <p className="text-xs text-slate-500">Real-time Nifty 50 signals — auto-refreshes every 15s</p>
          </div>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={cn('h-3 w-3', isFetching && 'animate-spin')} />
          {isFetching ? 'Scanning…' : 'Refresh'}
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex flex-wrap gap-1 rounded-xl border border-slate-800 bg-slate-900/60 p-1 w-fit">
        {FILTER_TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setFilterType(id)}
            className={cn(
              'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
              filterType === id ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200',
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>

      {/* Stats */}
      {!isLoading && !isError && results.length > 0 && <StatsBar results={results} />}

      {/* Table */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-800 p-4 gap-4">
          <div className="flex items-center gap-2 flex-1 max-w-xs">
            <Search className="h-3.5 w-3.5 text-slate-500 shrink-0" />
            <input
              type="text"
              placeholder="Search symbol…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="flex-1 bg-transparent text-xs text-slate-300 placeholder-slate-600 outline-none"
            />
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span>Sort:</span>
            <div className="flex rounded-lg border border-slate-700 overflow-hidden">
              {(['signal', 'change', 'volume'] as const).map((id) => (
                <button
                  key={id}
                  onClick={() => setSortBy(id)}
                  className={cn('px-2.5 py-1 font-medium capitalize', sortBy === id ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200')}
                >
                  {id === 'change' ? '% Change' : id.charAt(0).toUpperCase() + id.slice(1)}
                </button>
              ))}
            </div>
            <span className="text-slate-600 ml-1">{results.length} symbols</span>
          </div>
        </div>

        {isLoading ? (
          <div>{Array.from({ length: 8 }).map((_, i) => <div key={i} className="h-14 animate-pulse border-b border-slate-800/50 bg-slate-900/40" />)}</div>
        ) : isError ? (
          <div className="flex items-center justify-center py-16">
            <div className="text-center">
              <AlertCircle className="mx-auto mb-3 h-8 w-8 text-red-500/60" />
              <p className="text-sm text-slate-400">Failed to load scanner data</p>
            </div>
          </div>
        ) : results.length === 0 ? (
          <div className="flex items-center justify-center py-16">
            <div className="text-center">
              <Radar className="mx-auto mb-3 h-8 w-8 text-slate-600" />
              <p className="text-sm text-slate-400">{data?.note ?? 'No signals match the selected filter'}</p>
              {data?.note && <p className="text-xs text-slate-500 mt-1">Go to Settings to authenticate with Fyers</p>}
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-left text-slate-500">
                  <th className="px-4 py-2.5 font-medium">Symbol</th>
                  <th className="px-4 py-2.5 font-medium text-right">LTP</th>
                  <th className="px-4 py-2.5 font-medium text-right">Change</th>
                  <th className="px-4 py-2.5 font-medium text-right">Volume</th>
                  <th className="px-4 py-2.5 font-medium text-right">OI</th>
                  <th className="px-4 py-2.5 font-medium">Signal</th>
                </tr>
              </thead>
              <tbody>{results.map((r) => <ScannerRow key={r.symbol} result={r} />)}</tbody>
            </table>
          </div>
        )}
      </div>

      {data?.timestamp && (
        <p className="text-center text-[10px] text-slate-600">
          Last scanned: {new Date(data.timestamp).toLocaleTimeString('en-IN')} • Signals based on live Fyers quote data
        </p>
      )}
    </div>
  );
}

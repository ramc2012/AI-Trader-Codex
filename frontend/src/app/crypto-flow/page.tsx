'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import { DollarSign, TrendingUp, Bitcoin, RefreshCw, BarChart3 } from 'lucide-react';
import { cn } from '@/lib/utils';

// ─── Types ────────────────────────────────────────────────────────────────────

interface CorrelationEntry {
  pair: string;
  correlation: number;
  period: string;
}

interface CryptoSnapshotResponse {
  correlations: CorrelationEntry[];
  note?: string;
  timestamp: string;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

function useCryptoSnapshot() {
  return useQuery<CryptoSnapshotResponse>({
    queryKey: ['crypto', 'snapshot'],
    queryFn: () => apiFetch<CryptoSnapshotResponse>('/crypto/snapshot'),
    refetchInterval: 60_000,
  });
}

// ─── Helper ───────────────────────────────────────────────────────────────────

function correlationColor(c: number): string {
  if (c >= 0.4) return 'text-emerald-400';
  if (c >= 0.25) return 'text-teal-400';
  if (c >= 0.1) return 'text-slate-300';
  if (c >= -0.1) return 'text-slate-400';
  if (c >= -0.25) return 'text-orange-400';
  return 'text-red-400';
}

function correlationLabel(c: number): string {
  if (c >= 0.6) return 'Strong +ve';
  if (c >= 0.3) return 'Moderate +ve';
  if (c >= 0.1) return 'Weak +ve';
  if (c >= -0.1) return 'Neutral';
  if (c >= -0.3) return 'Weak -ve';
  return 'Strong -ve';
}

function CorrelationBar({ value }: { value: number }) {
  // Bar spans -1 to +1; we map that to 0-100% width
  const pct = ((value + 1) / 2) * 100;
  const isPos = value >= 0;
  return (
    <div className="relative h-2 w-full rounded-full bg-slate-800 overflow-hidden">
      {/* Center tick */}
      <div className="absolute inset-y-0 left-1/2 w-px bg-slate-600" />
      {isPos ? (
        <div
          className="absolute inset-y-0 left-1/2 rounded-r-full bg-emerald-500/70"
          style={{ width: `${pct - 50}%` }}
        />
      ) : (
        <div
          className="absolute inset-y-0 right-1/2 rounded-l-full bg-red-500/70"
          style={{ width: `${50 - pct}%` }}
        />
      )}
    </div>
  );
}

// ─── Grouped cards ────────────────────────────────────────────────────────────

function CorrelationGroup({
  title,
  icon: Icon,
  entries,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  entries: CorrelationEntry[];
}) {
  // Group by period
  const byPeriod: Record<string, CorrelationEntry[]> = {};
  for (const e of entries) {
    if (!byPeriod[e.period]) byPeriod[e.period] = [];
    byPeriod[e.period].push(e);
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
        <Icon className="h-4 w-4 text-amber-400" />
        <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
      </div>

      <div className="p-4 space-y-4">
        {entries.map((entry) => (
          <div key={`${entry.pair}-${entry.period}`} className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">
                {entry.pair} <span className="text-slate-600">({entry.period})</span>
              </span>
              <div className="flex items-center gap-2">
                <span className="text-slate-500 text-[10px]">{correlationLabel(entry.correlation)}</span>
                <span className={cn('font-mono font-bold', correlationColor(entry.correlation))}>
                  {entry.correlation >= 0 ? '+' : ''}{entry.correlation.toFixed(2)}
                </span>
              </div>
            </div>
            <CorrelationBar value={entry.correlation} />
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CryptoFlowPage() {
  const { data, isLoading, isError, refetch, isFetching } = useCryptoSnapshot();

  // Group correlations by base crypto asset
  const btcEntries = data?.correlations.filter((e) => e.pair.startsWith('BTC')) ?? [];
  const ethEntries = data?.correlations.filter((e) => e.pair.startsWith('ETH')) ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <DollarSign className="h-6 w-6 text-purple-400" />
          <div>
            <h1 className="text-xl font-bold text-slate-100">Crypto Flow</h1>
            <p className="text-xs text-slate-500">
              BTC &amp; ETH correlation against NSE indices
            </p>
          </div>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={cn('h-3 w-3', isFetching && 'animate-spin')} />
          Refresh
        </button>
      </div>

      {/* Explainer */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 text-xs text-slate-400 leading-relaxed">
        <p>
          <span className="text-slate-300 font-medium">Correlation</span> measures how closely crypto markets
          move with Indian equity indices. A value of <span className="text-emerald-400 font-medium">+1.0</span> means
          perfect positive correlation, <span className="text-red-400 font-medium">−1.0</span> means perfect negative
          correlation, and <span className="text-slate-300 font-medium">0</span> means no relationship.
        </p>
        {data?.note && (
          <p className="mt-2 text-amber-400/80">⚠ {data.note}</p>
        )}
      </div>

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={i} className="h-64 animate-pulse rounded-xl border border-slate-800 bg-slate-900/60" />
          ))}
        </div>
      ) : isError ? (
        <div className="flex items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60 py-16">
          <div className="text-center">
            <BarChart3 className="mx-auto mb-3 h-8 w-8 text-slate-600" />
            <p className="text-sm text-slate-400">Failed to load crypto correlation data</p>
          </div>
        </div>
      ) : (
        <>
          {/* Correlation matrix */}
          <div className="grid gap-4 md:grid-cols-2">
            <CorrelationGroup
              title="Bitcoin (BTC)"
              icon={Bitcoin}
              entries={btcEntries}
            />
            <CorrelationGroup
              title="Ethereum (ETH)"
              icon={TrendingUp}
              entries={ethEntries}
            />
          </div>

          {/* Legend */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h4 className="text-xs font-medium text-slate-400 mb-3">Correlation Legend</h4>
            <div className="flex flex-wrap gap-4 text-xs">
              {[
                { range: '0.4 to 1.0', label: 'Strong positive', color: 'text-emerald-400' },
                { range: '0.1 to 0.4', label: 'Moderate positive', color: 'text-teal-400' },
                { range: '-0.1 to 0.1', label: 'Neutral', color: 'text-slate-400' },
                { range: '-0.4 to -0.1', label: 'Moderate negative', color: 'text-orange-400' },
                { range: '-1.0 to -0.4', label: 'Strong negative', color: 'text-red-400' },
              ].map((item) => (
                <div key={item.range} className="flex items-center gap-1.5">
                  <span className={cn('font-mono font-bold', item.color)}>{item.range}</span>
                  <span className="text-slate-500">→ {item.label}</span>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-slate-600 mt-3">
              Last updated: {data?.timestamp ? new Date(data.timestamp).toLocaleTimeString('en-IN') : '—'}
              {' | '}Periods: 30D = 30-day rolling, 90D = 90-day rolling, 1Y = 1-year rolling
            </p>
          </div>
        </>
      )}
    </div>
  );
}

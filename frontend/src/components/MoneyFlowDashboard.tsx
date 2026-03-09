'use client';

import { useMemo } from 'react';
import {
  ArrowUpRight,
  ArrowDownRight,
  TrendingUp,
  TrendingDown,
  DollarSign,
  BarChart3,
  RefreshCw,
} from 'lucide-react';
import { useMoneyFlow } from '@/hooks/use-money-flow';
import { formatINR, formatNumber, formatPercent } from '@/lib/formatters';
import { cn } from '@/lib/utils';

interface MoneyFlowDashboardProps {
  endpoint?: string;
}

/**
 * Reusable money-flow dashboard.
 *
 * Shows:
 *   - Top bar: total net flow, top gainer, top loser
 *   - Sector breakdown table
 *   - Stock table sorted by net_flow descending
 */
export function MoneyFlowDashboard({
  endpoint = '/api/v1/money-flow/snapshot',
}: MoneyFlowDashboardProps) {
  const { data, isLoading, isError, error } = useMoneyFlow(endpoint);

  const sortedStocks = useMemo(() => {
    if (!data?.stocks) return [];
    return [...data.stocks].sort((a, b) => b.net_flow - a.net_flow);
  }, [data]);

  const sortedSectors = useMemo(() => {
    if (!data?.sectors) return [];
    return [...data.sectors].sort((a, b) => b.net_flow - a.net_flow);
  }, [data]);

  // Loading state
  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        {/* Top bar skeleton */}
        <div className="grid grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-24 animate-pulse rounded-xl border border-slate-800 bg-slate-900/60"
            />
          ))}
        </div>
        {/* Table skeleton */}
        <div className="h-64 animate-pulse rounded-xl border border-slate-800 bg-slate-900/60" />
        <div className="h-80 animate-pulse rounded-xl border border-slate-800 bg-slate-900/60" />
      </div>
    );
  }

  // Error state
  if (isError) {
    return (
      <div className="flex items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60 py-16">
        <div className="text-center">
          <BarChart3 className="mx-auto mb-3 h-8 w-8 text-slate-600" />
          <p className="text-sm text-slate-400">
            Failed to load money flow data
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {error instanceof Error ? error.message : 'Unknown error'}
          </p>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const totalNetFlow = Number.isFinite(data.total_net_flow) ? data.total_net_flow : 0;
  const totalPositive = totalNetFlow >= 0;
  const source = (data as { source?: string }).source ?? 'unknown';

  return (
    <div className="flex flex-col gap-4">
      {/* ── Top summary cards ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* Total Net Flow */}
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-slate-500">
            <DollarSign className="h-3.5 w-3.5" />
            Total Net Flow
          </div>
          <div className="flex items-baseline gap-2">
            <span
              className={cn(
                'font-mono text-2xl font-bold',
                totalPositive ? 'text-emerald-400' : 'text-red-400'
              )}
            >
              {totalPositive ? '+' : ''}
              {formatINR(totalNetFlow)}
            </span>
            {totalPositive ? (
              <ArrowUpRight className="h-5 w-5 text-emerald-400" />
            ) : (
              <ArrowDownRight className="h-5 w-5 text-red-400" />
            )}
          </div>
          <div className="mt-1 text-xs text-slate-500">
            {data.timestamp
              ? new Date(data.timestamp).toLocaleTimeString('en-IN', {
                  timeZone: 'Asia/Kolkata',
                  hour: '2-digit',
                  minute: '2-digit',
                  hour12: false,
                })
              : ''}
            <span className="ml-2 uppercase">{source.replaceAll('_', ' ')}</span>
          </div>
        </div>

        {/* Top Gainer */}
        {data.top_gainer && (
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-slate-500">
              <TrendingUp className="h-3.5 w-3.5 text-emerald-500" />
              Top Gainer
            </div>
            <div className="text-sm font-semibold text-slate-100">
              {data.top_gainer.symbol}
            </div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="font-mono text-lg font-bold text-emerald-400">
                +{formatINR(data.top_gainer.net_flow)}
              </span>
              <span className="text-xs text-emerald-400/70">
                {formatPercent(data.top_gainer.change_pct)}
              </span>
            </div>
            <div className="mt-1 font-mono text-xs text-slate-500">
              LTP {formatINR(data.top_gainer.ltp)}
            </div>
          </div>
        )}

        {/* Top Loser */}
        {data.top_loser && (
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-slate-500">
              <TrendingDown className="h-3.5 w-3.5 text-red-500" />
              Top Loser
            </div>
            <div className="text-sm font-semibold text-slate-100">
              {data.top_loser.symbol}
            </div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="font-mono text-lg font-bold text-red-400">
                {formatINR(data.top_loser.net_flow)}
              </span>
              <span className="text-xs text-red-400/70">
                {formatPercent(data.top_loser.change_pct)}
              </span>
            </div>
            <div className="mt-1 font-mono text-xs text-slate-500">
              LTP {formatINR(data.top_loser.ltp)}
            </div>
          </div>
        )}
      </div>

      {/* ── Sector breakdown ──────────────────────────────────────────────── */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60">
        <div className="border-b border-slate-800 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-200">
            Sector Breakdown
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[500px]">
            <thead>
              <tr className="border-b border-slate-800 text-left text-[11px] font-medium uppercase tracking-wider text-slate-500">
                <th className="px-4 py-2.5">Sector</th>
                <th className="px-4 py-2.5 text-right">Net Flow</th>
                <th className="px-4 py-2.5 text-right">Stocks</th>
                <th className="px-4 py-2.5">Top Gainer</th>
                <th className="px-4 py-2.5">Top Loser</th>
              </tr>
            </thead>
            <tbody>
              {sortedSectors.map((sector) => {
                const isPositive = sector.net_flow >= 0;
                return (
                  <tr
                    key={sector.sector}
                    className="border-b border-slate-800/50 transition-colors hover:bg-slate-800/30"
                  >
                    <td className="px-4 py-2.5 text-sm font-medium text-slate-200">
                      {sector.sector}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span
                        className={cn(
                          'font-mono text-sm font-semibold',
                          isPositive ? 'text-emerald-400' : 'text-red-400'
                        )}
                      >
                        {isPositive ? '+' : ''}
                        {formatINR(sector.net_flow)}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-sm text-slate-400">
                      {sector.stock_count}
                    </td>
                    <td className="px-4 py-2.5 text-sm text-emerald-400/80">
                      {sector.top_gainer || '—'}
                    </td>
                    <td className="px-4 py-2.5 text-sm text-red-400/80">
                      {sector.top_loser || '—'}
                    </td>
                  </tr>
                );
              })}
              {sortedSectors.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-8 text-center text-sm text-slate-500"
                  >
                    No sector data available
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Stock table ───────────────────────────────────────────────────── */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60">
        <div className="border-b border-slate-800 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-200">
            Stock-Level Flows
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[700px]">
            <thead>
              <tr className="border-b border-slate-800 text-left text-[11px] font-medium uppercase tracking-wider text-slate-500">
                <th className="px-4 py-2.5">Symbol</th>
                <th className="px-4 py-2.5 text-right">LTP</th>
                <th className="px-4 py-2.5 text-right">Change %</th>
                <th className="px-4 py-2.5 text-right">Volume</th>
                <th className="px-4 py-2.5 text-right">Net Flow</th>
              </tr>
            </thead>
            <tbody>
              {sortedStocks.map((stock) => {
                const isUp = stock.change_pct >= 0;
                const flowPositive = stock.net_flow >= 0;
                return (
                  <tr
                    key={stock.symbol}
                    className="border-b border-slate-800/50 transition-colors hover:bg-slate-800/30"
                  >
                    <td className="px-4 py-2.5">
                      <div className="text-sm font-medium text-slate-200">
                        {stock.symbol}
                      </div>
                      {stock.name && (
                        <div className="text-[11px] text-slate-500">
                          {stock.name}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-sm text-slate-200">
                      {formatINR(stock.ltp)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span
                        className={cn(
                          'inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 font-mono text-xs font-semibold',
                          isUp
                            ? 'bg-emerald-500/10 text-emerald-400'
                            : 'bg-red-500/10 text-red-400'
                        )}
                      >
                        {isUp ? (
                          <ArrowUpRight className="h-3 w-3" />
                        ) : (
                          <ArrowDownRight className="h-3 w-3" />
                        )}
                        {Math.abs(stock.change_pct).toFixed(2)}%
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-sm text-slate-400">
                      {formatNumber(stock.volume)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span
                        className={cn(
                          'font-mono text-sm font-semibold',
                          flowPositive ? 'text-emerald-400' : 'text-red-400'
                        )}
                      >
                        {flowPositive ? '+' : ''}
                        {formatINR(stock.net_flow)}
                      </span>
                    </td>
                  </tr>
                );
              })}
              {sortedStocks.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-8 text-center text-sm text-slate-500"
                  >
                    No stock data available
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default MoneyFlowDashboard;

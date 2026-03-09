'use client';

import { useMemo } from 'react';
import {
  Activity,
  TrendingUp,
  TrendingDown,
  RefreshCw,
  ArrowUpRight,
  ArrowDownRight,
  BarChart3,
  Eye,
} from 'lucide-react';
import { useOIQuadrants, useATMWatchlist } from '@/hooks/use-oi';
import type { QuadrantSymbol, ATMOption } from '@/hooks/use-oi';
import { formatINR, formatPercent, formatNumber } from '@/lib/formatters';
import { cn } from '@/lib/utils';

// ─── Quadrant card config ─────────────────────────────────────────────────────

interface QuadrantConfig {
  key: 'long_buildup' | 'short_buildup' | 'short_covering' | 'long_unwinding';
  label: string;
  description: string;
  colorClass: string;
  bgClass: string;
  borderClass: string;
  badgeClass: string;
  icon: typeof TrendingUp;
}

const QUADRANTS: QuadrantConfig[] = [
  {
    key: 'long_buildup',
    label: 'Long Buildup',
    description: 'Price up + OI up',
    colorClass: 'text-emerald-400',
    bgClass: 'bg-emerald-500/5',
    borderClass: 'border-emerald-500/20',
    badgeClass: 'bg-emerald-500/10 text-emerald-400',
    icon: TrendingUp,
  },
  {
    key: 'short_buildup',
    label: 'Short Buildup',
    description: 'Price down + OI up',
    colorClass: 'text-red-400',
    bgClass: 'bg-red-500/5',
    borderClass: 'border-red-500/20',
    badgeClass: 'bg-red-500/10 text-red-400',
    icon: TrendingDown,
  },
  {
    key: 'short_covering',
    label: 'Short Covering',
    description: 'Price up + OI down',
    colorClass: 'text-cyan-400',
    bgClass: 'bg-cyan-500/5',
    borderClass: 'border-cyan-500/20',
    badgeClass: 'bg-cyan-500/10 text-cyan-400',
    icon: ArrowUpRight,
  },
  {
    key: 'long_unwinding',
    label: 'Long Unwinding',
    description: 'Price down + OI down',
    colorClass: 'text-amber-400',
    bgClass: 'bg-amber-500/5',
    borderClass: 'border-amber-500/20',
    badgeClass: 'bg-amber-500/10 text-amber-400',
    icon: ArrowDownRight,
  },
];

// ─── Quadrant card component ──────────────────────────────────────────────────

function QuadrantCard({
  config,
  symbols,
}: {
  config: QuadrantConfig;
  symbols: QuadrantSymbol[];
}) {
  const Icon = config.icon;

  return (
    <div
      className={cn(
        'flex flex-col rounded-xl border',
        config.borderClass,
        config.bgClass
      )}
    >
      {/* Card header */}
      <div className="flex items-center justify-between border-b border-slate-800/50 px-4 py-3">
        <div className="flex items-center gap-2">
          <Icon className={cn('h-4 w-4', config.colorClass)} />
          <div>
            <div className={cn('text-sm font-semibold', config.colorClass)}>
              {config.label}
            </div>
            <div className="text-[10px] text-slate-500">{config.description}</div>
          </div>
        </div>
        <span
          className={cn(
            'rounded-full px-2 py-0.5 text-[10px] font-semibold',
            config.badgeClass
          )}
        >
          {symbols.length}
        </span>
      </div>

      {/* Table */}
      <div className="max-h-[280px] overflow-y-auto">
        <table className="w-full">
          <thead>
            <tr className="text-left text-[10px] font-medium uppercase tracking-wider text-slate-500">
              <th className="px-3 py-2">Symbol</th>
              <th className="px-3 py-2 text-right">Price Chg%</th>
              <th className="px-3 py-2 text-right">OI Chg%</th>
            </tr>
          </thead>
          <tbody>
            {symbols.length === 0 && (
              <tr>
                <td
                  colSpan={3}
                  className="px-3 py-6 text-center text-xs text-slate-500"
                >
                  No symbols in this quadrant
                </td>
              </tr>
            )}
            {symbols.map((sym) => {
              const priceUp = sym.price_change_pct >= 0;
              const oiUp = sym.oi_change_pct >= 0;
              return (
                <tr
                  key={sym.symbol}
                  className="border-t border-slate-800/30 transition-colors hover:bg-slate-800/20"
                >
                  <td className="px-3 py-1.5 text-xs font-medium text-slate-200">
                    {sym.symbol}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <span
                      className={cn(
                        'font-mono text-xs font-semibold',
                        priceUp ? 'text-emerald-400' : 'text-red-400'
                      )}
                    >
                      {priceUp ? '+' : ''}
                      {sym.price_change_pct.toFixed(2)}%
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <span
                      className={cn(
                        'font-mono text-xs font-semibold',
                        oiUp ? 'text-emerald-400' : 'text-red-400'
                      )}
                    >
                      {oiUp ? '+' : ''}
                      {sym.oi_change_pct.toFixed(2)}%
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── ATM Watchlist sidebar ────────────────────────────────────────────────────

function ATMSidebar({ entries }: { entries: ATMOption[] }) {
  if (entries.length === 0) {
    return (
      <div className="flex h-full items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-12">
        <div className="text-center">
          <Eye className="mx-auto mb-2 h-6 w-6 text-slate-600" />
          <p className="text-xs text-slate-500">No ATM data</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col rounded-xl border border-slate-800 bg-slate-900/60">
      <div className="border-b border-slate-800 px-4 py-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <Eye className="h-4 w-4 text-blue-400" />
          ATM Watchlist
        </h3>
        <p className="mt-0.5 text-[10px] text-slate-500">
          At-the-money options for indices and stocks
        </p>
      </div>

      <div className="max-h-[640px] overflow-y-auto">
        {entries.map((entry) => {
          const pcrColor =
            entry.pcr > 1.2
              ? 'text-emerald-400'
              : entry.pcr < 0.8
                ? 'text-red-400'
                : 'text-slate-300';

          return (
            <div
              key={entry.symbol}
              className="border-b border-slate-800/30 px-4 py-3 transition-colors hover:bg-slate-800/20"
            >
              {/* Symbol header */}
              <div className="mb-2 flex items-baseline justify-between">
                <div>
                  <span className="text-sm font-semibold text-slate-100">
                    {entry.display_name}
                  </span>
                  <span className="ml-2 font-mono text-xs text-slate-400">
                    Spot {formatINR(entry.spot)}
                  </span>
                </div>
                <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                  ATM {entry.atm_strike}
                </span>
              </div>

              {/* CE / PE row */}
              <div className="grid grid-cols-2 gap-3">
                {/* CE */}
                <div className="rounded-lg border border-emerald-500/10 bg-emerald-500/5 px-2.5 py-1.5">
                  <div className="mb-1 text-[10px] font-medium uppercase text-emerald-500/70">
                    CE
                  </div>
                  <div className="font-mono text-xs font-semibold text-emerald-300">
                    {formatINR(entry.ce_ltp)}
                  </div>
                  <div className="mt-0.5 flex justify-between font-mono text-[10px] text-slate-500">
                    <span>OI {formatNumber(entry.ce_oi)}</span>
                    <span>IV {entry.ce_iv.toFixed(1)}%</span>
                  </div>
                </div>

                {/* PE */}
                <div className="rounded-lg border border-red-500/10 bg-red-500/5 px-2.5 py-1.5">
                  <div className="mb-1 text-[10px] font-medium uppercase text-red-500/70">
                    PE
                  </div>
                  <div className="font-mono text-xs font-semibold text-red-300">
                    {formatINR(entry.pe_ltp)}
                  </div>
                  <div className="mt-0.5 flex justify-between font-mono text-[10px] text-slate-500">
                    <span>OI {formatNumber(entry.pe_oi)}</span>
                    <span>IV {entry.pe_iv.toFixed(1)}%</span>
                  </div>
                </div>
              </div>

              {/* Footer: PCR + Straddle */}
              <div className="mt-2 flex items-center justify-between text-[10px]">
                <span className="text-slate-500">
                  PCR{' '}
                  <span className={cn('font-mono font-semibold', pcrColor)}>
                    {entry.pcr.toFixed(2)}
                  </span>
                </span>
                <span className="text-slate-500">
                  Straddle{' '}
                  <span className="font-mono font-semibold text-slate-300">
                    {formatINR(entry.straddle_price)}
                  </span>
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function OIDashboardPage() {
  const {
    data: quadrants,
    isLoading: qLoading,
    isError: qError,
  } = useOIQuadrants();

  const {
    data: atm,
    isLoading: aLoading,
  } = useATMWatchlist();

  const isLoading = qLoading || aLoading;

  return (
    <div className="flex flex-col gap-4">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div>
        <h2 className="flex items-center gap-2 text-xl font-bold text-slate-100">
          <BarChart3 className="h-5 w-5 text-blue-400" />
          OI Dashboard
        </h2>
        <p className="text-xs text-slate-500">
          Open interest analysis across quadrants with ATM watchlist
        </p>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <RefreshCw className="h-3.5 w-3.5 animate-spin" />
          Loading OI data...
        </div>
      )}

      {qError && (
        <div className="rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-400">
          Failed to load OI quadrant data. The API may be unavailable.
        </div>
      )}

      {/* ── Main layout: quadrants + sidebar ───────────────────────────── */}
      <div className="flex gap-4">
        {/* Left: 2x2 quadrant grid */}
        <div className="flex-1">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {QUADRANTS.map((config) => {
              const symbols = quadrants?.[config.key] ?? [];
              return (
                <QuadrantCard
                  key={config.key}
                  config={config}
                  symbols={symbols}
                />
              );
            })}
          </div>

          {/* Timestamp */}
          {quadrants?.timestamp && (
            <div className="mt-3 text-right text-[10px] text-slate-500">
              Last updated:{' '}
              {new Date(quadrants.timestamp).toLocaleTimeString('en-IN', {
                timeZone: 'Asia/Kolkata',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false,
              })}
            </div>
          )}
        </div>

        {/* Right: ATM Watchlist sidebar */}
        <div className="hidden w-[340px] flex-shrink-0 xl:block">
          <ATMSidebar entries={atm?.entries ?? []} />
        </div>
      </div>

      {/* Mobile ATM section (shown below quadrants on small screens) */}
      <div className="xl:hidden">
        <ATMSidebar entries={atm?.entries ?? []} />
      </div>
    </div>
  );
}

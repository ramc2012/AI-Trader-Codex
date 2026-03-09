'use client';

import { type ReactNode, useMemo, useState } from 'react';
import { BarChart3, Clock3, Layers3, RefreshCw, Trophy } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { usePortfolio, usePortfolioInstruments } from '@/hooks/use-portfolio';
import { apiFetch } from '@/lib/api';
import { formatCurrency, formatDateTime, formatNumber, formatPercent } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import type { EquitySnapshot, PortfolioPeriod } from '@/types/api';

type PortfolioTab = 'analytics' | 'instruments';

const PERIODS: Array<{ key: PortfolioPeriod; label: string }> = [
  { key: 'daily', label: 'Daily' },
  { key: 'week', label: 'Week' },
  { key: 'month', label: 'Month' },
  { key: 'year', label: 'Year' },
];

function marketFromSymbol(symbol: string): string {
  const token = String(symbol || '').toUpperCase();
  if (token.startsWith('CRYPTO:')) return 'CRYPTO';
  if (token.startsWith('US:') || token.startsWith('NASDAQ:') || token.startsWith('NYSE:') || token.startsWith('AMEX:')) return 'US';
  if (token.startsWith('BSE:')) return 'BSE';
  return 'NSE';
}

function MiniCard({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: string;
  tone?: 'default' | 'positive' | 'negative';
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/75 px-4 py-3">
      <div className="text-[10px] uppercase tracking-[0.22em] text-slate-500">{label}</div>
      <div
        className={cn(
          'mt-2 text-xl font-semibold',
          tone === 'positive'
            ? 'text-emerald-300'
            : tone === 'negative'
              ? 'text-rose-300'
              : 'text-slate-100'
        )}
      >
        {value}
      </div>
    </div>
  );
}

function TabButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-xl border px-3 py-2 text-sm transition-colors',
        active
          ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-200'
          : 'border-slate-800 bg-slate-950/70 text-slate-400 hover:border-slate-700 hover:text-slate-200'
      )}
    >
      {label}
    </button>
  );
}

function BarMeter({
  value,
  tone,
}: {
  value: number;
  tone: 'emerald' | 'rose' | 'sky' | 'amber';
}) {
  const color =
    tone === 'emerald'
      ? 'bg-emerald-400'
      : tone === 'rose'
        ? 'bg-rose-400'
        : tone === 'amber'
          ? 'bg-amber-400'
          : 'bg-sky-400';
  return (
    <div className="h-2 overflow-hidden rounded-full bg-slate-800">
      <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${Math.min(Math.max(value, 4), 100)}%` }} />
    </div>
  );
}

export default function PortfolioSummaryPage() {
  const [period, setPeriod] = useState<PortfolioPeriod>('daily');
  const [activeTab, setActiveTab] = useState<PortfolioTab>('analytics');
  const { data: portfolio } = usePortfolio();
  const { data, isLoading, isFetching, error, refetch } = usePortfolioInstruments(period);
  const { data: equityCurve } = useQuery<EquitySnapshot[]>({
    queryKey: ['portfolio', 'equity-curve', period],
    queryFn: () => apiFetch<EquitySnapshot[]>('/portfolio/equity-curve'),
    refetchInterval: 5000,
    staleTime: 2500,
  });

  const rows = useMemo(() => data?.rows ?? [], [data?.rows]);
  const orderedByNet = useMemo(() => [...rows].sort((left, right) => right.net_pnl_inr - left.net_pnl_inr), [rows]);
  const orderedByExposure = useMemo(
    () => [...rows].sort((left, right) => right.open_market_value_inr - left.open_market_value_inr),
    [rows]
  );

  const totals = useMemo(() => {
    const totalWins = rows.reduce((sum, row) => sum + row.wins, 0);
    const totalTrades = rows.reduce((sum, row) => sum + row.trades, 0);
    return {
      trades: totalTrades,
      instruments: rows.length,
      winRate: totalTrades ? (totalWins / totalTrades) * 100 : 0,
      net: data?.total_net_pnl_inr ?? 0,
      realized: data?.total_realized_pnl_inr ?? 0,
      unrealized: data?.total_unrealized_pnl_inr ?? 0,
    };
  }, [data, rows]);

  const equityStats = useMemo(() => {
    const points = equityCurve ?? [];
    if (!points.length) {
      return null;
    }
    const start = points[0]?.value ?? 0;
    const end = points[points.length - 1]?.value ?? 0;
    const peak = Math.max(...points.map((point) => point.value));
    const trough = Math.min(...points.map((point) => point.value));
    const changePct = start > 0 ? ((end - start) / start) * 100 : 0;
    return { start, end, peak, trough, changePct };
  }, [equityCurve]);

  const marketCards = useMemo(() => {
    const breakdown = portfolio?.market_breakdown ?? {};
    const totalValue = Math.max(portfolio?.total_market_value_inr ?? 0, 1);
    return Object.entries(breakdown)
      .map(([market, row]) => ({
        market,
        label: market === 'CRYPTO' ? 'Crypto' : market === 'US' ? 'US' : 'India',
        openPositions: Number(row.open_positions ?? 0),
        netPnl: Number(row.net_pnl_inr ?? 0),
        value: Number(row.market_value_inr ?? 0),
        exposurePct: (Number(row.market_value_inr ?? 0) / totalValue) * 100,
      }))
      .sort((left, right) => right.value - left.value);
  }, [portfolio]);

  const best = orderedByNet[0];
  const worst = orderedByNet[orderedByNet.length - 1];
  const largestExposure = orderedByExposure[0];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-semibold text-slate-100">Portfolio</h2>
            <span
              className={cn(
                'inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em]',
                isFetching
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
                  : 'border-slate-800 bg-slate-950/80 text-slate-400'
              )}
            >
              <span className={cn('h-1.5 w-1.5 rounded-full', isFetching ? 'bg-emerald-400' : 'bg-slate-500')} />
              {isFetching ? 'Refreshing' : 'Stable'}
            </span>
          </div>
          {data && (
            <div className="text-xs text-slate-500">
              {formatDateTime(data.from_time)} IST to {formatDateTime(data.to_time)} IST
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1 rounded-xl border border-slate-800 bg-slate-950/70 p-1">
            {PERIODS.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setPeriod(item.key)}
                className={cn(
                  'rounded-lg px-3 py-1.5 text-xs transition-colors',
                  item.key === period
                    ? 'bg-emerald-500/10 text-emerald-200'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => refetch()}
            className="inline-flex items-center gap-1 rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2 text-sm text-slate-400 hover:border-slate-700 hover:text-slate-200"
          >
            <RefreshCw className={cn('h-4 w-4', isFetching && 'animate-spin')} />
            Refresh
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <TabButton active={activeTab === 'analytics'} label="Analytics" onClick={() => setActiveTab('analytics')} />
        <TabButton active={activeTab === 'instruments'} label="Instruments" onClick={() => setActiveTab('instruments')} />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MiniCard label="Net P&L" value={formatCurrency(totals.net, 'INR')} tone={totals.net >= 0 ? 'positive' : 'negative'} />
        <MiniCard label="Realized" value={formatCurrency(totals.realized, 'INR')} tone={totals.realized >= 0 ? 'positive' : 'negative'} />
        <MiniCard label="Unrealized" value={formatCurrency(totals.unrealized, 'INR')} tone={totals.unrealized >= 0 ? 'positive' : 'negative'} />
        <MiniCard label="Win Rate" value={formatPercent(totals.winRate, 1)} tone={totals.winRate >= 50 ? 'positive' : 'negative'} />
      </div>

      {activeTab === 'analytics' ? (
        <div className="space-y-5">
          <section className="grid grid-cols-1 gap-4 xl:grid-cols-4">
            <AnalyticsTile
              title="Top Winner"
              value={best ? formatCurrency(best.net_pnl_inr, 'INR') : '--'}
              detail={best ? best.symbol : 'No data'}
              tone={best && best.net_pnl_inr >= 0 ? 'positive' : 'default'}
              icon={<Trophy className="h-4 w-4 text-emerald-300" />}
            />
            <AnalyticsTile
              title="Top Drag"
              value={worst ? formatCurrency(worst.net_pnl_inr, 'INR') : '--'}
              detail={worst ? worst.symbol : 'No data'}
              tone={worst && worst.net_pnl_inr < 0 ? 'negative' : 'default'}
              icon={<BarChart3 className="h-4 w-4 text-rose-300" />}
            />
            <AnalyticsTile
              title="Largest Exposure"
              value={largestExposure ? formatCurrency(largestExposure.open_market_value_inr, 'INR') : '--'}
              detail={largestExposure ? largestExposure.symbol : 'No open exposure'}
              icon={<Layers3 className="h-4 w-4 text-sky-300" />}
            />
            <AnalyticsTile
              title="Equity Trend"
              value={equityStats ? formatPercent(equityStats.changePct, 2) : '--'}
              detail={
                equityStats
                  ? `Peak ${formatCurrency(equityStats.peak, 'INR')} · Low ${formatCurrency(equityStats.trough, 'INR')}`
                  : 'No curve data'
              }
              tone={equityStats && equityStats.changePct >= 0 ? 'positive' : 'negative'}
              icon={<Clock3 className="h-4 w-4 text-amber-300" />}
            />
          </section>

          <section className="rounded-[28px] border border-slate-800 bg-slate-900/70 p-5">
            <div className="mb-4 flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-slate-400" />
              <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-300">Market Analytics</h3>
            </div>
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
              {marketCards.map((item) => (
                <div key={item.market} className="rounded-2xl border border-slate-800 bg-slate-950/75 p-4">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold text-slate-100">{item.label}</div>
                    <div className="text-xs text-slate-500">{item.openPositions} open</div>
                  </div>
                  <div className="mt-3 text-lg font-semibold text-slate-100">{formatCurrency(item.value, 'INR')}</div>
                  <div className={cn('mt-1 text-sm', item.netPnl >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
                    {formatCurrency(item.netPnl, 'INR')}
                  </div>
                  <div className="mt-3 space-y-2">
                    <BarMeter value={item.exposurePct} tone={item.netPnl >= 0 ? 'emerald' : 'rose'} />
                    <div className="text-xs text-slate-500">Exposure {formatPercent(item.exposurePct, 1)}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <AnalyticsList
              title="Leaders"
              rows={orderedByNet.slice(0, 5)}
              value={(row) => formatCurrency(row.net_pnl_inr, 'INR')}
              tone={(row) => (row.net_pnl_inr >= 0 ? 'positive' : 'negative')}
            />
            <AnalyticsList
              title="Draggers"
              rows={[...orderedByNet].reverse().slice(0, 5)}
              value={(row) => formatCurrency(row.net_pnl_inr, 'INR')}
              tone={(row) => (row.net_pnl_inr >= 0 ? 'positive' : 'negative')}
            />
            <AnalyticsList
              title="Open Exposure"
              rows={orderedByExposure.slice(0, 5)}
              value={(row) => formatCurrency(row.open_market_value_inr, 'INR')}
              tone={() => 'default'}
              secondary={(row) => `${formatNumber(row.open_quantity)} open · ${marketFromSymbol(row.symbol)}`}
            />
          </section>
        </div>
      ) : (
        <section className="rounded-[28px] border border-slate-800 bg-slate-900/70 p-5">
          {isLoading ? (
            <div className="grid gap-3">
              {Array.from({ length: 7 }).map((_, index) => (
                <div key={index} className="h-14 animate-pulse rounded-2xl bg-slate-800/60" />
              ))}
            </div>
          ) : error ? (
            <div className="rounded-2xl border border-rose-500/20 bg-rose-500/5 px-4 py-10 text-center text-sm text-rose-300">
              Failed to load portfolio summary
            </div>
          ) : !rows.length ? (
            <div className="rounded-2xl border border-dashed border-slate-800 px-4 py-10 text-center text-sm text-slate-500">
              No data available for this period
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1180px] text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                    <th className="pb-3 pr-4 font-medium">Instrument</th>
                    <th className="pb-3 pr-4 text-right font-medium">Trades</th>
                    <th className="pb-3 pr-4 text-right font-medium">Win Rate</th>
                    <th className="pb-3 pr-4 text-right font-medium">Realized</th>
                    <th className="pb-3 pr-4 text-right font-medium">Unrealized</th>
                    <th className="pb-3 pr-4 text-right font-medium">Net</th>
                    <th className="pb-3 pr-4 text-right font-medium">Open Exposure</th>
                    <th className="pb-3 pr-4 text-right font-medium">Avg Hold</th>
                    <th className="pb-3 font-medium">Last Trade</th>
                  </tr>
                </thead>
                <tbody>
                  {orderedByNet.map((row) => {
                    const winRate = row.trades ? (row.wins / row.trades) * 100 : 0;
                    return (
                      <tr key={row.symbol} className="border-b border-slate-800/80 text-slate-300">
                        <td className="py-4 pr-4">
                          <div className="font-medium text-slate-100">{row.symbol}</div>
                          <div className="mt-1 text-xs text-slate-500">
                            {marketFromSymbol(row.symbol)} · {row.currency} (FX {row.fx_to_inr.toFixed(2)})
                          </div>
                        </td>
                        <td className="py-4 pr-4 text-right">{formatNumber(row.trades)}</td>
                        <td className="py-4 pr-4 text-right">
                          <div className={cn(winRate >= 50 ? 'text-emerald-300' : 'text-rose-300')}>
                            {formatPercent(winRate, 1)}
                          </div>
                          <div className="text-xs text-slate-500">
                            {formatNumber(row.wins)}/{formatNumber(row.losses)}
                          </div>
                        </td>
                        <td className="py-4 pr-4 text-right">{formatCurrency(row.realized_pnl_inr, 'INR')}</td>
                        <td className="py-4 pr-4 text-right">{formatCurrency(row.unrealized_pnl_inr, 'INR')}</td>
                        <td className={cn('py-4 pr-4 text-right font-medium', row.net_pnl_inr >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
                          {formatCurrency(row.net_pnl_inr, 'INR')}
                        </td>
                        <td className="py-4 pr-4 text-right">
                          <div className="text-slate-100">{formatCurrency(row.open_market_value_inr, 'INR')}</div>
                          <div className="text-xs text-slate-500">{formatNumber(row.open_quantity)} open</div>
                        </td>
                        <td className="py-4 pr-4 text-right">{formatNumber(row.avg_hold_minutes, 1)}m</td>
                        <td className="py-4 text-xs text-slate-400">
                          {row.last_trade_time ? formatDateTime(row.last_trade_time) : '--'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function AnalyticsTile({
  title,
  value,
  detail,
  icon,
  tone = 'default',
}: {
  title: string;
  value: string;
  detail: string;
  icon: ReactNode;
  tone?: 'default' | 'positive' | 'negative';
}) {
  return (
    <div className="rounded-[28px] border border-slate-800 bg-slate-900/70 p-5">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-[0.22em] text-slate-500">{title}</div>
        {icon}
      </div>
      <div
        className={cn(
          'mt-3 text-2xl font-semibold',
          tone === 'positive'
            ? 'text-emerald-300'
            : tone === 'negative'
              ? 'text-rose-300'
              : 'text-slate-100'
        )}
      >
        {value}
      </div>
      <div className="mt-2 text-sm text-slate-500">{detail}</div>
    </div>
  );
}

function AnalyticsList({
  title,
  rows,
  value,
  tone,
  secondary,
}: {
  title: string;
  rows: Array<{
    symbol: string;
    net_pnl_inr: number;
    open_market_value_inr: number;
    open_quantity: number;
  }>;
  value: (row: {
    symbol: string;
    net_pnl_inr: number;
    open_market_value_inr: number;
    open_quantity: number;
  }) => string;
  tone: (row: {
    symbol: string;
    net_pnl_inr: number;
    open_market_value_inr: number;
    open_quantity: number;
  }) => 'default' | 'positive' | 'negative';
  secondary?: (row: {
    symbol: string;
    net_pnl_inr: number;
    open_market_value_inr: number;
    open_quantity: number;
  }) => string;
}) {
  return (
    <div className="rounded-[28px] border border-slate-800 bg-slate-900/70 p-5">
      <div className="mb-4 text-sm font-semibold uppercase tracking-[0.2em] text-slate-300">{title}</div>
      <div className="space-y-3">
        {rows.map((row) => (
          <div key={`${title}-${row.symbol}`} className="rounded-2xl border border-slate-800 bg-slate-950/75 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="font-medium text-slate-100">{row.symbol}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {secondary ? secondary(row) : marketFromSymbol(row.symbol)}
                </div>
              </div>
              <div
                className={cn(
                  'text-sm font-medium',
                  tone(row) === 'positive'
                    ? 'text-emerald-300'
                    : tone(row) === 'negative'
                      ? 'text-rose-300'
                      : 'text-slate-200'
                )}
              >
                {value(row)}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

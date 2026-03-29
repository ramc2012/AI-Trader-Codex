'use client';

import { type ReactNode, useMemo, useState } from 'react';
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Clock3,
  History,
  Shield,
  Target,
  X,
} from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
import { useOrderPairs } from '@/hooks/use-orders';
import { usePortfolio } from '@/hooks/use-portfolio';
import { usePositions } from '@/hooks/use-positions';
import { usePositionsWS } from '@/hooks/use-positions-ws';
import { useDashboardWS } from '@/hooks/use-dashboard-ws';
import { formatCurrency, formatDateTime, formatNumber, formatPercent } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import type { PortfolioSummary, Position, TradePair } from '@/types/api';

type PositionsTab = 'positions' | 'history';

const MARKET_LABELS: Record<string, string> = {
  NSE: 'India',
  BSE: 'India',
  US: 'US',
  CRYPTO: 'Crypto',
};

function formatTimeLeft(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) {
    return '--';
  }
  const total = Math.max(seconds, 0);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
}

function formatDuration(entryTime?: string | null, exitTime?: string | null): string {
  if (!entryTime || !exitTime) {
    return '--';
  }
  const start = new Date(entryTime).getTime();
  const end = new Date(exitTime).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    return '--';
  }
  const totalMinutes = Math.round((end - start) / 60000);
  if (totalMinutes < 60) {
    return `${totalMinutes}m`;
  }
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${hours}h ${minutes}m`;
}

function marketPriority(market: string): number {
  const token = String(market || '').toUpperCase();
  if (token === 'CRYPTO') return 0;
  if (token === 'NSE' || token === 'BSE') return 1;
  if (token === 'US') return 2;
  return 3;
}

function isLongPosition(position: Position): boolean {
  const side = String(position.side || '').toUpperCase();
  return side === 'LONG' || side === 'BUY';
}

function positionMovePct(position: Position): number {
  if (position.avg_price <= 0) {
    return 0;
  }
  const raw = ((position.current_price - position.avg_price) / position.avg_price) * 100;
  return raw * (isLongPosition(position) ? 1 : -1);
}

function sortPositions(rows: Position[]): Position[] {
  return [...rows].sort((left, right) => {
    if (left.market_open !== right.market_open) {
      return left.market_open ? -1 : 1;
    }
    const marketDelta = marketPriority(left.market) - marketPriority(right.market);
    if (marketDelta !== 0) {
      return marketDelta;
    }
    const pnlLeft = Math.abs(left.unrealized_pnl_inr ?? left.unrealized_pnl ?? 0);
    const pnlRight = Math.abs(right.unrealized_pnl_inr ?? right.unrealized_pnl ?? 0);
    return pnlRight - pnlLeft;
  });
}

function tradeActivityTime(row: TradePair): number {
  const stamp = row.exit_time ?? row.entry_time;
  return stamp ? new Date(stamp).getTime() : 0;
}

function buildMarketTotals(portfolio?: PortfolioSummary) {
  const breakdown = portfolio?.market_breakdown ?? {};
  return Object.entries(breakdown)
    .map(([market, row]) => ({
      market,
      label: MARKET_LABELS[market] ?? market,
      openPositions: Number(row.open_positions ?? 0),
      closedTrades: Number(row.closed_trades ?? 0),
      marketValueInr: Number(row.market_value_inr ?? 0),
      unrealizedPnlInr: Number(row.unrealized_pnl_inr ?? 0),
      netPnlInr: Number(row.net_pnl_inr ?? 0),
      isLive: market === 'CRYPTO' || Number(row.open_positions ?? 0) > 0,
    }))
    .sort((left, right) => {
      if (left.isLive !== right.isLive) {
        return left.isLive ? -1 : 1;
      }
      const marketDelta = marketPriority(left.market) - marketPriority(right.market);
      if (marketDelta !== 0) {
        return marketDelta;
      }
      return right.openPositions - left.openPositions;
    });
}

function buildTradeStats(rows: TradePair[]) {
  const closed = rows.filter((row) => row.exit_time);
  const open = rows.filter((row) => !row.exit_time);
  const wins = closed.filter((row) => row.pnl_inr >= 0).length;
  const losses = Math.max(closed.length - wins, 0);
  const realized = closed.reduce((sum, row) => sum + (row.pnl_inr ?? 0), 0);
  return {
    closed: closed.length,
    open: open.length,
    wins,
    losses,
    realized,
    winRate: closed.length ? (wins / closed.length) * 100 : 0,
  };
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
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm transition-colors',
        active
          ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-200'
          : 'border-slate-800 bg-slate-950/70 text-slate-400 hover:border-slate-700 hover:text-slate-200'
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function MarketBadge({ market, live }: { market: string; live: boolean }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] uppercase tracking-[0.2em]',
        live ? 'bg-emerald-500/10 text-emerald-300' : 'bg-slate-800 text-slate-400'
      )}
    >
      <span className={cn('h-1.5 w-1.5 rounded-full', live ? 'bg-emerald-400' : 'bg-slate-500')} />
      {MARKET_LABELS[market] ?? market}
    </span>
  );
}

function SideBadge({ side }: { side: string }) {
  const positive = String(side).toUpperCase() === 'LONG' || String(side).toUpperCase() === 'BUY';
  return (
    <span
      className={cn(
        'inline-flex rounded-full px-2 py-0.5 text-[10px] uppercase tracking-[0.18em]',
        positive ? 'bg-emerald-500/10 text-emerald-300' : 'bg-rose-500/10 text-rose-300'
      )}
    >
      {side}
    </span>
  );
}

function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-14 w-full rounded-2xl" />
      ))}
    </div>
  );
}

function RiskTrack({ position }: { position: Position }) {
  const hasPlan =
    position.stop_loss !== null &&
    position.stop_loss !== undefined &&
    position.target !== null &&
    position.target !== undefined;

  if (!hasPlan) {
    return (
      <div className="rounded-xl border border-dashed border-slate-800 px-3 py-2 text-[11px] text-slate-500">
        No live exit plan
      </div>
    );
  }

  const progress = Math.min(Math.max(position.progress_to_target_pct ?? 0, 4), 100);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2">
      <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.18em] text-slate-500">
        <span>
          SL{' '}
          {position.distance_to_stop_pct !== null && position.distance_to_stop_pct !== undefined
            ? formatPercent(position.distance_to_stop_pct, 2)
            : '--'}
        </span>
        <span>
          TGT{' '}
          {position.distance_to_target_pct !== null && position.distance_to_target_pct !== undefined
            ? formatPercent(position.distance_to_target_pct, 2)
            : '--'}
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div
          className={cn(
            'h-full rounded-full transition-all',
            (position.progress_to_target_pct ?? 0) >= 70
              ? 'bg-emerald-400'
              : (position.progress_to_target_pct ?? 0) >= 35
                ? 'bg-amber-400'
                : 'bg-sky-400'
          )}
          style={{ width: `${progress}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] text-slate-500">
        <span>{formatCurrency(position.stop_loss ?? 0, position.currency ?? 'INR')}</span>
        <span>{formatCurrency(position.target ?? 0, position.currency ?? 'INR')}</span>
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] text-slate-500">
        <span>
          Progress{' '}
          {position.progress_to_target_pct !== null && position.progress_to_target_pct !== undefined
            ? `${formatNumber(position.progress_to_target_pct, 0)}%`
            : '--'}
        </span>
        <span>{position.time_exit_at ? `T-${formatTimeLeft(position.time_left_seconds)}` : '--'}</span>
      </div>
    </div>
  );
}

function PositionDetailsDialog({
  position,
  onClose,
}: {
  position: Position;
  onClose: () => void;
}) {
  const pnlInr = position.unrealized_pnl_inr ?? position.unrealized_pnl;
  const movePct = positionMovePct(position);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
      <div className="w-full max-w-3xl rounded-[28px] border border-slate-800 bg-slate-900 shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-800 px-5 py-4">
          <div>
            <div className="text-lg font-semibold text-slate-100">{position.symbol}</div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <MarketBadge market={position.market} live={position.market_open} />
              <SideBadge side={position.side} />
              <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-slate-400">
                {position.currency ?? 'INR'}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-800 bg-slate-950/80 p-2 text-slate-400 hover:border-slate-700 hover:text-slate-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-5 px-5 py-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <MiniCard label="Qty" value={formatNumber(position.quantity)} />
            <MiniCard label="Avg" value={formatCurrency(position.avg_price, position.currency ?? 'INR')} />
            <MiniCard label="Mark" value={formatCurrency(position.current_price, position.currency ?? 'INR')} />
            <MiniCard
              label="P&L"
              value={formatCurrency(pnlInr, 'INR')}
              tone={pnlInr >= 0 ? 'positive' : 'negative'}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.2fr_0.8fr]">
            <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
              <div className="mb-4 flex items-center gap-2">
                <Target className="h-4 w-4 text-sky-400" />
                <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-300">Risk / Move</h3>
              </div>
              <RiskTrack position={position} />
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-2">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Entry Move</div>
                  <div className={cn('mt-1 font-medium', movePct >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
                    {formatPercent(movePct, 2)}
                  </div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-2">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Timer</div>
                  <div className="mt-1 font-medium text-slate-100">
                    {position.time_exit_at ? `T-${formatTimeLeft(position.time_left_seconds)}` : 'No timer'}
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
              <div className="mb-4 flex items-center gap-2">
                <Shield className="h-4 w-4 text-slate-400" />
                <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-300">Details</h3>
              </div>
              <div className="space-y-3 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-slate-500">Strategy</span>
                  <span className="text-right text-slate-200">{position.strategy_tag || 'Manual'}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-slate-500">Market Value</span>
                  <span className="text-right text-slate-200">
                    {formatCurrency(position.market_value_inr ?? position.market_value, 'INR')}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-slate-500">Entry Time</span>
                  <span className="text-right text-slate-200">
                    {position.entry_time ? formatDateTime(position.entry_time) : '--'}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-slate-500">Stop Loss</span>
                  <span className="text-right text-slate-200">
                    {position.stop_loss !== null && position.stop_loss !== undefined
                      ? formatCurrency(position.stop_loss, position.currency ?? 'INR')
                      : '--'}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-slate-500">Target</span>
                  <span className="text-right text-slate-200">
                    {position.target !== null && position.target !== undefined
                      ? formatCurrency(position.target, position.currency ?? 'INR')
                      : '--'}
                  </span>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <span className="text-slate-500">Orders</span>
                  <span className="max-w-[60%] break-all text-right text-slate-200">
                    {position.order_ids?.length ? position.order_ids.join(', ') : '--'}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PositionsPage() {
  const [activeTab, setActiveTab] = useState<PositionsTab>('positions');
  const [selectedPosition, setSelectedPosition] = useState<Position | null>(null);
  const { isConnected: isDashboardConnected } = useDashboardWS();
  const { isConnected: isPositionsConnected } = usePositionsWS();

  const {
    data: positions,
    isLoading: positionsLoading,
    error: positionsError,
    isFetching: positionsFetching,
    dataUpdatedAt,
  } = usePositions(!isPositionsConnected);

  const { data: portfolio, isLoading: portfolioLoading } = usePortfolio(!isDashboardConnected);
  const { data: orderPairs, isLoading: historyLoading, error: historyError } = useOrderPairs();

  const sortedPositions = useMemo(() => sortPositions(positions ?? []), [positions]);
  const marketTotals = useMemo(() => buildMarketTotals(portfolio), [portfolio]);
  const historyRows = useMemo(
    () => [...(orderPairs ?? [])].sort((left, right) => tradeActivityTime(right) - tradeActivityTime(left)),
    [orderPairs]
  );
  const historyStats = useMemo(() => buildTradeStats(historyRows), [historyRows]);

  const totalPnlInr = portfolio?.total_pnl_inr ?? portfolio?.total_pnl ?? 0;
  const totalUnrealizedInr = portfolio?.total_unrealized_pnl_inr ?? portfolio?.total_unrealized_pnl ?? 0;
  const liveCount = sortedPositions.filter((row) => row.market_open).length;

  return (
    <>
      <div className="space-y-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <h2 className="text-2xl font-semibold text-slate-100">Positions</h2>
              <span
                className={cn(
                  'inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em]',
                  positionsFetching
                    ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
                    : 'border-slate-800 bg-slate-950/80 text-slate-400'
                )}
              >
                <span
                  className={cn(
                    'h-1.5 w-1.5 rounded-full',
                    isPositionsConnected ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'
                  )}
                />
                {isPositionsConnected ? 'Live stream' : positionsFetching ? 'Polling' : 'Idle'}
              </span>
            </div>
            <div className="text-xs text-slate-500">
              {dataUpdatedAt
                ? `Updated ${new Date(dataUpdatedAt).toLocaleTimeString('en-IN', {
                    timeZone: 'Asia/Kolkata',
                    hour12: false,
                  })} IST`
                : 'Waiting for position stream'}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <TabButton
              active={activeTab === 'positions'}
              icon={<Activity className="h-4 w-4" />}
              label="Positions"
              onClick={() => setActiveTab('positions')}
            />
            <TabButton
              active={activeTab === 'history'}
              icon={<History className="h-4 w-4" />}
              label="Trade History"
              onClick={() => setActiveTab('history')}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {portfolioLoading ? (
            <>
              <Skeleton className="h-24 w-full rounded-2xl" />
              <Skeleton className="h-24 w-full rounded-2xl" />
              <Skeleton className="h-24 w-full rounded-2xl" />
              <Skeleton className="h-24 w-full rounded-2xl" />
            </>
          ) : activeTab === 'positions' ? (
            <>
              <MiniCard label="Open" value={formatNumber(sortedPositions.length)} />
              <MiniCard label="Live Markets" value={formatNumber(liveCount)} />
              <MiniCard
                label="Unrealized"
                value={formatCurrency(totalUnrealizedInr, 'INR')}
                tone={totalUnrealizedInr >= 0 ? 'positive' : 'negative'}
              />
              <MiniCard
                label="Total P&L"
                value={formatCurrency(totalPnlInr, 'INR')}
                tone={totalPnlInr >= 0 ? 'positive' : 'negative'}
              />
            </>
          ) : (
            <>
              <MiniCard label="Closed Pairs" value={formatNumber(historyStats.closed)} />
              <MiniCard label="Open Legs" value={formatNumber(historyStats.open)} />
              <MiniCard
                label="Win Rate"
                value={formatPercent(historyStats.winRate, 1)}
                tone={historyStats.winRate >= 50 ? 'positive' : 'negative'}
              />
              <MiniCard
                label="Realized"
                value={formatCurrency(historyStats.realized, 'INR')}
                tone={historyStats.realized >= 0 ? 'positive' : 'negative'}
              />
            </>
          )}
        </div>

        {activeTab === 'positions' ? (
          <div className="space-y-5">
            <section className="rounded-[28px] border border-slate-800 bg-slate-900/70 p-5">
              {positionsLoading ? (
                <TableSkeleton rows={8} />
              ) : positionsError ? (
                <div className="rounded-2xl border border-rose-500/20 bg-rose-500/5 px-4 py-10 text-center text-sm text-rose-300">
                  Failed to load positions.
                </div>
              ) : !sortedPositions.length ? (
                <div className="rounded-2xl border border-dashed border-slate-800 px-4 py-10 text-center text-sm text-slate-500">
                  No open positions
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[1480px] text-left text-sm">
                    <thead>
                      <tr className="border-b border-slate-800 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                        <th className="pb-3 pr-4 font-medium">Instrument</th>
                        <th className="pb-3 pr-4 font-medium">Side</th>
                        <th className="pb-3 pr-4 text-right font-medium">Qty</th>
                        <th className="pb-3 pr-4 text-right font-medium">Avg</th>
                        <th className="pb-3 pr-4 text-right font-medium">Mark</th>
                        <th className="pb-3 pr-4 text-right font-medium">Move</th>
                        <th className="pb-3 pr-4 text-right font-medium">U/P&amp;L</th>
                        <th className="pb-3 pr-4 font-medium">SL</th>
                        <th className="pb-3 pr-4 font-medium">Target</th>
                        <th className="pb-3 pr-4 font-medium">Timer</th>
                        <th className="pb-3 pr-4 font-medium">Strategy</th>
                        <th className="pb-3 font-medium">Orders</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedPositions.map((position) => {
                        const pnlInr = position.unrealized_pnl_inr ?? position.unrealized_pnl;
                        const movePct = positionMovePct(position);
                        const hasPlan =
                          position.stop_loss !== null &&
                          position.stop_loss !== undefined &&
                          position.target !== null &&
                          position.target !== undefined;
                        const progress = Math.min(Math.max(position.progress_to_target_pct ?? 0, 4), 100);

                        return (
                          <tr
                            key={`${position.symbol}-${position.side}-${position.entry_time ?? 'open'}`}
                            onClick={() => setSelectedPosition(position)}
                            className={cn(
                              'cursor-pointer border-b border-slate-800/80 text-slate-300 transition-colors hover:bg-slate-800/35',
                              position.market_open ? 'bg-emerald-500/[0.03]' : ''
                            )}
                          >
                            <td className="py-3 pr-4">
                              <div className="font-medium text-slate-100">{position.symbol}</div>
                              <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                                <MarketBadge market={position.market} live={position.market_open} />
                                <span>{position.entry_time ? formatDateTime(position.entry_time) : '--'}</span>
                              </div>
                            </td>
                            <td className="py-3 pr-4">
                              <SideBadge side={position.side} />
                            </td>
                            <td className="py-3 pr-4 text-right">{formatNumber(position.quantity)}</td>
                            <td className="py-3 pr-4 text-right">
                              {formatCurrency(position.avg_price, position.currency ?? 'INR')}
                            </td>
                            <td className="py-3 pr-4 text-right">
                              <div>{formatCurrency(position.current_price, position.currency ?? 'INR')}</div>
                              <div className="mt-1 text-xs text-slate-500">
                                {formatCurrency(position.market_value_inr ?? position.market_value, 'INR')}
                              </div>
                            </td>
                            <td className="py-3 pr-4 text-right">
                              <div className={cn('inline-flex items-center gap-1', movePct >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
                                {movePct >= 0 ? (
                                  <ArrowUpRight className="h-3.5 w-3.5" />
                                ) : (
                                  <ArrowDownRight className="h-3.5 w-3.5" />
                                )}
                                <span>{formatPercent(movePct, 2)}</span>
                              </div>
                            </td>
                            <td className="py-3 pr-4 text-right">
                              <div className={cn('font-medium', pnlInr >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
                                {formatCurrency(pnlInr, 'INR')}
                              </div>
                              <div className="mt-1 text-xs text-slate-500">
                                {formatPercent(position.unrealized_pnl_pct, 2)}
                              </div>
                            </td>
                            <td className="py-3 pr-4">
                              {hasPlan ? (
                                <div className="space-y-1 text-xs">
                                  <div className="text-slate-200">
                                    {formatCurrency(position.stop_loss ?? 0, position.currency ?? 'INR')}
                                  </div>
                                  <div className="text-slate-500">
                                    {position.distance_to_stop_pct !== null && position.distance_to_stop_pct !== undefined
                                      ? formatPercent(position.distance_to_stop_pct, 2)
                                      : '--'}
                                  </div>
                                </div>
                              ) : (
                                <span className="text-xs text-slate-500">--</span>
                              )}
                            </td>
                            <td className="py-3 pr-4">
                              {hasPlan ? (
                                <div className="space-y-1 text-xs">
                                  <div className="text-slate-200">
                                    {formatCurrency(position.target ?? 0, position.currency ?? 'INR')}
                                  </div>
                                  <div className="text-slate-500">
                                    {position.distance_to_target_pct !== null &&
                                    position.distance_to_target_pct !== undefined
                                      ? formatPercent(position.distance_to_target_pct, 2)
                                      : '--'}
                                  </div>
                                </div>
                              ) : (
                                <span className="text-xs text-slate-500">--</span>
                              )}
                            </td>
                            <td className="py-3 pr-4">
                              <div className="min-w-[120px]">
                                <div className="flex items-center gap-1 text-xs text-slate-400">
                                  <Clock3 className="h-3.5 w-3.5" />
                                  <span>{position.time_exit_at ? `T-${formatTimeLeft(position.time_left_seconds)}` : '--'}</span>
                                </div>
                                {hasPlan ? (
                                  <>
                                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800">
                                      <div
                                        className={cn(
                                          'h-full rounded-full',
                                          (position.progress_to_target_pct ?? 0) >= 70
                                            ? 'bg-emerald-400'
                                            : (position.progress_to_target_pct ?? 0) >= 35
                                              ? 'bg-amber-400'
                                              : 'bg-sky-400'
                                        )}
                                        style={{ width: `${progress}%` }}
                                      />
                                    </div>
                                    <div className="mt-1 text-[11px] text-slate-500">
                                      {position.progress_to_target_pct !== null &&
                                      position.progress_to_target_pct !== undefined
                                        ? `${formatNumber(position.progress_to_target_pct, 0)}%`
                                        : '--'}
                                    </div>
                                  </>
                                ) : (
                                  <div className="mt-1 text-[11px] text-slate-500">No plan</div>
                                )}
                              </div>
                            </td>
                            <td className="py-3 pr-4 text-xs text-slate-400">{position.strategy_tag || 'Manual'}</td>
                            <td className="py-3 text-xs text-slate-500">
                              {position.order_ids?.length ? position.order_ids.join(', ') : '--'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="rounded-[28px] border border-slate-800 bg-slate-900/70 p-5">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[860px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-slate-800 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                      <th className="pb-3 pr-4 font-medium">Market</th>
                      <th className="pb-3 pr-4 font-medium">Status</th>
                      <th className="pb-3 pr-4 text-right font-medium">Open</th>
                      <th className="pb-3 pr-4 text-right font-medium">Closed</th>
                      <th className="pb-3 pr-4 text-right font-medium">Value</th>
                      <th className="pb-3 pr-4 text-right font-medium">Unrealized</th>
                      <th className="pb-3 text-right font-medium">Net P&amp;L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {marketTotals.map((row) => (
                      <tr key={row.market} className="border-b border-slate-800/80 text-slate-300">
                        <td className="py-3 pr-4 font-medium text-slate-100">{row.label}</td>
                        <td className="py-3 pr-4">
                          <MarketBadge market={row.market} live={row.isLive} />
                        </td>
                        <td className="py-3 pr-4 text-right">{formatNumber(row.openPositions)}</td>
                        <td className="py-3 pr-4 text-right">{formatNumber(row.closedTrades)}</td>
                        <td className="py-3 pr-4 text-right">{formatCurrency(row.marketValueInr, 'INR')}</td>
                        <td
                          className={cn(
                            'py-3 pr-4 text-right',
                            row.unrealizedPnlInr >= 0 ? 'text-emerald-300' : 'text-rose-300'
                          )}
                        >
                          {formatCurrency(row.unrealizedPnlInr, 'INR')}
                        </td>
                        <td
                          className={cn(
                            'py-3 text-right font-medium',
                            row.netPnlInr >= 0 ? 'text-emerald-300' : 'text-rose-300'
                          )}
                        >
                          {formatCurrency(row.netPnlInr, 'INR')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        ) : (
          <section className="rounded-[28px] border border-slate-800 bg-slate-900/70 p-5">
            {historyLoading ? (
              <TableSkeleton rows={7} />
            ) : historyError ? (
              <div className="rounded-2xl border border-rose-500/20 bg-rose-500/5 px-4 py-10 text-center text-sm text-rose-300">
                Failed to load trade history.
              </div>
            ) : !historyRows.length ? (
              <div className="rounded-2xl border border-dashed border-slate-800 px-4 py-10 text-center text-sm text-slate-500">
                No trade history yet.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1280px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-slate-800 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                      <th className="pb-3 pr-4 font-medium">Instrument</th>
                      <th className="pb-3 pr-4 font-medium">Side</th>
                      <th className="pb-3 pr-4 text-right font-medium">Qty</th>
                      <th className="pb-3 pr-4 text-right font-medium">Entry</th>
                      <th className="pb-3 pr-4 text-right font-medium">Exit</th>
                      <th className="pb-3 pr-4 text-right font-medium">P&amp;L</th>
                      <th className="pb-3 pr-4 font-medium">Strategy</th>
                      <th className="pb-3 pr-4 font-medium">Entry Time</th>
                      <th className="pb-3 pr-4 font-medium">Exit Time</th>
                      <th className="pb-3 font-medium">Duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {historyRows.map((pair) => {
                      const isOpen = !pair.exit_time;
                      return (
                        <tr key={pair.pair_id} className="border-b border-slate-800/80 text-slate-300">
                          <td className="py-3 pr-4">
                            <div className="font-medium text-slate-100">{pair.symbol}</div>
                            <div className="mt-1 text-xs text-slate-500">{isOpen ? 'Open leg' : pair.pair_id}</div>
                          </td>
                          <td className="py-3 pr-4">
                            <SideBadge side={pair.side} />
                          </td>
                          <td className="py-3 pr-4 text-right">{formatNumber(pair.quantity)}</td>
                          <td className="py-3 pr-4 text-right">
                            {formatCurrency(pair.entry_price, pair.currency || 'INR')}
                          </td>
                          <td className="py-3 pr-4 text-right">
                            {pair.exit_price !== null
                              ? formatCurrency(pair.exit_price, pair.currency || 'INR')
                              : '--'}
                          </td>
                          <td
                            className={cn(
                              'py-3 pr-4 text-right font-medium',
                              isOpen ? 'text-slate-500' : pair.pnl_inr >= 0 ? 'text-emerald-300' : 'text-rose-300'
                            )}
                          >
                            {isOpen ? '--' : formatCurrency(pair.pnl_inr, 'INR')}
                          </td>
                          <td className="py-3 pr-4 text-slate-400">{pair.strategy_tag || 'Manual'}</td>
                          <td className="py-3 pr-4 text-xs text-slate-400">
                            {pair.entry_time ? formatDateTime(pair.entry_time) : '--'}
                          </td>
                          <td className="py-3 pr-4 text-xs text-slate-400">
                            {pair.exit_time ? formatDateTime(pair.exit_time) : '--'}
                          </td>
                          <td className="py-3 text-xs text-slate-500">
                            {isOpen ? 'Open' : formatDuration(pair.entry_time, pair.exit_time)}
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

      {selectedPosition && (
        <PositionDetailsDialog
          position={selectedPosition}
          onClose={() => setSelectedPosition(null)}
        />
      )}
    </>
  );
}

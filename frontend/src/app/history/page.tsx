'use client';

import { useState, useMemo } from 'react';
import {
  Database,
  TrendingUp,
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  AlertCircle,
  BarChart3,
} from 'lucide-react';
import { useOrderHistory, useTradeHistory, useTradingSummary } from '@/hooks/use-history';
import { useOrderPairs } from '@/hooks/use-orders';
import { useDashboardWS } from '@/hooks/use-dashboard-ws';
import { formatINR, formatNumber, formatDateTime, formatCurrency } from '@/lib/formatters';
import { cn } from '@/lib/utils';

// ─── Status config ────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<string, { icon: React.ComponentType<{ className?: string }>; color: string; bg: string }> = {
  TRADED: { icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  CANCELLED: { icon: XCircle, color: 'text-slate-400', bg: 'bg-slate-500/10' },
  REJECTED: { icon: AlertCircle, color: 'text-red-400', bg: 'bg-red-500/10' },
  PENDING: { icon: Clock, color: 'text-amber-400', bg: 'bg-amber-500/10' },
  TRANSIT: { icon: Clock, color: 'text-blue-400', bg: 'bg-blue-500/10' },
};

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG['TRANSIT'];
  const Icon = cfg.icon;
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', cfg.bg, cfg.color)}>
      <Icon className="h-3 w-3" />
      {status}
    </span>
  );
}

// ─── Summary cards ────────────────────────────────────────────────────────────

function SummaryCards({ isConnected }: { isConnected: boolean }) {
  const { data: summary, isLoading } = useTradingSummary(!isConnected);

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-xl border border-slate-800 bg-slate-900/60" />
        ))}
      </div>
    );
  }

  if (!summary?.authenticated) {
    return (
      <div className="flex items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60 py-10">
        <div className="text-center">
          <AlertCircle className="mx-auto mb-2 h-8 w-8 text-amber-400" />
          <p className="text-sm text-slate-300">Not logged in to Fyers</p>
          <p className="text-xs text-slate-500 mt-1">{summary?.note ?? 'Go to Settings → Authenticate to view live data'}</p>
        </div>
      </div>
    );
  }

  const { orders, trades } = summary;

  const cards = [
    {
      label: 'Total Orders',
      value: formatNumber(orders?.total ?? 0),
      sub: `${orders?.executed ?? 0} executed`,
      icon: BarChart3,
      color: 'text-blue-400',
    },
    {
      label: 'Executed',
      value: formatNumber(orders?.executed ?? 0),
      sub: `${orders?.cancelled ?? 0} cancelled`,
      icon: CheckCircle2,
      color: 'text-emerald-400',
    },
    {
      label: 'Total Traded Value',
      value: formatINR((trades?.total_buy_value ?? 0) + (trades?.total_sell_value ?? 0)),
      sub: `${trades?.total ?? 0} trades`,
      icon: TrendingUp,
      color: 'text-violet-400',
    },
    {
      label: 'Net Flow',
      value: formatINR(trades?.net_value ?? 0),
      sub: trades?.net_value && trades.net_value >= 0 ? 'Net sell' : 'Net buy',
      icon: trades?.net_value && trades.net_value >= 0 ? ArrowUpRight : ArrowDownRight,
      color: trades?.net_value && trades.net_value >= 0 ? 'text-emerald-400' : 'text-red-400',
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <div
            key={card.label}
            className="rounded-xl border border-slate-800 bg-slate-900/60 p-4"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-slate-400">{card.label}</span>
              <Icon className={cn('h-4 w-4', card.color)} />
            </div>
            <div className={cn('text-lg font-bold', card.color)}>{card.value}</div>
            <div className="text-xs text-slate-500 mt-1">{card.sub}</div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Orders table ─────────────────────────────────────────────────────────────

function OrdersTable({ isConnected }: { isConnected: boolean }) {
  const { data, isLoading, isError, refetch, isFetching } = useOrderHistory(!isConnected);
  const [sideFilter, setSideFilter] = useState<'all' | 'BUY' | 'SELL'>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  const filtered = useMemo(() => {
    if (!data?.orders) return [];
    return data.orders.filter((o) => {
      if (sideFilter !== 'all' && o.side !== sideFilter) return false;
      if (statusFilter !== 'all' && o.status !== statusFilter) return false;
      return true;
    });
  }, [data, sideFilter, statusFilter]);

  const statuses = useMemo(() => {
    const s = new Set(data?.orders.map((o) => o.status) ?? []);
    return ['all', ...Array.from(s)];
  }, [data]);

  if (isLoading) {
    return (
      <div className="h-64 animate-pulse rounded-xl border border-slate-800 bg-slate-900/60" />
    );
  }

  if (isError) {
    return (
      <div className="flex items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60 py-12">
        <p className="text-sm text-slate-400">Failed to load order history</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 p-4">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-200">Order Book</h3>
          <span className="rounded-full bg-slate-700 px-2 py-0.5 text-xs text-slate-300">
            {filtered.length}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {/* Side filter */}
          <div className="flex rounded-lg border border-slate-700 overflow-hidden text-xs">
            {(['all', 'BUY', 'SELL'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setSideFilter(f)}
                className={cn(
                  'px-2.5 py-1 font-medium',
                  sideFilter === f
                    ? 'bg-slate-700 text-slate-100'
                    : 'text-slate-400 hover:text-slate-200',
                )}
              >
                {f === 'all' ? 'All' : f}
              </button>
            ))}
          </div>
          {/* Status filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-300"
          >
            {statuses.map((s) => (
              <option key={s} value={s}>
                {s === 'all' ? 'All Status' : s}
              </option>
            ))}
          </select>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-1 rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
          >
            <RefreshCw className={cn('h-3 w-3', isFetching && 'animate-spin')} />
          </button>
        </div>
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <div className="flex items-center justify-center py-16">
          <div className="text-center">
            <Database className="mx-auto mb-3 h-8 w-8 text-slate-600" />
            <p className="text-sm text-slate-400">No orders found</p>
            <p className="text-xs text-slate-500 mt-1">
              {data?.note ?? 'Orders will appear after trading activity'}
            </p>
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-left text-slate-500">
                <th className="px-4 py-2.5 font-medium">Symbol</th>
                <th className="px-4 py-2.5 font-medium">Side</th>
                <th className="px-4 py-2.5 font-medium">Qty</th>
                <th className="px-4 py-2.5 font-medium text-right">Limit</th>
                <th className="px-4 py-2.5 font-medium text-right">Fill</th>
                <th className="px-4 py-2.5 font-medium">Type</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {filtered.map((order, i) => (
                <tr key={order.order_id || i} className="hover:bg-slate-800/30 transition-colors">
                  <td className="px-4 py-2.5">
                    <span className="font-medium text-slate-200">
                      {order.symbol.replace('NSE:', '').replace('BSE:', '').replace('-EQ', '')}
                    </span>
                    {order.tag && (
                      <span className="ml-1 text-slate-500">[{order.tag}]</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={cn(
                        'font-semibold',
                        order.side === 'BUY' ? 'text-emerald-400' : 'text-red-400',
                      )}
                    >
                      {order.side}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-slate-300">
                    <span>{formatNumber(order.filled_quantity)}</span>
                    {order.quantity !== order.filled_quantity && (
                      <span className="text-slate-500">/{formatNumber(order.quantity)}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right text-slate-300">
                    {order.limit_price > 0 ? formatINR(order.limit_price) : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-right text-slate-200">
                    {order.fill_price > 0 ? formatINR(order.fill_price) : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-slate-400">{order.order_type}</td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={order.status} />
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {order.placed_at ? `${formatDateTime(order.placed_at)} IST` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Trades table ─────────────────────────────────────────────────────────────

function TradesTable({ isConnected }: { isConnected: boolean }) {
  const { data, isLoading, refetch, isFetching } = useTradeHistory(!isConnected);
  const [sideFilter, setSideFilter] = useState<'all' | 'BUY' | 'SELL'>('all');

  const filtered = useMemo(() => {
    if (!data?.trades) return [];
    return sideFilter === 'all' ? data.trades : data.trades.filter((t) => t.side === sideFilter);
  }, [data, sideFilter]);

  if (isLoading) {
    return <div className="h-64 animate-pulse rounded-xl border border-slate-800 bg-slate-900/60" />;
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 p-4">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-200">Trade Book</h3>
          <span className="rounded-full bg-slate-700 px-2 py-0.5 text-xs text-slate-300">
            {filtered.length}
          </span>
          {data && (
            <span className="text-xs text-slate-500">
              Buy: <span className="text-emerald-400">{formatINR(data.total_buy_value)}</span>
              {' | '}
              Sell: <span className="text-red-400">{formatINR(data.total_sell_value)}</span>
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-slate-700 overflow-hidden text-xs">
            {(['all', 'BUY', 'SELL'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setSideFilter(f)}
                className={cn(
                  'px-2.5 py-1 font-medium',
                  sideFilter === f
                    ? 'bg-slate-700 text-slate-100'
                    : 'text-slate-400 hover:text-slate-200',
                )}
              >
                {f === 'all' ? 'All' : f}
              </button>
            ))}
          </div>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-1 rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
          >
            <RefreshCw className={cn('h-3 w-3', isFetching && 'animate-spin')} />
          </button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="flex items-center justify-center py-16">
          <div className="text-center">
            <Database className="mx-auto mb-3 h-8 w-8 text-slate-600" />
            <p className="text-sm text-slate-400">No trades today</p>
            <p className="text-xs text-slate-500 mt-1">
              {data?.note ?? 'Executed trades will appear here'}
            </p>
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-left text-slate-500">
                <th className="px-4 py-2.5 font-medium">Symbol</th>
                <th className="px-4 py-2.5 font-medium">Side</th>
                <th className="px-4 py-2.5 font-medium text-right">Qty</th>
                <th className="px-4 py-2.5 font-medium text-right">Price</th>
                <th className="px-4 py-2.5 font-medium text-right">Value</th>
                <th className="px-4 py-2.5 font-medium">Product</th>
                <th className="px-4 py-2.5 font-medium">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {filtered.map((trade, i) => (
                <tr key={trade.trade_id || i} className="hover:bg-slate-800/30 transition-colors">
                  <td className="px-4 py-2.5">
                    <span className="font-medium text-slate-200">
                      {trade.symbol.replace('NSE:', '').replace('BSE:', '').replace('-EQ', '')}
                    </span>
                    <span className="ml-1 text-slate-600">{trade.exchange}</span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={cn(
                        'font-semibold',
                        trade.side === 'BUY' ? 'text-emerald-400' : 'text-red-400',
                      )}
                    >
                      {trade.side}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right text-slate-300">
                    {formatNumber(trade.quantity)}
                  </td>
                  <td className="px-4 py-2.5 text-right text-slate-200">
                    {formatINR(trade.price)}
                  </td>
                  <td className="px-4 py-2.5 text-right font-medium text-slate-100">
                    {formatINR(trade.value)}
                  </td>
                  <td className="px-4 py-2.5 text-slate-400">{trade.product_type}</td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {trade.traded_at ? `${formatDateTime(trade.traded_at)} IST` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PairedTradesTable({ isConnected }: { isConnected: boolean }) {
  const { data: pairs, isLoading, isError, refetch, isFetching } = useOrderPairs(!isConnected);

  if (isLoading) {
    return <div className="h-64 animate-pulse rounded-xl border border-slate-800 bg-slate-900/60" />;
  }

  if (isError) {
    return (
      <div className="flex items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60 py-12">
        <p className="text-sm text-slate-400">Failed to load paired trades</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-800 p-4">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-200">Paired Trades (FIFO)</h3>
          <span className="rounded-full bg-slate-700 px-2 py-0.5 text-xs text-slate-300">{pairs?.length ?? 0}</span>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-1 rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
        >
          <RefreshCw className={cn('h-3 w-3', isFetching && 'animate-spin')} />
          Refresh
        </button>
      </div>

      {!pairs || pairs.length === 0 ? (
        <div className="py-12 text-center text-sm text-slate-500">No paired trades available</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-left text-slate-500">
                <th className="px-4 py-2.5 font-medium">Pair</th>
                <th className="px-4 py-2.5 font-medium">Symbol</th>
                <th className="px-4 py-2.5 font-medium">Side</th>
                <th className="px-4 py-2.5 font-medium text-right">Qty</th>
                <th className="px-4 py-2.5 font-medium text-right">Entry</th>
                <th className="px-4 py-2.5 font-medium text-right">Exit</th>
                <th className="px-4 py-2.5 font-medium text-right">P&L</th>
                <th className="px-4 py-2.5 font-medium">Entry Time</th>
                <th className="px-4 py-2.5 font-medium">Exit Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {pairs.map((pair) => (
                <tr key={pair.pair_id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="px-4 py-2.5 font-mono text-slate-500">{pair.pair_id}</td>
                  <td className="px-4 py-2.5 font-medium text-slate-200">{pair.symbol}</td>
                  <td className="px-4 py-2.5">
                    <span className={cn('font-semibold', pair.side === 'LONG' ? 'text-emerald-400' : 'text-red-400')}>
                      {pair.side}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right text-slate-300">{formatNumber(pair.quantity)}</td>
                  <td className="px-4 py-2.5 text-right text-slate-300">{formatCurrency(pair.entry_price, pair.currency)}</td>
                  <td className="px-4 py-2.5 text-right text-slate-300">
                    {pair.exit_price !== null ? formatCurrency(pair.exit_price, pair.currency) : '—'}
                  </td>
                  <td
                    className={cn(
                      'px-4 py-2.5 text-right font-semibold',
                      pair.exit_time
                        ? pair.pnl_inr >= 0
                          ? 'text-emerald-400'
                          : 'text-red-400'
                        : 'text-slate-500'
                    )}
                  >
                    {pair.exit_time ? formatCurrency(pair.pnl_inr, 'INR') : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {pair.entry_time ? `${formatDateTime(pair.entry_time)} IST` : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {pair.exit_time ? `${formatDateTime(pair.exit_time)} IST` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

type Tab = 'orders' | 'trades' | 'paired';

export default function HistoryPage() {
  const [tab, setTab] = useState<Tab>('orders');
  const { isConnected } = useDashboardWS();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Database className="h-6 w-6 text-blue-400" />
          <div>
            <h1 className="text-xl font-bold text-slate-100">Trade History</h1>
            <p className="text-xs text-slate-500">Today&apos;s order book and executed trades from Fyers</p>
          </div>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-slate-800 bg-slate-950/80 px-3 py-1 text-[11px] uppercase tracking-[0.2em]">
          <span className={cn('h-1.5 w-1.5 rounded-full', isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500')} />
          <span className={isConnected ? 'text-emerald-400' : 'text-slate-500'}>
            {isConnected ? 'Live stream' : 'Polling'}
          </span>
        </div>
      </div>
 
      {/* Summary Cards */}
      <SummaryCards isConnected={isConnected} />

      {/* Tab selector */}
      <div className="flex gap-1 rounded-xl border border-slate-800 bg-slate-900/60 p-1 w-fit">
        {([
          { id: 'orders' as Tab, label: 'Orders' },
          { id: 'trades' as Tab, label: 'Trades' },
          { id: 'paired' as Tab, label: 'Paired Trades' },
        ]).map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={cn(
              'rounded-lg px-4 py-2 text-sm font-medium transition-colors',
              tab === id
                ? 'bg-slate-700 text-slate-100'
                : 'text-slate-400 hover:text-slate-200',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tables */}
      {tab === 'orders' && <OrdersTable isConnected={isConnected} />}
      {tab === 'trades' && <TradesTable isConnected={isConnected} />}
      {tab === 'paired' && <PairedTradesTable isConnected={isConnected} />}
    </div>
  );
}

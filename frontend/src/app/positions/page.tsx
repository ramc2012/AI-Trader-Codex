'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { usePositions } from '@/hooks/use-positions';
import { useOrders } from '@/hooks/use-orders';
import { formatINRFull, formatPercent, formatDateTime } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import { Skeleton } from '@/components/ui/skeleton';

function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

function PnlCell({ value, pct }: { value: number; pct?: number }) {
  const color = value >= 0 ? 'text-emerald-400' : 'text-red-400';
  return (
    <span className={cn('font-medium', color)}>
      {formatINRFull(value)}
      {pct !== undefined && (
        <span className="ml-1 text-xs">({formatPercent(pct)})</span>
      )}
    </span>
  );
}

export default function PositionsPage() {
  const { data: positions, isLoading: posLoading, error: posError } = usePositions();
  const { data: orders, isLoading: ordLoading, error: ordError } = useOrders();
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const toggleRow = (key: string) => {
    setExpandedRow(expandedRow === key ? null : key);
  };

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Positions & Orders</h2>
        <p className="mt-1 text-sm text-slate-400">
          Open positions and order history
        </p>
      </div>

      {/* Open Positions */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <h3 className="mb-4 text-lg font-semibold text-slate-200">
          Open Positions
          {positions && positions.length > 0 && (
            <span className="ml-2 text-sm font-normal text-slate-400">
              ({positions.length})
            </span>
          )}
        </h3>

        {posLoading ? (
          <TableSkeleton />
        ) : posError ? (
          <p className="text-sm text-red-400">
            Failed to load positions. Backend may be offline.
          </p>
        ) : !positions || positions.length === 0 ? (
          <p className="text-sm text-slate-500">No open positions</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-slate-400">
                  <th className="pb-3 pr-2 font-medium w-6"></th>
                  <th className="pb-3 pr-4 font-medium">Symbol</th>
                  <th className="pb-3 pr-4 font-medium">Side</th>
                  <th className="pb-3 pr-4 font-medium text-right">Qty</th>
                  <th className="pb-3 pr-4 font-medium text-right">Avg Price</th>
                  <th className="pb-3 pr-4 font-medium text-right">Current</th>
                  <th className="pb-3 pr-4 font-medium text-right">P&L</th>
                  <th className="pb-3 pr-4 font-medium text-right">Mkt Value</th>
                  <th className="pb-3 font-medium">Strategy</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos, i) => {
                  const rowKey = `${pos.symbol}-${i}`;
                  const isExpanded = expandedRow === rowKey;
                  return (
                    <>
                      <tr
                        key={rowKey}
                        onClick={() => toggleRow(rowKey)}
                        className={cn(
                          'border-b border-slate-800 text-slate-300 cursor-pointer transition-colors duration-150',
                          'hover:bg-slate-800/50',
                          isExpanded && 'bg-slate-800/30'
                        )}
                      >
                        <td className="py-3 pr-2">
                          {isExpanded ? (
                            <ChevronDown className="h-4 w-4 text-slate-500" />
                          ) : (
                            <ChevronRight className="h-4 w-4 text-slate-500" />
                          )}
                        </td>
                        <td className="py-3 pr-4 font-medium text-slate-100">
                          {pos.symbol}
                        </td>
                        <td className="py-3 pr-4">
                          <span
                            className={cn(
                              'rounded px-2 py-0.5 text-xs font-medium',
                              pos.side === 'BUY'
                                ? 'bg-emerald-500/20 text-emerald-400'
                                : 'bg-red-500/20 text-red-400'
                            )}
                          >
                            {pos.side}
                          </span>
                        </td>
                        <td className="py-3 pr-4 text-right">{pos.quantity}</td>
                        <td className="py-3 pr-4 text-right">
                          {formatINRFull(pos.avg_price)}
                        </td>
                        <td className="py-3 pr-4 text-right">
                          {formatINRFull(pos.current_price)}
                        </td>
                        <td className="py-3 pr-4 text-right">
                          <PnlCell value={pos.unrealized_pnl} pct={pos.unrealized_pnl_pct} />
                        </td>
                        <td className="py-3 pr-4 text-right">
                          {formatINRFull(pos.market_value)}
                        </td>
                        <td className="py-3 text-xs text-slate-400">
                          {pos.strategy_tag}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr key={`${rowKey}-detail`} className="bg-slate-800/20">
                          <td colSpan={9} className="px-8 py-4">
                            <div className="animate-fade-in grid grid-cols-2 gap-4 sm:grid-cols-4 text-sm">
                              <div>
                                <p className="text-xs text-slate-500">Entry Time</p>
                                <p className="text-slate-300">
                                  {pos.entry_time ? formatDateTime(pos.entry_time) : '--'}
                                </p>
                              </div>
                              <div>
                                <p className="text-xs text-slate-500">Unrealized P&L</p>
                                <p className={cn(
                                  'font-medium',
                                  pos.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
                                )}>
                                  {formatINRFull(pos.unrealized_pnl)}
                                </p>
                              </div>
                              <div>
                                <p className="text-xs text-slate-500">Realized P&L</p>
                                <p className={cn(
                                  'font-medium',
                                  (pos.realized_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'
                                )}>
                                  {formatINRFull(pos.realized_pnl ?? 0)}
                                </p>
                              </div>
                              <div>
                                <p className="text-xs text-slate-500">Market Value</p>
                                <p className="text-slate-300">
                                  {formatINRFull(pos.market_value)}
                                </p>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Order History */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <h3 className="mb-4 text-lg font-semibold text-slate-200">
          Order History
          {orders && orders.length > 0 && (
            <span className="ml-2 text-sm font-normal text-slate-400">
              ({orders.length})
            </span>
          )}
        </h3>

        {ordLoading ? (
          <TableSkeleton />
        ) : ordError ? (
          <p className="text-sm text-red-400">
            Failed to load orders. Backend may be offline.
          </p>
        ) : !orders || orders.length === 0 ? (
          <p className="text-sm text-slate-500">No orders</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-slate-400">
                  <th className="pb-3 pr-4 font-medium">Order ID</th>
                  <th className="pb-3 pr-4 font-medium">Symbol</th>
                  <th className="pb-3 pr-4 font-medium">Side</th>
                  <th className="pb-3 pr-4 font-medium">Type</th>
                  <th className="pb-3 pr-4 font-medium text-right">Qty</th>
                  <th className="pb-3 pr-4 font-medium text-right">Limit</th>
                  <th className="pb-3 pr-4 font-medium text-right">Fill Price</th>
                  <th className="pb-3 pr-4 font-medium">Status</th>
                  <th className="pb-3 font-medium">Time</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((ord, i) => (
                  <tr
                    key={ord.order_id ?? `order-${i}`}
                    className="border-b border-slate-800 text-slate-300 transition-colors duration-150 hover:bg-slate-800/50"
                  >
                    <td className="py-3 pr-4 font-mono text-xs text-slate-400">
                      {ord.order_id ? ord.order_id.slice(0, 8) : '--'}
                    </td>
                    <td className="py-3 pr-4 font-medium text-slate-100">
                      {ord.symbol}
                    </td>
                    <td className="py-3 pr-4">
                      <span
                        className={cn(
                          'rounded px-2 py-0.5 text-xs font-medium',
                          ord.side === 'BUY'
                            ? 'bg-emerald-500/20 text-emerald-400'
                            : 'bg-red-500/20 text-red-400'
                        )}
                      >
                        {ord.side}
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-xs">{ord.order_type}</td>
                    <td className="py-3 pr-4 text-right">
                      {ord.fill_quantity}/{ord.quantity}
                    </td>
                    <td className="py-3 pr-4 text-right">
                      {ord.limit_price ? formatINRFull(ord.limit_price) : '--'}
                    </td>
                    <td className="py-3 pr-4 text-right">
                      {ord.fill_price ? formatINRFull(ord.fill_price) : '--'}
                    </td>
                    <td className="py-3 pr-4">
                      <span
                        className={cn(
                          'rounded px-2 py-0.5 text-xs font-medium',
                          ord.status === 'FILLED'
                            ? 'bg-emerald-500/20 text-emerald-400'
                            : ord.status === 'REJECTED' || ord.status === 'CANCELLED'
                              ? 'bg-red-500/20 text-red-400'
                              : 'bg-yellow-500/20 text-yellow-400'
                        )}
                      >
                        {ord.status}
                      </span>
                    </td>
                    <td className="py-3 text-xs text-slate-400">
                      {ord.placed_at ? formatDateTime(ord.placed_at) : '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

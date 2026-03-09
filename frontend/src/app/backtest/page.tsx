'use client';

import { useState } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
} from 'recharts';
import { FlaskConical, Play } from 'lucide-react';
import { useRunBacktest, useBacktestResults, type BacktestParams } from '@/hooks/use-backtest';
import { formatINR, formatPercent, formatDateTime } from '@/lib/formatters';
import { cn } from '@/lib/utils';

const STRATEGIES = [
  'ema_crossover',
  'rsi_reversal',
  'macd_trend',
  'bollinger_breakout',
];

const SYMBOLS = [
  'NSE:NIFTY50-INDEX',
  'NSE:NIFTYBANK-INDEX',
  'NSE:FINNIFTY-INDEX',
  'NSE:NIFTYMIDCAP50-INDEX',
  'BSE:SENSEX-INDEX',
  'NSE:RELIANCE-EQ',
  'NSE:TCS-EQ',
  'NSE:INFY-EQ',
  'NSE:HDFCBANK-EQ',
];

function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn('animate-pulse rounded bg-slate-800', className)} />
  );
}

function ResultCard({
  title,
  value,
  valueColor,
}: {
  title: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <p className="text-xs text-slate-500">{title}</p>
      <p className={cn('mt-1 text-lg font-semibold', valueColor || 'text-slate-200')}>
        {value}
      </p>
    </div>
  );
}

export default function BacktestPage() {
  const [form, setForm] = useState<BacktestParams>({
    strategy_name: STRATEGIES[0],
    symbol: SYMBOLS[0],
    start_date: '2024-01-01',
    end_date: '2024-12-31',
    initial_capital: 1000000,
  });

  const runMutation = useRunBacktest();
  const { data: pastResults, isLoading: resultsLoading } = useBacktestResults();

  const result = runMutation.data;

  const equityData = result?.trades
    ? result.trades.reduce(
        (acc, trade, i) => {
          const prevEquity = acc.length > 0 ? acc[acc.length - 1].equity : (result.initial_capital ?? 1000000);
          acc.push({
            trade: i + 1,
            equity: prevEquity + trade.pnl,
          });
          return acc;
        },
        [] as Array<{ trade: number; equity: number }>
      )
    : [];

  const handleRun = () => {
    runMutation.mutate(form);
  };

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Backtest</h2>
        <p className="mt-1 text-sm text-slate-400">
          Run and analyze strategy backtests
        </p>
      </div>

      {/* Backtest Form */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="mb-4 flex items-center gap-2">
          <FlaskConical className="h-5 w-5 text-slate-400" />
          <h3 className="text-lg font-semibold text-slate-200">
            Run Backtest
          </h3>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">
              Strategy
            </label>
            <select
              value={form.strategy_name}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, strategy_name: e.target.value }))
              }
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
            >
              {STRATEGIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">
              Symbol
            </label>
            <select
              value={form.symbol}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, symbol: e.target.value }))
              }
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
            >
              {SYMBOLS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">
              Start Date
            </label>
            <input
              type="date"
              value={form.start_date}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, start_date: e.target.value }))
              }
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">
              End Date
            </label>
            <input
              type="date"
              value={form.end_date}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, end_date: e.target.value }))
              }
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
            />
          </div>

          <div className="flex items-end">
            <button
              onClick={handleRun}
              disabled={runMutation.isPending}
              className={cn(
                'flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                runMutation.isPending
                  ? 'cursor-not-allowed bg-slate-700 text-slate-400'
                  : 'bg-emerald-600 text-white hover:bg-emerald-500'
              )}
            >
              <Play className="h-4 w-4" />
              {runMutation.isPending ? 'Running...' : 'Run Backtest'}
            </button>
          </div>
        </div>

        {runMutation.isError && (
          <p className="mt-3 text-sm text-red-400">
            Backtest failed: {runMutation.error?.message ?? 'Unknown error'}
          </p>
        )}
      </div>

      {/* Results */}
      {result && (
        <div className="space-y-6">
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
            <h3 className="mb-4 text-lg font-semibold text-slate-200">
              Results: {result.strategy_name} on {result.symbol}
            </h3>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <ResultCard
                title="Total P&L"
                value={formatINR(result.total_pnl)}
                valueColor={
                  result.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
                }
              />
              <ResultCard
                title="Return"
                value={formatPercent(result.total_return_pct)}
                valueColor={
                  result.total_return_pct >= 0
                    ? 'text-emerald-400'
                    : 'text-red-400'
                }
              />
              <ResultCard
                title="Win Rate"
                value={formatPercent(result.win_rate)}
              />
              <ResultCard
                title="Max Drawdown"
                value={formatPercent(-result.max_drawdown_pct)}
                valueColor="text-red-400"
              />
              <ResultCard
                title="Profit Factor"
                value={result.profit_factor.toFixed(2)}
              />
              <ResultCard
                title="Total Trades"
                value={String(result.total_trades)}
              />
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <ResultCard
                title="Initial Capital"
                value={formatINR(result.initial_capital)}
              />
              <ResultCard
                title="Final Capital"
                value={formatINR(result.final_capital)}
              />
              <ResultCard
                title="Avg Win"
                value={formatINR(result.avg_win)}
                valueColor="text-emerald-400"
              />
              <ResultCard
                title="Avg Loss"
                value={formatINR(result.avg_loss)}
                valueColor="text-red-400"
              />
            </div>
          </div>

          {/* Equity Curve */}
          {equityData.length > 0 && (
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
              <h3 className="mb-4 text-sm font-medium text-slate-400">
                Equity Curve (by trade)
              </h3>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={equityData}>
                    <defs>
                      <linearGradient
                        id="btEquity"
                        x1="0"
                        y1="0"
                        x2="0"
                        y2="1"
                      >
                        <stop
                          offset="5%"
                          stopColor="#10b981"
                          stopOpacity={0.3}
                        />
                        <stop
                          offset="95%"
                          stopColor="#10b981"
                          stopOpacity={0}
                        />
                      </linearGradient>
                    </defs>
                    <XAxis
                      dataKey="trade"
                      stroke="#475569"
                      fontSize={12}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis
                      stroke="#475569"
                      fontSize={12}
                      tickLine={false}
                      axisLine={false}
                      tickFormatter={(val) =>
                        `${(Number(val) / 100000).toFixed(0)}L`
                      }
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#1e293b',
                        border: '1px solid #334155',
                        borderRadius: '8px',
                        color: '#f1f5f9',
                      }}
                      formatter={(val) => [formatINR(Number(val)), 'Equity']}
                    />
                    <Area
                      type="monotone"
                      dataKey="equity"
                      stroke="#10b981"
                      strokeWidth={2}
                      fill="url(#btEquity)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Trade List */}
          {result.trades && result.trades.length > 0 && (
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
              <h3 className="mb-4 text-lg font-semibold text-slate-200">
                Trade History ({result.trades.length} trades)
              </h3>
              <div className="max-h-96 overflow-y-auto">
                <table className="w-full text-left text-sm">
                  <thead className="sticky top-0 bg-slate-900">
                    <tr className="border-b border-slate-700 text-slate-400">
                      <th className="pb-3 pr-3 font-medium">#</th>
                      <th className="pb-3 pr-3 font-medium">Entry</th>
                      <th className="pb-3 pr-3 font-medium">Exit</th>
                      <th className="pb-3 pr-3 font-medium">Side</th>
                      <th className="pb-3 pr-3 font-medium text-right">
                        Entry Price
                      </th>
                      <th className="pb-3 pr-3 font-medium text-right">
                        Exit Price
                      </th>
                      <th className="pb-3 pr-3 font-medium text-right">
                        P&L
                      </th>
                      <th className="pb-3 font-medium">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.map((t, i) => (
                      <tr
                        key={i}
                        className="border-b border-slate-800 text-slate-300"
                      >
                        <td className="py-2 pr-3 text-slate-500">{i + 1}</td>
                        <td className="py-2 pr-3 text-xs">
                          {formatDateTime(t.entry_time)}
                        </td>
                        <td className="py-2 pr-3 text-xs">
                          {t.exit_time ? formatDateTime(t.exit_time) : '--'}
                        </td>
                        <td className="py-2 pr-3">
                          <span
                            className={cn(
                              'rounded px-1.5 py-0.5 text-xs font-medium',
                              t.side === 'BUY'
                                ? 'bg-emerald-500/20 text-emerald-400'
                                : 'bg-red-500/20 text-red-400'
                            )}
                          >
                            {t.side}
                          </span>
                        </td>
                        <td className="py-2 pr-3 text-right">
                          {formatINR(t.entry_price)}
                        </td>
                        <td className="py-2 pr-3 text-right">
                          {t.exit_price ? formatINR(t.exit_price) : '--'}
                        </td>
                        <td className="py-2 pr-3 text-right">
                          <span
                            className={cn(
                              'font-medium',
                              t.pnl >= 0
                                ? 'text-emerald-400'
                                : 'text-red-400'
                            )}
                          >
                            {formatINR(t.pnl)}
                          </span>
                        </td>
                        <td className="py-2 text-xs text-slate-500">
                          {t.exit_reason}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Past Results */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <h3 className="mb-4 text-lg font-semibold text-slate-200">
          Previous Backtests
        </h3>

        {resultsLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full rounded-lg" />
            ))}
          </div>
        ) : !pastResults || pastResults.length === 0 ? (
          <p className="text-sm text-slate-500">
            No previous backtest results
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-slate-400">
                  <th className="pb-3 pr-4 font-medium">Strategy</th>
                  <th className="pb-3 pr-4 font-medium">Symbol</th>
                  <th className="pb-3 pr-4 font-medium">Period</th>
                  <th className="pb-3 pr-4 font-medium text-right">Trades</th>
                  <th className="pb-3 pr-4 font-medium text-right">Return</th>
                  <th className="pb-3 pr-4 font-medium text-right">
                    Win Rate
                  </th>
                  <th className="pb-3 font-medium text-right">Drawdown</th>
                </tr>
              </thead>
              <tbody>
                {pastResults.map((r, i) => (
                  <tr
                    key={r.id ?? i}
                    className="border-b border-slate-800 text-slate-300"
                  >
                    <td className="py-2 pr-4 font-medium text-slate-200">
                      {r.strategy_name}
                    </td>
                    <td className="py-2 pr-4">{r.symbol}</td>
                    <td className="py-2 pr-4 text-xs">
                      {r.start_date} - {r.end_date}
                    </td>
                    <td className="py-2 pr-4 text-right">{r.total_trades}</td>
                    <td className="py-2 pr-4 text-right">
                      <span
                        className={cn(
                          'font-medium',
                          r.total_return_pct >= 0
                            ? 'text-emerald-400'
                            : 'text-red-400'
                        )}
                      >
                        {formatPercent(r.total_return_pct)}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-right">
                      {formatPercent(r.win_rate)}
                    </td>
                    <td className="py-2 text-right text-red-400">
                      {formatPercent(-r.max_drawdown_pct)}
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

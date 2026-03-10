'use client';

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
} from 'recharts';
import { Shield, AlertTriangle } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useRiskSummary } from '@/hooks/use-risk-summary';
import { useRiskMetrics } from '@/hooks/use-risk-metrics';
import { usePortfolio } from '@/hooks/use-portfolio';
import { apiFetch } from '@/lib/api';
import { formatINR, formatPercent, formatNumber } from '@/lib/formatters';
import { buildEquityChartData, equityChartWidth } from '@/lib/equity-chart';
import { cn } from '@/lib/utils';
import { Skeleton } from '@/components/ui/skeleton';
import type { EquitySnapshot, PortfolioPeriod } from '@/types/api';

function MetricCard({
  title,
  value,
  subtitle,
  isLoading,
  valueColor,
}: {
  title: string;
  value: string;
  subtitle?: string;
  isLoading?: boolean;
  valueColor?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <p className="text-sm font-medium text-slate-400">{title}</p>
      {isLoading ? (
        <Skeleton className="mt-3 h-8 w-24" />
      ) : (
        <p className={cn('mt-2 text-2xl font-bold', valueColor || 'text-slate-100')}>
          {value}
        </p>
      )}
      {subtitle && !isLoading && (
        <p className="mt-1 text-xs text-slate-500">{subtitle}</p>
      )}
    </div>
  );
}

function boundedMetric(
  value: number | null | undefined,
  min: number,
  max: number,
): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null;
  }
  if (value < min || value > max) {
    return null;
  }
  return value;
}

export default function RiskPage() {
  const equityPeriod: PortfolioPeriod = 'daily';
  const { data: risk, isLoading: riskLoading } = useRiskSummary();
  const { data: metrics, isLoading: metricsLoading } = useRiskMetrics();
  const { data: portfolio } = usePortfolio();

  // Fetch equity curve from API instead of hardcoded sample data
  const { data: equityCurveApi, isLoading: equityLoading } = useQuery<EquitySnapshot[]>({
    queryKey: ['equity-curve', equityPeriod],
    queryFn: () => apiFetch<EquitySnapshot[]>(`/portfolio/equity-curve?period=${encodeURIComponent(equityPeriod)}`),
    refetchInterval: 10000,
  });

  // Also check for live WebSocket snapshots
  const { data: equityCurveLive } = useQuery<EquitySnapshot[]>({
    queryKey: ['equity-curve-live'],
    enabled: false, // populated by WebSocket hook on dashboard
  });

  // Use live data if available, else API data, else empty
  const equityCurveData = buildEquityChartData(equityCurveApi, equityCurveLive, equityPeriod);
  const chartWidth = equityChartWidth(equityCurveData.length);
  const maxDrawdown = boundedMetric(metrics?.max_drawdown, -1, 0);
  const totalReturn = boundedMetric(metrics?.total_return, -10, 10);
  const volatility = boundedMetric(metrics?.volatility, 0, 10);

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Risk & Analytics</h2>
        <p className="mt-1 text-sm text-slate-400">
          Portfolio risk metrics and performance analytics
        </p>
      </div>

      {/* Risk Metric Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Sharpe Ratio"
          value={metrics?.sharpe_ratio?.toFixed(2) ?? '--'}
          subtitle="Risk-adjusted return"
          isLoading={metricsLoading}
          valueColor={
            metrics
              ? metrics.sharpe_ratio >= 1
                ? 'text-emerald-400'
                : metrics.sharpe_ratio >= 0
                  ? 'text-yellow-400'
                  : 'text-red-400'
              : undefined
          }
        />
        <MetricCard
          title="Sortino Ratio"
          value={metrics?.sortino_ratio?.toFixed(2) ?? '--'}
          subtitle="Downside risk adjusted"
          isLoading={metricsLoading}
          valueColor={
            metrics
              ? metrics.sortino_ratio >= 1.5
                ? 'text-emerald-400'
                : 'text-yellow-400'
              : undefined
          }
        />
        <MetricCard
          title="Max Drawdown"
          value={maxDrawdown !== null ? formatPercent(-maxDrawdown) : '--'}
          subtitle={
            maxDrawdown !== null && metrics
              ? `Duration: ${metrics.max_drawdown_duration} days`
              : undefined
          }
          isLoading={metricsLoading}
          valueColor="text-red-400"
        />
        <MetricCard
          title="VaR (95%)"
          value={metrics ? formatINR(metrics.var_95) : '--'}
          subtitle={
            metrics ? `99% VaR: ${formatINR(metrics.var_99)}` : undefined
          }
          isLoading={metricsLoading}
          valueColor="text-yellow-400"
        />
      </div>

      {/* Additional Metrics */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <MetricCard
          title="Profit Factor"
          value={metrics?.profit_factor?.toFixed(2) ?? '--'}
          isLoading={metricsLoading}
        />
        <MetricCard
          title="Win Rate"
          value={metrics ? formatPercent(metrics.win_rate) : '--'}
          isLoading={metricsLoading}
        />
        <MetricCard
          title="Avg Win"
          value={metrics ? formatINR(metrics.avg_win) : '--'}
          isLoading={metricsLoading}
          valueColor="text-emerald-400"
        />
        <MetricCard
          title="Avg Loss"
          value={metrics ? formatINR(metrics.avg_loss) : '--'}
          isLoading={metricsLoading}
          valueColor="text-red-400"
        />
        <MetricCard
          title="Total Return"
          value={totalReturn !== null ? formatPercent(totalReturn) : '--'}
          isLoading={metricsLoading}
        />
        <MetricCard
          title="Volatility"
          value={volatility !== null ? formatPercent(volatility) : '--'}
          isLoading={metricsLoading}
        />
      </div>

      {/* Equity Curve */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-slate-400">
            Equity Curve
          </h3>
          {equityCurveLive && equityCurveLive.length > 1 && (
            <span className="text-xs text-emerald-500">
              {equityCurveLive.length} live snapshots
            </span>
          )}
        </div>
        <div className="h-72 overflow-x-auto">
          {equityLoading ? (
            <div className="flex h-full items-center justify-center">
              <Skeleton className="h-full w-full" />
            </div>
          ) : equityCurveData.length > 0 ? (
            <AreaChart width={chartWidth} height={288} data={equityCurveData}>
                <defs>
                  <linearGradient id="riskEquity" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="label"
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
                  tickFormatter={(val) => `${(Number(val) / 100000).toFixed(1)}L`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1e293b',
                    border: '1px solid #334155',
                    borderRadius: '8px',
                    color: '#f1f5f9',
                  }}
                  labelFormatter={(_, payload) =>
                    payload?.[0]?.payload?.isoTime
                      ? new Date(String(payload[0].payload.isoTime)).toLocaleString('en-IN', {
                          day: '2-digit',
                          month: 'short',
                          hour: '2-digit',
                          minute: '2-digit',
                          hour12: false,
                          timeZone: 'Asia/Kolkata',
                        })
                      : ''
                  }
                  formatter={(val) => [formatINR(Number(val)), 'Equity']}
                />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="#10b981"
                  strokeWidth={2}
                  fill="url(#riskEquity)"
                  isAnimationActive={false}
                />
            </AreaChart>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-500">
              Equity data will appear once trading begins
            </div>
          )}
        </div>
      </div>

      {/* Risk State Panel */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="flex items-center gap-2">
          <Shield className="h-5 w-5 text-slate-400" />
          <h3 className="text-lg font-semibold text-slate-200">Risk State</h3>
        </div>

        {riskLoading ? (
          <div className="mt-4 space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : risk ? (
          <div className="mt-4 space-y-4">
            {/* Circuit Breaker / Emergency Stop */}
            {(risk.circuit_breaker_triggered || risk.emergency_stop) && (
              <div className="flex items-center gap-2 rounded-lg bg-red-500/10 px-4 py-3">
                <AlertTriangle className="h-5 w-5 text-red-400" />
                <span className="text-sm font-medium text-red-400">
                  {risk.emergency_stop
                    ? 'EMERGENCY STOP ACTIVE'
                    : 'CIRCUIT BREAKER TRIGGERED'}
                </span>
              </div>
            )}

            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div>
                <p className="text-xs text-slate-500">Capital</p>
                <p className="text-sm font-medium text-slate-200">
                  {formatINR(risk.total_allocated_capital_inr || risk.capital)}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Total P&L</p>
                <p
                  className={cn(
                    'text-sm font-medium',
                    risk.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
                  )}
                >
                  {formatINR(risk.total_pnl)}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Daily Loss Limit</p>
                <p className="text-sm font-medium text-slate-200">
                  {formatINR(risk.daily_loss_limit)}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Available Risk</p>
                <p className="text-sm font-medium text-slate-200">
                  {formatINR(risk.available_risk)}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">P&L On Capital</p>
                <p
                  className={cn(
                    'text-sm font-medium',
                    risk.total_pnl_pct_on_allocated >= 0 ? 'text-emerald-400' : 'text-red-400'
                  )}
                >
                  {formatPercent(risk.total_pnl_pct_on_allocated)}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Total Trades</p>
                <p className="text-sm font-medium text-slate-200">
                  {formatNumber(risk.total_trades)}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Winning</p>
                <p className="text-sm font-medium text-emerald-400">
                  {risk.winning_trades}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Losing</p>
                <p className="text-sm font-medium text-red-400">
                  {risk.losing_trades}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Open Positions</p>
                <p className="text-sm font-medium text-slate-200">
                  {risk.open_positions}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Configured cap: {risk.max_open_positions}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
              {Object.entries(portfolio?.market_breakdown ?? {}).map(([market, row]) => (
                <div key={market} className="rounded-lg border border-slate-800 bg-slate-950/60 p-4">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold text-slate-100">{row.label ?? market}</div>
                    <div className="text-xs text-slate-500">{row.open_positions ?? 0} open</div>
                  </div>
                  <div className="mt-2 text-sm text-slate-300">
                    Exposure:{' '}
                    <span className="text-slate-100">
                      {row.currency === 'USD'
                        ? `${row.currency_symbol}${Number(row.market_value ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                        : formatINR(Number(row.market_value_inr ?? 0))}
                    </span>
                  </div>
                  <div className={cn('mt-2 text-sm', Number(row.net_pnl_inr ?? 0) >= 0 ? 'text-emerald-300' : 'text-red-300')}>
                    Net P&L:{' '}
                    {row.currency === 'USD'
                      ? `${row.currency_symbol}${Number(row.net_pnl ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                      : formatINR(Number(row.net_pnl_inr ?? 0))}
                  </div>
                  <div className="mt-2 text-xs text-slate-500">
                    Allocation{' '}
                    {row.currency === 'USD'
                      ? `${row.currency_symbol}${Number(row.allocated_capital ?? 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}`
                      : formatINR(Number(row.allocated_capital_inr ?? 0))}
                    {' · '}
                    Used {formatPercent(Number(row.capital_used_pct ?? 0), 1)}
                    {' · '}
                    P&L {formatPercent(Number(row.pnl_pct_on_allocated ?? 0), 2)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="mt-4 text-sm text-slate-500">
            Risk data unavailable. Backend may be offline.
          </p>
        )}
      </div>
    </div>
  );
}

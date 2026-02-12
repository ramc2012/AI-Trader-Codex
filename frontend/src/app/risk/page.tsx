'use client';

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
} from 'recharts';
import { Shield, AlertTriangle } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useRiskSummary } from '@/hooks/use-risk-summary';
import { useRiskMetrics } from '@/hooks/use-risk-metrics';
import { apiFetch } from '@/lib/api';
import { formatINR, formatPercent, formatNumber } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import { Skeleton } from '@/components/ui/skeleton';
import type { EquitySnapshot } from '@/types/api';

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

export default function RiskPage() {
  const { data: risk, isLoading: riskLoading } = useRiskSummary();
  const { data: metrics, isLoading: metricsLoading } = useRiskMetrics();

  // Fetch equity curve from API instead of hardcoded sample data
  const { data: equityCurveApi, isLoading: equityLoading } = useQuery<EquitySnapshot[]>({
    queryKey: ['equity-curve'],
    queryFn: () => apiFetch<EquitySnapshot[]>('/portfolio/equity-curve'),
    refetchInterval: 10000,
  });

  // Also check for live WebSocket snapshots
  const { data: equityCurveLive } = useQuery<EquitySnapshot[]>({
    queryKey: ['equity-curve-live'],
    enabled: false, // populated by WebSocket hook on dashboard
  });

  // Use live data if available, else API data, else empty
  const equityCurveData = (equityCurveLive && equityCurveLive.length > 1)
    ? equityCurveLive.map((s) => ({
        time: new Date(s.time).toLocaleTimeString('en-IN', {
          hour: '2-digit',
          minute: '2-digit',
          hour12: false,
          timeZone: 'Asia/Kolkata',
        }),
        value: s.value,
      }))
    : (equityCurveApi ?? []).map((s) => ({
        time: new Date(s.time).toLocaleTimeString('en-IN', {
          hour: '2-digit',
          minute: '2-digit',
          hour12: false,
          timeZone: 'Asia/Kolkata',
        }),
        value: s.value,
      }));

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
          value={metrics ? formatPercent(-metrics.max_drawdown) : '--'}
          subtitle={
            metrics
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
          value={metrics ? formatPercent(metrics.total_return) : '--'}
          isLoading={metricsLoading}
        />
        <MetricCard
          title="Volatility"
          value={metrics ? formatPercent(metrics.volatility) : '--'}
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
        <div className="h-72">
          {equityLoading ? (
            <div className="flex h-full items-center justify-center">
              <Skeleton className="h-full w-full" />
            </div>
          ) : equityCurveData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={equityCurveData}>
                <defs>
                  <linearGradient id="riskEquity" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="time"
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
            </ResponsiveContainer>
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
                  {formatINR(risk.capital)}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Daily P&L</p>
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
                  {risk.open_positions} / {risk.max_open_positions}
                </p>
              </div>
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

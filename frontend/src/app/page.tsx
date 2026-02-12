'use client';

import { useEffect, useRef, useState } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Briefcase,
  Target,
  AlertTriangle,
  Trophy,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import { useQuery } from '@tanstack/react-query';
import { usePortfolio } from '@/hooks/use-portfolio';
import { useRiskSummary } from '@/hooks/use-risk-summary';
import { useStrategies } from '@/hooks/use-strategies';
import { useAlertCounts } from '@/hooks/use-alerts';
import { useDashboardWS } from '@/hooks/use-dashboard-ws';
import { apiFetch } from '@/lib/api';
import { formatINR, formatPercent } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import { Skeleton } from '@/components/ui/skeleton';
import type { EquitySnapshot } from '@/types/api';

/**
 * Detects when a displayed value changes and triggers a brief highlight.
 */
function useValueChange(value: string) {
  const [changed, setChanged] = useState(false);
  const prevRef = useRef(value);

  useEffect(() => {
    if (prevRef.current !== value && prevRef.current !== '') {
      setChanged(true);
      prevRef.current = value;
      const timer = setTimeout(() => setChanged(false), 600);
      return () => clearTimeout(timer);
    }
    prevRef.current = value;
  }, [value]);

  return changed;
}

function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  valueColor,
  isLoading,
}: {
  title: string;
  value: string;
  subtitle?: string;
  icon: React.ComponentType<{ className?: string }>;
  valueColor?: string;
  isLoading?: boolean;
}) {
  const changed = useValueChange(value);

  return (
    <div
      className={cn(
        'rounded-xl border border-slate-800 bg-slate-900 p-5 transition-all duration-300',
        changed && 'ring-1 ring-emerald-500/30 bg-slate-800/80'
      )}
    >
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-400">{title}</p>
        <Icon className="h-5 w-5 text-slate-500" />
      </div>
      {isLoading ? (
        <Skeleton className="mt-3 h-8 w-32" />
      ) : (
        <p
          className={cn(
            'mt-2 text-2xl font-bold transition-all duration-300',
            valueColor || 'text-slate-100'
          )}
        >
          {value}
        </p>
      )}
      {subtitle && !isLoading && (
        <p className="mt-1 text-xs text-slate-500">{subtitle}</p>
      )}
      {isLoading && <Skeleton className="mt-2 h-4 w-20" />}
    </div>
  );
}

export default function DashboardPage() {
  const { data: portfolio, isLoading: portfolioLoading } = usePortfolio();
  const { data: risk, isLoading: riskLoading } = useRiskSummary();
  const { data: strategies, isLoading: strategiesLoading } = useStrategies();
  const { data: alertCounts, isLoading: alertsLoading } = useAlertCounts();

  // Wire WebSocket for real-time updates (injects into React Query cache)
  const { isConnected } = useDashboardWS();

  // Fetch equity curve from API (or use live WS snapshots)
  const { data: equityCurveApi } = useQuery<EquitySnapshot[]>({
    queryKey: ['equity-curve'],
    queryFn: () => apiFetch<EquitySnapshot[]>('/portfolio/equity-curve'),
    refetchInterval: 10000,
  });
  const { data: equityCurveLive } = useQuery<EquitySnapshot[]>({
    queryKey: ['equity-curve-live'],
    enabled: false, // populated by WebSocket hook
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

  const totalPnl = portfolio?.total_pnl ?? 0;
  const pnlColor = totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400';
  const PnlIcon = totalPnl >= 0 ? TrendingUp : TrendingDown;

  const totalAlerts =
    (alertCounts?.warning ?? 0) +
    (alertCounts?.critical ?? 0) +
    (alertCounts?.emergency ?? 0);

  const winRate = risk
    ? risk.total_trades > 0
      ? (risk.winning_trades / risk.total_trades) * 100
      : 0
    : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-100">Dashboard</h2>
          <p className="mt-1 text-sm text-slate-400">
            Real-time overview of your trading system
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isConnected ? (
            <Wifi className="h-4 w-4 text-emerald-500" />
          ) : (
            <WifiOff className="h-4 w-4 text-slate-600" />
          )}
          <span
            className={cn(
              'text-xs font-medium',
              isConnected ? 'text-emerald-400' : 'text-slate-500'
            )}
          >
            {isConnected ? 'Live' : 'Polling'}
          </span>
          <span
            className={cn(
              'h-2 w-2 rounded-full',
              isConnected ? 'bg-emerald-500 animate-pulse' : 'bg-slate-600'
            )}
          />
        </div>
      </div>

      {/* Stat cards grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard
          title="Portfolio Value"
          value={formatINR(portfolio?.total_market_value ?? 0)}
          subtitle={`${portfolio?.position_count ?? 0} positions`}
          icon={Briefcase}
          isLoading={portfolioLoading}
        />

        <StatCard
          title="Daily P&L"
          value={formatINR(totalPnl)}
          subtitle={
            portfolio
              ? `Realized: ${formatINR(portfolio.total_realized_pnl)} | Unrealized: ${formatINR(portfolio.total_unrealized_pnl)}`
              : undefined
          }
          icon={PnlIcon}
          valueColor={pnlColor}
          isLoading={portfolioLoading}
        />

        <StatCard
          title="Open Positions"
          value={String(risk?.open_positions ?? 0)}
          subtitle={`Max: ${risk?.max_open_positions ?? 0}`}
          icon={Briefcase}
          isLoading={riskLoading}
        />

        <StatCard
          title="Active Strategies"
          value={String(strategies?.enabled_count ?? 0)}
          subtitle={`${strategies?.total_signals ?? 0} signals | ${strategies?.total_trades ?? 0} trades`}
          icon={Target}
          isLoading={strategiesLoading}
        />

        <StatCard
          title="Alerts"
          value={String(totalAlerts)}
          subtitle={`${alertCounts?.critical ?? 0} critical | ${alertCounts?.warning ?? 0} warnings`}
          icon={AlertTriangle}
          valueColor={totalAlerts > 0 ? 'text-yellow-400' : 'text-slate-100'}
          isLoading={alertsLoading}
        />

        <StatCard
          title="Win Rate"
          value={formatPercent(winRate)}
          subtitle={`${risk?.winning_trades ?? 0}W / ${risk?.losing_trades ?? 0}L of ${risk?.total_trades ?? 0} trades`}
          icon={Trophy}
          valueColor={winRate >= 50 ? 'text-emerald-400' : 'text-red-400'}
          isLoading={riskLoading}
        />
      </div>

      {/* Equity curve */}
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
        <div className="h-64">
          {equityCurveData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={equityCurveData}>
                <defs>
                  <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
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
                  formatter={(val) => [formatINR(Number(val)), 'Value']}
                />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="#10b981"
                  strokeWidth={2}
                  fill="url(#equityGradient)"
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
    </div>
  );
}

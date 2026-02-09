'use client';

import {
  TrendingUp,
  TrendingDown,
  Briefcase,
  Target,
  AlertTriangle,
  Trophy,
} from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import { usePortfolio } from '@/hooks/use-portfolio';
import { useRiskSummary } from '@/hooks/use-risk-summary';
import { useStrategies } from '@/hooks/use-strategies';
import { useAlertCounts } from '@/hooks/use-alerts';
import { formatINR, formatPercent } from '@/lib/formatters';
import { cn } from '@/lib/utils';

// Sample equity curve data for the placeholder chart
const equityCurveData = [
  { time: '09:15', value: 1000000 },
  { time: '09:30', value: 1002500 },
  { time: '09:45', value: 1001800 },
  { time: '10:00', value: 1005200 },
  { time: '10:15', value: 1008100 },
  { time: '10:30', value: 1006500 },
  { time: '10:45', value: 1009800 },
  { time: '11:00', value: 1012000 },
  { time: '11:15', value: 1010500 },
  { time: '11:30', value: 1015200 },
  { time: '11:45', value: 1018000 },
  { time: '12:00', value: 1016200 },
  { time: '12:15', value: 1019500 },
  { time: '12:30', value: 1022000 },
  { time: '12:45', value: 1020800 },
  { time: '13:00', value: 1024500 },
  { time: '13:15', value: 1027000 },
  { time: '13:30', value: 1025200 },
  { time: '13:45', value: 1028800 },
  { time: '14:00', value: 1032000 },
  { time: '14:15', value: 1030500 },
  { time: '14:30', value: 1034200 },
  { time: '14:45', value: 1036800 },
  { time: '15:00', value: 1035000 },
  { time: '15:15', value: 1038500 },
];

function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn('animate-pulse rounded bg-slate-800', className)} />
  );
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
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-400">{title}</p>
        <Icon className="h-5 w-5 text-slate-500" />
      </div>
      {isLoading ? (
        <Skeleton className="mt-3 h-8 w-32" />
      ) : (
        <p className={cn('mt-2 text-2xl font-bold', valueColor || 'text-slate-100')}>
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
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Dashboard</h2>
        <p className="mt-1 text-sm text-slate-400">
          Real-time overview of your trading system
        </p>
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
        <h3 className="mb-4 text-sm font-medium text-slate-400">
          Intraday Equity Curve
        </h3>
        <div className="h-64">
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
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

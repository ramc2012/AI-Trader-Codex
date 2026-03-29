'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
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
import { AreaChart, Area, XAxis, YAxis, Tooltip } from 'recharts';
import { useQuery } from '@tanstack/react-query';
import { usePortfolio } from '@/hooks/use-portfolio';
import { useRiskSummary } from '@/hooks/use-risk-summary';
import { useStrategies } from '@/hooks/use-strategies';
import { useAlertCounts } from '@/hooks/use-alerts';
import { useDashboardWS } from '@/hooks/use-dashboard-ws';
import { useWebSocket } from '@/hooks/use-websocket';
import { apiFetch } from '@/lib/api';
import { formatINR, formatPercent } from '@/lib/formatters';
import { buildEquityChartData, equityChartWidth } from '@/lib/equity-chart';
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
      prevRef.current = value;
      const startTimer = setTimeout(() => setChanged(true), 0);
      const resetTimer = setTimeout(() => setChanged(false), 600);
      return () => {
        clearTimeout(startTimer);
        clearTimeout(resetTimer);
      };
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
  const [equityPeriod, setEquityPeriod] = useState<'daily' | 'week' | 'month' | 'year'>('daily');
  const [macroData, setMacroData] = useState<{
    news_sentiment: string;
    sentiment_score: number;
    fii_net_crores: number;
    dii_net_crores: number;
    market_breadth_ratio: number;
  } | null>(null);

  // Wire WebSocket for real-time updates (injects into React Query cache)
  const { isConnected } = useDashboardWS();

  const { data: portfolio, isLoading: portfolioLoading } = usePortfolio(!isConnected);
  const { data: risk, isLoading: riskLoading } = useRiskSummary(!isConnected);
  const { data: strategies, isLoading: strategiesLoading } = useStrategies(!isConnected);
  const { data: alertCounts, isLoading: alertsLoading } = useAlertCounts(!isConnected);

  useWebSocket({
    path: '/ws/stream',
    onMessage: useCallback((msg: any) => {
      if (msg.event_type === 'macro_update') {
        setMacroData(msg.payload);
      }
    }, []),
    enabled: true,
  });

  // Fetch equity curve from API (or use live WS snapshots)
  const { data: equityCurveApi } = useQuery<EquitySnapshot[]>({
    queryKey: ['equity-curve', equityPeriod],
    queryFn: () => apiFetch<EquitySnapshot[]>(`/portfolio/equity-curve?period=${encodeURIComponent(equityPeriod)}`),
  });
  const { data: equityCurveLive } = useQuery<EquitySnapshot[]>({
    queryKey: ['equity-curve-live'],
    enabled: false, // populated by WebSocket hook
  });

  // Use live data if available, else API data, else empty
  const equityCurveData = buildEquityChartData(equityCurveApi, equityCurveLive, equityPeriod);
  const chartWidth = equityChartWidth(equityCurveData.length);

  const totalPnl = portfolio?.total_pnl_inr ?? portfolio?.total_pnl ?? 0;
  const totalAllocatedCapital = portfolio?.total_allocated_capital_inr ?? 0;
  const totalPnlPct = portfolio?.total_pnl_pct_on_allocated ?? 0;
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
          title="Allocated Capital"
          value={formatINR(totalAllocatedCapital)}
          subtitle={`${portfolio?.position_count ?? 0} positions across all markets`}
          icon={Briefcase}
          isLoading={portfolioLoading}
        />

        <StatCard
          title="Total P&L"
          value={formatINR(totalPnl)}
          subtitle={
            portfolio
              ? `${formatPercent(totalPnlPct)} on capital | Realized ${formatINR(portfolio.total_realized_pnl_inr ?? portfolio.total_realized_pnl)}`
              : undefined
          }
          icon={PnlIcon}
          valueColor={pnlColor}
          isLoading={portfolioLoading}
        />

        <StatCard
          title="Open Positions"
          value={String(risk?.open_positions ?? 0)}
          subtitle="Currently open trade groups across active markets"
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

      {/* Macro & Sentiment Widget */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {macroData ? (
          <>
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 col-span-1 lg:col-span-2">
               <h3 className="text-sm font-medium text-slate-400 mb-4">News Sentiment (AI)</h3>
               <div className="flex items-center gap-4">
                 <div className={cn(
                   "text-2xl font-bold uppercase",
                   macroData.sentiment_score > 0.4 ? 'text-emerald-500' : macroData.sentiment_score < -0.4 ? 'text-red-500' : 'text-slate-300'
                 )}>{macroData.news_sentiment}</div>
                 <div className="flex-1 bg-slate-800 rounded-full h-2.5 overflow-hidden flex">
                    <div className="bg-red-500 h-full transition-all duration-300" style={{ width: `${Math.max(0, -macroData.sentiment_score * 100)}%`, marginLeft: 'auto' }}></div>
                    <div className="bg-emerald-500 h-full transition-all duration-300" style={{ width: `${Math.max(0, macroData.sentiment_score * 100)}%` }}></div>
                 </div>
                 <span className="text-xs text-slate-500 w-12 text-right">{(macroData.sentiment_score).toFixed(2)}</span>
               </div>
            </div>
            
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 col-span-1">
               <h3 className="text-sm font-medium text-slate-400 mb-1">Institutional Flow</h3>
               <div className="flex flex-col gap-2 mt-3">
                 <div className="flex justify-between text-sm">
                   <span className="text-slate-500">FII Net</span>
                   <span className={cn('font-medium', macroData.fii_net_crores >= 0 ? 'text-emerald-400' : 'text-red-400')}>{macroData.fii_net_crores > 0 ? '+' : ''}{macroData.fii_net_crores} Cr</span>
                 </div>
                 <div className="flex justify-between text-sm">
                   <span className="text-slate-500">DII Net</span>
                   <span className={cn('font-medium', macroData.dii_net_crores >= 0 ? 'text-emerald-400' : 'text-red-400')}>{macroData.dii_net_crores > 0 ? '+' : ''}{macroData.dii_net_crores} Cr</span>
                 </div>
               </div>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 col-span-1">
               <h3 className="text-sm font-medium text-slate-400 mb-1">Market Breadth</h3>
               <div className="mt-3 text-3xl font-light text-slate-100 flex items-center justify-between">
                 {macroData.market_breadth_ratio.toFixed(2)}
                 <span className="text-xs text-slate-500 ml-2">A/D Ratio</span>
               </div>
               <div className="w-full bg-slate-800 h-1.5 mt-4 rounded-full overflow-hidden">
                 <div className={cn('h-full transition-all', macroData.market_breadth_ratio >= 1 ? 'bg-emerald-500' : 'bg-red-500')} style={{ width: `${Math.min(100, Math.max(10, macroData.market_breadth_ratio * 30))}%` }} />
               </div>
            </div>
          </>
        ) : (
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 col-span-full">
            <div className="flex justify-between items-center mb-4"><Skeleton className="h-4 w-32" /><Skeleton className="h-4 w-12" /></div>
            <Skeleton className="h-12 w-full" />
          </div>
        )}
      </div>

      {/* Equity curve */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium text-slate-400">
              Equity Curve
            </h3>
            <div className="flex items-center gap-1 rounded-lg border border-slate-800 bg-slate-950/70 p-1">
              {(['daily', 'week', 'month', 'year'] as const).map((period) => (
                <button
                  key={period}
                  type="button"
                  onClick={() => setEquityPeriod(period)}
                  className={cn(
                    'rounded px-2 py-1 text-[11px] uppercase tracking-[0.12em]',
                    equityPeriod === period
                      ? 'bg-emerald-500/10 text-emerald-200'
                      : 'text-slate-400 hover:text-slate-200'
                  )}
                >
                  {period}
                </button>
              ))}
            </div>
          </div>
          {equityCurveLive && equityCurveLive.length > 1 && (
            <span className="text-xs text-emerald-500">
              {equityCurveLive.length} live snapshots
            </span>
          )}
        </div>
        <div className="h-64 overflow-x-auto">
          {equityCurveData.length > 0 ? (
            <AreaChart width={chartWidth} height={256} data={equityCurveData}>
                <defs>
                  <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
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
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-500">
              Equity data will appear once trading begins
            </div>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="mb-4">
          <h3 className="text-sm font-medium text-slate-400">Market Overview</h3>
        </div>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          {Object.entries(portfolio?.market_breakdown ?? {}).map(([market, row]) => (
            <div key={market} className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-slate-100">{row.label ?? market}</div>
                <div className="text-xs text-slate-500">{row.open_positions ?? 0} open</div>
              </div>
              <div className="mt-3 text-[11px] uppercase tracking-[0.18em] text-slate-500">Exposure</div>
              <div className="mt-1 text-lg font-semibold text-slate-100">
                {row.currency === 'USD'
                  ? `${row.currency_symbol}${Number(row.market_value ?? 0).toLocaleString('en-US', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`
                  : formatINR(Number(row.market_value_inr ?? 0))}
              </div>
              <div className="mt-3 text-[11px] uppercase tracking-[0.18em] text-slate-500">Net P&L</div>
              <div className={cn('mt-1 text-sm font-medium', Number(row.net_pnl_inr ?? 0) >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
                {row.currency === 'USD'
                  ? `${row.currency_symbol}${Number(row.net_pnl ?? 0).toLocaleString('en-US', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`
                  : formatINR(Number(row.net_pnl_inr ?? 0))}
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-xs text-slate-400">
                <div>
                  <div className="text-slate-500">Allocated</div>
                  <div className="mt-1 text-slate-200">
                    {row.currency === 'USD'
                      ? `${row.currency_symbol}${Number(row.allocated_capital ?? 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}`
                      : formatINR(Number(row.allocated_capital_inr ?? 0))}
                  </div>
                </div>
                <div>
                  <div className="text-slate-500">Used</div>
                  <div className="mt-1 text-slate-200">{formatPercent(Number(row.capital_used_pct ?? 0), 1)}</div>
                </div>
                <div>
                  <div className="text-slate-500">P&L %</div>
                  <div className={cn('mt-1', Number(row.pnl_pct_on_allocated ?? 0) >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
                    {formatPercent(Number(row.pnl_pct_on_allocated ?? 0), 2)}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

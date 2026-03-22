'use client';

import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  BarChart3,
  BrainCircuit,
  Layers3,
  Loader2,
  Radar,
  RefreshCw,
  Target,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';

import { apiFetch } from '@/lib/api';
import { cn } from '@/lib/utils';

interface ConditionRow {
  condition: string;
  support: number;
  hit_rate: number;
  lift: number;
}

interface CandidateRow {
  symbol: string;
  spot_symbol: string;
  market: 'NSE' | 'US';
  asset_type: 'stock' | 'index';
  date: string;
  source: string;
  variant: 'classic' | 'ai';
  direction: 'up' | 'down';
  target_name: string;
  score: number;
  strength: 'strong' | 'moderate' | 'weak';
  direction_probability: number;
  neutral_probability: number;
  direction_edge: number;
  allow_overnight: boolean;
  planned_holding_days: number;
  expected_move_pct: number;
  stop_loss: number;
  target: number;
  atr_pct: number;
  market_regime: 'bull' | 'bear' | 'neutral';
  baseline_hit_rate: number;
  matched_conditions: ConditionRow[];
  model_available: boolean;
  ai_adjustment?: number;
}

interface StrategyStats {
  closed_trades?: number;
  win_rate_pct?: number;
  net_pnl?: number;
  net_pnl_inr?: number;
  open_positions?: number;
  signals?: number;
  entries?: number;
  currency_symbol?: string;
}

interface MarketSummaryRow {
  market: string;
  asset_type: string;
  target: string;
  rows: number;
  symbols: number;
  hit_rate: number;
  top_condition?: string | null;
  top_condition_hit_rate?: number | null;
  top_condition_lift?: number | null;
}

interface OverviewResponse {
  research: {
    ready: boolean;
    dataset_rows: number;
    dataset_symbols: number;
    start_date?: string | null;
    end_date?: string | null;
    coverage_symbols: number;
    models_available: string[];
    summary: MarketSummaryRow[];
  };
  agent: {
    nse_universe_size: number;
    us_universe_size: number;
    strategy_enabled: Record<string, boolean>;
    active_strategies: string[];
    strategy_stats: Record<string, StrategyStats>;
    strategy_market_stats: Record<string, Record<string, StrategyStats>>;
  };
  classic_candidates: CandidateRow[];
  ai_candidates: CandidateRow[];
}

function formatNumber(value: number | undefined, digits = 0): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return value.toLocaleString('en-IN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function formatPct(value: number | undefined, digits = 1): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return `${value.toFixed(digits)}%`;
}

function formatPnl(stats: StrategyStats | undefined): string {
  if (!stats) return '—';
  const pnl = typeof stats.net_pnl_inr === 'number' ? stats.net_pnl_inr : stats.net_pnl;
  if (typeof pnl !== 'number' || !Number.isFinite(pnl)) return '—';
  const prefix = pnl > 0 ? '+' : '';
  return `${prefix}${formatNumber(pnl, 0)}`;
}

function directionClasses(direction: CandidateRow['direction']) {
  return direction === 'up'
    ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
    : 'border-rose-500/30 bg-rose-500/10 text-rose-200';
}

function StrategyCard({
  name,
  enabled,
  stats,
  marketStats,
  accent,
}: {
  name: string;
  enabled: boolean;
  stats: StrategyStats | undefined;
  marketStats: Record<string, StrategyStats> | undefined;
  accent: string;
}) {
  const marketBreakdown = Object.entries(marketStats ?? {})
    .filter(([, row]) => (row.closed_trades ?? 0) > 0 || (row.open_positions ?? 0) > 0 || (row.signals ?? 0) > 0)
    .map(([market, row]) => `${market} ${row.closed_trades ?? 0} closed`)
    .join(' · ');

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className={cn('inline-flex rounded-full border px-2.5 py-1 text-[11px] uppercase tracking-[0.2em]', accent)}>
            {enabled ? 'Enabled' : 'Configured Off'}
          </div>
          <h2 className="mt-3 text-lg font-semibold text-slate-100">{name}</h2>
        </div>
        <Radar className="h-4 w-4 text-slate-500" />
      </div>
      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Closed Trades</p>
          <p className="mt-2 text-xl font-semibold text-slate-100">{formatNumber(stats?.closed_trades, 0)}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Win Rate</p>
          <p className="mt-2 text-xl font-semibold text-slate-100">{formatPct(stats?.win_rate_pct, 1)}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Net P&amp;L</p>
          <p className="mt-2 text-xl font-semibold text-slate-100">{formatPnl(stats)}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Open Positions</p>
          <p className="mt-2 text-xl font-semibold text-slate-100">{formatNumber(stats?.open_positions, 0)}</p>
        </div>
      </div>
      <p className="mt-4 text-xs leading-5 text-slate-400">
        {marketBreakdown || 'No recorded trades yet. Once fills happen, the agent status ledger will keep this strategy separate from the other swing lanes.'}
      </p>
    </div>
  );
}

function CandidateTable({
  title,
  subtitle,
  candidates,
  accent,
}: {
  title: string;
  subtitle: string;
  candidates: CandidateRow[];
  accent: string;
}) {
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/70">
      <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">{title}</h2>
          <p className="mt-1 text-xs text-slate-400">{subtitle}</p>
        </div>
        <div className={cn('rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.18em]', accent)}>
          {candidates.length} candidates
        </div>
      </div>

      {candidates.length === 0 ? (
        <div className="p-5 text-sm text-slate-300">No names cleared the current threshold.</div>
      ) : (
        <div className="overflow-x-auto">
          <div className="min-w-[1050px]">
            <div className="grid grid-cols-[0.8fr_0.5fr_0.6fr_0.55fr_0.55fr_0.65fr_0.6fr_1.2fr] gap-3 border-b border-slate-800 px-5 py-3 text-[11px] uppercase tracking-[0.18em] text-slate-500">
              <span>Symbol</span>
              <span>Market</span>
              <span>Direction</span>
              <span className="text-right">Score</span>
              <span className="text-right">Prob</span>
              <span className="text-right">Move</span>
              <span>Target</span>
              <span>Top Condition</span>
            </div>
            {candidates.map((candidate) => {
              const topCondition = candidate.matched_conditions[0];
              return (
                <div
                  key={`${candidate.variant}-${candidate.spot_symbol}-${candidate.date}`}
                  className="grid grid-cols-[0.8fr_0.5fr_0.6fr_0.55fr_0.55fr_0.65fr_0.6fr_1.2fr] gap-3 border-b border-slate-800/70 px-5 py-4 text-sm text-slate-200 last:border-b-0"
                >
                  <div>
                    <p className="font-medium text-slate-100">{candidate.symbol}</p>
                    <p className="mt-1 text-xs text-slate-500">{candidate.date}</p>
                  </div>
                  <div className="text-xs text-slate-300">{candidate.market}</div>
                  <div>
                    <div className={cn('inline-flex rounded-full border px-2 py-1 text-[11px] uppercase tracking-[0.18em]', directionClasses(candidate.direction))}>
                      {candidate.direction}
                    </div>
                    <p className="mt-2 text-xs text-slate-500">{candidate.market_regime}</p>
                  </div>
                  <div className="text-right">
                    <p className="font-medium text-slate-100">{formatNumber(candidate.score, 1)}</p>
                    <p className="mt-1 text-xs text-slate-500">{candidate.model_available ? 'model' : 'rules'}</p>
                  </div>
                  <div className="text-right">
                    <p className="font-medium text-slate-100">{formatPct(candidate.direction_probability * 100, 1)}</p>
                    <p className="mt-1 text-xs text-slate-500">edge {formatPct(candidate.direction_edge * 100, 1)}</p>
                  </div>
                  <div className="text-right">
                    <p className="font-medium text-slate-100">{formatPct(candidate.expected_move_pct, 1)}</p>
                    <p className="mt-1 text-xs text-slate-500">{candidate.planned_holding_days}D hold</p>
                  </div>
                  <div className="text-xs text-slate-300">{candidate.target_name}</div>
                  <div>
                    <p className="line-clamp-2 text-sm text-slate-200">
                      {topCondition?.condition ?? 'No matched profile condition'}
                    </p>
                    {topCondition ? (
                      <p className="mt-1 text-xs text-slate-500">
                        lift {formatNumber(topCondition.lift, 2)} · hit {formatPct(topCondition.hit_rate * 100, 1)}
                      </p>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}

export default function ProfileSwingRadarPage() {
  const overviewQuery = useQuery<OverviewResponse>({
    queryKey: ['profile-swing-radar-overview'],
    queryFn: () => apiFetch('/profile-swing-radar/overview?limit=24&min_score=58'),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  if (overviewQuery.isLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <div className="flex items-center gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 px-5 py-4 text-sm text-slate-300">
          <Loader2 className="h-4 w-4 animate-spin text-cyan-400" />
          Loading profile swing radar...
        </div>
      </div>
    );
  }

  if (overviewQuery.isError || !overviewQuery.data) {
    return (
      <section className="rounded-2xl border border-rose-500/20 bg-rose-500/5 p-6">
        <p className="text-sm font-medium text-rose-200">Profile swing radar failed to load.</p>
        <p className="mt-2 text-sm text-slate-300">
          {overviewQuery.error instanceof Error ? overviewQuery.error.message : 'Unknown error'}
        </p>
      </section>
    );
  }

  const { research, agent, classic_candidates, ai_candidates } = overviewQuery.data;
  const classicStats = agent.strategy_stats.Profile_Swing_Radar;
  const aiStats = agent.strategy_stats.Profile_AI_Swing_Radar;

  return (
    <div className="space-y-6">
      <section className="rounded-[28px] border border-slate-800 bg-[radial-gradient(circle_at_top_left,_rgba(34,197,94,0.14),_transparent_26%),radial-gradient(circle_at_top_right,_rgba(59,130,246,0.16),_transparent_32%),linear-gradient(135deg,rgba(15,23,42,0.97),rgba(2,6,23,0.99))] p-6 shadow-[0_18px_70px_rgba(2,6,23,0.45)]">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.24em] text-emerald-200">
              <Layers3 className="h-3.5 w-3.5" />
              Daily · Weekly · Monthly Profiles
            </div>
            <h1 className="mt-4 text-3xl font-semibold tracking-tight text-slate-100">
              Profile Swing Radar
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
              Two new swing lanes built from the hourly market-profile study: a rules-based profile
              radar and a learning-assisted AI variant. Both are tracked as separate strategies in
              the live agent, so their fills and performance stay isolated.
            </p>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-right">
            <div className="flex items-center justify-end gap-2 text-xs text-slate-400">
              {overviewQuery.isFetching ? (
                <RefreshCw className="h-3.5 w-3.5 animate-spin text-emerald-300" />
              ) : (
                <Activity className="h-3.5 w-3.5 text-emerald-300" />
              )}
              Latest profile artifact snapshot
            </div>
            <p className="mt-1 text-sm font-medium text-slate-100">{research.end_date ?? 'Unavailable'}</p>
            <p className="mt-1 text-xs text-slate-500">
              Models bundled: {research.models_available.length > 0 ? research.models_available.length : 'none yet'}
            </p>
          </div>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
            <div className="flex items-center justify-between">
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Dataset</p>
              <BarChart3 className="h-4 w-4 text-slate-500" />
            </div>
            <p className="mt-3 text-2xl font-semibold text-slate-100">{formatNumber(research.dataset_rows, 0)}</p>
            <p className="mt-1 text-xs text-slate-400">
              {research.dataset_symbols} symbols · {research.start_date ?? '—'} to {research.end_date ?? '—'}
            </p>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
            <div className="flex items-center justify-between">
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Classic Lane</p>
              <TrendingUp className="h-4 w-4 text-slate-500" />
            </div>
            <p className="mt-3 text-2xl font-semibold text-slate-100">{classic_candidates.length}</p>
            <p className="mt-1 text-xs text-slate-400">
              {agent.strategy_enabled.Profile_Swing_Radar ? 'Enabled in runtime' : 'Not enabled'} · NSE {agent.nse_universe_size} · US {agent.us_universe_size}
            </p>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
            <div className="flex items-center justify-between">
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">AI Lane</p>
              <BrainCircuit className="h-4 w-4 text-slate-500" />
            </div>
            <p className="mt-3 text-2xl font-semibold text-slate-100">{ai_candidates.length}</p>
            <p className="mt-1 text-xs text-slate-400">
              {agent.strategy_enabled.Profile_AI_Swing_Radar ? 'Enabled in runtime' : 'Not enabled'} · uses online learning bias when trade history accumulates
            </p>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
            <div className="flex items-center justify-between">
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Coverage</p>
              <Target className="h-4 w-4 text-slate-500" />
            </div>
            <p className="mt-3 text-2xl font-semibold text-slate-100">{formatNumber(research.coverage_symbols, 0)}</p>
            <p className="mt-1 text-xs text-slate-400">Symbols with constructed profile history in the research snapshot</p>
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-2">
        <StrategyCard
          name="Profile_Swing_Radar"
          enabled={agent.strategy_enabled.Profile_Swing_Radar}
          stats={classicStats}
          marketStats={agent.strategy_market_stats.Profile_Swing_Radar}
          accent="border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
        />
        <StrategyCard
          name="Profile_AI_Swing_Radar"
          enabled={agent.strategy_enabled.Profile_AI_Swing_Radar}
          stats={aiStats}
          marketStats={agent.strategy_market_stats.Profile_AI_Swing_Radar}
          accent="border-sky-500/30 bg-sky-500/10 text-sky-200"
        />
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-200">
          <Target className="h-4 w-4 text-slate-400" />
          Research Summary
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {research.summary.map((row) => (
            <div key={`${row.market}-${row.asset_type}-${row.target}`} className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
              <div className="flex items-center justify-between text-[11px] uppercase tracking-[0.18em] text-slate-500">
                <span>{row.market} {row.asset_type}</span>
                <span>{row.target}</span>
              </div>
              <p className="mt-3 text-xl font-semibold text-slate-100">{formatPct(row.hit_rate * 100, 1)}</p>
              <p className="mt-1 text-xs text-slate-400">{row.rows} rows · {row.symbols} symbols</p>
              <p className="mt-3 line-clamp-2 text-sm text-slate-300">{row.top_condition ?? 'No top condition stored'}</p>
              {row.top_condition_lift ? (
                <p className="mt-1 text-xs text-slate-500">
                  lift {formatNumber(row.top_condition_lift, 2)} · hit {formatPct((row.top_condition_hit_rate ?? 0) * 100, 1)}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-2">
        <CandidateTable
          title="Classic Profile Candidates"
          subtitle="Condition-led swing setups from the profile interaction study."
          candidates={classic_candidates}
          accent="border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
        />
        <CandidateTable
          title="AI Profile Candidates"
          subtitle="Same profile structure, but scored with model/learning assistance when artifacts exist."
          candidates={ai_candidates}
          accent="border-sky-500/30 bg-sky-500/10 text-sky-200"
        />
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5 text-sm leading-6 text-slate-300">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-100">
          <TrendingDown className="h-4 w-4 text-slate-400" />
          Strategy Behavior
        </div>
        <p className="mt-3">
          The classic lane only scores profile-condition interactions. The AI lane uses the same
          profile features, then adds model probabilities when joblib artifacts are present and
          adjusts confidence using the strategy’s own live learning profile once enough trades exist.
        </p>
      </section>
    </div>
  );
}

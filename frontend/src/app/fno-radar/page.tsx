'use client';

import { useQuery } from '@tanstack/react-query';
import type { ComponentType } from 'react';
import {
  Activity,
  BrainCircuit,
  Clock3,
  Database,
  Loader2,
  Radar,
  RefreshCw,
  Target,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';

import { apiFetch } from '@/lib/api';
import { formatDateTime, formatNumber } from '@/lib/formatters';
import { cn } from '@/lib/utils';

interface FnORadarCondition {
  condition: string;
  support: number;
  hit_rate: number;
  lift: number;
}

interface FnORadarCandidate {
  symbol: string;
  spot_symbol: string;
  sector: string;
  price: number;
  date: string;
  source: string;
  direction: 'up' | 'down';
  horizon: '2D' | '10_15D';
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
  matched_conditions: FnORadarCondition[];
}

interface FnORadarOverview {
  research: {
    ready: boolean;
    requested_symbols?: number;
    downloaded_symbols?: number;
    dataset_rows?: number;
    dataset_symbols?: number;
    start_date?: string;
    end_date?: string;
    failed_symbols?: string[];
    selected_short?: { multiplier?: number; positive_rate?: number };
    selected_long?: { multiplier?: number; positive_rate?: number };
  };
  local_market_data: {
    daily_symbols: number;
    expected_symbols: number;
    latest_daily_bar?: string | null;
  };
  agent: {
    nse_universe_size: number;
    configured_fno_symbols: number;
    expected_fno_symbols: number;
    strategy_enabled: boolean;
    active_strategies: string[];
  };
  candidates: FnORadarCandidate[];
}

function formatPct(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return '—';
  return `${value.toFixed(digits)}%`;
}

function directionClasses(direction: 'up' | 'down') {
  return direction === 'up'
    ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
    : 'border-rose-500/30 bg-rose-500/10 text-rose-200';
}

function regimeClasses(regime: FnORadarCandidate['market_regime']) {
  if (regime === 'bull') return 'text-emerald-300';
  if (regime === 'bear') return 'text-rose-300';
  return 'text-slate-300';
}

function SummaryCard({
  title,
  value,
  subtitle,
  icon: Icon,
}: {
  title: string;
  value: string;
  subtitle: string;
  icon: ComponentType<{ className?: string }>;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
      <div className="flex items-center justify-between">
        <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">{title}</p>
        <Icon className="h-4 w-4 text-slate-500" />
      </div>
      <p className="mt-3 text-2xl font-semibold text-slate-100">{value}</p>
      <p className="mt-1 text-xs leading-5 text-slate-400">{subtitle}</p>
    </div>
  );
}

export default function FnORadarPage() {
  const overviewQuery = useQuery<FnORadarOverview>({
    queryKey: ['fno-radar-overview'],
    queryFn: () => apiFetch('/fno-radar/overview?limit=60&min_score=55'),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  if (overviewQuery.isLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <div className="flex items-center gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 px-5 py-4 text-sm text-slate-300">
          <Loader2 className="h-4 w-4 animate-spin text-cyan-400" />
          Loading FnO swing research snapshot...
        </div>
      </div>
    );
  }

  if (overviewQuery.isError || !overviewQuery.data) {
    return (
      <section className="rounded-2xl border border-rose-500/20 bg-rose-500/5 p-6">
        <p className="text-sm font-medium text-rose-200">FnO Radar failed to load.</p>
        <p className="mt-2 text-sm text-slate-300">
          {overviewQuery.error instanceof Error ? overviewQuery.error.message : 'Unknown error'}
        </p>
      </section>
    );
  }

  const { research, local_market_data: localData, agent, candidates } = overviewQuery.data;
  const topCandidate = candidates[0] ?? null;
  const bullish = candidates.filter((item) => item.direction === 'up').length;
  const bearish = candidates.filter((item) => item.direction === 'down').length;

  return (
    <div className="space-y-6">
      <section className="rounded-[28px] border border-slate-800 bg-[radial-gradient(circle_at_top_left,_rgba(8,145,178,0.18),_transparent_28%),linear-gradient(135deg,rgba(15,23,42,0.96),rgba(2,6,23,0.99))] p-6 shadow-[0_18px_70px_rgba(2,6,23,0.45)]">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.24em] text-cyan-200">
              <Radar className="h-3.5 w-3.5" />
              Research-Backed
            </div>
            <h1 className="mt-4 text-3xl font-semibold tracking-tight text-slate-100">
              FnO Radar
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
              Daily swing board for the full FnO equity universe. It ranks names using the
              10-year research run, shows the current artifact status, and highlights how much
              of that universe is already available in the local live database.
            </p>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-right">
            <div className="flex items-center justify-end gap-2 text-xs text-slate-400">
              {overviewQuery.isFetching ? (
                <RefreshCw className="h-3.5 w-3.5 animate-spin text-cyan-300" />
              ) : (
                <Activity className="h-3.5 w-3.5 text-cyan-300" />
              )}
              Latest artifact snapshot
            </div>
            <p className="mt-1 text-sm font-medium text-slate-100">
              {research.end_date ?? 'Unavailable'}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Agent strategy {agent.strategy_enabled ? 'enabled' : 'not enabled'} in the current runtime.
            </p>
          </div>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <SummaryCard
            title="Research Symbols"
            value={`${research.downloaded_symbols ?? 0}/${research.requested_symbols ?? 0}`}
            subtitle={`${research.dataset_symbols ?? 0} symbols usable in the labeled swing dataset`}
            icon={Database}
          />
          <SummaryCard
            title="Dataset Rows"
            value={formatNumber(research.dataset_rows ?? 0, 0)}
            subtitle={`Research window ${research.start_date ?? '—'} to ${research.end_date ?? '—'}`}
            icon={BrainCircuit}
          />
          <SummaryCard
            title="Local Daily Coverage"
            value={`${localData.daily_symbols}/${localData.expected_symbols}`}
            subtitle={localData.latest_daily_bar ? `Latest local D bar ${formatDateTime(localData.latest_daily_bar)}` : 'Local D candles not populated yet'}
            icon={Activity}
          />
          <SummaryCard
            title="Agent FnO Universe"
            value={`${agent.configured_fno_symbols}/${agent.expected_fno_symbols}`}
            subtitle={`${agent.active_strategies.length} active strategies in the current agent config`}
            icon={Target}
          />
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.45fr_0.95fr]">
        <div className="rounded-2xl border border-slate-800 bg-slate-900/70">
          <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-100">Swing Candidates</h2>
              <p className="mt-1 text-xs text-slate-400">
                Top names ranked from the completed research snapshot. Bullish {bullish} · Bearish {bearish}
              </p>
            </div>
            <div className="text-right text-xs text-slate-500">
              <p>2D target multiplier {research.selected_short?.multiplier ?? '—'}x ATR</p>
              <p>10-15D target multiplier {research.selected_long?.multiplier ?? '—'}x ATR</p>
            </div>
          </div>

          {candidates.length === 0 ? (
            <div className="p-6 text-sm text-slate-300">No candidates cleared the current score threshold.</div>
          ) : (
            <div className="overflow-x-auto">
              <div className="min-w-[960px]">
                <div className="grid grid-cols-[0.9fr_0.65fr_0.55fr_0.6fr_0.6fr_0.75fr_0.9fr_1.1fr] gap-3 border-b border-slate-800 px-5 py-3 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                  <span>Symbol</span>
                  <span>Direction</span>
                  <span className="text-right">Score</span>
                  <span className="text-right">Prob</span>
                  <span className="text-right">Move</span>
                  <span>Horizon</span>
                  <span>Regime</span>
                  <span>Top Condition</span>
                </div>

                {candidates.map((item) => {
                  const topCondition = item.matched_conditions[0];
                  return (
                    <div
                      key={`${item.symbol}-${item.horizon}`}
                      className="grid grid-cols-[0.9fr_0.65fr_0.55fr_0.6fr_0.6fr_0.75fr_0.9fr_1.1fr] gap-3 border-b border-slate-800/60 px-5 py-4"
                    >
                      <div>
                        <p className="text-sm font-semibold text-slate-100">{item.symbol}</p>
                        <p className="mt-1 text-xs text-slate-400">
                          {item.sector} · {formatNumber(item.price, 2)}
                        </p>
                      </div>
                      <div className="flex items-start">
                        <span className={cn('inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium', directionClasses(item.direction))}>
                          {item.direction === 'up' ? (
                            <TrendingUp className="h-3.5 w-3.5" />
                          ) : (
                            <TrendingDown className="h-3.5 w-3.5" />
                          )}
                          {item.direction === 'up' ? 'Bullish' : 'Bearish'}
                        </span>
                      </div>
                      <div className="text-right">
                        <p className="text-xl font-semibold text-slate-100">{item.score.toFixed(0)}</p>
                        <p className="mt-1 text-xs text-slate-500">{item.strength}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-medium text-slate-100">{formatPct(item.direction_probability * 100, 1)}</p>
                        <p className="mt-1 text-xs text-slate-500">edge {formatPct(item.direction_edge * 100, 1)}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-medium text-slate-100">{formatPct(item.expected_move_pct, 1)}</p>
                        <p className="mt-1 text-xs text-slate-500">ATR {formatPct(item.atr_pct, 1)}</p>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-slate-100">{item.horizon.replace('_', '-')}</p>
                        <p className="mt-1 text-xs text-slate-500">{item.planned_holding_days} trading days</p>
                      </div>
                      <div>
                        <p className={cn('text-sm font-medium capitalize', regimeClasses(item.market_regime))}>
                          {item.market_regime}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          baseline {formatPct(item.baseline_hit_rate, 1)}
                        </p>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-slate-100">
                          {topCondition?.condition ?? 'No matched research condition'}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {topCondition ? `lift ${topCondition.lift.toFixed(2)} · hit ${formatPct(topCondition.hit_rate * 100, 1)}` : item.source}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <aside className="space-y-4">
          <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Top Candidate</p>
            {topCandidate ? (
              <>
                <div className="mt-3 flex items-start justify-between gap-4">
                  <div>
                    <h2 className="text-2xl font-semibold text-slate-100">{topCandidate.symbol}</h2>
                    <p className="mt-1 text-sm text-slate-400">
                      {topCandidate.sector} · {topCandidate.spot_symbol}
                    </p>
                  </div>
                  <span className={cn('inline-flex items-center gap-1 rounded-full border px-3 py-1 text-sm font-medium', directionClasses(topCandidate.direction))}>
                    {topCandidate.direction === 'up' ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
                    {topCandidate.direction === 'up' ? 'Bullish' : 'Bearish'}
                  </span>
                </div>

                <div className="mt-5 grid gap-3">
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Setup</p>
                    <p className="mt-2 text-sm text-slate-100">
                      Score {topCandidate.score.toFixed(0)} · {formatPct(topCandidate.direction_probability * 100, 1)} directional confidence
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {topCandidate.horizon.replace('_', '-')} horizon with {topCandidate.planned_holding_days} trading-day hold allowance
                    </p>
                  </div>

                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Trade Map</p>
                    <p className="mt-2 text-sm text-slate-100">
                      Entry {formatNumber(topCandidate.price, 2)} · Stop {formatNumber(topCandidate.stop_loss, 2)} · Target {formatNumber(topCandidate.target, 2)}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      Expected volatility-adjusted move {formatPct(topCandidate.expected_move_pct, 1)}
                    </p>
                  </div>

                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Research Match</p>
                    <p className="mt-2 text-sm text-slate-100">
                      {topCandidate.matched_conditions[0]?.condition ?? 'No high-lift condition matched'}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {topCandidate.matched_conditions[0]
                        ? `Lift ${topCandidate.matched_conditions[0].lift.toFixed(2)} · support ${formatNumber(topCandidate.matched_conditions[0].support, 0)}`
                        : `Source ${topCandidate.source}`}
                    </p>
                  </div>
                </div>
              </>
            ) : (
              <p className="mt-3 text-sm text-slate-300">No high-conviction swing candidate available.</p>
            )}
          </section>

          <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
            <h3 className="text-lg font-semibold text-slate-100">What This Means</h3>
            <div className="mt-4 space-y-3 text-sm leading-6 text-slate-300">
              <p>
                The research pull is complete through <span className="font-medium text-slate-100">{research.end_date ?? '—'}</span>.
                These ranks come from that completed artifact snapshot, not from partial intraday data.
              </p>
              <p>
                Local live coverage is currently <span className="font-medium text-slate-100">{localData.daily_symbols}/{localData.expected_symbols}</span>.
                The agent can still trade beyond that count if broker or cache backfill is available at scan time.
              </p>
              <p>
                `FnO_Swing_Radar` is {agent.strategy_enabled ? 'enabled' : 'disabled'} and the configured agent universe currently
                covers <span className="font-medium text-slate-100">{agent.configured_fno_symbols}/{agent.expected_fno_symbols}</span> FnO stocks.
              </p>
            </div>

            <div className="mt-5 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
              <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-slate-500">
                <Clock3 className="h-3.5 w-3.5" />
                Failed Downloads
              </div>
              <p className="mt-2 text-sm text-slate-300">
                {(research.failed_symbols ?? []).length > 0
                  ? research.failed_symbols?.join(', ')
                  : 'None in the stored research summary.'}
              </p>
            </div>
          </section>
        </aside>
      </section>
    </div>
  );
}

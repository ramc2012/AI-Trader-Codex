'use client';

import React, { useState } from 'react';
import {
  Activity,
  BarChart2,
  BookOpen,
  Brain,
  RefreshCw,
  Save,
  Settings2,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react';

import {
  useAgentInspector,
  useAgentStatus,
  useAvailableStrategies,
  useSetAgentStrategy,
  useUpdateAgentStrategyParams,
} from '@/hooks/use-agent';
import { useSignals } from '@/hooks/use-signals';
import { useStrategies } from '@/hooks/use-strategies';
import { formatDateTime, formatINR } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import type {
  AgentInspectorStrategy,
  AgentOptionContractSnapshot,
  AgentOptionsAnalytics,
  AgentStrategySettingField,
  PerformanceStats,
} from '@/types/api';

// ─────────────────────────────────────────────────────────────────────────────
// Formatters
// ─────────────────────────────────────────────────────────────────────────────
function formatNumber(value: unknown, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return value.toLocaleString('en-IN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') return formatNumber(value, 4);
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value)) return value.length ? value.map((item) => formatValue(item)).join(', ') : '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function flattenEntries(value: unknown, prefix = ''): Array<{ key: string; value: unknown }> {
  if (value === null || value === undefined) return prefix ? [{ key: prefix, value: null }] : [];
  if (Array.isArray(value)) return prefix ? [{ key: prefix, value }] : [];
  if (typeof value !== 'object') return prefix ? [{ key: prefix, value }] : [];
  const entries = Object.entries(value as Record<string, unknown>);
  const flattened = entries.flatMap(([key, nested]) =>
    flattenEntries(nested, prefix ? `${prefix}.${key}` : key),
  );
  return flattened.length > 0 ? flattened : prefix ? [{ key: prefix, value }] : [];
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function pruneObjectKeys(value: unknown, blockedKeys: Set<string>): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => pruneObjectKeys(item, blockedKeys));
  }
  if (!isPlainRecord(value)) {
    return value;
  }
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => !blockedKeys.has(key))
      .map(([key, nested]) => [key, pruneObjectKeys(nested, blockedKeys)]),
  );
}

function isDirectionalMetric(key: string): boolean {
  const token = key.toLowerCase();
  return [
    'change',
    'delta',
    'spread',
    'bias',
    'pressure',
    'distance',
    'pnl',
    'diff',
    'roc',
    'return',
    'drawdown',
    'score',
  ].some((part) => token.includes(part));
}

function formatGridValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number' && Number.isFinite(value)) {
    const digits = key.toLowerCase().includes('pct') ? 2 : 4;
    const formatted = formatNumber(value, digits);
    return isDirectionalMetric(key) && value > 0 ? `+${formatted}` : formatted;
  }
  return formatValue(value);
}

type MetricTone = 'positive' | 'negative' | 'warning' | 'info' | 'neutral' | 'default';

function toneClasses(tone: MetricTone): { card: string; value: string; dot: string } {
  switch (tone) {
    case 'positive':
      return {
        card: 'border-emerald-900/70 bg-emerald-950/20',
        value: 'text-emerald-200',
        dot: 'bg-emerald-400',
      };
    case 'negative':
      return {
        card: 'border-rose-900/70 bg-rose-950/20',
        value: 'text-rose-200',
        dot: 'bg-rose-400',
      };
    case 'warning':
      return {
        card: 'border-amber-900/70 bg-amber-950/20',
        value: 'text-amber-200',
        dot: 'bg-amber-400',
      };
    case 'info':
      return {
        card: 'border-sky-900/70 bg-sky-950/20',
        value: 'text-sky-200',
        dot: 'bg-sky-400',
      };
    case 'neutral':
      return {
        card: 'border-slate-700 bg-slate-950/70',
        value: 'text-slate-300',
        dot: 'bg-slate-500',
      };
    default:
      return {
        card: 'border-slate-800 bg-slate-950/60',
        value: 'text-slate-200',
        dot: 'bg-slate-600',
      };
  }
}

function classifyMetricTone(key: string, value: unknown): MetricTone {
  const token = key.toLowerCase();
  if (typeof value === 'boolean') {
    return value ? 'positive' : 'warning';
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (token.includes('rsi')) {
      if (value <= 30) return 'positive';
      if (value >= 70) return 'negative';
      return 'neutral';
    }
    if (token.includes('win_rate')) {
      if (value >= 55) return 'positive';
      if (value < 45) return 'negative';
      return 'warning';
    }
    if (isDirectionalMetric(token)) {
      if (value > 0) return 'positive';
      if (value < 0) return 'negative';
      return 'neutral';
    }
  }
  if (typeof value === 'string') {
    const normalized = value.toLowerCase();
    if (['bullish', 'buy', 'up', 'accepted', 'supportive', 'ready', 'enabled', 'oversold'].includes(normalized)) {
      return 'positive';
    }
    if (['bearish', 'sell', 'down', 'adverse', 'error', 'disabled', 'overbought'].includes(normalized)) {
      return 'negative';
    }
    if (['neutral', 'flat', 'balanced', 'mixed', 'hold'].includes(normalized)) {
      return 'neutral';
    }
    if (['trending', 'breakout_drive', 'gap_and_go', 'acceptance_trend'].includes(normalized)) {
      return 'info';
    }
  }
  return 'default';
}

// ─────────────────────────────────────────────────────────────────────────────
// Strategy descriptions
// ─────────────────────────────────────────────────────────────────────────────
const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  EMA_Crossover: 'Fast/slow EMA crossover with ADX trend-strength filter. Skips signals in choppy (ADX < 20) markets.',
  RSI_Reversal: 'RSI oversold/overbought reversals with volume-surge confirmation. Requires 1.5× volume above 20-period MA.',
  MACD_RSI: 'MACD histogram crossovers confirmed by RSI momentum divergence.',
  MP_OrderFlow_Breakout: 'Market Profile breakout from value area edges combined with live order-flow imbalance.',
  Fractal_Profile_Breakout: 'Fractal price-structure breakouts aligned with hourly market profile shapes.',
  Bollinger_MeanReversion: 'Bollinger Band mean-reversion with RSI confirmation. ADX regime filter blocks signals in trending (ADX > 25) markets.',
  Supertrend_Breakout: 'Supertrend directional bias shifts used as entry triggers.',
  ML_Ensemble: 'Online-learning ensemble of GBM, XGBoost, and RF models with adaptive confidence threshold.',
  FnO_Swing_Radar: 'Research-driven daily FnO swing strategy that scores 2-day and 10-15 day volatility-adjusted moves and allows multi-day option holds.',
  US_Swing_Radar: 'Research-driven US equity swing strategy for the 200-stock sector universe, with tuned live filters and multi-day option holds in paper/live simulation.',
  Profile_Swing_Radar: 'Rules-based swing strategy built from daily, weekly, and monthly profile interactions mined from the hourly research dataset.',
  Profile_AI_Swing_Radar: 'Learning-assisted profile swing strategy that blends the profile interaction research with optional model probabilities and online strategy learning.',
};

// ─────────────────────────────────────────────────────────────────────────────
// Indicator Filter Badges
// ─────────────────────────────────────────────────────────────────────────────
type BadgeTone = 'green' | 'amber' | 'red' | 'blue' | 'slate';

function FilterBadge({ label, value, tone }: { label: string; value: string; tone: BadgeTone }) {
  const toneClass: Record<BadgeTone, string> = {
    green: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
    amber: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
    red: 'border-rose-500/40 bg-rose-500/10 text-rose-300',
    blue: 'border-sky-500/40 bg-sky-500/10 text-sky-300',
    slate: 'border-slate-700 bg-slate-800/60 text-slate-400',
  };
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium', toneClass[tone])}>
      <span className="text-[9px] uppercase tracking-[0.15em] opacity-70">{label}</span>
      <span>{value}</span>
    </span>
  );
}

function IndicatorFiltersPanel({ snapshot }: { snapshot: Record<string, unknown> }) {
  const badges: React.ReactElement[] = [];

  // ADX (EMA_Crossover, Bollinger_MeanReversion, any with adx key)
  if (typeof snapshot.adx === 'number') {
    const adx = snapshot.adx;
    const tone: BadgeTone = adx < 20 ? 'red' : adx < 25 ? 'amber' : 'green';
    const label = adx < 20 ? 'Choppy' : adx < 25 ? 'Moderate' : 'Trending';
    badges.push(<FilterBadge key="adx" label="ADX" value={`${adx.toFixed(1)} — ${label}`} tone={tone} />);
  }

  // Regime (Bollinger)
  if (typeof snapshot.regime === 'string') {
    const regime = snapshot.regime as string;
    const tone: BadgeTone = regime === 'trending' ? 'amber' : 'green';
    badges.push(<FilterBadge key="regime" label="Regime" value={regime.charAt(0).toUpperCase() + regime.slice(1)} tone={tone} />);
  }

  // Volume surge (RSI_Reversal)
  if (typeof snapshot.volume_ratio === 'number') {
    const ratio = snapshot.volume_ratio;
    const surge = ratio >= 1.5;
    const tone: BadgeTone = surge ? 'green' : 'amber';
    badges.push(
      <FilterBadge key="vol" label="Volume" value={`${ratio.toFixed(2)}× ${surge ? '— Surge ✓' : '— Low'}`} tone={tone} />,
    );
  }

  // RSI level
  if (typeof snapshot.rsi === 'number') {
    const rsi = snapshot.rsi;
    const tone: BadgeTone = rsi < 30 ? 'green' : rsi > 70 ? 'red' : 'slate';
    const label = rsi < 30 ? 'Oversold' : rsi > 70 ? 'Overbought' : 'Neutral';
    badges.push(<FilterBadge key="rsi" label="RSI" value={`${rsi.toFixed(1)} — ${label}`} tone={tone} />);
  }

  // EMA crossover direction
  if (typeof snapshot.crossover_diff === 'number') {
    const diff = snapshot.crossover_diff;
    const tone: BadgeTone = diff > 0 ? 'green' : 'red';
    badges.push(<FilterBadge key="cross" label="EMA Cross" value={diff > 0 ? `+${diff.toFixed(2)} Bullish` : `${diff.toFixed(2)} Bearish`} tone={tone} />);
  }

  // ML confidence threshold
  if (typeof snapshot.confidence_threshold === 'number') {
    const thresh = snapshot.confidence_threshold;
    const tone: BadgeTone = thresh > 0.70 ? 'amber' : thresh < 0.55 ? 'green' : 'blue';
    badges.push(<FilterBadge key="conf" label="Confidence" value={`≥ ${(thresh * 100).toFixed(0)}%`} tone={tone} />);
  }

  if (badges.length === 0) return null;

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <span className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Filter State</span>
      {badges}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Strategy Health Bar (win rate + signal efficiency)
// ─────────────────────────────────────────────────────────────────────────────
function StrategyHealthBar({
  overallStats,
  signalCount,
  tradeCount,
}: {
  overallStats?: PerformanceStats;
  signalCount?: number;
  tradeCount?: number;
}) {
  if (!overallStats && !signalCount) return null;

  const winRate = overallStats?.win_rate_pct ?? 0;
  const closedTrades = overallStats?.closed_trades ?? 0;
  const signals = signalCount ?? 1;
  const trades = tradeCount ?? 0;
  const efficiency = signals > 0 ? Math.round((trades / signals) * 100) : 0;
  const pnlPct = overallStats?.pnl_pct_on_allocated ?? 0;

  const winTone = winRate >= 55 ? 'text-emerald-300' : winRate >= 45 ? 'text-amber-300' : 'text-rose-300';
  const effTone = efficiency >= 30 ? 'text-sky-300' : efficiency >= 15 ? 'text-amber-300' : 'text-slate-400';
  const pnlTone = pnlPct >= 0 ? 'text-emerald-300' : 'text-rose-300';

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 rounded-lg border border-slate-800 bg-slate-950/60 px-4 py-2.5">
      <div className="flex items-center gap-2">
        <BarChart2 className="h-3.5 w-3.5 text-slate-500" />
        <span className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Health</span>
      </div>
      {closedTrades > 0 ? (
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-slate-500">Win Rate</span>
          <span className={cn('text-xs font-semibold', winTone)}>{winRate.toFixed(1)}%</span>
          <span className="text-[10px] text-slate-600">({closedTrades} closed)</span>
        </div>
      ) : null}
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-slate-500">Signal→Trade</span>
        <span className={cn('text-xs font-semibold', effTone)}>{efficiency}%</span>
      </div>
      {pnlPct !== 0 ? (
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-slate-500">ROC on Alloc</span>
          <span className={cn('text-xs font-semibold', pnlTone)}>{pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%</span>
        </div>
      ) : null}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Online Learning Status Panel
// ─────────────────────────────────────────────────────────────────────────────
function OnlineLearningPanel({
  strategyStats,
}: {
  strategyStats?: Record<string, PerformanceStats>;
}) {
  if (!strategyStats) return null;

  const entries = Object.entries(strategyStats);
  if (entries.length === 0) return null;

  return (
    <section className="rounded-2xl border border-sky-900/50 bg-sky-950/20 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-sky-400" />
          <div>
            <h2 className="text-sm font-semibold text-sky-200">Online Learning Engine</h2>
            <p className="mt-0.5 text-xs text-sky-400/70">
              Models retrain incrementally after every 25 labelled trade outcomes. Weights and threshold adapt automatically.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-400" />
          <span className="text-[11px] font-medium text-sky-300">Active</span>
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {entries.map(([name, stats]) => {
          const wr = stats.win_rate_pct;
          const closed = stats.closed_trades;
          const pnl = stats.pnl_pct_on_allocated;
          const tone = wr >= 55 ? 'border-emerald-800/50 bg-emerald-950/30' : wr >= 45 ? 'border-amber-800/50 bg-amber-950/20' : 'border-slate-800 bg-slate-950/60';
          const wrTone = wr >= 55 ? 'text-emerald-300' : wr >= 45 ? 'text-amber-300' : 'text-rose-300';
          return (
            <div key={name} className={cn('rounded-xl border px-3 py-3', tone)}>
              <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-slate-400 truncate">{name.replace(/_/g, ' ')}</div>
              <div className="mt-2 flex items-end justify-between gap-2">
                <div>
                  <div className={cn('text-base font-semibold', wrTone)}>
                    {closed > 0 ? `${wr.toFixed(1)}% WR` : 'No trades'}
                  </div>
                  <div className="text-[10px] text-slate-500">{closed} closed · {stats.open_positions} open</div>
                </div>
                {pnl !== 0 ? (
                  <div className={cn('text-xs font-medium', pnl >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                    {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-3 text-[11px] text-sky-400/50">
        Strategy auto-disable activates when rolling Sharpe &lt; −0.5 after 20+ trades. Re-enable manually or wait for recovery.
      </p>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Available (not active) strategies panel
// ─────────────────────────────────────────────────────────────────────────────
function AvailableStrategiesPanel({
  allStrategies,
  activeStrategies,
  onEnable,
  pending,
}: {
  allStrategies: string[];
  activeStrategies: string[];
  onEnable: (name: string) => void;
  pending: boolean;
}) {
  const inactive = allStrategies.filter((name) => !activeStrategies.includes(name));
  if (inactive.length === 0) return null;

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
      <div className="flex items-center gap-2">
        <BookOpen className="h-4 w-4 text-slate-400" />
        <div>
          <h2 className="text-lg font-semibold text-slate-200">Available Strategies — Not Active</h2>
          <p className="mt-1 text-xs text-slate-500">
            These strategies exist in the registry but are not currently active. Enable them to start receiving their signals.
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {inactive.map((name) => (
          <div key={name} className="flex flex-col gap-3 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div>
              <div className="flex items-center gap-2">
                <Target className="h-3.5 w-3.5 text-slate-500" />
                <span className="text-sm font-semibold text-slate-200">{name.replace(/_/g, ' ')}</span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-slate-500">
                {STRATEGY_DESCRIPTIONS[name] ?? 'No description available.'}
              </p>
            </div>
            <button
              type="button"
              disabled={pending}
              onClick={() => onEnable(name)}
              className="mt-auto inline-flex items-center justify-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-medium text-emerald-200 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Sparkles className="h-3.5 w-3.5" />
              Add to Agent
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// DataGrid
// ─────────────────────────────────────────────────────────────────────────────
function DataGrid({ title, subtitle, value }: { title: string; subtitle?: string; value: unknown }) {
  const entries = flattenEntries(value);
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
        {subtitle ? <p className="mt-1 text-xs text-slate-500">{subtitle}</p> : null}
      </div>
      {entries.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-800 px-3 py-6 text-center text-sm text-slate-500">
          No data available
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {entries.map((entry) => {
            const tone = toneClasses(classifyMetricTone(entry.key, entry.value));
            return (
            <div key={entry.key} className={cn('rounded-lg border px-3 py-2', tone.card)}>
              <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{entry.key}</div>
              <div className={cn('mt-1 flex items-center gap-2 break-words font-mono text-xs font-medium', tone.value)}>
                <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', tone.dot)} />
                <span>{formatGridValue(entry.key, entry.value)}</span>
              </div>
            </div>
          )})}
        </div>
      )}
    </section>
  );
}

function OptionsAnalyticsPanel({
  optionsAnalytics,
  selectedContract,
  signalType,
}: {
  optionsAnalytics: AgentOptionsAnalytics | null | undefined;
  selectedContract: AgentOptionContractSnapshot | null | undefined;
  signalType: string | null | undefined;
}) {
  if (!optionsAnalytics && !selectedContract) return null;

  const resolvedContract =
    selectedContract
    ?? optionsAnalytics?.selected_contract
    ?? (signalType === 'BUY' ? optionsAnalytics?.bullish_call : null)
    ?? (signalType === 'SELL' ? optionsAnalytics?.bearish_put : null)
    ?? optionsAnalytics?.atm_call
    ?? optionsAnalytics?.atm_put
    ?? null;

  const metrics: Array<{ label: string; value: unknown }> = [
    { label: 'Suggested Side', value: optionsAnalytics?.suggested_side ?? (signalType === 'BUY' ? 'bullish_call' : signalType === 'SELL' ? 'bearish_put' : null) },
    { label: 'PCR', value: optionsAnalytics?.pcr },
    { label: 'Call OI Change', value: optionsAnalytics?.call_oi_change },
    { label: 'Put OI Change', value: optionsAnalytics?.put_oi_change },
    { label: 'Avg Call IV', value: optionsAnalytics?.avg_call_iv },
    { label: 'Avg Put IV', value: optionsAnalytics?.avg_put_iv },
    { label: 'ATM Strike', value: optionsAnalytics?.atm_strike },
    { label: 'Days to Expiry', value: optionsAnalytics?.days_to_expiry },
  ].filter((item) => item.value !== null && item.value !== undefined);

  return (
    <section className="rounded-xl border border-sky-900/50 bg-sky-950/15 p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-sky-100">Options Context</h3>
          <p className="mt-1 text-xs text-sky-300/70">
            Chain snapshot and selected contract used for options-only execution.
          </p>
        </div>
        {optionsAnalytics?.nearest_expiry ? (
          <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-sky-200">
            Expiry {optionsAnalytics.nearest_expiry}
          </span>
        ) : null}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
          <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Selected Contract</div>
          {resolvedContract ? (
            <>
              <div className="mt-2 text-sm font-semibold text-slate-100">{resolvedContract.symbol}</div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {[
                  { label: 'Strike', value: resolvedContract.strike },
                  { label: 'LTP', value: resolvedContract.ltp },
                  {
                    label: 'Bid / Ask',
                    value: `${formatNumber(resolvedContract.bid, 2)} / ${formatNumber(resolvedContract.ask, 2)}`,
                  },
                  { label: 'Volume', value: resolvedContract.volume },
                  { label: 'OI', value: resolvedContract.oi },
                  { label: 'OI Change', value: resolvedContract.oi_change },
                  { label: 'IV', value: resolvedContract.iv },
                  { label: 'Delta', value: resolvedContract.delta },
                  { label: 'Gamma', value: resolvedContract.gamma },
                  { label: 'Theta', value: resolvedContract.theta },
                  { label: 'Vega', value: resolvedContract.vega },
                ].map(({ label, value }) => {
                  const tone = toneClasses(classifyMetricTone(label, value));
                  return (
                    <div key={label} className={cn('rounded-lg border px-3 py-2', tone.card)}>
                      <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                      <div className={cn('mt-1 font-mono text-xs font-medium', tone.value)}>
                        {typeof value === 'string' ? value : formatGridValue(label, value)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <div className="mt-3 rounded-lg border border-dashed border-slate-800 px-3 py-5 text-sm text-slate-500">
              No contract selected for the latest signal.
            </div>
          )}
        </div>

        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
          {metrics.map(({ label, value }) => {
            const tone = toneClasses(classifyMetricTone(label, value));
            return (
              <div key={label} className={cn('rounded-lg border px-3 py-2', tone.card)}>
                <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                <div className={cn('mt-1 font-mono text-xs font-medium', tone.value)}>
                  {formatGridValue(label, value)}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Settings form
// ─────────────────────────────────────────────────────────────────────────────
function buildFieldValues(fields: AgentStrategySettingField[]): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {};
  for (const f of fields) {
    if (f.type === 'boolean') { out[f.name] = Boolean(f.value); continue; }
    out[f.name] = f.value === null || f.value === undefined ? '' : String(f.value);
  }
  return out;
}

function StrategySettingsForm({
  strategyName, fields, disabled, saving, onSave,
}: {
  strategyName: string;
  fields: AgentStrategySettingField[];
  disabled: boolean;
  saving: boolean;
  onSave: (strategyName: string, values: Record<string, unknown>) => void;
}) {
  const [values, setValues] = useState<Record<string, string | boolean>>(() => buildFieldValues(fields));

  if (fields.length === 0) {
    return (
      <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
        <div className="mb-3 flex items-center gap-2">
          <Settings2 className="h-4 w-4 text-slate-400" />
          <h3 className="text-sm font-semibold text-slate-200">Runtime Settings</h3>
        </div>
        <div className="rounded-lg border border-dashed border-slate-800 px-3 py-6 text-center text-sm text-slate-500">
          No editable settings exposed for this strategy.
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Settings2 className="h-4 w-4 text-slate-400" />
        <div>
          <h3 className="text-sm font-semibold text-slate-200">Runtime Settings</h3>
          <p className="mt-1 text-xs text-slate-500">Applies immediately to the live strategy instance.</p>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {fields.map((field) => (
          <label key={field.name} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{field.name}</span>
              <span className="text-[10px] uppercase tracking-[0.18em] text-slate-600">{field.type}</span>
            </div>
            {field.type === 'boolean' ? (
              <input
                type="checkbox"
                checked={Boolean(values[field.name])}
                disabled={disabled || saving}
                onChange={(e) => setValues((c) => ({ ...c, [field.name]: e.target.checked }))}
                className="mt-3 h-4 w-4 rounded border-slate-700 bg-slate-900 text-emerald-400 focus:ring-emerald-400"
              />
            ) : (
              <input
                type="number"
                step={field.type === 'integer' ? '1' : 'any'}
                value={typeof values[field.name] === 'string' ? (values[field.name] as string) : ''}
                disabled={disabled || saving}
                onChange={(e) => setValues((c) => ({ ...c, [field.name]: e.target.value }))}
                className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-emerald-400"
              />
            )}
            <div className="mt-2 text-xs text-slate-500">Default: {formatValue(field.default)}</div>
          </label>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => onSave(strategyName, values)}
          disabled={disabled || saving}
          className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm font-medium text-emerald-200 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Save className="h-4 w-4" />
          {saving ? 'Saving…' : 'Apply Settings'}
        </button>
        <span className="text-xs text-slate-500">Runtime-only. Reapply after a full agent reset.</span>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Strategy Card (reorganised)
// ─────────────────────────────────────────────────────────────────────────────
function StrategyCard({
  name, summary, overallStats, marketStats, instrumentStatsMap, selectedSymbol,
  inspector, sharedOptionsAnalytics, onToggle, togglePending, savePending, onSaveSettings,
}: {
  name: string;
  summary?: { enabled: boolean; signals: number; trades: number; pnl: number };
  overallStats?: PerformanceStats;
  marketStats?: Record<string, PerformanceStats>;
  instrumentStatsMap?: Record<string, PerformanceStats>;
  selectedSymbol: string;
  inspector?: AgentInspectorStrategy;
  sharedOptionsAnalytics?: AgentOptionsAnalytics | null;
  onToggle: (name: string, enabled: boolean) => void;
  togglePending: boolean;
  savePending: boolean;
  onSaveSettings: (strategyName: string, values: Record<string, unknown>) => void;
}) {
  const [statsTab, setStatsTab] = useState<'market' | 'instrument'>('market');
  const [selectedInstrumentStat, setSelectedInstrumentStat] = useState('');
  const enabled = inspector?.enabled ?? summary?.enabled ?? false;
  const latestSignal = inspector?.latest_signal;
  const instrumentStatSymbols = Object.keys(instrumentStatsMap ?? {}).sort((a, b) => a.localeCompare(b));
  const activeInstrumentKey = (() => {
    if (selectedInstrumentStat && instrumentStatSymbols.includes(selectedInstrumentStat)) return selectedInstrumentStat;
    if (selectedSymbol && instrumentStatSymbols.includes(selectedSymbol)) return selectedSymbol;
    return instrumentStatSymbols[0] ?? '';
  })();
  const activeInstrumentStats = activeInstrumentKey ? instrumentStatsMap?.[activeInstrumentKey] : undefined;
  const signalTone =
    latestSignal?.signal_type === 'BUY' ? 'text-emerald-300'
    : latestSignal?.signal_type === 'SELL' ? 'text-rose-300'
    : 'text-slate-400';
  const latestSignalMetadata = isPlainRecord(latestSignal?.metadata) ? latestSignal.metadata : {};
  const snapshot = inspector?.indicator_snapshot ?? {};
  const description = STRATEGY_DESCRIPTIONS[name];
  const genericGridBlockedKeys = new Set(['options_analytics', 'selected_option_candidate', 'option_flow']);
  const sanitizedSnapshot = pruneObjectKeys(snapshot, genericGridBlockedKeys) as Record<string, unknown>;
  const sanitizedLatestSignalMetadata = pruneObjectKeys(
    latestSignalMetadata,
    genericGridBlockedKeys,
  ) as Record<string, unknown>;
  const optionsAnalytics = (
    isPlainRecord(latestSignalMetadata.options_analytics)
      ? (latestSignalMetadata.options_analytics as unknown as AgentOptionsAnalytics)
      : sharedOptionsAnalytics
  ) ?? null;
  const selectedOptionCandidate = isPlainRecord(latestSignalMetadata.selected_option_candidate)
    ? (latestSignalMetadata.selected_option_candidate as unknown as AgentOptionContractSnapshot)
    : optionsAnalytics?.selected_contract ?? null;

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">

      {/* ── 1. HEADER ── */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl">
          <div className="flex flex-wrap items-center gap-2">
            <Target className="h-4 w-4 text-slate-400" />
            <h2 className="text-lg font-semibold text-slate-100">{name.replace(/_/g, ' ')}</h2>
            <span className={cn(
              'rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em]',
              enabled ? 'bg-emerald-500/10 text-emerald-300' : 'bg-slate-800 text-slate-400',
            )}>
              {enabled ? 'Enabled' : 'Disabled'}
            </span>
            {inspector ? (
              <span className={cn(
                'rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em]',
                inspector.ready ? 'bg-sky-500/10 text-sky-300' : 'bg-amber-500/10 text-amber-300',
              )}>
                {inspector.ready ? 'Ready' : 'Warming Up'}
              </span>
            ) : null}
            {/* Auto-disabled badge — shown when win rate is very low and trades exist */}
            {(overallStats?.closed_trades ?? 0) >= 20 && (overallStats?.win_rate_pct ?? 100) < 35 ? (
              <span className="rounded bg-rose-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-rose-300">
                Low Performance
              </span>
            ) : null}
          </div>
          <p className="mt-2 text-sm leading-relaxed text-slate-400">
            {description ?? inspector?.algorithm_summary ?? 'Strategy algorithm summary unavailable.'}
          </p>
          {inspector ? (
            <p className="mt-1.5 text-xs text-slate-500">
              Preferred TFs: <span className="text-slate-400">{inspector.preferred_timeframes.join(', ') || '—'}</span>
              {' '}· Inspecting <span className="text-slate-400">{inspector.timeframe}</span>
              {' '}· Bars <span className="text-slate-400">{inspector.bars_available}/{inspector.min_bars_required}+</span>
            </p>
          ) : null}

          {/* ── 2. INDICATOR FILTER STATUS ── */}
          <IndicatorFiltersPanel snapshot={snapshot} />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => onToggle(name, !enabled)}
            disabled={togglePending}
            className={cn(
              'rounded-lg border px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50',
              enabled
                ? 'border-amber-500/40 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20'
                : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20',
            )}
          >
            {togglePending ? 'Updating…' : enabled ? 'Disable' : 'Enable'}
          </button>
        </div>
      </div>

      {/* ── 3. HEALTH BAR ── */}
      <StrategyHealthBar
        overallStats={overallStats}
        signalCount={summary?.signals}
        tradeCount={summary?.trades}
      />

      {inspector?.error ? (
        <div className="mt-3 rounded-lg border border-rose-900/60 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {inspector.error}
        </div>
      ) : null}

      {/* ── 4. PERFORMANCE METRICS GRID ── */}
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3">
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <Zap className="h-3.5 w-3.5" /> Signals
          </div>
          <div className="mt-1 text-lg font-semibold text-slate-200">{summary?.signals ?? 0}</div>
          <div className="mt-0.5 text-xs text-slate-500">Entries {overallStats?.entries ?? 0}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3">
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <Activity className="h-3.5 w-3.5" /> Trades
          </div>
          <div className="mt-1 text-lg font-semibold text-slate-200">{summary?.trades ?? 0}</div>
          <div className="mt-0.5 text-xs text-slate-500">Closed {overallStats?.closed_trades ?? 0}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3">
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            {(overallStats?.net_pnl_inr ?? summary?.pnl ?? 0) >= 0
              ? <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
              : <TrendingDown className="h-3.5 w-3.5 text-rose-400" />}
            Net P&amp;L
          </div>
          <div className={cn('mt-1 text-lg font-semibold', (overallStats?.net_pnl_inr ?? summary?.pnl ?? 0) >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
            {overallStats ? formatINR(overallStats.net_pnl_inr) : formatINR(summary?.pnl ?? 0)}
          </div>
          <div className="mt-0.5 text-xs text-slate-500">Open {overallStats?.open_positions ?? 0} positions</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3">
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <Zap className="h-3.5 w-3.5" /> Latest Signal
          </div>
          {latestSignal ? (
            <>
              <div className={cn('mt-1 font-mono text-sm font-semibold', signalTone)}>
                {latestSignal.signal_type} {latestSignal.strength ? `· ${latestSignal.strength}` : ''}
              </div>
              <div className="mt-0.5 text-xs text-slate-500">
                {latestSignal.on_latest_bar
                  ? 'On current bar'
                  : `${latestSignal.bars_ago ?? '—'} bars ago`}
              </div>
            </>
          ) : (
            <div className="mt-1 text-xs text-slate-500">No actionable signal yet.</div>
          )}
        </div>
      </div>

      {/* ── 5. STATS TABLES (Market / Instrument) ── */}
      <div className="mt-4 grid gap-4 xl:grid-cols-2">

        {/* Settings */}
        <StrategySettingsForm
          key={`${name}:${(inspector?.settings_schema ?? []).map((f) => `${f.name}:${String(f.value)}`).join('|')}`}
          strategyName={name}
          fields={inspector?.settings_schema ?? []}
          disabled={!inspector}
          saving={savePending}
          onSave={onSaveSettings}
        />

        {/* Strategy Stats */}
        <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-200">Strategy Statistics</h3>
              <p className="mt-1 text-xs text-slate-500">Market-wide vs instrument performance.</p>
            </div>
            <div className="flex items-center gap-2">
              {(['market', 'instrument'] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setStatsTab(tab)}
                  className={cn(
                    'rounded-lg border px-3 py-1.5 text-xs transition capitalize',
                    statsTab === tab
                      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                      : 'border-slate-700 bg-slate-950/60 text-slate-400'
                  )}
                >
                  {tab === 'market' ? 'By Market' : 'Instrument'}
                </button>
              ))}
            </div>
          </div>

          {statsTab === 'market' ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                    <th className="pb-3 pr-3 font-medium">Market</th>
                    <th className="pb-3 pr-3 text-right font-medium">Entries</th>
                    <th className="pb-3 pr-3 text-right font-medium">Closed</th>
                    <th className="pb-3 pr-3 text-right font-medium">Win%</th>
                    <th className="pb-3 pr-3 text-right font-medium">Net P&amp;L</th>
                    <th className="pb-3 text-right font-medium">Used%</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(marketStats ?? {}).map(([market, row]) => (
                    <tr key={market} className="border-b border-slate-800/80 text-slate-300">
                      <td className="py-3 pr-3">
                        <div className="font-medium text-slate-100">{market}</div>
                        <div className="text-xs text-slate-500">{row.currency_symbol}{formatNumber(row.allocated_capital, 0)} alloc</div>
                      </td>
                      <td className="py-3 pr-3 text-right">{formatNumber(row.entries)}</td>
                      <td className="py-3 pr-3 text-right">{formatNumber(row.closed_trades)}</td>
                      <td className={cn(
                        'py-3 pr-3 text-right font-medium',
                        row.win_rate_pct >= 55 ? 'text-emerald-300' : row.win_rate_pct >= 45 ? 'text-amber-300' : 'text-rose-300',
                      )}>
                        {formatNumber(row.win_rate_pct, 1)}%
                      </td>
                      <td className={cn(
                        'py-3 pr-3 text-right font-medium',
                        row.net_pnl_inr > 0 ? 'text-emerald-300' : row.net_pnl_inr < 0 ? 'text-rose-300' : 'text-slate-400',
                      )}>
                        {row.currency === 'USD'
                          ? `${row.currency_symbol}${formatNumber(row.net_pnl, 2)}`
                          : formatINR(row.net_pnl_inr)}
                      </td>
                      <td className={cn(
                        'py-3 text-right font-medium',
                        row.capital_used_pct >= 70 ? 'text-rose-300' : row.capital_used_pct >= 35 ? 'text-amber-300' : 'text-sky-300',
                      )}>
                        {formatNumber(row.capital_used_pct, 2)}%
                      </td>
                    </tr>
                  ))}
                  {Object.keys(marketStats ?? {}).length === 0 ? (
                    <tr><td colSpan={6} className="py-6 text-center text-sm text-slate-500">No market statistics yet.</td></tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          ) : activeInstrumentStats ? (
            <div className="space-y-3">
              <label className="block">
                <span className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Instrument</span>
                <select
                  value={activeInstrumentKey}
                  onChange={(e) => setSelectedInstrumentStat(e.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-400"
                >
                  {instrumentStatSymbols.map((symbol) => (
                    <option key={symbol} value={symbol}>{symbol}</option>
                  ))}
                </select>
              </label>
              <div className="grid gap-2 sm:grid-cols-3">
                {[
                  ['Win Rate', `${formatNumber(activeInstrumentStats.win_rate_pct, 1)}%`],
                  ['Closed', formatNumber(activeInstrumentStats.closed_trades)],
                  ['Open', formatNumber(activeInstrumentStats.open_positions)],
                  ['Net P&L', activeInstrumentStats.currency === 'USD'
                    ? `${activeInstrumentStats.currency_symbol}${formatNumber(activeInstrumentStats.net_pnl, 2)}`
                    : formatINR(activeInstrumentStats.net_pnl_inr)],
                  ['P/L %', `${formatNumber(activeInstrumentStats.pnl_pct_on_allocated, 2)}%`],
                  ['Capital Used%', `${formatNumber(activeInstrumentStats.capital_used_pct, 2)}%`],
                ].map(([label, value]) => {
                  const tone = toneClasses(classifyMetricTone(label, value));
                  return (
                  <div key={label} className={cn('rounded-lg border px-3 py-2', tone.card)}>
                    <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                    <div className={cn('mt-1 font-mono text-xs font-medium', tone.value)}>{value}</div>
                  </div>
                )})}
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-slate-800 px-3 py-6 text-center text-sm text-slate-500">
              No statistics yet for this strategy.
            </div>
          )}
        </section>
      </div>

      {/* ── 6. LIVE INPUTS ── */}
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <DataGrid
          title="Live Indicator Snapshot"
          subtitle="Current values computed from the same bars the agent is inspecting."
          value={sanitizedSnapshot}
        />
        <DataGrid title="Runtime Parameters" value={inspector?.params ?? {}} />
      </div>

      {optionsAnalytics || selectedOptionCandidate ? (
        <div className="mt-4">
          <OptionsAnalyticsPanel
            optionsAnalytics={optionsAnalytics}
            selectedContract={selectedOptionCandidate}
            signalType={latestSignal?.signal_type}
          />
        </div>
      ) : null}

      {/* ── 7. LATEST SIGNAL METADATA ── */}
      {Object.keys(sanitizedLatestSignalMetadata).length > 0 ? (
        <div className="mt-4">
          <DataGrid
            title="Latest Signal Metadata"
            subtitle="Signal-only context after removing duplicated option-chain payloads."
            value={sanitizedLatestSignalMetadata}
          />
        </div>
      ) : null}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────
export default function StrategiesPage() {
  const { data: executor, isLoading: execLoading, error: execError } = useStrategies();
  const { data: signals, isLoading: sigLoading, error: sigError } = useSignals();
  const { data: status } = useAgentStatus();
  const { data: strategiesData } = useAvailableStrategies();
  const toggleStrategy = useSetAgentStrategy();
  const updateStrategyParams = useUpdateAgentStrategyParams();

  const [symbolOverride, setSymbolOverride] = useState<string | null>(null);
  const [timeframeOverride, setTimeframeOverride] = useState<string | null>(null);
  const [lookbackBars, setLookbackBars] = useState(240);
  const [selectedStrategiesOverride, setSelectedStrategiesOverride] = useState<string[] | null>(null);

  const symbolOptions = Array.from(new Set([
    ...(status?.symbols ?? []),
    ...(status?.us_symbols ?? []),
    ...(status?.crypto_symbols ?? []),
  ]));
  const timeframeOptions =
    status?.execution_timeframes && status.execution_timeframes.length > 0
      ? status.execution_timeframes
      : ['3', '5', '15', '60', 'D'];
  const strategyNames = Array.from(new Set([
    ...(strategiesData?.strategies ?? []),
    ...Object.keys(executor?.strategies ?? {}),
  ]));
  const symbol = symbolOverride ?? symbolOptions[0] ?? '';
  const timeframe = timeframeOverride ?? timeframeOptions[0] ?? '';
  const effectiveStrategies = selectedStrategiesOverride ?? status?.active_strategies ?? strategyNames;

  const inspectorQuery = useAgentInspector({
    symbol, timeframe, lookbackBars,
    strategies: effectiveStrategies,
    enabled: Boolean(symbol && timeframe),
  });

  const inspectorByName = Object.fromEntries(
    (inspectorQuery.data?.strategies ?? []).map((s) => [s.name, s]),
  );

  const toggleSelectedStrategy = (name: string) => {
    const base = selectedStrategiesOverride ?? status?.active_strategies ?? [];
    setSelectedStrategiesOverride(
      base.includes(name) ? base.filter((item) => item !== name) : [...base, name],
    );
  };

  return (
    <div className="space-y-6">

      {/* ── INSPECTOR CONTROLS ── */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-4xl">
            <div className="flex items-center gap-2 text-emerald-300">
              <Brain className="h-4 w-4" />
              <span className="text-[10px] font-semibold uppercase tracking-[0.24em]">Strategy Monitor</span>
            </div>
            <h1 className="mt-2 text-2xl font-semibold text-slate-100">Strategies + Live Inputs</h1>
            <p className="mt-2 text-sm text-slate-400">
              Inspect real-time indicator states, view per-strategy learning health, monitor signal filter logic, and tune runtime parameters.
            </p>
          </div>
          {executor ? (
            <div className="flex flex-wrap items-center gap-3">
              <span className={cn(
                'rounded-full px-3 py-1 text-xs font-medium',
                executor.state === 'running' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-yellow-500/20 text-yellow-400',
              )}>
                {executor.state.toUpperCase()}
              </span>
              {executor.paper_mode ? (
                <span className="rounded-full bg-yellow-500/20 px-3 py-1 text-xs font-medium text-yellow-400">PAPER</span>
              ) : null}
              <span className="text-sm text-slate-400">
                {executor.enabled_count}/{executor.strategies_count} active
              </span>
            </div>
          ) : null}
        </div>

        {/* Symbol / TF / Lookback / Strategy filter */}
        <div className="mt-5 grid gap-4 xl:grid-cols-[1.2fr_1fr_1fr_1.2fr]">
          <label className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Symbol</div>
            <select value={symbol} onChange={(e) => setSymbolOverride(e.target.value)}
              className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-400">
              {symbolOptions.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>

          <label className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Timeframe</div>
            <select value={timeframe} onChange={(e) => setTimeframeOverride(e.target.value)}
              className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-400">
              {timeframeOptions.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>

          <label className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Lookback Bars</div>
            <input type="number" min={50} max={1000} step={10} value={lookbackBars}
              onChange={(e) => setLookbackBars(Number(e.target.value) || 240)}
              className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-400"
            />
          </label>

          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Strategy Filter</div>
            <div className="mt-3 flex flex-wrap gap-2">
              {strategyNames.map((name) => {
                const selected = effectiveStrategies.includes(name);
                return (
                  <button key={name} type="button" onClick={() => toggleSelectedStrategy(name)}
                    className={cn(
                      'rounded-full border px-2.5 py-1 text-xs transition',
                      selected
                        ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                        : 'border-slate-700 bg-slate-900 text-slate-400',
                    )}>
                    {name.replace(/_/g, ' ')}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Inspect status bar */}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3">
          <div className="text-sm text-slate-400">
            {inspectorQuery.data ? (
              <>
                Inspecting <span className="font-medium text-slate-200">{inspectorQuery.data.symbol}</span> ·{' '}
                <span className="font-medium text-slate-200">{inspectorQuery.data.timeframe}</span> ·{' '}
                Last bar {formatDateTime(String(inspectorQuery.data.freshness?.last_bar_time ?? ''))}.
              </>
            ) : 'Select a symbol and timeframe to load strategy inputs.'}
          </div>
          <button type="button" onClick={() => inspectorQuery.refetch()}
            disabled={inspectorQuery.isFetching || !symbol || !timeframe}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 transition hover:border-emerald-400 disabled:cursor-not-allowed disabled:opacity-50">
            <RefreshCw className={cn('h-4 w-4', inspectorQuery.isFetching && 'animate-spin')} />
            Refresh Inputs
          </button>
        </div>
      </section>

      {/* ── ONLINE LEARNING PANEL ── */}
      <OnlineLearningPanel strategyStats={status?.strategy_stats} />

      {/* ── ERRORS ── */}
      {execError ? (
        <div className="rounded-xl border border-rose-900/60 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">
          Failed to load strategies. Backend may be offline.
        </div>
      ) : null}
      {inspectorQuery.isError ? (
        <div className="rounded-xl border border-rose-900/60 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">
          {inspectorQuery.error instanceof Error ? inspectorQuery.error.message : 'Could not load inspector data.'}
        </div>
      ) : null}

      {/* ── ACTIVE STRATEGY CARDS ── */}
      <div className="space-y-4">
        {execLoading && strategyNames.length === 0 ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900 px-5 py-10 text-center text-sm text-slate-500">
            Loading strategies…
          </div>
        ) : strategyNames.length === 0 ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900 px-5 py-10 text-center text-sm text-slate-500">
            No strategies configured.
          </div>
        ) : (
          strategyNames
            .filter((name) => effectiveStrategies.includes(name))
            .map((name) => (
              <StrategyCard
                key={name}
                name={name}
                summary={executor?.strategies?.[name]}
                overallStats={status?.strategy_stats?.[name]}
                marketStats={status?.strategy_market_stats?.[name]}
                instrumentStatsMap={status?.strategy_instrument_stats?.[name]}
                selectedSymbol={symbol}
                inspector={inspectorByName[name]}
                sharedOptionsAnalytics={inspectorQuery.data?.options_analytics}
                onToggle={(strategyName, enabled) =>
                  toggleStrategy.mutate({ strategy: strategyName, enabled })
                }
                togglePending={toggleStrategy.isPending && toggleStrategy.variables?.strategy === name}
                savePending={updateStrategyParams.isPending && updateStrategyParams.variables?.strategy === name}
                onSaveSettings={(strategyName, values) =>
                  updateStrategyParams.mutate({ strategy: strategyName, params: values })
                }
              />
            ))
        )}
      </div>

      {/* ── AVAILABLE STRATEGIES (not active) ── */}
      <AvailableStrategiesPanel
        allStrategies={strategiesData?.strategies ?? strategyNames}
        activeStrategies={status?.active_strategies ?? effectiveStrategies}
        onEnable={(name) => toggleStrategy.mutate({ strategy: name, enabled: true })}
        pending={toggleStrategy.isPending}
      />

      {/* ── RECENT SIGNALS ── */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-slate-400" />
          <h2 className="text-lg font-semibold text-slate-200">Recent Signals</h2>
        </div>

        {sigLoading ? (
          <div className="mt-4 text-sm text-slate-500">Loading signal feed…</div>
        ) : sigError ? (
          <div className="mt-4 text-sm text-rose-300">Failed to load recent signals.</div>
        ) : !signals || signals.length === 0 ? (
          <div className="mt-4 text-sm text-slate-500">No signals generated yet.</div>
        ) : (
          <div className="mt-4 space-y-2">
            {signals.slice(0, 20).map((sig, index) => (
              <div
                key={`${sig.timestamp}-${sig.symbol}-${index}`}
                className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950 px-4 py-3"
              >
                <div className="flex items-center gap-3">
                  <Zap className={cn('h-4 w-4', sig.signal_type === 'BUY' || sig.signal_type === 'LONG' ? 'text-emerald-400' : 'text-rose-400')} />
                  <div>
                    <p className="text-sm font-medium text-slate-200">
                      {sig.symbol}{' '}
                      <span className={cn(
                        'ml-1 rounded px-1.5 py-0.5 text-xs font-medium',
                        sig.signal_type === 'BUY' || sig.signal_type === 'LONG'
                          ? 'bg-emerald-500/20 text-emerald-400'
                          : 'bg-rose-500/20 text-rose-400',
                      )}>
                        {sig.signal_type}
                      </span>
                    </p>
                    <p className="text-xs text-slate-500">{sig.strategy_name} · {sig.strength}</p>
                  </div>
                </div>
                <div className="text-right">
                  {sig.price ? <p className="text-sm text-slate-300">{formatINR(sig.price)}</p> : null}
                  <p className="text-xs text-slate-500">{formatDateTime(sig.timestamp)}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

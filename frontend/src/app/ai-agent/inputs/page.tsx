'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import {
  ArrowLeft,
  Brain,
  CandlestickChart,
  Clock3,
  RefreshCw,
  SlidersHorizontal,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';

import { useAgentInspector, useAgentStatus, useAvailableStrategies } from '@/hooks/use-agent';
import { useWatchlistUniverse } from '@/hooks/use-watchlist';
import { buildInstrumentOptions } from '@/lib/instrument-universe';
import { cn } from '@/lib/utils';
import type { AgentInspectorStrategy } from '@/types/api';

function formatNumber(value: unknown, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  return value.toLocaleString('en-IN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function formatDateTime(value: unknown): string {
  if (typeof value !== 'string' || !value) {
    return '—';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return String(value);
  }
  return parsed.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  if (typeof value === 'number') {
    return formatNumber(value, 4);
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }
  if (Array.isArray(value)) {
    return value.length ? value.map((item) => formatValue(item)).join(', ') : '—';
  }
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value);
}

function flattenEntries(
  value: unknown,
  prefix = '',
): Array<{ key: string; value: unknown }> {
  if (value === null || value === undefined) {
    return prefix ? [{ key: prefix, value: null }] : [];
  }

  if (Array.isArray(value)) {
    return prefix ? [{ key: prefix, value }] : [];
  }

  if (typeof value !== 'object') {
    return prefix ? [{ key: prefix, value }] : [];
  }

  const entries = Object.entries(value as Record<string, unknown>);
  const flattened = entries.flatMap(([key, nested]) =>
    flattenEntries(nested, prefix ? `${prefix}.${key}` : key),
  );
  return flattened.length > 0 ? flattened : prefix ? [{ key: prefix, value }] : [];
}

function DataGrid({
  title,
  subtitle,
  value,
}: {
  title: string;
  subtitle?: string;
  value: unknown;
}) {
  const entries = flattenEntries(value);

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-slate-200">{title}</h2>
        {subtitle ? <p className="mt-1 text-xs text-slate-500">{subtitle}</p> : null}
      </div>
      {entries.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-800 px-3 py-6 text-center text-sm text-slate-500">
          No data available
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {entries.map((entry) => (
            <div key={entry.key} className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
              <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{entry.key}</div>
              <div className="mt-1 break-words font-mono text-xs text-slate-200">{formatValue(entry.value)}</div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function StrategyCard({ strategy }: { strategy: AgentInspectorStrategy }) {
  const latestSignal = strategy.latest_signal;
  const signalTone =
    latestSignal?.signal_type === 'BUY'
      ? 'text-emerald-300'
      : latestSignal?.signal_type === 'SELL'
        ? 'text-rose-300'
        : 'text-slate-400';

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-slate-200">{strategy.name}</h2>
            <span
              className={cn(
                'rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em]',
                strategy.enabled ? 'bg-emerald-500/10 text-emerald-300' : 'bg-slate-800 text-slate-400',
              )}
            >
              {strategy.enabled ? 'Enabled' : 'Disabled'}
            </span>
            <span
              className={cn(
                'rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em]',
                strategy.ready ? 'bg-sky-500/10 text-sky-300' : 'bg-amber-500/10 text-amber-300',
              )}
            >
              {strategy.ready ? 'Ready' : 'Waiting'}
            </span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Inspecting `{strategy.timeframe}`. Preferred: {strategy.preferred_timeframes.join(', ') || '—'}.
            Bars: {strategy.bars_available}/{strategy.min_bars_required}+.
          </p>
        </div>
        <div className="min-w-[220px] rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
          <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Latest Signal</div>
          {latestSignal ? (
            <>
              <div className={cn('mt-1 font-mono text-sm font-semibold', signalTone)}>
                {latestSignal.signal_type} {latestSignal.strength ? `· ${latestSignal.strength}` : ''}
              </div>
              <div className="mt-1 text-xs text-slate-400">
                Price {formatNumber(latestSignal.price)} · SL {formatNumber(latestSignal.stop_loss)} · TGT{' '}
                {formatNumber(latestSignal.target)}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {latestSignal.on_latest_bar
                  ? 'Generated on latest bar'
                  : `Last signal ${latestSignal.bars_ago ?? '—'} bars ago`}
              </div>
            </>
          ) : (
            <div className="mt-1 text-xs text-slate-500">No actionable signal on this dataset.</div>
          )}
        </div>
      </div>

      {strategy.error ? (
        <div className="mt-3 rounded-lg border border-rose-900/60 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {strategy.error}
        </div>
      ) : null}

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <DataGrid title="Parameters" value={strategy.params} />
        <DataGrid title="Indicator Snapshot" value={strategy.indicator_snapshot} />
      </div>

      {latestSignal?.metadata && Object.keys(latestSignal.metadata).length > 0 ? (
        <div className="mt-4">
          <DataGrid title="Latest Signal Metadata" value={latestSignal.metadata} />
        </div>
      ) : null}
    </section>
  );
}

export default function AgentInputsPage() {
  const { data: status } = useAgentStatus();
  const { data: strategiesData } = useAvailableStrategies();
  const { data: universe } = useWatchlistUniverse();

  const [symbolOverride, setSymbolOverride] = useState<string | null>(null);
  const [timeframeOverride, setTimeframeOverride] = useState<string | null>(null);
  const [lookbackBars, setLookbackBars] = useState(240);
  const [selectedStrategiesOverride, setSelectedStrategiesOverride] = useState<string[] | null>(null);

  const instrumentOptions = useMemo(() => buildInstrumentOptions(universe), [universe]);
  const symbolOptions = useMemo(
    () => instrumentOptions.map((item) => item.value),
    [instrumentOptions],
  );
  const timeframeOptions =
    status?.execution_timeframes && status.execution_timeframes.length > 0
      ? status.execution_timeframes
      : ['3', '5', '15', '60', 'D'];
  const availableStrategies = strategiesData?.strategies ?? [];
  const defaultSymbol =
    status?.active_symbols?.[0]
    ?? status?.symbols?.[0]
    ?? status?.us_symbols?.[0]
    ?? status?.crypto_symbols?.[0]
    ?? symbolOptions[0]
    ?? '';
  const symbol = symbolOverride ?? (symbolOptions.includes(defaultSymbol) ? defaultSymbol : symbolOptions[0] ?? '');
  const timeframe = timeframeOverride ?? status?.execution_timeframes?.[0] ?? timeframeOptions[0] ?? '';
  const effectiveStrategies = selectedStrategiesOverride ?? status?.active_strategies ?? [];

  const inspectorQuery = useAgentInspector({
    symbol,
    timeframe,
    lookbackBars,
    strategies: effectiveStrategies,
    enabled: Boolean(symbol && timeframe),
  });

  const toggleStrategy = (name: string) => {
    const base = selectedStrategiesOverride ?? status?.active_strategies ?? [];
    setSelectedStrategiesOverride(
      base.includes(name) ? base.filter((item) => item !== name) : [...base, name],
    );
  };

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <div className="flex items-center gap-2 text-emerald-300">
              <Brain className="h-4 w-4" />
              <span className="text-[10px] font-semibold uppercase tracking-[0.24em]">AI Inputs</span>
            </div>
            <h1 className="mt-2 text-xl font-semibold text-slate-100">Agent Input Inspector</h1>
            <p className="mt-2 text-sm text-slate-400">
              Dedicated view of the exact candle data, freshness checks, higher-timeframe bias,
              options context, strategy parameters, indicator snapshots, and latest signal state
              the AI agent is using across the full watchlist universe.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => inspectorQuery.refetch()}
              disabled={inspectorQuery.isFetching || !symbol || !timeframe}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 transition-colors hover:border-slate-600 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw className={cn('h-4 w-4', inspectorQuery.isFetching && 'animate-spin')} />
              Refresh
            </button>
            <Link
              href="/ai-agent"
              className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 transition-colors hover:border-slate-600 hover:text-slate-100"
            >
              <ArrowLeft className="h-4 w-4" />
              AI Agent
            </Link>
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-3 xl:grid-cols-4">
          <label className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Symbol</div>
            <select
              value={symbol}
              onChange={(event) => setSymbolOverride(event.target.value)}
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
            >
              {instrumentOptions.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Timeframe</div>
            <select
              value={timeframe}
              onChange={(event) => setTimeframeOverride(event.target.value)}
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
            >
              {timeframeOptions.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>

          <label className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Lookback Bars</div>
            <input
              type="number"
              min={60}
              max={500}
              step={10}
              value={lookbackBars}
              onChange={(event) => setLookbackBars(Number(event.target.value) || 240)}
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
            />
          </label>

          <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-slate-500">
              <SlidersHorizontal className="h-3.5 w-3.5" />
              Strategy Filter
            </div>
            <div className="mt-2 text-xs text-slate-500">
              Defaults to active strategies. Toggle any strategy below to inspect it explicitly.
            </div>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {availableStrategies.map((name) => {
            const active = effectiveStrategies.includes(name);
            return (
              <button
                key={name}
                onClick={() => toggleStrategy(name)}
                className={cn(
                  'rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                  active
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                    : 'border-slate-700 bg-slate-950/60 text-slate-400 hover:text-slate-200',
                )}
              >
                {name}
              </button>
            );
          })}
        </div>
      </section>

      {inspectorQuery.isError ? (
        <section className="rounded-xl border border-rose-900/60 bg-rose-950/30 p-4 text-sm text-rose-200">
          {inspectorQuery.error instanceof Error
            ? inspectorQuery.error.message
            : 'Could not load AI input inspector data.'}
        </section>
      ) : null}

      {inspectorQuery.data ? (
        <>
          {inspectorQuery.data.data_source.fallback_used ? (
            <section className="rounded-xl border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-200">
              No live {inspectorQuery.data.timeframe} data was available for `{inspectorQuery.data.symbol}`.
              Showing `{inspectorQuery.data.resolved_timeframe}` from {inspectorQuery.data.data_source.source.replaceAll('_', ' ')}
              {inspectorQuery.data.data_source.last_session_date
                ? ` (last session ${inspectorQuery.data.data_source.last_session_date}).`
                : '.'}
            </section>
          ) : null}

          {!inspectorQuery.data.timeframe_active ? (
            <section className="rounded-xl border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-200">
              `{inspectorQuery.data.resolved_timeframe}` is not in the agent&apos;s configured execution timeframe
              list. The inspector is still showing the data, but the live loop will only scan
              {` ${inspectorQuery.data.execution_timeframes.join(', ') || ' configured timeframes'}`}.
            </section>
          ) : null}

          <section className="grid gap-4 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
              <div className="flex items-center gap-2 text-slate-400">
                <Clock3 className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">Freshness</span>
              </div>
              <div className="mt-3 text-lg font-semibold text-slate-100">
                {String(inspectorQuery.data.freshness.fresh) === 'true' ? 'Fresh' : 'Stale'}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                Last bar {formatDateTime(inspectorQuery.data.freshness.last_bar_time)}
              </div>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
              <div className="flex items-center gap-2 text-slate-400">
                <CandlestickChart className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">Latest Bar</span>
              </div>
              <div className="mt-3 text-lg font-semibold text-slate-100">
                {formatNumber(inspectorQuery.data.latest_bar?.close)}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                O {formatNumber(inspectorQuery.data.latest_bar?.open)} · H {formatNumber(inspectorQuery.data.latest_bar?.high)} ·
                L {formatNumber(inspectorQuery.data.latest_bar?.low)}
              </div>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
              <div className="flex items-center gap-2 text-slate-400">
                {inspectorQuery.data.reference_bias.dominant_trend === 'bearish' ? (
                  <TrendingDown className="h-4 w-4" />
                ) : (
                  <TrendingUp className="h-4 w-4" />
                )}
                <span className="text-xs uppercase tracking-[0.18em]">Reference Bias</span>
              </div>
              <div className="mt-3 text-lg font-semibold text-slate-100">
                {inspectorQuery.data.reference_bias.dominant_trend}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                Bulls {inspectorQuery.data.reference_bias.bullish_votes} · Bears{' '}
                {inspectorQuery.data.reference_bias.bearish_votes}
              </div>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
              <div className="flex items-center gap-2 text-slate-400">
                <Brain className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">Data Window</span>
              </div>
              <div className="mt-3 text-lg font-semibold text-slate-100">
                {inspectorQuery.data.data_window.bars} bars
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {formatDateTime(inspectorQuery.data.data_window.start)} to{' '}
                {formatDateTime(inspectorQuery.data.data_window.end)}
              </div>
            </div>
          </section>

          {inspectorQuery.data.options_analytics ? (
            <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
              <DataGrid
                title="Options Trade Context"
                subtitle="Nearest-expiry chain, OI pressure, and the call/put candidates the agent can route into."
                value={inspectorQuery.data.options_analytics}
              />
              <DataGrid
                title="Inspector Source"
                subtitle="Shows whether this payload is live or continuity mode from the last tradable session."
                value={inspectorQuery.data.data_source}
              />
            </div>
          ) : (
            <DataGrid
              title="Inspector Source"
              subtitle="Shows whether this payload is live or continuity mode from the last tradable session."
              value={inspectorQuery.data.data_source}
            />
          )}

          <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
            <DataGrid
              title="Common Indicator Snapshot"
              subtitle="Baseline indicators on the selected timeframe before strategy-specific logic."
              value={inspectorQuery.data.common_indicators}
            />
            <DataGrid
              title="Reference Timeframe Bias"
              subtitle="Higher-timeframe trend checks used for confirmation."
              value={inspectorQuery.data.reference_bias.timeframes}
            />
          </div>

          <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
            <div className="mb-3">
              <h2 className="text-sm font-semibold text-slate-200">Recent Bars</h2>
              <p className="mt-1 text-xs text-slate-500">
                Latest 20 candles used for inspection on `{inspectorQuery.data.symbol}` / `{inspectorQuery.data.timeframe}`.
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-800 text-left text-xs">
                <thead>
                  <tr className="text-slate-500">
                    <th className="px-3 py-2 font-medium">Timestamp</th>
                    <th className="px-3 py-2 font-medium">Open</th>
                    <th className="px-3 py-2 font-medium">High</th>
                    <th className="px-3 py-2 font-medium">Low</th>
                    <th className="px-3 py-2 font-medium">Close</th>
                    <th className="px-3 py-2 font-medium">Volume</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-900/80">
                  {inspectorQuery.data.recent_bars.map((bar) => (
                    <tr key={bar.timestamp} className="text-slate-300">
                      <td className="px-3 py-2 font-mono text-[11px] text-slate-400">
                        {formatDateTime(bar.timestamp)}
                      </td>
                      <td className="px-3 py-2 font-mono">{formatNumber(bar.open)}</td>
                      <td className="px-3 py-2 font-mono">{formatNumber(bar.high)}</td>
                      <td className="px-3 py-2 font-mono">{formatNumber(bar.low)}</td>
                      <td className="px-3 py-2 font-mono">{formatNumber(bar.close)}</td>
                      <td className="px-3 py-2 font-mono">{formatNumber(bar.volume, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div className="space-y-4">
            {inspectorQuery.data.strategies.map((strategy) => (
              <StrategyCard key={`${strategy.name}-${strategy.timeframe}`} strategy={strategy} />
            ))}
          </div>
        </>
      ) : (
        <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-8 text-center text-sm text-slate-500">
          {inspectorQuery.isLoading ? 'Loading AI agent inputs…' : 'Select a symbol to inspect agent inputs.'}
        </section>
      )}
    </div>
  );
}

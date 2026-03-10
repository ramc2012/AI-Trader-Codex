'use client';

import { useState } from 'react';
import { Brain, RefreshCw, Save, Settings2, Target, Zap } from 'lucide-react';

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
import type { AgentInspectorStrategy, AgentStrategySettingField, PerformanceStats } from '@/types/api';

function formatNumber(value: unknown, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  return value.toLocaleString('en-IN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
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
        <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
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

function buildFieldValues(fields: AgentStrategySettingField[]): Record<string, string | boolean> {
  const nextValues: Record<string, string | boolean> = {};
  for (const field of fields) {
    if (field.type === 'boolean') {
      nextValues[field.name] = Boolean(field.value);
      continue;
    }
    nextValues[field.name] = field.value === null || field.value === undefined ? '' : String(field.value);
  }
  return nextValues;
}

function StrategySettingsForm({
  strategyName,
  fields,
  disabled,
  saving,
  onSave,
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
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [field.name]: event.target.checked,
                  }))
                }
                className="mt-3 h-4 w-4 rounded border-slate-700 bg-slate-900 text-emerald-400 focus:ring-emerald-400"
              />
            ) : (
              <input
                type="number"
                step={field.type === 'integer' ? '1' : 'any'}
                value={typeof values[field.name] === 'string' ? (values[field.name] as string) : ''}
                disabled={disabled || saving}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [field.name]: event.target.value,
                  }))
                }
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
        <span className="text-xs text-slate-500">
          Runtime-only for the current agent instance. Reapply after a full agent reset if needed.
        </span>
      </div>
    </section>
  );
}

function StrategyCard({
  name,
  summary,
  overallStats,
  marketStats,
  instrumentStatsMap,
  selectedSymbol,
  inspector,
  onToggle,
  togglePending,
  savePending,
  onSaveSettings,
}: {
  name: string;
  summary?: { enabled: boolean; signals: number; trades: number; pnl: number };
  overallStats?: PerformanceStats;
  marketStats?: Record<string, PerformanceStats>;
  instrumentStatsMap?: Record<string, PerformanceStats>;
  selectedSymbol: string;
  inspector?: AgentInspectorStrategy;
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
    if (selectedInstrumentStat && instrumentStatSymbols.includes(selectedInstrumentStat)) {
      return selectedInstrumentStat;
    }
    if (selectedSymbol && instrumentStatSymbols.includes(selectedSymbol)) {
      return selectedSymbol;
    }
    return instrumentStatSymbols[0] ?? '';
  })();
  const activeInstrumentStats = activeInstrumentKey ? instrumentStatsMap?.[activeInstrumentKey] : undefined;
  const signalTone =
    latestSignal?.signal_type === 'BUY'
      ? 'text-emerald-300'
      : latestSignal?.signal_type === 'SELL'
        ? 'text-rose-300'
        : 'text-slate-400';

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl">
          <div className="flex flex-wrap items-center gap-2">
            <Target className="h-4 w-4 text-slate-400" />
            <h2 className="text-lg font-semibold text-slate-100">{name}</h2>
            <span
              className={cn(
                'rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em]',
                enabled ? 'bg-emerald-500/10 text-emerald-300' : 'bg-slate-800 text-slate-400',
              )}
            >
              {enabled ? 'Enabled' : 'Disabled'}
            </span>
            {inspector ? (
              <span
                className={cn(
                  'rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em]',
                  inspector.ready ? 'bg-sky-500/10 text-sky-300' : 'bg-amber-500/10 text-amber-300',
                )}
              >
                {inspector.ready ? 'Ready' : 'Waiting'}
              </span>
            ) : null}
          </div>
          <p className="mt-2 text-sm text-slate-400">
            {inspector?.algorithm_summary || 'Strategy algorithm summary unavailable.'}
          </p>
          {inspector ? (
            <p className="mt-2 text-xs text-slate-500">
              Preferred TFs: {inspector.preferred_timeframes.join(', ') || '—'} · Inspecting {inspector.timeframe} ·
              Bars {inspector.bars_available}/{inspector.min_bars_required}+
            </p>
          ) : null}
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
            {togglePending ? 'Updating…' : enabled ? 'Disable Strategy' : 'Enable Strategy'}
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-4 py-3">
          <div className="text-xs text-slate-500">Signals</div>
          <div className="mt-1 text-lg font-semibold text-slate-200">{summary?.signals ?? 0}</div>
          <div className="mt-1 text-xs text-slate-500">Agent entries {overallStats?.entries ?? 0}</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-4 py-3">
          <div className="text-xs text-slate-500">Trades</div>
          <div className="mt-1 text-lg font-semibold text-slate-200">{summary?.trades ?? 0}</div>
          <div className="mt-1 text-xs text-slate-500">Closed {overallStats?.closed_trades ?? 0}</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-4 py-3">
          <div className="text-xs text-slate-500">Net P&L</div>
          <div
            className={cn(
              'mt-1 text-lg font-semibold',
              (overallStats?.net_pnl_inr ?? summary?.pnl ?? 0) >= 0 ? 'text-emerald-300' : 'text-rose-300',
            )}
          >
            {overallStats ? formatINR(overallStats.net_pnl_inr) : formatINR(summary?.pnl ?? 0)}
          </div>
          <div className="mt-1 text-xs text-slate-500">Open positions {overallStats?.open_positions ?? 0}</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-4 py-3">
          <div className="text-xs text-slate-500">Latest Signal</div>
          {latestSignal ? (
            <>
              <div className={cn('mt-1 font-mono text-sm font-semibold', signalTone)}>
                {latestSignal.signal_type} {latestSignal.strength ? `· ${latestSignal.strength}` : ''}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {latestSignal.on_latest_bar
                  ? 'Generated on latest bar'
                  : `Last fired ${latestSignal.bars_ago ?? '—'} bars ago`}
              </div>
            </>
          ) : (
            <div className="mt-1 text-xs text-slate-500">No actionable signal on current data.</div>
          )}
        </div>
      </div>

      {inspector?.error ? (
        <div className="mt-4 rounded-lg border border-rose-900/60 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {inspector.error}
        </div>
      ) : null}

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <StrategySettingsForm
          key={`${name}:${(inspector?.settings_schema ?? [])
            .map((field) => `${field.name}:${String(field.value)}`)
            .join('|')}`}
          strategyName={name}
          fields={inspector?.settings_schema ?? []}
          disabled={!inspector}
          saving={savePending}
          onSave={onSaveSettings}
        />
        <DataGrid
          title="Live Inputs"
          subtitle="Current indicator snapshot calculated from the same bars the agent is inspecting."
          value={inspector?.indicator_snapshot ?? {}}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <DataGrid title="Runtime Parameters" value={inspector?.params ?? {}} />
        <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-200">Strategy Statistics</h3>
              <p className="mt-1 text-xs text-slate-500">
                Separate market-wide performance from the selected instrument so symbol inspector data stays honest.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setStatsTab('market')}
                className={cn(
                  'rounded-lg border px-3 py-1.5 text-xs transition',
                  statsTab === 'market'
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                    : 'border-slate-700 bg-slate-950/60 text-slate-400'
                )}
              >
                By Market
              </button>
              <button
                type="button"
                onClick={() => setStatsTab('instrument')}
                className={cn(
                  'rounded-lg border px-3 py-1.5 text-xs transition',
                  statsTab === 'instrument'
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                    : 'border-slate-700 bg-slate-950/60 text-slate-400'
                )}
              >
                Instrument Focus
              </button>
            </div>
          </div>

          {statsTab === 'market' ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                    <th className="pb-3 pr-3 font-medium">Market</th>
                    <th className="pb-3 pr-3 text-right font-medium">Entries</th>
                    <th className="pb-3 pr-3 text-right font-medium">Closed</th>
                    <th className="pb-3 pr-3 text-right font-medium">Open</th>
                    <th className="pb-3 pr-3 text-right font-medium">Net</th>
                    <th className="pb-3 pr-3 text-right font-medium">P/L %</th>
                    <th className="pb-3 text-right font-medium">Used %</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(marketStats ?? {}).map(([market, row]) => (
                    <tr key={market} className="border-b border-slate-800/80 text-slate-300">
                      <td className="py-3 pr-3">
                        <div className="font-medium text-slate-100">{market}</div>
                        <div className="text-xs text-slate-500">
                          {row.currency_symbol}{formatNumber(row.allocated_capital, 0)} allocated
                        </div>
                      </td>
                      <td className="py-3 pr-3 text-right">{formatNumber(row.entries)}</td>
                      <td className="py-3 pr-3 text-right">{formatNumber(row.closed_trades)}</td>
                      <td className="py-3 pr-3 text-right">{formatNumber(row.open_positions)}</td>
                      <td className={cn('py-3 pr-3 text-right', row.net_pnl_inr >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
                        {row.currency === 'USD'
                          ? `${row.currency_symbol}${formatNumber(row.net_pnl, 2)}`
                          : formatINR(row.net_pnl_inr)}
                      </td>
                      <td className={cn('py-3 pr-3 text-right', row.pnl_pct_on_allocated >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
                        {formatNumber(row.pnl_pct_on_allocated, 2)}%
                      </td>
                      <td className="py-3 text-right">{formatNumber(row.capital_used_pct, 2)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : activeInstrumentStats ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-xs text-slate-500">Selected Instrument</div>
                  <div className="mt-1 text-sm font-medium text-slate-100">{activeInstrumentKey}</div>
                </div>
                <label className="min-w-[260px] max-w-full">
                  <span className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Instrument</span>
                  <select
                    value={activeInstrumentKey}
                    onChange={(event) => setSelectedInstrumentStat(event.target.value)}
                    className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-emerald-400"
                  >
                    {instrumentStatSymbols.map((symbol) => (
                      <option key={symbol} value={symbol}>
                        {symbol}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {[
                  ['Entries', formatNumber(activeInstrumentStats.entries)],
                  ['Closed Trades', formatNumber(activeInstrumentStats.closed_trades)],
                  ['Open Positions', formatNumber(activeInstrumentStats.open_positions)],
                  ['Net P&L', activeInstrumentStats.currency === 'USD' ? `${activeInstrumentStats.currency_symbol}${formatNumber(activeInstrumentStats.net_pnl, 2)}` : formatINR(activeInstrumentStats.net_pnl_inr)],
                  ['P/L % On Allocation', `${formatNumber(activeInstrumentStats.pnl_pct_on_allocated, 2)}%`],
                  ['Capital Used', activeInstrumentStats.currency === 'USD' ? `${activeInstrumentStats.currency_symbol}${formatNumber(activeInstrumentStats.capital_used, 2)}` : formatINR(activeInstrumentStats.capital_used_inr)],
                  ['Capital Used %', `${formatNumber(activeInstrumentStats.capital_used_pct, 2)}%`],
                  ['Win Rate', `${formatNumber(activeInstrumentStats.win_rate_pct, 2)}%`],
                  ['Signals', formatNumber(activeInstrumentStats.signals)],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                    <div className="mt-1 font-mono text-xs text-slate-200">{value}</div>
                  </div>
                ))}
              </div>

              <div className="overflow-x-auto">
                <table className="w-full min-w-[860px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-slate-800 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                      <th className="pb-3 pr-3 font-medium">Instrument</th>
                      <th className="pb-3 pr-3 text-right font-medium">Entries</th>
                      <th className="pb-3 pr-3 text-right font-medium">Closed</th>
                      <th className="pb-3 pr-3 text-right font-medium">Open</th>
                      <th className="pb-3 pr-3 text-right font-medium">Net</th>
                      <th className="pb-3 pr-3 text-right font-medium">P/L %</th>
                      <th className="pb-3 text-right font-medium">Used %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {instrumentStatSymbols
                      .slice()
                      .sort((left, right) =>
                        (instrumentStatsMap?.[right]?.net_pnl_inr ?? 0) - (instrumentStatsMap?.[left]?.net_pnl_inr ?? 0)
                      )
                      .map((symbol) => {
                        const row = instrumentStatsMap?.[symbol];
                        if (!row) {
                          return null;
                        }
                        return (
                          <tr
                            key={symbol}
                            className={cn(
                              'cursor-pointer border-b border-slate-800/80 text-slate-300',
                              symbol === activeInstrumentKey && 'bg-emerald-500/5'
                            )}
                            onClick={() => setSelectedInstrumentStat(symbol)}
                          >
                            <td className="py-3 pr-3">
                              <div className="font-medium text-slate-100">{symbol}</div>
                              <div className="text-xs text-slate-500">{row.currency_symbol}{formatNumber(row.allocated_capital, 0)} allocated</div>
                            </td>
                            <td className="py-3 pr-3 text-right">{formatNumber(row.entries)}</td>
                            <td className="py-3 pr-3 text-right">{formatNumber(row.closed_trades)}</td>
                            <td className="py-3 pr-3 text-right">{formatNumber(row.open_positions)}</td>
                            <td className={cn('py-3 pr-3 text-right', row.net_pnl_inr >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
                              {row.currency === 'USD'
                                ? `${row.currency_symbol}${formatNumber(row.net_pnl, 2)}`
                                : formatINR(row.net_pnl_inr)}
                            </td>
                            <td className={cn('py-3 pr-3 text-right', row.pnl_pct_on_allocated >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
                              {formatNumber(row.pnl_pct_on_allocated, 2)}%
                            </td>
                            <td className="py-3 text-right">{formatNumber(row.capital_used_pct, 2)}%</td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-slate-800 px-3 py-6 text-center text-sm text-slate-500">
              No strategy statistics exist yet for {selectedSymbol}. This strategy has not traded any tracked instrument.
            </div>
          )}
        </section>
      </div>

      {latestSignal?.metadata && Object.keys(latestSignal.metadata).length > 0 ? (
        <div className="mt-4">
          <DataGrid title="Latest Signal Metadata" value={latestSignal.metadata} />
        </div>
      ) : null}
    </section>
  );
}

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

  const symbolOptions = Array.from(
    new Set([
      ...(status?.symbols ?? []),
      ...(status?.us_symbols ?? []),
      ...(status?.crypto_symbols ?? []),
    ]),
  );
  const timeframeOptions =
    status?.execution_timeframes && status.execution_timeframes.length > 0
      ? status.execution_timeframes
      : ['3', '5', '15', '60', 'D'];
  const strategyNames = Array.from(
    new Set([
      ...(strategiesData?.strategies ?? []),
      ...Object.keys(executor?.strategies ?? {}),
    ]),
  );
  const symbol = symbolOverride ?? symbolOptions[0] ?? '';
  const timeframe = timeframeOverride ?? timeframeOptions[0] ?? '';
  const effectiveStrategies = selectedStrategiesOverride ?? status?.active_strategies ?? strategyNames;

  const inspectorQuery = useAgentInspector({
    symbol,
    timeframe,
    lookbackBars,
    strategies: effectiveStrategies,
    enabled: Boolean(symbol && timeframe),
  });

  const inspectorByName = Object.fromEntries(
    (inspectorQuery.data?.strategies ?? []).map((strategy) => [strategy.name, strategy]),
  );

  const toggleSelectedStrategy = (name: string) => {
    const base = selectedStrategiesOverride ?? status?.active_strategies ?? [];
    setSelectedStrategiesOverride(
      base.includes(name) ? base.filter((item) => item !== name) : [...base, name],
    );
  };

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-4xl">
            <div className="flex items-center gap-2 text-emerald-300">
              <Brain className="h-4 w-4" />
              <span className="text-[10px] font-semibold uppercase tracking-[0.24em]">Strategies + Inputs</span>
            </div>
            <h1 className="mt-2 text-2xl font-semibold text-slate-100">Strategy Monitor</h1>
            <p className="mt-2 text-sm text-slate-400">
              Inspect the same inputs the agent sees, review each strategy&apos;s algorithm context, and fine tune
              runtime settings without leaving the Strategies page.
            </p>
          </div>

          {executor ? (
            <div className="flex flex-wrap items-center gap-3">
              <span
                className={cn(
                  'rounded-full px-3 py-1 text-xs font-medium',
                  executor.state === 'running'
                    ? 'bg-emerald-500/20 text-emerald-400'
                    : 'bg-yellow-500/20 text-yellow-400',
                )}
              >
                {executor.state.toUpperCase()}
              </span>
              {executor.paper_mode ? (
                <span className="rounded-full bg-yellow-500/20 px-3 py-1 text-xs font-medium text-yellow-400">
                  PAPER MODE
                </span>
              ) : null}
              <span className="text-sm text-slate-400">
                {executor.enabled_count}/{executor.strategies_count} strategies enabled
              </span>
            </div>
          ) : null}
        </div>

        <div className="mt-5 grid gap-4 xl:grid-cols-[1.2fr_1fr_1fr_1.2fr]">
          <label className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Symbol</div>
            <select
              value={symbol}
              onChange={(event) => setSymbolOverride(event.target.value)}
              className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-emerald-400"
            >
              {symbolOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <label className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Timeframe</div>
            <select
              value={timeframe}
              onChange={(event) => setTimeframeOverride(event.target.value)}
              className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-emerald-400"
            >
              {timeframeOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <label className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Lookback Bars</div>
            <input
              type="number"
              min={50}
              max={1000}
              step={10}
              value={lookbackBars}
              onChange={(event) => setLookbackBars(Number(event.target.value) || 240)}
              className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-emerald-400"
            />
          </label>

          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Strategy Filter</div>
            <div className="mt-3 flex flex-wrap gap-2">
              {strategyNames.map((name) => {
                const selected = effectiveStrategies.includes(name);
                return (
                  <button
                    key={name}
                    type="button"
                    onClick={() => toggleSelectedStrategy(name)}
                    className={cn(
                      'rounded-full border px-3 py-1.5 text-sm transition',
                      selected
                        ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                        : 'border-slate-700 bg-slate-900 text-slate-400',
                    )}
                  >
                    {name}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3">
          <div className="text-sm text-slate-400">
            {inspectorQuery.data ? (
              <>
                Inspecting <span className="font-medium text-slate-200">{inspectorQuery.data.symbol}</span> on{' '}
                <span className="font-medium text-slate-200">{inspectorQuery.data.timeframe}</span>. Last bar{' '}
                {formatDateTime(String(inspectorQuery.data.freshness.last_bar_time ?? ''))}.
              </>
            ) : (
              'Select a symbol and timeframe to load strategy inputs.'
            )}
          </div>
          <button
            type="button"
            onClick={() => inspectorQuery.refetch()}
            disabled={inspectorQuery.isFetching || !symbol || !timeframe}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 transition hover:border-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className={cn('h-4 w-4', inspectorQuery.isFetching && 'animate-spin')} />
            Refresh Inputs
          </button>
        </div>
      </section>

      {execError ? (
        <div className="rounded-xl border border-rose-900/60 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">
          Failed to load strategies. Backend may be offline.
        </div>
      ) : null}

      {inspectorQuery.isError ? (
        <div className="rounded-xl border border-rose-900/60 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">
          {inspectorQuery.error instanceof Error
            ? inspectorQuery.error.message
            : 'Could not load strategy input inspector data.'}
        </div>
      ) : null}

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
                className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950 px-4 py-3"
              >
                <div className="flex items-center gap-3">
                  <Zap
                    className={cn(
                      'h-4 w-4',
                      sig.signal_type === 'BUY' || sig.signal_type === 'LONG'
                        ? 'text-emerald-400'
                        : 'text-rose-400',
                    )}
                  />
                  <div>
                    <p className="text-sm font-medium text-slate-200">
                      {sig.symbol}{' '}
                      <span
                        className={cn(
                          'ml-1 rounded px-1.5 py-0.5 text-xs font-medium',
                          sig.signal_type === 'BUY' || sig.signal_type === 'LONG'
                            ? 'bg-emerald-500/20 text-emerald-400'
                            : 'bg-rose-500/20 text-rose-400',
                        )}
                      >
                        {sig.signal_type}
                      </span>
                    </p>
                    <p className="text-xs text-slate-500">
                      {sig.strategy_name} | Strength: {sig.strength}
                    </p>
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

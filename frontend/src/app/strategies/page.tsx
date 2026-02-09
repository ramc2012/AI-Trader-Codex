'use client';

import { Target, Zap } from 'lucide-react';
import { useStrategies } from '@/hooks/use-strategies';
import { useSignals } from '@/hooks/use-signals';
import { formatINR, formatDateTime } from '@/lib/formatters';
import { cn } from '@/lib/utils';

function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn('animate-pulse rounded bg-slate-800', className)} />
  );
}

export default function StrategiesPage() {
  const { data: executor, isLoading: execLoading, error: execError } = useStrategies();
  const { data: signals, isLoading: sigLoading, error: sigError } = useSignals();

  const strategyEntries = executor?.strategies
    ? Object.entries(executor.strategies)
    : [];

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Strategy Monitor</h2>
        <p className="mt-1 text-sm text-slate-400">
          Active strategies and recent signals
        </p>
      </div>

      {/* Executor Status */}
      {executor && (
        <div className="flex items-center gap-4">
          <span
            className={cn(
              'rounded-full px-3 py-1 text-xs font-medium',
              executor.state === 'running'
                ? 'bg-emerald-500/20 text-emerald-400'
                : 'bg-yellow-500/20 text-yellow-400'
            )}
          >
            {executor.state.toUpperCase()}
          </span>
          {executor.paper_mode && (
            <span className="rounded-full bg-yellow-500/20 px-3 py-1 text-xs font-medium text-yellow-400">
              PAPER MODE
            </span>
          )}
          <span className="text-sm text-slate-400">
            {executor.enabled_count}/{executor.strategies_count} strategies enabled
          </span>
        </div>
      )}

      {/* Strategy Cards */}
      <div>
        <h3 className="mb-4 text-lg font-semibold text-slate-200">
          Strategies
        </h3>
        {execLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-40 w-full rounded-xl" />
            ))}
          </div>
        ) : execError ? (
          <p className="text-sm text-red-400">
            Failed to load strategies. Backend may be offline.
          </p>
        ) : strategyEntries.length === 0 ? (
          <p className="text-sm text-slate-500">No strategies configured</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {strategyEntries.map(([name, info]) => (
              <div
                key={name}
                className="rounded-xl border border-slate-800 bg-slate-900 p-5"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Target className="h-4 w-4 text-slate-400" />
                    <h4 className="font-medium text-slate-100">{name}</h4>
                  </div>
                  <span
                    className={cn(
                      'rounded-full px-2 py-0.5 text-xs font-medium',
                      info.enabled
                        ? 'bg-emerald-500/20 text-emerald-400'
                        : 'bg-slate-700 text-slate-400'
                    )}
                  >
                    {info.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                </div>

                <div className="mt-4 grid grid-cols-3 gap-3">
                  <div>
                    <p className="text-xs text-slate-500">Signals</p>
                    <p className="text-lg font-semibold text-slate-200">
                      {info.signals}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">Trades</p>
                    <p className="text-lg font-semibold text-slate-200">
                      {info.trades}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">P&L</p>
                    <p
                      className={cn(
                        'text-lg font-semibold',
                        info.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
                      )}
                    >
                      {formatINR(info.pnl)}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Signals Feed */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <h3 className="mb-4 text-lg font-semibold text-slate-200">
          Recent Signals
        </h3>

        {sigLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full rounded-lg" />
            ))}
          </div>
        ) : sigError ? (
          <p className="text-sm text-red-400">
            Failed to load signals. Backend may be offline.
          </p>
        ) : !signals || signals.length === 0 ? (
          <p className="text-sm text-slate-500">No signals generated yet</p>
        ) : (
          <div className="space-y-2">
            {signals.slice(0, 20).map((sig, i) => (
              <div
                key={`${sig.timestamp}-${sig.symbol}-${i}`}
                className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950 px-4 py-3"
              >
                <div className="flex items-center gap-3">
                  <Zap
                    className={cn(
                      'h-4 w-4',
                      sig.signal_type === 'BUY' || sig.signal_type === 'LONG'
                        ? 'text-emerald-400'
                        : 'text-red-400'
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
                            : 'bg-red-500/20 text-red-400'
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
                  {sig.price && (
                    <p className="text-sm text-slate-300">
                      {formatINR(sig.price)}
                    </p>
                  )}
                  <p className="text-xs text-slate-500">
                    {formatDateTime(sig.timestamp)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

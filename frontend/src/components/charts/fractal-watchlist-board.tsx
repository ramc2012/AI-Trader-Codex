'use client';

import { useMemo } from 'react';
import { Activity, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react';

import { useFractalWatchlist } from '@/hooks/use-fractal-profile';
import { formatINR } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import type {
  FractalProfileContextResponse,
  FractalTradeCandidate,
  HourlyFractalProfile,
} from '@/types/api';

const DEFAULT_SYMBOLS = [
  'NSE:NIFTY50-INDEX',
  'NSE:NIFTYBANK-INDEX',
  'NSE:FINNIFTY-INDEX',
  'NSE:NIFTYMIDCAP50-INDEX',
  'BSE:SENSEX-INDEX',
];

const LABELS: Record<string, string> = {
  'NSE:NIFTY50-INDEX': 'Nifty 50',
  'NSE:NIFTYBANK-INDEX': 'Bank Nifty',
  'NSE:FINNIFTY-INDEX': 'Fin Nifty',
  'NSE:NIFTYMIDCAP50-INDEX': 'Midcap Nifty',
  'BSE:SENSEX-INDEX': 'Sensex',
};

function todayInIST(): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}

function shapeTone(shape: string): string {
  if (shape === 'elongated_up') return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/20';
  if (shape === 'elongated_down') return 'bg-rose-500/15 text-rose-300 border-rose-500/20';
  if (shape === 'P') return 'bg-sky-500/15 text-sky-300 border-sky-500/20';
  if (shape === 'b') return 'bg-amber-500/15 text-amber-300 border-amber-500/20';
  return 'bg-slate-800 text-slate-300 border-slate-700';
}

function directionTone(direction: string): string {
  return direction === 'bullish' ? 'text-emerald-300' : 'text-rose-300';
}

function CurrentHourProfile({ profile }: { profile: HourlyFractalProfile }) {
  const maxTpo = Math.max(...profile.levels.map((level) => level.tpo_count), 1);
  const step = Math.max(Math.ceil(profile.levels.length / 12), 1);
  const sampled = profile.levels
    .slice()
    .reverse()
    .filter((_, index, rows) => index === 0 || index === rows.length - 1 || index % step === 0);

  return (
    <div className="space-y-1 font-mono text-[10px]">
      {sampled.map((level) => {
        const width = `${Math.max((level.tpo_count / maxTpo) * 100, 10)}%`;
        const isPoc = Math.abs(level.price - profile.poc) < profile.tick_size * 0.5;
        const isVa = level.price >= profile.val && level.price <= profile.vah;
        return (
          <div key={`${profile.start}-${level.price}`} className="flex items-center gap-2">
            <span className={cn('w-14 text-right', isPoc ? 'text-amber-300' : 'text-slate-500')}>
              {level.price.toFixed(0)}
            </span>
            <div className="flex-1">
              <div
                className={cn(
                  'rounded-sm px-1 py-0.5',
                  isPoc
                    ? 'bg-amber-500/20 text-amber-200'
                    : isVa
                      ? 'bg-sky-500/10 text-sky-200'
                      : 'bg-slate-900 text-slate-300',
                  level.single_print ? 'ring-1 ring-emerald-500/30' : '',
                )}
                style={{ width }}
              >
                {level.tpo_count}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function HourlySequence({ profiles }: { profiles: HourlyFractalProfile[] }) {
  const recent = profiles.slice(-6);

  return (
    <div className="flex gap-1">
      {recent.map((profile) => (
        <div
          key={profile.start}
          className={cn(
            'flex-1 rounded border px-1 py-1 text-center text-[10px] font-semibold',
            shapeTone(profile.shape),
          )}
          title={`${profile.shape} · ${profile.va_migration_vs_prev}`}
        >
          {new Date(profile.start).toLocaleTimeString('en-IN', {
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
            timeZone: 'Asia/Kolkata',
          })}
        </div>
      ))}
    </div>
  );
}

function FractalWatchCard({
  context,
  candidate,
  onSelectSymbol,
}: {
  context: FractalProfileContextResponse;
  candidate: FractalTradeCandidate | null;
  onSelectSymbol?: (symbol: string) => void;
}) {
  const currentHour = context.hourly_profiles[context.hourly_profiles.length - 1] ?? null;
  const DirectionIcon = candidate?.direction === 'bearish' ? TrendingDown : TrendingUp;
  const clickable = typeof onSelectSymbol === 'function';

  return (
    <button
      type="button"
      onClick={() => onSelectSymbol?.(context.symbol)}
      disabled={!clickable}
      className={cn(
        'rounded-xl border border-slate-800 bg-slate-950/55 p-3 text-left',
        clickable ? 'transition-colors hover:border-slate-700 hover:bg-slate-950/75' : '',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-slate-100">
            {LABELS[context.symbol] ?? context.symbol}
          </div>
          <div className="text-[11px] text-slate-500">{context.symbol}</div>
        </div>
        {candidate ? (
          <div className="flex items-center gap-1">
            <DirectionIcon className={cn('h-3.5 w-3.5', directionTone(candidate.direction))} />
            <span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] font-semibold text-slate-200">
              {candidate.conviction}
            </span>
          </div>
        ) : null}
      </div>

      {!currentHour || !context.daily_profile ? (
        <div className="mt-3 rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-6 text-center text-xs text-slate-500">
          Fractal profile unavailable
        </div>
      ) : (
        <>
          <div className="mt-3">
            <HourlySequence profiles={context.hourly_profiles} />
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-400">
            <div>
              Daily <span className="text-slate-200">{context.daily_profile.shape}</span>
            </div>
            <div>
              Hour <span className="text-slate-200">{currentHour.shape}</span>
            </div>
            <div>
              POC <span className="font-mono text-slate-200">{formatINR(currentHour.poc)}</span>
            </div>
            <div>
              VA <span className="font-mono text-slate-200">{formatINR(currentHour.val)} - {formatINR(currentHour.vah)}</span>
            </div>
          </div>

          <div className="mt-3 rounded-lg border border-slate-800 bg-slate-900/40 p-2">
            <CurrentHourProfile profile={currentHour} />
          </div>

          <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 px-2 py-1.5">
              <div className="text-slate-500">Migration</div>
              <div className="font-semibold text-slate-200">{currentHour.consecutive_direction_hours}h</div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 px-2 py-1.5">
              <div className="text-slate-500">IB</div>
              <div className="font-mono text-slate-200">{formatINR(currentHour.ib_low)}</div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 px-2 py-1.5">
              <div className="text-slate-500">SP</div>
              <div className="font-semibold text-slate-200">{currentHour.single_prints.length}</div>
            </div>
          </div>
        </>
      )}

      {candidate ? (
        <div className="mt-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-[11px]">
          <div className={cn('font-semibold', directionTone(candidate.direction))}>
            {candidate.direction.toUpperCase()} setup · {candidate.hourly_shape}
          </div>
          <div className="mt-1 flex items-center justify-between gap-2 text-slate-300">
            <span>Entry {formatINR(candidate.entry_trigger)}</span>
            <span>Stop {formatINR(candidate.stop_reference)}</span>
          </div>
        </div>
      ) : (
        <div className="mt-3 text-[11px] text-slate-500">
          No candidate passed full structure + order-flow filter this cycle.
        </div>
      )}
    </button>
  );
}

export default function FractalWatchlistBoard({
  symbols = DEFAULT_SYMBOLS,
  onSelectSymbol,
}: {
  symbols?: string[];
  onSelectSymbol?: (symbol: string) => void;
}) {
  const sessionDate = todayInIST();
  const query = useFractalWatchlist(symbols, sessionDate, symbols.length, 2);

  const candidateMap = useMemo(() => {
    const map = new Map<string, FractalTradeCandidate>();
    for (const candidate of query.data?.scan?.candidates ?? []) {
      map.set(candidate.symbol, candidate);
    }
    return map;
  }, [query.data?.scan?.candidates]);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2.5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Fractal Watchlist
          </p>
          <p className="text-[11px] text-slate-500">
            Hourly profiles built from 3-minute TPO periods across the full watchlist
          </p>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-slate-500">
          {query.isFetching ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : null}
          <span>{query.data?.scan?.stages?.final ?? 0} live candidates</span>
        </div>
      </div>

      {query.isLoading ? (
        <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2 xl:grid-cols-5">
          {symbols.map((symbol) => (
            <div key={symbol} className="h-72 animate-pulse rounded-xl border border-slate-800 bg-slate-950/40" />
          ))}
        </div>
      ) : (
        <div className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
            <span className="rounded-full bg-slate-950 px-2.5 py-1">
              Built {query.data?.scan?.stages?.profile_built ?? 0}/{symbols.length}
            </span>
            <span className="rounded-full bg-slate-950 px-2.5 py-1">
              Shape {query.data?.scan?.stages?.shape_pass ?? 0}
            </span>
            <span className="rounded-full bg-slate-950 px-2.5 py-1">
              Order flow {query.data?.scan?.stages?.orderflow_pass ?? 0}
            </span>
            {query.data?.generated_at ? (
              <span className="ml-auto flex items-center gap-1">
                <Activity className="h-3.5 w-3.5" />
                {new Date(query.data.generated_at).toLocaleTimeString('en-IN', { hour12: false })}
              </span>
            ) : null}
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-5">
            {(query.data?.contexts ?? []).map((context) => (
              <FractalWatchCard
                key={context.symbol}
                context={context}
                candidate={candidateMap.get(context.symbol) ?? context.candidate}
                onSelectSymbol={onSelectSymbol}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

'use client';

import { useState } from 'react';
import {
  Activity,
  BarChart3,
  RefreshCw,
  Shield,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';

import { useFractalProfileContext, useFractalScanner } from '@/hooks/use-fractal-profile';
import { formatINR, formatNumber } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import type {
  FractalAssessment,
  FractalProfileWindow,
  FractalTradeCandidate,
  HourlyFractalProfile,
} from '@/types/api';

const SYMBOLS = [
  { value: 'NSE:NIFTY50-INDEX', label: 'Nifty 50' },
  { value: 'NSE:NIFTYBANK-INDEX', label: 'Bank Nifty' },
  { value: 'NSE:FINNIFTY-INDEX', label: 'Fin Nifty' },
  { value: 'NSE:RELIANCE-EQ', label: 'Reliance' },
  { value: 'NSE:HDFCBANK-EQ', label: 'HDFC Bank' },
  { value: 'NSE:ICICIBANK-EQ', label: 'ICICI Bank' },
  { value: 'NSE:SBIN-EQ', label: 'SBI' },
  { value: 'NSE:TCS-EQ', label: 'TCS' },
  { value: 'US:SPY', label: 'SPY' },
  { value: 'US:QQQ', label: 'QQQ' },
  { value: 'US:AAPL', label: 'Apple' },
  { value: 'CRYPTO:BTCUSDT', label: 'BTCUSDT' },
  { value: 'CRYPTO:ETHUSDT', label: 'ETHUSDT' },
  { value: 'CRYPTO:SOLUSDT', label: 'SOLUSDT' },
];

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

function migrationTone(migration: string): string {
  if (migration === 'up' || migration === 'gap_up') return 'text-emerald-300';
  if (migration === 'down' || migration === 'gap_down') return 'text-rose-300';
  return 'text-slate-400';
}

function directionTone(direction: string): string {
  return direction === 'bullish' ? 'text-emerald-300' : 'text-rose-300';
}

function MetricCard({
  label,
  value,
  tone = 'text-slate-100',
  subtext,
}: {
  label: string;
  value: string;
  tone?: string;
  subtext?: string;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={cn('mt-1 text-lg font-semibold', tone)}>{value}</div>
      {subtext ? <div className="mt-1 text-[11px] text-slate-500">{subtext}</div> : null}
    </div>
  );
}

function ProfileMini({
  profile,
  title,
  subtitle,
}: {
  profile: FractalProfileWindow;
  title: string;
  subtitle: string;
}) {
  const maxTpo = Math.max(...profile.levels.map((level) => level.tpo_count), 1);
  const rows = profile.levels.slice().reverse();

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/50">
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
        <div>
          <div className="text-xs font-semibold text-slate-200">{title}</div>
          <div className="text-[11px] text-slate-500">{subtitle}</div>
        </div>
        <div className={cn('rounded border px-2 py-0.5 text-[10px] font-semibold', shapeTone(profile.shape))}>
          {profile.shape}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 border-b border-slate-800 px-3 py-2 text-[11px] text-slate-400">
        <div>POC {formatINR(profile.poc)}</div>
        <div>VA {formatINR(profile.val)} - {formatINR(profile.vah)}</div>
        <div>IB {formatINR(profile.ib_low)} - {formatINR(profile.ib_high)}</div>
      </div>
      <div className="max-h-44 overflow-y-auto px-2 py-2 font-mono text-[10px]">
        {rows.map((level) => {
          const width = `${Math.max((level.tpo_count / maxTpo) * 100, 6)}%`;
          const isPoc = Math.abs(level.price - profile.poc) < profile.tick_size * 0.5;
          const isVa = level.price >= profile.val && level.price <= profile.vah;
          return (
            <div key={`${title}-${level.price}`} className="flex items-center gap-2 py-0.5">
              <span className={cn('w-16 text-right', isPoc ? 'text-amber-300' : 'text-slate-500')}>
                {level.price.toFixed(2)}
              </span>
              <div className="flex-1">
                <div
                  className={cn(
                    'rounded-sm px-1 py-0.5',
                    isPoc ? 'bg-amber-500/20 text-amber-200' : isVa ? 'bg-sky-500/10 text-sky-200' : 'bg-slate-900 text-slate-300',
                    level.single_print ? 'ring-1 ring-emerald-500/30' : '',
                  )}
                  style={{ width }}
                >
                  {level.periods.join(' ')}
                </div>
              </div>
              <span className="w-6 text-right text-slate-600">{level.tpo_count}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function HourlyProfileCard({ profile }: { profile: HourlyFractalProfile }) {
  const label = new Date(profile.start).toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Asia/Kolkata',
  });
  const maxTpo = Math.max(...profile.levels.map((level) => level.tpo_count), 1);
  const rows = profile.levels.slice().reverse();

  return (
    <div className="min-w-[220px] rounded-xl border border-slate-800 bg-slate-950/55">
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
        <div>
          <div className="text-xs font-semibold text-slate-200">{label} hour</div>
          <div className={cn('text-[11px]', migrationTone(profile.va_migration_vs_prev))}>
            {profile.va_migration_vs_prev} · {profile.consecutive_direction_hours}h streak
          </div>
        </div>
        <div className={cn('rounded border px-2 py-0.5 text-[10px] font-semibold', shapeTone(profile.shape))}>
          {profile.shape}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 border-b border-slate-800 px-3 py-2 text-[11px] text-slate-400">
        <div>POC {formatINR(profile.poc)}</div>
        <div>VA {formatINR(profile.val)} - {formatINR(profile.vah)}</div>
        <div>IB {formatINR(profile.ib_low)} - {formatINR(profile.ib_high)}</div>
        <div>Overlap {(profile.va_overlap_ratio * 100).toFixed(0)}%</div>
      </div>
      <div className="max-h-44 overflow-y-auto px-2 py-2 font-mono text-[10px]">
        {rows.map((level) => {
          const width = `${Math.max((level.tpo_count / maxTpo) * 100, 6)}%`;
          const isPoc = Math.abs(level.price - profile.poc) < profile.tick_size * 0.5;
          const isVa = level.price >= profile.val && level.price <= profile.vah;
          return (
            <div key={`${profile.start}-${level.price}`} className="flex items-center gap-2 py-0.5">
              <span className={cn('w-14 text-right', isPoc ? 'text-amber-300' : 'text-slate-500')}>
                {level.price.toFixed(2)}
              </span>
              <div className="flex-1">
                <div
                  className={cn(
                    'rounded-sm px-1 py-0.5',
                    isPoc ? 'bg-amber-500/20 text-amber-200' : isVa ? 'bg-sky-500/10 text-sky-200' : 'bg-slate-900 text-slate-300',
                    level.single_print ? 'ring-1 ring-emerald-500/30' : '',
                  )}
                  style={{ width }}
                >
                  {level.periods.join(' ')}
                </div>
              </div>
              <span className="w-5 text-right text-slate-600">{level.tpo_count}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AssessmentPanel({ assessment }: { assessment: FractalAssessment | null | undefined }) {
  if (!assessment) return null;
  const tone =
    assessment.bias === 'bullish' ? 'text-emerald-300' : assessment.bias === 'bearish' ? 'text-rose-300' : 'text-slate-300';

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Profile Assessment</span>
        <span className={cn('rounded border px-2 py-0.5 text-xs font-semibold capitalize', tone, 'border-current/20 bg-current/5')}>
          {assessment.bias}
        </span>
        <span className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-xs text-slate-300">
          {assessment.setup_type.replaceAll('_', ' ')}
        </span>
        <span className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-xs text-slate-300">
          acceptance {assessment.value_acceptance}
        </span>
        {assessment.exhaustion_warning ? (
          <span className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-xs font-semibold text-amber-300">
            exhaustion watch
          </span>
        ) : null}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-4">
        <MetricCard label="Active Hour" value={assessment.current_hour_shape} tone="text-slate-100" />
        <MetricCard label="Migration" value={assessment.current_migration} tone="text-slate-100" />
        <MetricCard label="Streak" value={`${assessment.consecutive_direction_hours}h`} tone="text-slate-100" />
        <MetricCard label="Daily Shape" value={assessment.daily_shape} tone="text-slate-100" />
      </div>
      {assessment.no_trade_reasons.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {assessment.no_trade_reasons.map((reason) => (
            <span key={reason} className="rounded-full border border-amber-500/20 bg-amber-500/10 px-3 py-1 text-xs text-amber-200">
              {reason}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function CandidateBanner({ candidate }: { candidate: FractalTradeCandidate }) {
  const DirectionIcon = candidate.direction === 'bullish' ? TrendingUp : TrendingDown;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <DirectionIcon className={cn('h-5 w-5', directionTone(candidate.direction))} />
            <div className={cn('text-lg font-semibold', directionTone(candidate.direction))}>
              {candidate.symbol} · {candidate.direction}
            </div>
            <span className="rounded bg-slate-800 px-2 py-0.5 text-xs font-semibold text-slate-300">
              {candidate.conviction}/100
            </span>
          </div>
          <div className="mt-1 text-sm text-slate-400">{candidate.rationale}</div>
        </div>
        <div className="grid min-w-[280px] grid-cols-3 gap-2 text-sm">
          <MetricCard label="Entry" value={formatINR(candidate.entry_trigger)} tone="text-slate-100" />
          <MetricCard label="Stop" value={formatINR(candidate.stop_reference)} tone="text-rose-300" />
          <MetricCard
            label="Target"
            value={candidate.target_reference ? formatINR(candidate.target_reference) : '—'}
            tone="text-emerald-300"
          />
        </div>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-3">
        <MetricCard
          label="Flow"
          value={candidate.aggressive_flow_detected ? 'Confirmed' : 'Mixed'}
          tone={candidate.aggressive_flow_detected ? 'text-emerald-300' : 'text-amber-300'}
          subtext={`IV ${candidate.iv_behavior}`}
        />
        <MetricCard
          label="Contract"
          value={candidate.suggested_contract ?? 'Unavailable'}
          tone="text-slate-100"
          subtext={candidate.suggested_delta ? `Delta ${candidate.suggested_delta.toFixed(2)}` : 'No option snapshot'}
        />
        <MetricCard
          label="Structure"
          value={`${candidate.setup_type.replaceAll('_', ' ')} · ${candidate.consecutive_migration_hours}h`}
          tone="text-sky-300"
          subtext={`${candidate.hourly_shape} · acceptance ${candidate.value_acceptance}`}
        />
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-3">
        <MetricCard
          label="Sizing"
          value={`${candidate.position_size_multiplier.toFixed(2)}x`}
          tone="text-slate-100"
          subtext={candidate.exhaustion_warning ? 'trimmed for exhaustion risk' : 'adaptive position size'}
        />
        <MetricCard
          label="Risk/Reward"
          value={`${candidate.adaptive_risk_reward.toFixed(2)}R`}
          tone="text-emerald-300"
          subtext={candidate.approaching_single_prints ? 'single-print target active' : 'fallback structural target'}
        />
        <MetricCard
          label="Context"
          value={candidate.daily_alignment ? 'Daily aligned' : 'Daily mixed'}
          tone={candidate.daily_alignment ? 'text-emerald-300' : 'text-amber-300'}
          subtext={candidate.oi_direction_confirmed ? 'options flow supportive' : 'spot/orderflow only'}
        />
      </div>
    </div>
  );
}

export default function HourlyFractalProfileWorkbench() {
  const [symbol, setSymbol] = useState(SYMBOLS[0].value);
  const [sessionDate, setSessionDate] = useState(todayInIST);
  const contextQuery = useFractalProfileContext(symbol, sessionDate);
  const scanQuery = useFractalScanner(undefined, sessionDate, 8, 2);

  const context = contextQuery.data;
  const scan = scanQuery.data;
  const currentHour = context?.hourly_profiles?.[context.hourly_profiles.length - 1] ?? null;

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/80 px-3 py-2">
            <BarChart3 className="h-4 w-4 text-slate-400" />
            <select
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
              className="bg-transparent text-sm text-slate-100 outline-none"
            >
              {SYMBOLS.map((item) => (
                <option key={item.value} value={item.value} className="bg-slate-950">
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <input
            type="date"
            value={sessionDate}
            onChange={(event) => setSessionDate(event.target.value)}
            className="rounded-lg border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-slate-100 outline-none"
          />

          <div className="ml-auto flex items-center gap-2 text-xs text-slate-500">
            {(contextQuery.isFetching || scanQuery.isFetching) ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : null}
            <span>{context?.source_timeframe ? `source ${context.source_timeframe}m/DB` : 'on-demand profile scan'}</span>
          </div>
        </div>

        {context?.error ? (
          <div className="mt-4 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-sm text-amber-300">
            {context.error}
          </div>
        ) : null}

        {context && !context.error && context.daily_profile ? (
          <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-4">
            <MetricCard
              label="Daily Profile"
              value={context.daily_profile.shape}
              tone="text-slate-100"
              subtext={`POC ${formatINR(context.daily_profile.poc)}`}
            />
            <MetricCard
              label="Current Hour"
              value={currentHour ? currentHour.shape : '—'}
              tone={currentHour ? migrationTone(currentHour.va_migration_vs_prev) : 'text-slate-100'}
              subtext={currentHour ? `${currentHour.va_migration_vs_prev} migration` : 'Awaiting data'}
            />
            <MetricCard
              label="Single Prints"
              value={String(context.prev_day_profile?.single_prints.length ?? 0)}
              tone="text-emerald-300"
              subtext="Previous session targets"
            />
            <MetricCard
              label="Pipeline"
              value={`${scan?.stages?.final ?? 0} candidates`}
              tone="text-sky-300"
              subtext={`shape ${scan?.stages?.shape_pass ?? 0} · daily ${scan?.stages?.daily_pass ?? 0}`}
            />
          </div>
        ) : null}
      </div>

      {contextQuery.isLoading ? (
        <div className="flex h-56 items-center justify-center rounded-xl border border-slate-800 bg-slate-900/40">
          <RefreshCw className="h-5 w-5 animate-spin text-slate-500" />
        </div>
      ) : null}

      <AssessmentPanel assessment={context?.assessment} />
      {context?.candidate ? <CandidateBanner candidate={context.candidate} /> : null}

      {context && !context.error && context.daily_profile ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.1fr,1.9fr]">
          <div className="space-y-4">
            <ProfileMini
              profile={context.daily_profile}
              title="Daily Context"
              subtitle={`VA ${formatINR(context.daily_profile.val)} - ${formatINR(context.daily_profile.vah)}`}
            />
            {context.prev_day_profile ? (
              <ProfileMini
                profile={context.prev_day_profile}
                title="Previous Session"
                subtitle={`${context.prev_day_profile.single_prints.length} single-print zone(s)`}
              />
            ) : null}
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold text-slate-100">Hourly Fractal Sequence</div>
                <div className="text-xs text-slate-500">Each hour is rebuilt from 3-minute TPO periods</div>
              </div>
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <Activity className="h-3.5 w-3.5" />
                <span>{context.hourly_profiles.length} profile windows</span>
              </div>
            </div>
            <div className="flex gap-3 overflow-x-auto pb-1">
              {context.hourly_profiles.map((profile) => (
                <HourlyProfileCard key={profile.start} profile={profile} />
              ))}
            </div>
          </div>
        </div>
      ) : null}

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold text-slate-100">Scanner Output</div>
            <div className="text-xs text-slate-500">
              Progressive filter: shape → migration → daily alignment → order flow
            </div>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            {scanQuery.isFetching ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : null}
            <span>{scan ? `${formatNumber(scan.total_symbols)} symbols` : '—'}</span>
          </div>
        </div>

        <div className="mb-3 grid grid-cols-2 gap-2 text-xs lg:grid-cols-6">
          {Object.entries(scan?.stages ?? {}).map(([key, value]) => (
            <div key={key} className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
              <div className="uppercase tracking-wider text-slate-500">{key.replace('_', ' ')}</div>
              <div className="mt-1 text-base font-semibold text-slate-100">{value}</div>
            </div>
          ))}
        </div>

        <div className="overflow-hidden rounded-lg border border-slate-800">
          <div className="max-h-[360px] overflow-auto">
            <table className="w-full min-w-[880px] text-sm">
              <thead className="sticky top-0 bg-slate-950 text-xs uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left">Symbol</th>
                  <th className="px-3 py-2 text-left">Direction</th>
                  <th className="px-3 py-2 text-right">Conviction</th>
                  <th className="px-3 py-2 text-left">Structure</th>
                  <th className="px-3 py-2 text-right">Entry</th>
                  <th className="px-3 py-2 text-right">Stop</th>
                  <th className="px-3 py-2 text-right">Target</th>
                  <th className="px-3 py-2 text-left">Contract</th>
                </tr>
              </thead>
              <tbody>
                {scan?.candidates?.map((candidate) => (
                  <tr key={`${candidate.symbol}-${candidate.direction}`} className="border-t border-slate-800/70">
                    <td className="px-3 py-2 font-medium text-slate-100">{candidate.symbol}</td>
                    <td className={cn('px-3 py-2 font-semibold', directionTone(candidate.direction))}>
                      {candidate.direction}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-slate-200">{candidate.conviction}</td>
                    <td className="px-3 py-2 text-slate-300">
                      {candidate.hourly_shape} · {candidate.consecutive_migration_hours}h
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-slate-300">{formatINR(candidate.entry_trigger)}</td>
                    <td className="px-3 py-2 text-right font-mono text-rose-300">{formatINR(candidate.stop_reference)}</td>
                    <td className="px-3 py-2 text-right font-mono text-emerald-300">
                      {candidate.target_reference ? formatINR(candidate.target_reference) : '—'}
                    </td>
                    <td className="px-3 py-2 text-slate-400">{candidate.suggested_contract ?? '—'}</td>
                  </tr>
                ))}
                {!scan?.candidates?.length ? (
                  <tr>
                    <td colSpan={8} className="px-3 py-6 text-center text-slate-500">
                      No candidates passed the structural and order-flow filters for this session.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>

        {scan?.generated_at ? (
          <div className="mt-3 flex items-center gap-2 text-[11px] text-slate-500">
            <Shield className="h-3.5 w-3.5" />
            <span>Generated {new Date(scan.generated_at).toLocaleTimeString('en-IN', { hour12: false })}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

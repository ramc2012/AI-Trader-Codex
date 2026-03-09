'use client';

import { useMemo, useState } from 'react';
import { CalendarDays, RefreshCw, SplitSquareVertical } from 'lucide-react';

import { useHistoricalData } from '@/hooks/use-watchlist';
import {
  buildInstrumentOptions,
  defaultSymbolForMarket,
  filterInstrumentOptions,
  type InstrumentOption,
} from '@/lib/instrument-universe';
import {
  aggregateCandlesByMinutes,
  calculateTPOProfile,
  groupCandlesBySessionMode,
  type SessionMode,
  type TPOLevel,
  type TPOProfile,
} from '@/lib/tpo-calculator';
import { cn } from '@/lib/utils';

const MARKET_FILTERS = ['ALL', 'NSE', 'BSE', 'US', 'CRYPTO'] as const;
const TOP_PERIODS = [
  { label: '30m TPO', value: 30 },
  { label: '2h TPO', value: 120 },
  { label: '4h TPO', value: 240 },
] as const;
const TOP_MODES: Array<{ label: string; value: SessionMode }> = [
  { label: 'Daily', value: 'daily' },
  { label: 'Weekly', value: 'weekly' },
  { label: 'Monthly', value: 'monthly' },
];
const TOP_HEIGHT = 360;
const BOTTOM_HEIGHT = 320;
const HEADER_HEIGHT = 30;
const MIN_ROW_HEIGHT = 3;
const MAX_ROW_HEIGHT = 18;
const LETTER_COLORS = [
  'text-emerald-300',
  'text-sky-300',
  'text-amber-300',
  'text-rose-300',
  'text-violet-300',
  'text-cyan-300',
  'text-lime-300',
  'text-fuchsia-300',
];

interface ProfileView extends TPOProfile {
  key: string;
  label: string;
}

interface HourlyProfileView extends ProfileView {
  sessionDate: string;
  startLabel: string;
}

type CandleRow = {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

function toEpochMs(value: number | string): number {
  return typeof value === 'number' ? value * 1000 : new Date(value).getTime();
}

function istDateParts(value: number | string) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(new Date(toEpochMs(value)));

  const read = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? '0');
  return {
    year: read('year'),
    month: read('month'),
    day: read('day'),
    hour: read('hour'),
    minute: read('minute'),
  };
}

function formatSessionKey(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

function shiftSessionDate(sessionDate: string, days: number): string {
  const shifted = new Date(`${sessionDate}T00:00:00+05:30`);
  shifted.setUTCDate(shifted.getUTCDate() + days);
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(shifted);
}

function hourlySessionKey(value: number | string, market: string): string {
  const parts = istDateParts(value);
  const dayKey = formatSessionKey(parts.year, parts.month, parts.day);
  if (market === 'US' && parts.hour < 19) {
    return shiftSessionDate(dayKey, -1);
  }
  return dayKey;
}

function hourlySessionAnchorMs(sessionDate: string, market: string): number {
  const anchorTime =
    market === 'US'
      ? '19:00:00'
      : market === 'NSE' || market === 'BSE'
        ? '09:15:00'
        : '00:00:00';
  return new Date(`${sessionDate}T${anchorTime}+05:30`).getTime();
}

function letterColor(letterIndex: number): string {
  return LETTER_COLORS[letterIndex % LETTER_COLORS.length];
}

function buildUnifiedGrid(profiles: Array<ProfileView | HourlyProfileView>) {
  if (!profiles.length) return [];
  let globalHigh = -Infinity;
  let globalLow = Infinity;
  let minTick = Infinity;
  for (const profile of profiles) {
    globalHigh = Math.max(globalHigh, profile.high);
    globalLow = Math.min(globalLow, profile.low);
    minTick = Math.min(minTick, profile.tickSize ?? 1);
  }
  const tick = Number.isFinite(minTick) && minTick > 0 ? minTick : 1;
  const gridLow = Math.floor(globalLow / tick) * tick;
  const gridHigh = Math.ceil(globalHigh / tick) * tick;
  const prices: number[] = [];
  for (let price = gridHigh; price >= gridLow; price -= tick) {
    prices.push(Number(price.toFixed(2)));
  }
  return prices;
}

function rowHeightForGrid(rowCount: number, totalHeight: number) {
  if (!rowCount) return 12;
  const usable = totalHeight - HEADER_HEIGHT;
  const scaled = usable / rowCount;
  return Math.max(MIN_ROW_HEIGHT, Math.min(MAX_ROW_HEIGHT, scaled));
}

function marketFromSymbol(symbol: string): string {
  const [market] = symbol.split(':');
  return market?.toUpperCase() || 'NSE';
}

function normalizeTickSize(rawTick: number): number {
  if (!Number.isFinite(rawTick) || rawTick <= 0) {
    return 1;
  }
  const magnitude = 10 ** Math.floor(Math.log10(rawTick));
  const normalized = rawTick / magnitude;
  const ladder = [1, 2, 2.5, 5, 10];
  const multiplier = ladder.find((step) => normalized <= step) ?? 10;
  return Number((multiplier * magnitude).toFixed(6));
}

function computeAdaptiveTickSize(
  candles: CandleRow[],
  market: string,
): number | undefined {
  if (candles.length < 2) return undefined;
  if (market === 'NSE' || market === 'BSE') {
    return 10;
  }

  const ordered = [...candles].sort((a, b) => toEpochMs(a.timestamp) - toEpochMs(b.timestamp));
  const sessionHigh = Math.max(...ordered.map((bar) => bar.high));
  const sessionLow = Math.min(...ordered.map((bar) => bar.low));
  const range = sessionHigh - sessionLow;

  if (!Number.isFinite(range) || range <= 0) return undefined;

  const lastClose = Math.abs(ordered[ordered.length - 1]?.close ?? 0);
  const pctStep = lastClose * 0.0005;
  const autoStep = Math.max(range / 80, 0.1);
  return normalizeTickSize(Math.max(autoStep, pctStep));
}

function sessionLimitForMode(mode: SessionMode): number {
  if (mode === 'weekly') return 10;
  if (mode === 'monthly') return 8;
  return 10;
}

function lookbackDaysForMode(mode: SessionMode): number {
  if (mode === 'weekly') return 120;
  if (mode === 'monthly') return 365;
  return 30;
}

function Letters({ letters }: { letters: string[] }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-[1px] font-mono">
      {letters.map((letter, index) => (
        <span key={`${letter}-${index}`} className={letterColor(index)}>
          {letter}
        </span>
      ))}
    </span>
  );
}

function ProfileColumn({
  profile,
  priceGrid,
  maxTpo,
  rowHeight,
  showDaySeparator = false,
}: {
  profile: ProfileView | HourlyProfileView;
  priceGrid: number[];
  maxTpo: number;
  rowHeight: number;
  showDaySeparator?: boolean;
}) {
  const levelMap = useMemo(() => {
    const map = new Map<number, TPOLevel>();
    for (const level of profile.levels) {
      map.set(Number(level.price.toFixed(2)), level);
    }
    return map;
  }, [profile.levels]);

  const maxLetters = useMemo(
    () => Math.max(...profile.levels.map((level) => level.letters.length), 1),
    [profile.levels],
  );
  const width = Math.max(86, maxLetters * 8 + 28);
  const tickSize = profile.tickSize ?? 1;

  return (
    <div
      className={cn(
        'flex flex-shrink-0 flex-col border-r border-slate-800/70',
        showDaySeparator && 'border-l-2 border-l-slate-500/80',
      )}
      style={{ width: `${width}px` }}
    >
      <div className="flex h-[30px] items-center justify-center border-b border-slate-800 bg-slate-900/70 px-2">
        <div className="text-center">
          <div className="text-[10px] font-semibold text-slate-200">{profile.label}</div>
          {'startLabel' in profile ? (
            <div className="text-[9px] text-slate-500">{profile.startLabel}</div>
          ) : null}
        </div>
      </div>
      <div className="flex-1">
        {priceGrid.map((price) => {
          const level = levelMap.get(Number(price.toFixed(2)));
          const isPoc = Math.abs(price - profile.poc) < tickSize * 0.5;
          const isVa = price >= profile.val && price <= profile.vah;
          const isIb = price >= profile.ibLow && price <= profile.ibHigh;
          return (
            <div
              key={`${profile.key}-${price}`}
              className={cn(
                'relative flex items-center px-1.5',
                isPoc ? 'bg-amber-500/15' : isVa ? 'bg-sky-500/8' : '',
              )}
              style={{ height: `${rowHeight}px`, fontSize: '10px' }}
            >
              {isIb ? <span className="absolute left-0 text-cyan-500/60">│</span> : null}
              {level ? (
                <div
                  className={cn(
                    'rounded-sm px-1 leading-none',
                    isPoc ? 'bg-amber-500/10' : '',
                  )}
                  style={{ opacity: 0.4 + (level.tpoCount / Math.max(maxTpo, 1)) * 0.6 }}
                >
                  <Letters letters={level.letters} />
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Pane({
  title,
  subtitle,
  profiles,
  height,
  continuous = false,
}: {
  title: string;
  subtitle: string;
  profiles: Array<ProfileView | HourlyProfileView>;
  height: number;
  continuous?: boolean;
}) {
  const priceGrid = useMemo(() => buildUnifiedGrid(profiles), [profiles]);
  const maxTpo = useMemo(
    () => Math.max(...profiles.flatMap((profile) => profile.levels.map((level) => level.tpoCount)), 1),
    [profiles],
  );
  const rowHeight = useMemo(() => rowHeightForGrid(priceGrid.length, height), [height, priceGrid.length]);

  return (
    <div className="rounded-xl border border-slate-800 bg-[#0a0f18]">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-slate-200">{title}</div>
          <div className="text-[11px] text-slate-500">{subtitle}</div>
        </div>
        <div className="flex gap-3 text-[11px] text-slate-500">
          <span><span className="text-amber-300">■</span> POC</span>
          <span><span className="text-sky-300">■</span> Value</span>
          <span><span className="text-cyan-300">│</span> IB</span>
          {continuous ? <span><span className="text-slate-300">┃</span> Day separator</span> : null}
        </div>
      </div>
      {!profiles.length ? (
        <div className="flex items-center justify-center text-sm text-slate-500" style={{ height: `${height}px` }}>
          No profile data available for the current selection
        </div>
      ) : (
        <div className="flex overflow-hidden" style={{ height: `${height}px` }}>
          <div className="z-10 flex flex-shrink-0 flex-col overflow-hidden border-r border-slate-800 bg-[#0a0f18]">
            <div className="h-[30px] border-b border-slate-800" />
            <div className="flex-1">
              {priceGrid.map((price) => (
                <div
                  key={`${title}-${price}`}
                  className="flex items-center justify-end px-2 font-mono text-slate-500"
                  style={{ height: `${rowHeight}px`, fontSize: '10px' }}
                >
                  {price.toFixed(2)}
                </div>
              ))}
            </div>
          </div>
          <div className="flex-1 overflow-x-auto overflow-y-hidden">
            <div className="flex min-w-max">
              {profiles.map((profile, index) => {
                const previous = profiles[index - 1];
                const showDaySeparator =
                  continuous &&
                  'sessionDate' in profile &&
                  previous &&
                  'sessionDate' in previous &&
                  profile.sessionDate !== previous.sessionDate;
                return (
                  <ProfileColumn
                    key={profile.key}
                    profile={profile}
                    priceGrid={priceGrid}
                    maxTpo={maxTpo}
                    rowHeight={rowHeight}
                    showDaySeparator={showDaySeparator}
                  />
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function buildTopProfiles(
  candles: CandleRow[],
  mode: SessionMode,
  periodMinutes: number,
  tickSize?: number,
): ProfileView[] {
  const baseBars = candles.map((bar) => ({
    timestamp: bar.timestamp,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    volume: bar.volume,
  }));
  const sourceBars = periodMinutes === 30 ? baseBars : aggregateCandlesByMinutes(baseBars, periodMinutes);
  const groups = groupCandlesBySessionMode(sourceBars, mode);
  return groups
    .map((group) => {
      const profile = calculateTPOProfile(
        group.candles,
        tickSize,
        0.70,
        {
          periodMinutes,
          periodStartTime: group.candles[0]?.timestamp,
          sessionLabel: group.label,
        },
      );
      if (!profile) return null;
      return {
        ...profile,
        key: group.key,
        label: group.label,
      };
    })
    .filter((profile): profile is ProfileView => profile !== null)
    .slice(-sessionLimitForMode(mode));
}

function buildHourlyProfiles(
  candles: CandleRow[],
  market: string,
  tickSize?: number,
): HourlyProfileView[] {
  const dayBuckets = new Map<string, CandleRow[]>();
  for (const candle of candles) {
    const key = hourlySessionKey(candle.timestamp, market);
    const existing = dayBuckets.get(key) ?? [];
    existing.push(candle);
    dayBuckets.set(key, existing);
  }

  const output: HourlyProfileView[] = [];
  for (const [sessionDate, rows] of Array.from(dayBuckets.entries()).sort((a, b) => a[0].localeCompare(b[0]))) {
    const ordered = [...rows].sort((a, b) => toEpochMs(a.timestamp) - toEpochMs(b.timestamp));
    const anchor = hourlySessionAnchorMs(sessionDate, market);
    const hourBuckets = new Map<number, typeof ordered>();
    for (const row of ordered) {
      const bucketIndex = Math.max(0, Math.floor((toEpochMs(row.timestamp) - anchor) / 3_600_000));
      const bucket = hourBuckets.get(bucketIndex) ?? [];
      bucket.push(row);
      hourBuckets.set(bucketIndex, bucket);
    }
    for (const [bucketIndex, bucketRows] of Array.from(hourBuckets.entries()).sort((a, b) => a[0] - b[0])) {
      if (bucketRows.length < 2) continue;
      const startMs = anchor + bucketIndex * 3_600_000;
      const startLabel = new Date(startMs).toLocaleTimeString('en-IN', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
        timeZone: 'Asia/Kolkata',
      });
      const profile = calculateTPOProfile(
        bucketRows,
        tickSize,
        0.70,
        {
          periodMinutes: 3,
          periodStartTime: startMs,
          ibPeriods: 2,
          sessionLabel: startLabel,
        },
      );
      if (!profile) continue;
      output.push({
        ...profile,
        key: `${sessionDate}-${bucketIndex}`,
        label: new Date(startMs).toLocaleDateString('en-IN', {
          day: '2-digit',
          month: 'short',
          timeZone: 'Asia/Kolkata',
        }),
        startLabel,
        sessionDate,
      });
    }
  }
  return output;
}

export default function MarketProfileWorkspace({
  options,
  initialSymbol,
}: {
  options: InstrumentOption[];
  initialSymbol?: string | null;
}) {
  const normalizedOptions = useMemo(
    () => (options.length ? options : buildInstrumentOptions(undefined)),
    [options],
  );
  const [market, setMarket] = useState<string>('ALL');
  const filteredOptions = useMemo(() => filterInstrumentOptions(normalizedOptions, market), [market, normalizedOptions]);
  const [requestedSymbol, setRequestedSymbol] = useState(() =>
    defaultSymbolForMarket(normalizedOptions, 'ALL', initialSymbol ?? 'NSE:NIFTY50-INDEX'),
  );
  const symbol = useMemo(() => {
    if (filteredOptions.some((item) => item.value === requestedSymbol)) {
      return requestedSymbol;
    }
    return defaultSymbolForMarket(normalizedOptions, market, initialSymbol ?? requestedSymbol);
  }, [filteredOptions, initialSymbol, market, normalizedOptions, requestedSymbol]);
  const [topMode, setTopMode] = useState<SessionMode>('daily');
  const [topPeriodMinutes, setTopPeriodMinutes] = useState<number>(30);
  const symbolMarket = useMemo(() => marketFromSymbol(symbol), [symbol]);

  const topQuery = useHistoricalData(symbol, lookbackDaysForMode(topMode), '30', Boolean(symbol));
  const bottomQuery = useHistoricalData(symbol, 8, '3', Boolean(symbol));
  const topTickSize = useMemo(
    () => computeAdaptiveTickSize(topQuery.data?.data ?? [], symbolMarket),
    [symbolMarket, topQuery.data?.data],
  );
  const bottomTickSize = useMemo(
    () => computeAdaptiveTickSize(bottomQuery.data?.data ?? [], symbolMarket),
    [bottomQuery.data?.data, symbolMarket],
  );

  const topProfiles = useMemo(
    () => buildTopProfiles(topQuery.data?.data ?? [], topMode, topPeriodMinutes, topTickSize),
    [topMode, topPeriodMinutes, topQuery.data?.data, topTickSize],
  );
  const hourlyProfiles = useMemo(
    () => buildHourlyProfiles(bottomQuery.data?.data ?? [], symbolMarket, bottomTickSize),
    [bottomQuery.data?.data, bottomTickSize, symbolMarket],
  );

  const topLoading = topQuery.isLoading || topQuery.isFetching;
  const bottomLoading = bottomQuery.isLoading || bottomQuery.isFetching;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/70 p-4">
        <select
          value={market}
          onChange={(e) => setMarket(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
        >
          {MARKET_FILTERS.map((item) => (
            <option key={item} value={item}>
              {item === 'ALL' ? 'All Markets' : item}
            </option>
          ))}
        </select>
        <select
          value={symbol}
          onChange={(e) => setRequestedSymbol(e.target.value)}
          className="min-w-[240px] rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
        >
          {filteredOptions.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <div className="flex gap-1 rounded-lg border border-slate-800 bg-slate-950 p-1">
          {TOP_MODES.map((item) => (
            <button
              key={item.value}
              onClick={() => setTopMode(item.value)}
              className={cn(
                'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                topMode === item.value ? 'bg-emerald-500/20 text-emerald-300' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200',
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="flex gap-1 rounded-lg border border-slate-800 bg-slate-950 p-1">
          {TOP_PERIODS.map((item) => (
            <button
              key={item.value}
              onClick={() => setTopPeriodMinutes(item.value)}
              className={cn(
                'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                topPeriodMinutes === item.value ? 'bg-sky-500/20 text-sky-300' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200',
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-3 text-[11px] text-slate-500">
          <span className="inline-flex items-center gap-1">
            <CalendarDays className="h-3.5 w-3.5" />
            Top: {topMode} composite from {topPeriodMinutes}m periods
          </span>
          <span className="inline-flex items-center gap-1">
            <SplitSquareVertical className="h-3.5 w-3.5" />
            Bottom: continuous hourly profile from 3m periods
          </span>
          <span>{symbolMarket === 'NSE' || symbolMarket === 'BSE' ? 'Bracket: fixed 10 points' : 'Bracket: 0.05% adaptive'}</span>
          {(topLoading || bottomLoading) ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : null}
        </div>
      </div>

      <Pane
        title="Composite Profiles"
        subtitle="ABCD-style TPO letters rendered in color. Switch between daily, weekly, and monthly session composites."
        profiles={topProfiles}
        height={TOP_HEIGHT}
      />

      <Pane
        title="Continuous Hourly Profiles"
        subtitle="Fractal hourly profiles built from 3-minute periods with day separators across sessions."
        profiles={hourlyProfiles}
        height={BOTTOM_HEIGHT}
        continuous
      />
    </div>
  );
}

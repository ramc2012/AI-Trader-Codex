'use client';

import { useMemo, useState } from 'react';
import { Calendar, Layers, RefreshCw } from 'lucide-react';
import { useMultiTPO } from '@/hooks/use-tpo';
import { cn } from '@/lib/utils';

const PROFILE_VIEW_HEIGHT = 520;
const PROFILE_HEADER_HEIGHT = 28;
const PROFILE_MIN_ROW_PX = 7;
const PROFILE_MAX_ROW_PX = 20;

const SYMBOLS = [
  'NSE:NIFTY50-INDEX',
  'NSE:NIFTYBANK-INDEX',
  'NSE:FINNIFTY-INDEX',
  'NSE:NIFTYMIDCAP50-INDEX',
  'BSE:SENSEX-INDEX',
  'NSE:RELIANCE-EQ',
  'NSE:HDFCBANK-EQ',
  'NSE:INFY-EQ',
  'NSE:TCS-EQ',
  'NSE:SBIN-EQ',
  'NSE:ICICIBANK-EQ',
  'US:SPY',
  'US:QQQ',
  'US:AAPL',
  'US:MSFT',
  'CRYPTO:BTCUSDT',
  'CRYPTO:ETHUSDT',
  'CRYPTO:SOLUSDT',
];

const PERIODS = [
  { label: '5D', value: 5 },
  { label: '10D', value: 10 },
  { label: '20D', value: 20 },
  { label: '40D', value: 40 },
];

interface TPOLevel {
  price: number;
  tpo_count: number;
  letters: string[];
  volume: number;
}

interface DayProfile {
  date: string;
  poc: number;
  vah: number;
  val: number;
  ib_high: number;
  ib_low: number;
  open: number;
  close: number;
  high: number;
  low: number;
  total_volume: number;
  levels: TPOLevel[];
}

function buildUnifiedGrid(profiles: DayProfile[], tickSize: number) {
  let globalHigh = -Infinity;
  let globalLow = Infinity;
  for (const p of profiles) {
    if (p.high > globalHigh) globalHigh = p.high;
    if (p.low < globalLow) globalLow = p.low;
  }
  const gridLow = Math.floor(globalLow / tickSize) * tickSize;
  const gridHigh = Math.ceil(globalHigh / tickSize) * tickSize;
  const prices: number[] = [];
  for (let p = gridHigh; p >= gridLow; p -= tickSize) {
    prices.push(Math.round(p * 100) / 100);
  }
  return prices;
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
  } catch {
    return dateStr;
  }
}

function DayColumn({
  profile,
  priceGrid,
  maxTPO,
  tickSize,
  rowHeightPx,
}: {
  profile: DayProfile;
  priceGrid: number[];
  maxTPO: number;
  tickSize: number;
  rowHeightPx: number;
}) {
  const levelMap = useMemo(() => {
    const map = new Map<number, TPOLevel>();
    for (const l of profile.levels) {
      const snapped = Math.round(l.price / tickSize) * tickSize;
      map.set(Math.round(snapped * 100) / 100, l);
    }
    return map;
  }, [profile.levels, tickSize]);

  const maxLetters = useMemo(() => {
    let m = 1;
    for (const l of profile.levels) {
      if (l.letters.length > m) m = l.letters.length;
    }
    return m;
  }, [profile.levels]);

  const colWidth = Math.max(72, maxLetters * 7 + 22);

  return (
    <div className="flex flex-shrink-0 flex-col border-r border-slate-800/60" style={{ width: `${colWidth}px` }}>
      <div className="flex h-7 items-center justify-center border-b border-slate-800 bg-slate-900/40">
        <span className="text-[10px] font-semibold text-slate-300">{formatDate(profile.date)}</span>
      </div>
      <div className="flex-1 overflow-hidden">
        <div className="flex flex-col">
          {priceGrid.map((price) => {
            const level = levelMap.get(price);
            const isPOC = level && Math.abs(price - profile.poc) < tickSize * 0.5;
            const isVA = price >= profile.val && price <= profile.vah;
            const isIB = price >= profile.ib_low && price <= profile.ib_high;

            return (
              <div
                key={`${profile.date}-${price}`}
                className={cn(
                  'relative flex items-center px-1',
                  isPOC ? 'bg-amber-500/15' : isVA ? 'bg-blue-500/5' : '',
                )}
                style={{ height: `${rowHeightPx}px`, fontSize: '9px' }}
              >
                {isIB && (
                  <span className="absolute left-0 text-cyan-500/50" style={{ fontSize: '9px' }}>
                    │
                  </span>
                )}
                {level ? (
                  <span
                    className={cn(
                      'pl-1.5 font-mono leading-none',
                      isPOC ? 'font-bold text-amber-300' : isVA ? 'text-blue-300' : 'text-slate-400',
                    )}
                    style={{ opacity: 0.4 + (level.tpo_count / maxTPO) * 0.6 }}
                  >
                    {level.letters.join('')}
                  </span>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function TradingViewMarketProfile() {
  const [symbol, setSymbol] = useState(SYMBOLS[0]);
  const [days, setDays] = useState(10);
  const { data: multiData, isLoading: profilesLoading } = useMultiTPO(symbol, days);

  const profiles = useMemo<DayProfile[]>(() => multiData?.profiles ?? [], [multiData]);
  const latestProfile = profiles[profiles.length - 1];

  const tickSize = useMemo(() => {
    if (!profiles.length || !profiles[0].levels || profiles[0].levels.length < 2) return 5;
    const sorted = [...profiles[0].levels].sort((a, b) => a.price - b.price);
    const diff = sorted[1].price - sorted[0].price;
    return diff > 0 ? diff : 5;
  }, [profiles]);

  const priceGrid = useMemo(() => {
    if (!profiles.length) return [];
    return buildUnifiedGrid(profiles, tickSize);
  }, [profiles, tickSize]);

  const maxTPO = useMemo(() => {
    let max = 1;
    for (const p of profiles) {
      for (const l of p.levels) {
        if (l.tpo_count > max) max = l.tpo_count;
      }
    }
    return max;
  }, [profiles]);

  const rowHeightPx = useMemo(() => {
    if (!priceGrid.length) return 14;
    const usableHeight = PROFILE_VIEW_HEIGHT - PROFILE_HEADER_HEIGHT;
    const scaled = usableHeight / priceGrid.length;
    return Math.max(PROFILE_MIN_ROW_PX, Math.min(PROFILE_MAX_ROW_PX, scaled));
  }, [priceGrid.length]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-300"
        >
          {SYMBOLS.map((s) => (
            <option key={s} value={s}>
              {s.replace('NSE:', '').replace('-EQ', '').replace('-INDEX', '')}
            </option>
          ))}
        </select>

        <div className="flex gap-0.5">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => setDays(p.value)}
              className={cn(
                'rounded px-2.5 py-1 text-xs font-medium',
                days === p.value ? 'bg-amber-500/20 text-amber-400' : 'text-slate-500 hover:bg-slate-800 hover:text-slate-300',
              )}
            >
              {p.label}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2 text-[11px] text-slate-500">
          {profilesLoading && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
          {latestProfile && (
            <>
              <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-300">POC {latestProfile.poc.toFixed(1)}</span>
              <span className="rounded bg-blue-500/10 px-1.5 py-0.5 text-blue-300">
                VA {latestProfile.val.toFixed(1)}-{latestProfile.vah.toFixed(1)}
              </span>
            </>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-slate-800 bg-[#0a0e17] overflow-hidden">
        {!profiles.length ? (
          <div className="flex items-center justify-center text-xs text-slate-500" style={{ height: `${PROFILE_VIEW_HEIGHT}px` }}>
            No market profile data available
          </div>
        ) : (
          <div className="flex" style={{ height: `${PROFILE_VIEW_HEIGHT}px` }}>
            <div className="z-10 flex flex-shrink-0 flex-col border-r border-slate-800 bg-[#0a0e17]">
              <div className="h-7 border-b border-slate-800" />
              <div className="flex-1 overflow-hidden">
                <div className="flex flex-col">
                  {priceGrid.map((price) => (
                    <div
                      key={price}
                      className="flex items-center justify-end px-1.5 font-mono text-slate-500"
                      style={{ height: `${rowHeightPx}px`, fontSize: '10px' }}
                    >
                      {price.toFixed(1)}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex-1 overflow-x-auto overflow-y-hidden">
              <div className="flex" style={{ minWidth: 'max-content' }}>
                {profiles.map((profile) => (
                  <DayColumn
                    key={profile.date}
                    profile={profile}
                    priceGrid={priceGrid}
                    maxTPO={maxTPO}
                    tickSize={tickSize}
                    rowHeightPx={rowHeightPx}
                  />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="flex gap-4 px-1 text-[10px] text-slate-500">
        <span><Calendar className="mr-1 inline h-3 w-3" />Session Profiles</span>
        <span><span className="text-amber-400">■</span> POC</span>
        <span><span className="text-blue-400">■</span> Value Area</span>
        <span><span className="text-cyan-400">│</span> Initial Balance</span>
        <span><Layers className="mr-1 inline h-3 w-3" />Scroll horizontally for multi-day structure</span>
      </div>
    </div>
  );
}

export default TradingViewMarketProfile;

/**
 * Client-side TPO (Time-Price Opportunity) Market Profile calculator.
 * Generates profile data from OHLC candles for chart rendering.
 */

import type { OHLCBar } from './indicators';

export interface TPOLevel {
  price: number;
  tpoCount: number;
  letters: string[];
  volume: number;
}

export interface TPOProfile {
  date: string;
  levels: TPOLevel[];
  poc: number;
  vah: number;
  val: number;
  ibHigh: number;
  ibLow: number;
  open: number;
  close: number;
  high: number;
  low: number;
  tickSize?: number;
  periodMinutes?: number;
  sessionLabel?: string;
}

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';

export interface TPOCalculationOptions {
  periodMinutes?: number;
  periodStartTime?: number | string | Date;
  labels?: string[];
  ibPeriods?: number;
  sessionLabel?: string;
}

export type SessionMode = 'daily' | 'weekly' | 'monthly';

function toDate(timestamp: number | string | Date): Date {
  if (timestamp instanceof Date) return timestamp;
  if (typeof timestamp === 'number') return new Date(timestamp * 1000);
  return new Date(timestamp);
}

function labelForPeriod(index: number, labels?: string[]): string {
  if (labels?.[index]) return labels[index];
  if (index < LETTERS.length) return LETTERS[index];
  return LETTERS[index % LETTERS.length];
}

/**
 * Generate Market Profile from intraday candles.
 */
export function calculateTPOProfile(
  candles: OHLCBar[],
  tickSize?: number,
  valueAreaPct: number = 0.70,
  options: TPOCalculationOptions = {},
): TPOProfile | null {
  if (candles.length < 2) return null;
  const sortedCandles = [...candles].sort(
    (a, b) => toDate(a.timestamp).getTime() - toDate(b.timestamp).getTime(),
  );
  const periodMinutes = Math.max(options.periodMinutes ?? 30, 1);
  const periodStartTime =
    options.periodStartTime !== undefined
      ? toDate(options.periodStartTime).getTime()
      : toDate(sortedCandles[0].timestamp).getTime();
  const ibPeriods = Math.max(options.ibPeriods ?? 2, 1);

  const highs = sortedCandles.map((c) => c.high);
  const lows = sortedCandles.map((c) => c.low);
  const sessionHigh = Math.max(...highs);
  const sessionLow = Math.min(...lows);
  const range = sessionHigh - sessionLow;

  if (range <= 0) return null;

  const tick = tickSize ?? Math.max(Math.round((range / 50) * 100) / 100, 0.5);

  // Build price grid
  const gridLow = Math.floor(sessionLow / tick) * tick;
  const gridHigh = Math.ceil(sessionHigh / tick) * tick;
  const levels = new Map<number, TPOLevel>();

  for (let p = gridLow; p <= gridHigh; p += tick) {
    const rounded = Math.round(p * 100) / 100;
    levels.set(rounded, { price: rounded, tpoCount: 0, letters: [], volume: 0 });
  }

  // Group candles into fixed periods from the provided session anchor.
  const periods = new Map<number, OHLCBar[]>();
  const periodMs = periodMinutes * 60 * 1000;
  for (const c of sortedCandles) {
    const ts = toDate(c.timestamp).getTime();
    const periodIdx = Math.max(0, Math.floor((ts - periodStartTime) / periodMs));
    const existing = periods.get(periodIdx) ?? [];
    existing.push(c);
    periods.set(periodIdx, existing);
  }

  let ibHigh = 0;
  let ibLow = Infinity;

  for (const [periodIdx, periodCandles] of Array.from(periods.entries()).sort((a, b) => a[0] - b[0])) {
    const letter = labelForPeriod(periodIdx, options.labels);
    const pH = Math.max(...periodCandles.map((c) => c.high));
    const pL = Math.min(...periodCandles.map((c) => c.low));

    if (periodIdx < ibPeriods) {
      ibHigh = Math.max(ibHigh, pH);
      ibLow = Math.min(ibLow, pL);
    }

    for (const [price, level] of levels) {
      if (pL <= price && price <= pH) {
        level.tpoCount++;
        level.letters.push(letter);
      }
    }
  }

  // Find POC
  const activeLevels = Array.from(levels.values()).filter((l) => l.tpoCount > 0);
  if (activeLevels.length === 0) return null;

  activeLevels.sort((a, b) => a.price - b.price);
  const pocLevel = activeLevels.reduce((best, l) => (l.tpoCount > best.tpoCount ? l : best));
  const poc = pocLevel.price;

  // Value Area
  const totalTPOs = activeLevels.reduce((s, l) => s + l.tpoCount, 0);
  const targetTPOs = Math.floor(totalTPOs * valueAreaPct);
  const pocIdx = activeLevels.findIndex((l) => l.price === poc);
  let upper = pocIdx;
  let lower = pocIdx;
  let vaTPOs = pocLevel.tpoCount;

  while (vaTPOs < targetTPOs) {
    const upVal = upper + 1 < activeLevels.length ? activeLevels[upper + 1].tpoCount : 0;
    const downVal = lower - 1 >= 0 ? activeLevels[lower - 1].tpoCount : 0;
    if (upVal === 0 && downVal === 0) break;
    if (upVal >= downVal) { upper++; vaTPOs += upVal; }
    else { lower--; vaTPOs += downVal; }
  }

  const firstCandle = sortedCandles[0];
  const lastCandle = sortedCandles[sortedCandles.length - 1];
  const ts = toDate(firstCandle.timestamp);

  return {
    date: ts.toISOString().split('T')[0],
    levels: activeLevels,
    poc,
    vah: activeLevels[upper].price,
    val: activeLevels[lower].price,
    ibHigh: ibHigh || sessionHigh,
    ibLow: ibLow === Infinity ? sessionLow : ibLow,
    open: firstCandle.open,
    close: lastCandle.close,
    high: sessionHigh,
    low: sessionLow,
    tickSize: tick,
    periodMinutes,
    sessionLabel: options.sessionLabel,
  };
}

export function aggregateCandlesByMinutes(candles: OHLCBar[], minutes: number): OHLCBar[] {
  const bucketMinutes = Math.max(minutes, 1);
  const ordered = [...candles].sort(
    (a, b) => toDate(a.timestamp).getTime() - toDate(b.timestamp).getTime(),
  );
  const buckets = new Map<number, OHLCBar>();
  const bucketMs = bucketMinutes * 60 * 1000;

  for (const candle of ordered) {
    const ts = toDate(candle.timestamp).getTime();
    const bucket = Math.floor(ts / bucketMs) * bucketMs;
    const existing = buckets.get(bucket);
    if (!existing) {
      buckets.set(bucket, {
        timestamp: new Date(bucket).toISOString(),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
        volume: candle.volume ?? 0,
      });
      continue;
    }
    existing.high = Math.max(existing.high, candle.high);
    existing.low = Math.min(existing.low, candle.low);
    existing.close = candle.close;
    existing.volume = (existing.volume ?? 0) + (candle.volume ?? 0);
  }

  return Array.from(buckets.values()).sort(
    (a, b) => toDate(a.timestamp).getTime() - toDate(b.timestamp).getTime(),
  );
}

export function groupCandlesBySessionMode(
  candles: OHLCBar[],
  mode: SessionMode,
): Array<{ key: string; candles: OHLCBar[]; label: string }> {
  const ordered = [...candles].sort(
    (a, b) => toDate(a.timestamp).getTime() - toDate(b.timestamp).getTime(),
  );
  const groups = new Map<string, { key: string; candles: OHLCBar[]; label: string; order: number }>();

  for (const candle of ordered) {
    const ts = toDate(candle.timestamp);
    let key = '';
    let label = '';
    let order = 0;
    if (mode === 'weekly') {
      const day = new Date(Date.UTC(ts.getUTCFullYear(), ts.getUTCMonth(), ts.getUTCDate()));
      const weekday = day.getUTCDay() || 7;
      day.setUTCDate(day.getUTCDate() + 4 - weekday);
      const yearStart = new Date(Date.UTC(day.getUTCFullYear(), 0, 1));
      const week = Math.ceil((((day.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
      key = `${day.getUTCFullYear()}-W${String(week).padStart(2, '0')}`;
      label = key;
      order = day.getTime();
    } else if (mode === 'monthly') {
      key = `${ts.getUTCFullYear()}-${String(ts.getUTCMonth() + 1).padStart(2, '0')}`;
      label = ts.toLocaleDateString('en-IN', { month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' });
      order = Date.UTC(ts.getUTCFullYear(), ts.getUTCMonth(), 1);
    } else {
      key = ts.toISOString().split('T')[0];
      label = ts.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'Asia/Kolkata' });
      order = Date.UTC(ts.getUTCFullYear(), ts.getUTCMonth(), ts.getUTCDate());
    }

    const existing = groups.get(key);
    if (!existing) {
      groups.set(key, { key, candles: [candle], label, order });
    } else {
      existing.candles.push(candle);
    }
  }

  return Array.from(groups.values())
    .sort((a, b) => a.order - b.order)
    .map(({ key, candles: rows, label }) => ({ key, candles: rows, label }));
}

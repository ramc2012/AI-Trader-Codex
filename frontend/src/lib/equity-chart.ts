import type { EquitySnapshot, PortfolioPeriod } from '@/types/api';

export type EquityChartPoint = {
  isoTime: string;
  label: string;
  value: number;
};

function formatEquityLabel(isoTime: string, period: PortfolioPeriod): string {
  const date = new Date(isoTime);
  if (Number.isNaN(date.getTime())) {
    return isoTime;
  }
  if (period === 'daily') {
    return date.toLocaleTimeString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'Asia/Kolkata',
    });
  }
  if (period === 'week' || period === 'month') {
    return date.toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'Asia/Kolkata',
    });
  }
  return date.toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    timeZone: 'Asia/Kolkata',
  });
}

export function buildEquityChartData(
  apiSnapshots: EquitySnapshot[] | undefined,
  liveSnapshots: EquitySnapshot[] | undefined,
  period: PortfolioPeriod,
): EquityChartPoint[] {
  const merged = new Map<string, number>();

  for (const snapshot of apiSnapshots ?? []) {
    if (typeof snapshot?.time !== 'string' || typeof snapshot?.value !== 'number') {
      continue;
    }
    merged.set(snapshot.time, snapshot.value);
  }

  const live = (liveSnapshots ?? []).slice().sort((a, b) => a.time.localeCompare(b.time));
  for (const snapshot of live) {
    if (typeof snapshot?.time !== 'string' || typeof snapshot?.value !== 'number') {
      continue;
    }
    merged.set(snapshot.time, snapshot.value);
  }

  return Array.from(merged.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([isoTime, value]) => ({
      isoTime,
      label: formatEquityLabel(isoTime, period),
      value,
    }));
}

export function equityChartWidth(points: number): number {
  return Math.max(720, points * 56);
}

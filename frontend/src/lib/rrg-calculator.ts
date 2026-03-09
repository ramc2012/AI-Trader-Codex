/**
 * Client-side Relative Rotation Graph calculation.
 * Computes RS-Ratio and RS-Momentum for RRG visualisation.
 */

export interface RRGPoint {
  symbol: string;
  timestamp: string;
  rsRatio: number;
  rsMomentum: number;
  quadrant: 'Leading' | 'Weakening' | 'Lagging' | 'Improving';
}

export type RRGQuadrant = RRGPoint['quadrant'];

export const QUADRANT_COLORS: Record<RRGQuadrant, string> = {
  Leading: '#22c55e',
  Weakening: '#f59e0b',
  Lagging: '#ef4444',
  Improving: '#3b82f6',
};

function emaSmooth(values: number[], period: number): number[] {
  if (!values.length || period < 1) return values;
  const k = 2 / (period + 1);
  const result = [values[0]];
  for (let i = 1; i < values.length; i++) {
    result.push(values[i] * k + result[i - 1] * (1 - k));
  }
  return result;
}

function stdDev(values: number[]): number {
  if (values.length < 2) return 0;
  const mean = values.reduce((s, v) => s + v, 0) / values.length;
  const variance = values.reduce((s, v) => s + (v - mean) ** 2, 0) / values.length;
  return Math.sqrt(variance);
}

function classifyQuadrant(ratio: number, momentum: number): RRGQuadrant {
  if (ratio >= 100 && momentum >= 100) return 'Leading';
  if (ratio >= 100 && momentum < 100) return 'Weakening';
  if (ratio < 100 && momentum < 100) return 'Lagging';
  return 'Improving';
}

/**
 * Compute RRG data for one symbol vs benchmark.
 * Both arrays should be same-length aligned close prices.
 */
export function computeRRGSeries(
  symbolCloses: number[],
  benchmarkCloses: number[],
  timestamps: string[],
  symbol: string,
  smoothing: number = 5,
  lookback: number = 14,
  tailLength: number = 8,
): RRGPoint[] {
  if (symbolCloses.length !== benchmarkCloses.length || symbolCloses.length < lookback + smoothing) {
    return [];
  }

  // RS-Line
  const rsLine = symbolCloses.map((s, i) =>
    benchmarkCloses[i] > 0 ? (s / benchmarkCloses[i]) * 100 : 100
  );

  // EMA smooth
  const rsSmoothed = emaSmooth(rsLine, smoothing);

  // Normalise to 100
  const tail = rsSmoothed.slice(-lookback);
  const mean = tail.reduce((s, v) => s + v, 0) / tail.length;
  const std = stdDev(tail) || 1;
  const rsRatio = rsSmoothed.map((v) => 100 + ((v - mean) / std) * 10);

  // RS-Momentum (rate of change)
  const rsMomentum: number[] = [100];
  for (let i = 1; i < rsRatio.length; i++) {
    const prev = rsRatio[i - 1];
    const roc = prev !== 0 ? ((rsRatio[i] - prev) / Math.abs(prev)) * 1000 : 0;
    rsMomentum.push(100 + roc);
  }

  // Return trailing points
  const start = Math.max(0, rsRatio.length - tailLength);
  const points: RRGPoint[] = [];
  for (let i = start; i < rsRatio.length; i++) {
    points.push({
      symbol,
      timestamp: timestamps[i] ?? '',
      rsRatio: Math.round(rsRatio[i] * 100) / 100,
      rsMomentum: Math.round(rsMomentum[i] * 100) / 100,
      quadrant: classifyQuadrant(rsRatio[i], rsMomentum[i]),
    });
  }

  return points;
}

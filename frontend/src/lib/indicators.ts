/**
 * Client-side technical indicator calculations.
 *
 * Lightweight implementations for chart overlays.
 * These mirror the server-side Python indicators for client rendering.
 */

export interface OHLCBar {
  timestamp: number | string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ── Moving Averages ──────────────────────────────────────────────────────

export function calculateSMA(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = [];
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push(null);
    } else {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) sum += data[j];
      result.push(sum / period);
    }
  }
  return result;
}

export function calculateEMA(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = [];
  const k = 2 / (period + 1);

  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push(null);
    } else if (i === period - 1) {
      let sum = 0;
      for (let j = 0; j < period; j++) sum += data[j];
      result.push(sum / period);
    } else {
      const prev = result[i - 1];
      if (prev !== null) {
        result.push(data[i] * k + prev * (1 - k));
      } else {
        result.push(null);
      }
    }
  }
  return result;
}

// ── RSI ──────────────────────────────────────────────────────────────────

export function calculateRSI(closes: number[], period: number = 14): (number | null)[] {
  const result: (number | null)[] = [null]; // first element has no delta
  if (closes.length < period + 1) return closes.map(() => null);

  const deltas: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    deltas.push(closes[i] - closes[i - 1]);
  }

  // Initial average gain/loss
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 0; i < period; i++) {
    if (deltas[i] > 0) avgGain += deltas[i];
    else avgLoss += Math.abs(deltas[i]);
  }
  avgGain /= period;
  avgLoss /= period;

  // Fill nulls for warmup period
  for (let i = 0; i < period - 1; i++) result.push(null);

  // First RSI value
  const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
  result.push(100 - 100 / (1 + rs));

  // Subsequent values using smoothed averages
  for (let i = period; i < deltas.length; i++) {
    const gain = deltas[i] > 0 ? deltas[i] : 0;
    const loss = deltas[i] < 0 ? Math.abs(deltas[i]) : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    const rsi = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    result.push(rsi);
  }

  return result;
}

// ── MACD ─────────────────────────────────────────────────────────────────

export interface MACDResult {
  macd: (number | null)[];
  signal: (number | null)[];
  histogram: (number | null)[];
}

export function calculateMACD(
  closes: number[],
  fastPeriod: number = 12,
  slowPeriod: number = 26,
  signalPeriod: number = 9,
): MACDResult {
  const fastEMA = calculateEMA(closes, fastPeriod);
  const slowEMA = calculateEMA(closes, slowPeriod);

  const macdLine: (number | null)[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (fastEMA[i] !== null && slowEMA[i] !== null) {
      macdLine.push(fastEMA[i]! - slowEMA[i]!);
    } else {
      macdLine.push(null);
    }
  }

  // Signal line = EMA of MACD values (skip nulls)
  const nonNullMACD = macdLine.filter((v): v is number => v !== null);
  const signalEMA = calculateEMA(nonNullMACD, signalPeriod);

  // Map signal back to full-length array
  const signal: (number | null)[] = [];
  let idx = 0;
  for (let i = 0; i < macdLine.length; i++) {
    if (macdLine[i] !== null) {
      signal.push(signalEMA[idx] ?? null);
      idx++;
    } else {
      signal.push(null);
    }
  }

  // Histogram
  const histogram: (number | null)[] = [];
  for (let i = 0; i < macdLine.length; i++) {
    if (macdLine[i] !== null && signal[i] !== null) {
      histogram.push(macdLine[i]! - signal[i]!);
    } else {
      histogram.push(null);
    }
  }

  return { macd: macdLine, signal, histogram };
}

// ── Bollinger Bands ──────────────────────────────────────────────────────

export interface BollingerBands {
  upper: (number | null)[];
  middle: (number | null)[];
  lower: (number | null)[];
}

export function calculateBollingerBands(
  closes: number[],
  period: number = 20,
  stdDev: number = 2,
): BollingerBands {
  const middle = calculateSMA(closes, period);
  const upper: (number | null)[] = [];
  const lower: (number | null)[] = [];

  for (let i = 0; i < closes.length; i++) {
    if (middle[i] === null || i < period - 1) {
      upper.push(null);
      lower.push(null);
    } else {
      let sumSq = 0;
      for (let j = i - period + 1; j <= i; j++) {
        sumSq += (closes[j] - middle[i]!) ** 2;
      }
      const std = Math.sqrt(sumSq / period);
      upper.push(middle[i]! + stdDev * std);
      lower.push(middle[i]! - stdDev * std);
    }
  }

  return { upper, middle, lower };
}

// ── ATR ──────────────────────────────────────────────────────────────────

export function calculateATR(bars: OHLCBar[], period: number = 14): (number | null)[] {
  if (bars.length < 2) return bars.map(() => null);

  const tr: number[] = [bars[0].high - bars[0].low];
  for (let i = 1; i < bars.length; i++) {
    const hl = bars[i].high - bars[i].low;
    const hc = Math.abs(bars[i].high - bars[i - 1].close);
    const lc = Math.abs(bars[i].low - bars[i - 1].close);
    tr.push(Math.max(hl, hc, lc));
  }

  const result: (number | null)[] = [];
  for (let i = 0; i < tr.length; i++) {
    if (i < period - 1) {
      result.push(null);
    } else if (i === period - 1) {
      let sum = 0;
      for (let j = 0; j < period; j++) sum += tr[j];
      result.push(sum / period);
    } else {
      const prev = result[i - 1]!;
      result.push((prev * (period - 1) + tr[i]) / period);
    }
  }

  return result;
}

// ── VWAP ─────────────────────────────────────────────────────────────────

export function calculateVWAP(bars: OHLCBar[]): number[] {
  let cumTPV = 0;
  let cumVol = 0;
  return bars.map((bar) => {
    const tp = (bar.high + bar.low + bar.close) / 3;
    cumTPV += tp * bar.volume;
    cumVol += bar.volume;
    return cumVol > 0 ? cumTPV / cumVol : tp;
  });
}

// ── Supertrend ───────────────────────────────────────────────────────────

export interface SupertrendResult {
  supertrend: (number | null)[];
  direction: (1 | -1 | null)[];  // 1 = bullish, -1 = bearish
}

export function calculateSupertrend(
  bars: OHLCBar[],
  period: number = 10,
  multiplier: number = 3,
): SupertrendResult {
  const atr = calculateATR(bars, period);
  const supertrend: (number | null)[] = [];
  const direction: (1 | -1 | null)[] = [];

  for (let i = 0; i < bars.length; i++) {
    if (atr[i] === null) {
      supertrend.push(null);
      direction.push(null);
      continue;
    }

    const hl2 = (bars[i].high + bars[i].low) / 2;
    const upperBand = hl2 + multiplier * atr[i]!;
    const lowerBand = hl2 - multiplier * atr[i]!;

    if (i === 0 || direction[i - 1] === null) {
      supertrend.push(lowerBand);
      direction.push(1);
    } else {
      const prevDir = direction[i - 1]!;
      const prevST = supertrend[i - 1]!;

      if (prevDir === 1) {
        if (bars[i].close < prevST) {
          supertrend.push(upperBand);
          direction.push(-1);
        } else {
          supertrend.push(Math.max(lowerBand, prevST));
          direction.push(1);
        }
      } else {
        if (bars[i].close > prevST) {
          supertrend.push(lowerBand);
          direction.push(1);
        } else {
          supertrend.push(Math.min(upperBand, prevST));
          direction.push(-1);
        }
      }
    }
  }

  return { supertrend, direction };
}

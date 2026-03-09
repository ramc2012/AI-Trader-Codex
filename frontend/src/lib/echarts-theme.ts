/**
 * ECharts dark theme configuration for the trading dashboard.
 * Provides consistent colours for charts across the application.
 */

export const CHART_COLORS = {
  // Candle / trend
  bullish: '#22c55e',    // green-500
  bearish: '#ef4444',    // red-500
  neutral: '#94a3b8',    // slate-400

  // Backgrounds
  bg: '#0f172a',         // slate-900
  bgCard: '#1e293b',     // slate-800
  bgTooltip: '#1e293b',

  // Text
  textPrimary: '#f1f5f9',  // slate-100
  textSecondary: '#94a3b8', // slate-400
  textMuted: '#64748b',     // slate-500

  // Grid / axis
  gridLine: '#334155',   // slate-700
  axisLine: '#475569',   // slate-600

  // Accents
  accent1: '#3b82f6',    // blue-500
  accent2: '#a855f7',    // purple-500
  accent3: '#f59e0b',    // amber-500
  accent4: '#06b6d4',    // cyan-500
  accent5: '#ec4899',    // pink-500

  // OI / volume
  ceColor: '#22c55e',
  peColor: '#ef4444',
  volumeUp: 'rgba(34,197,94,0.4)',
  volumeDown: 'rgba(239,68,68,0.4)',

  // RRG quadrants
  rrgLeading: '#22c55e',
  rrgWeakening: '#f59e0b',
  rrgLagging: '#ef4444',
  rrgImproving: '#3b82f6',
} as const;

/** Colour palette for multi-series charts (e.g. RRG symbols). */
export const SERIES_PALETTE = [
  '#3b82f6', '#22c55e', '#ef4444', '#f59e0b', '#a855f7',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#8b5cf6',
  '#14b8a6', '#e11d48', '#0ea5e9', '#65a30d', '#d946ef',
];

/** Default ECharts theme options (dark). */
export const ECHARTS_DARK_THEME = {
  backgroundColor: 'transparent',
  textStyle: {
    color: CHART_COLORS.textSecondary,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: 11,
  },
  title: {
    textStyle: { color: CHART_COLORS.textPrimary, fontSize: 14 },
    subtextStyle: { color: CHART_COLORS.textMuted },
  },
  legend: {
    textStyle: { color: CHART_COLORS.textSecondary },
  },
  tooltip: {
    backgroundColor: CHART_COLORS.bgTooltip,
    borderColor: CHART_COLORS.gridLine,
    textStyle: { color: CHART_COLORS.textPrimary, fontSize: 12 },
  },
  xAxis: {
    axisLine: { lineStyle: { color: CHART_COLORS.axisLine } },
    axisTick: { lineStyle: { color: CHART_COLORS.axisLine } },
    axisLabel: { color: CHART_COLORS.textMuted },
    splitLine: { lineStyle: { color: CHART_COLORS.gridLine, type: 'dashed' as const } },
  },
  yAxis: {
    axisLine: { lineStyle: { color: CHART_COLORS.axisLine } },
    axisTick: { lineStyle: { color: CHART_COLORS.axisLine } },
    axisLabel: { color: CHART_COLORS.textMuted },
    splitLine: { lineStyle: { color: CHART_COLORS.gridLine, type: 'dashed' as const } },
  },
  grid: {
    borderColor: CHART_COLORS.gridLine,
  },
};

/**
 * Format epoch or ISO timestamp to IST time string.
 */
export function formatTimeIST(ts: number | string): string {
  const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
  return d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false });
}

/**
 * Short time format (HH:mm) in IST.
 */
export function formatShortTimeIST(ts: number | string): string {
  const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
  return d.toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/**
 * Format date as YYYY-MM-DD.
 */
export function formatDateIST(ts: number | string): string {
  const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
  return d.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' }); // en-CA gives YYYY-MM-DD
}

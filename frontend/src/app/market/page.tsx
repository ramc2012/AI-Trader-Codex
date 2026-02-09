'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, CandlestickSeries, type IChartApi, type UTCTimestamp } from 'lightweight-charts';
import { useOHLC } from '@/hooks/use-ohlc';
import { cn } from '@/lib/utils';

const SYMBOLS = [
  'NSE:NIFTY50-INDEX',
  'NSE:NIFTYBANK-INDEX',
  'NSE:RELIANCE-EQ',
  'NSE:TCS-EQ',
  'NSE:INFY-EQ',
  'NSE:HDFCBANK-EQ',
  'NSE:ICICIBANK-EQ',
  'NSE:SBIN-EQ',
];

const TIMEFRAMES = [
  { label: '1m', value: '1m' },
  { label: '5m', value: '5m' },
  { label: '15m', value: '15m' },
  { label: '1h', value: '1h' },
  { label: '1D', value: '1D' },
];

export default function MarketPage() {
  const [symbol, setSymbol] = useState(SYMBOLS[0]);
  const [timeframe, setTimeframe] = useState('5m');
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const { data: ohlcData, isLoading, error } = useOHLC(symbol, timeframe);

  const initChart = useCallback(() => {
    if (!chartContainerRef.current) return;

    // Remove existing chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      width: chartContainerRef.current.clientWidth,
      height: 500,
      crosshair: {
        vertLine: { color: '#475569', labelBackgroundColor: '#334155' },
        horzLine: { color: '#475569', labelBackgroundColor: '#334155' },
      },
      timeScale: {
        borderColor: '#1e293b',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: '#1e293b',
      },
    });

    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderDownColor: '#ef4444',
      borderUpColor: '#10b981',
      wickDownColor: '#ef4444',
      wickUpColor: '#10b981',
    });

    if (ohlcData?.candles && ohlcData.candles.length > 0) {
      const formatted = ohlcData.candles.map((c) => ({
        time: (new Date(c.timestamp).getTime() / 1000) as UTCTimestamp,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));

      // Sort by time ascending for lightweight-charts
      formatted.sort((a, b) => (a.time as number) - (b.time as number));

      candleSeries.setData(formatted);
      chart.timeScale().fitContent();
    }

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, [ohlcData]);

  useEffect(() => {
    const cleanup = initChart();
    return () => {
      cleanup?.();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [initChart]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Market Data</h2>
        <p className="mt-1 text-sm text-slate-400">
          Live candlestick charts and market overview
        </p>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Symbol Selector */}
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-400">
            Symbol
          </label>
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
          >
            {SYMBOLS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        {/* Timeframe Selector */}
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-400">
            Timeframe
          </label>
          <div className="flex gap-1">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf.value}
                onClick={() => setTimeframe(tf.value)}
                className={cn(
                  'rounded-md px-3 py-2 text-sm font-medium transition-colors',
                  timeframe === tf.value
                    ? 'bg-emerald-500/20 text-emerald-400'
                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                )}
              >
                {tf.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Chart */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        {isLoading && (
          <div className="flex h-[500px] items-center justify-center">
            <div className="text-sm text-slate-400">Loading chart data...</div>
          </div>
        )}
        {error && (
          <div className="flex h-[500px] items-center justify-center">
            <div className="text-sm text-red-400">
              Failed to load chart data. Backend may be offline.
            </div>
          </div>
        )}
        <div
          ref={chartContainerRef}
          className={cn(isLoading || error ? 'hidden' : '')}
        />
        {!isLoading && !error && (!ohlcData?.candles || ohlcData.candles.length === 0) && (
          <div className="flex h-[500px] items-center justify-center">
            <div className="text-sm text-slate-500">
              No data available for {symbol} ({timeframe})
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

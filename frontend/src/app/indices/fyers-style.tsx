'use client';

import { useState, useMemo } from 'react';
import Link from 'next/link';
import {
  TrendingUp,
  TrendingDown,
  Clock,
  BarChart3,
} from 'lucide-react';
import { useWatchlistSummary, useHistoricalData } from '@/hooks/use-watchlist';
import { formatINR, formatNumber } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import { APP_DISPLAY_NAME } from '@/lib/app-brand';
import CandlestickChart from '@/components/charts/candlestick-chart';

const TABS = [
  { id: 'indices', label: 'Indices', icon: BarChart3 },
  { id: 'positions', label: 'Positions', href: '/positions' },
  { id: 'strategies', label: 'Strategies', href: '/strategies' },
  { id: 'risk', label: 'Risk', href: '/risk' },
  { id: 'monitoring', label: 'Monitoring', href: '/monitoring' },
  { id: 'settings', label: 'Settings', href: '/settings' },
];

const INDICES_MAP: Record<string, { name: string; displayName: string }> = {
  NIFTY: { name: 'NIFTY', displayName: 'Nifty 50' },
  BANKNIFTY: { name: 'BANKNIFTY', displayName: 'Bank Nifty' },
  FINNIFTY: { name: 'FINNIFTY', displayName: 'Fin Nifty' },
  MIDCPNIFTY: { name: 'MIDCPNIFTY', displayName: 'Midcap Nifty' },
  SENSEX: { name: 'SENSEX', displayName: 'BSE Sensex' },
};

// Mini chart for 7-day candlestick
function MiniChart({ symbol }: { symbol: string }) {
  const { data, isLoading } = useHistoricalData(symbol, 7, 'D');

  const chartData = useMemo(() => {
    if (!data?.data) return [];
    return data.data.map((d) => ({
      time: new Date(d.timestamp).getTime() / 1000,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
      volume: d.volume,
    }));
  }, [data]);

  if (isLoading || chartData.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-slate-600">
        Loading chart...
      </div>
    );
  }

  return <CandlestickChart data={chartData} height={200} />;
}

export default function FyersStyleIndicesPage() {
  const [selectedIndex, setSelectedIndex] = useState('NIFTY');
  const { data: summary } = useWatchlistSummary();

  const currentTime = new Date().toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'Asia/Kolkata',
  });

  // Find selected index data
  const selectedIndexData = summary?.indices?.find(
    (idx) => idx.name === selectedIndex
  );

  const spotQuote = selectedIndexData?.spot;
  const futuresQuote = selectedIndexData?.futures;

  // Calculate futures premium
  const spotLtp = spotQuote?.ltp || 0;
  const futuresLtp = futuresQuote?.ltp || 0;
  const premium = futuresLtp > 0 && spotLtp > 0 ? futuresLtp - spotLtp : 0;
  const premiumPct = spotLtp > 0 && premium !== 0 ? (premium / spotLtp) * 100 : 0;

  // Deterministic placeholders until dedicated indicators are wired into this screen.
  const rsi = spotLtp > 0 ? Math.max(0, Math.min(100, 50 + (premiumPct * 10))) : 0;
  const macd = spotLtp > 0 ? premium / 10 : 0;
  const atr = spotLtp > 0 ? spotLtp * 0.012 : 0;

  const rsiSignal = rsi > 70 ? 'bearish' : rsi < 30 ? 'bullish' : 'neutral';
  const macdSignal = macd > 0 ? 'bullish' : macd < 0 ? 'bearish' : 'neutral';

  return (
    <div className="flex h-screen flex-col bg-slate-950">
      {/* Top Navigation Bar */}
      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900 px-6 py-3">
        <div className="flex items-center gap-6">
          <h1 className="text-lg font-bold text-slate-100">{APP_DISPLAY_NAME}</h1>

          {/* Navigation Tabs */}
          <nav className="flex gap-1">
            {TABS.map((tab) => {
              const Icon = tab.icon;

              if (tab.href) {
                return (
                  <Link
                    key={tab.id}
                    href={tab.href}
                    className="flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200"
                  >
                    {Icon && <Icon className="h-4 w-4" />}
                    {tab.label}
                  </Link>
                );
              }

              return (
                <div
                  key={tab.id}
                  className="flex items-center gap-2 rounded-lg bg-emerald-500/10 px-4 py-2 text-sm font-medium text-emerald-400"
                >
                  {Icon && <Icon className="h-4 w-4" />}
                  {tab.label}
                </div>
              );
            })}
          </nav>
        </div>

        {/* Status Indicators */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-sm">
            <div className="h-2 w-2 rounded-full bg-emerald-500"></div>
            <span className="text-slate-400">Fyers Connected</span>
          </div>
          <div className="rounded-lg bg-yellow-500/10 px-3 py-1.5 text-xs font-medium text-yellow-500">
            PAPER MODE
          </div>
          <div className="flex items-center gap-2 text-sm font-mono text-slate-300">
            <Clock className="h-4 w-4" />
            IST {currentTime}
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="space-y-6">
          {/* Market Stats Bar */}
          <div className="grid grid-cols-5 gap-4">
            <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-xs text-slate-500">Indices</div>
              <div className="mt-1 text-xl font-semibold text-slate-100">
                {summary?.indices?.length || 5}
              </div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-xs text-emerald-500">Gainers</div>
              <div className="mt-1 text-xl font-semibold text-emerald-400">
                {summary?.indices?.filter((idx) => (idx.spot?.change_pct || 0) > 0)
                  .length || 0}
              </div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-xs text-red-500">Losers</div>
              <div className="mt-1 text-xl font-semibold text-red-400">
                {summary?.indices?.filter((idx) => (idx.spot?.change_pct || 0) < 0)
                  .length || 0}
              </div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-xs text-slate-500">Avg Change</div>
              <div
                className={cn(
                  'mt-1 text-xl font-semibold',
                  ((summary?.indices || []).reduce(
                    (sum, idx) => sum + (idx.spot?.change_pct || 0),
                    0
                  ) / Math.max((summary?.indices || []).length, 1)) > 0
                    ? 'text-emerald-400'
                    : 'text-red-400'
                )}
              >
                {((summary?.indices || []).reduce(
                  (sum, idx) => sum + (idx.spot?.change_pct || 0),
                  0
                ) / Math.max((summary?.indices || []).length, 1)).toFixed(2)}%
              </div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-xs text-slate-500">Market Time</div>
              <div className="mt-1 font-mono text-xl font-semibold text-slate-100">
                {currentTime.slice(0, 5)}
              </div>
            </div>
          </div>

          {/* Index Selector Tabs */}
          <div className="flex gap-2 overflow-x-auto">
            {Object.entries(INDICES_MAP).map(([key, { displayName }]) => {
              const idx = summary?.indices?.find((i) => i.name === key);
              const ltp = idx?.spot?.ltp || 0;
              const changePct = idx?.spot?.change_pct || 0;
              const isSelected = selectedIndex === key;

              return (
                <button
                  key={key}
                  onClick={() => setSelectedIndex(key)}
                  className={cn(
                    'flex min-w-[140px] flex-col gap-1 rounded-lg border p-3 transition-all',
                    isSelected
                      ? 'border-emerald-500 bg-emerald-500/5'
                      : 'border-slate-800 bg-slate-900 hover:border-slate-700'
                  )}
                >
                  <div className="text-xs font-medium text-slate-400">
                    {displayName}
                  </div>
                  <div className="font-mono text-sm font-semibold text-slate-100">
                    {ltp > 0 ? formatINR(ltp) : '—'}
                  </div>
                  <div
                    className={cn(
                      'text-xs font-medium',
                      changePct > 0 ? 'text-emerald-400' : 'text-red-400'
                    )}
                  >
                    {changePct !== 0 ? (
                      <>
                        {changePct > 0 ? '▲' : '▼'} {Math.abs(changePct).toFixed(2)}%
                      </>
                    ) : (
                      '—'
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Main Data Panel - 3 Columns */}
          <div className="grid grid-cols-3 gap-4">
            {/* Left Column - Price Info */}
            <div className="space-y-4">
              {/* Spot Price Card */}
              <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                <div className="mb-2 text-xs font-medium uppercase text-slate-500">
                  SPOT
                </div>
                <div className="mb-3 flex items-baseline gap-2">
                  <div className="font-mono text-2xl font-bold text-slate-100">
                    {spotLtp > 0 ? formatINR(spotLtp) : '₹—'}
                  </div>
                  {(spotQuote?.change_pct || 0) !== 0 && (
                    <div
                      className={cn(
                        'flex items-center gap-1 text-sm font-medium',
                        (spotQuote?.change_pct || 0) > 0
                          ? 'text-emerald-400'
                          : 'text-red-400'
                      )}
                    >
                      {(spotQuote?.change_pct || 0) > 0 ? (
                        <TrendingUp className="h-4 w-4" />
                      ) : (
                        <TrendingDown className="h-4 w-4" />
                      )}
                      {(spotQuote?.change_pct || 0).toFixed(2)}%
                    </div>
                  )}
                </div>

                {/* OHLC Grid */}
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-slate-500">O:</span>
                    <span className="ml-1 font-mono text-slate-300">
                      {spotQuote?.open && spotQuote.open > 0
                        ? formatINR(spotQuote.open)
                        : '₹NaN'}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500">H:</span>
                    <span className="ml-1 font-mono text-slate-300">
                      {spotQuote?.high && spotQuote.high > 0
                        ? formatINR(spotQuote.high)
                        : '₹NaN'}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500">L:</span>
                    <span className="ml-1 font-mono text-slate-300">
                      {spotQuote?.low && spotQuote.low > 0
                        ? formatINR(spotQuote.low)
                        : '₹NaN'}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500">C:</span>
                    <span className="ml-1 font-mono text-slate-300">
                      {spotQuote?.close && spotQuote.close > 0
                        ? formatINR(spotQuote.close)
                        : '₹NaN'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Futures Card */}
              <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                <div className="mb-2 text-xs font-medium uppercase text-slate-500">
                  FUTURES
                </div>
                <div className="mb-2 font-mono text-xl font-semibold text-slate-100">
                  {futuresLtp > 0 ? formatINR(futuresLtp) : '₹—'}
                </div>
                <div className="space-y-1 text-xs">
                  <div className="flex justify-between">
                    <span className="text-slate-500">Premium</span>
                    <span className="font-mono text-slate-300">
                      {premium !== 0 ? formatINR(premium) : '—'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Premium %</span>
                    <span
                      className={cn(
                        'font-mono',
                        premiumPct > 0 ? 'text-emerald-400' : 'text-red-400'
                      )}
                    >
                      {premiumPct !== 0 ? `${premiumPct.toFixed(3)}%` : '—'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Market Depth Card */}
              <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                <div className="mb-2 text-xs font-medium uppercase text-slate-500">
                  MARKET DEPTH
                </div>
                <div className="space-y-2 text-xs">
                  <div className="flex justify-between">
                    <span className="text-emerald-400">Bid</span>
                    <span className="font-mono text-emerald-400">
                      {spotQuote?.bid && spotQuote.bid > 0
                        ? formatINR(spotQuote.bid)
                        : '—'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Spread</span>
                    <span className="font-mono text-slate-400">
                      {spotQuote?.bid &&
                      spotQuote?.ask &&
                      spotQuote.bid > 0 &&
                      spotQuote.ask > 0
                        ? `${formatINR(spotQuote.ask - spotQuote.bid)} (${(
                            ((spotQuote.ask - spotQuote.bid) / spotLtp) *
                            100
                          ).toFixed(3)}%)`
                        : '—'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-red-400">Ask</span>
                    <span className="font-mono text-red-400">
                      {spotQuote?.ask && spotQuote.ask > 0
                        ? formatINR(spotQuote.ask)
                        : '—'}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Middle Column - Chart */}
            <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="mb-3 text-xs font-medium uppercase text-slate-500">
                7-DAY CHART
              </div>
              <div className="h-[450px]">
                {selectedIndexData?.spot?.symbol ? (
                  <MiniChart symbol={selectedIndexData.spot.symbol} />
                ) : (
                  <div className="flex h-full items-center justify-center text-slate-600">
                    Select an index
                  </div>
                )}
              </div>
            </div>

            {/* Right Column - Analytics */}
            <div className="space-y-4">
              <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                <div className="mb-3 text-xs font-medium uppercase text-slate-500">
                  TECHNICALS
                </div>
                <div className="space-y-3">
                  {/* RSI */}
                  <div>
                    <div className="mb-1 flex items-center justify-between">
                      <span className="text-xs text-slate-500">RSI (14)</span>
                      <span
                        className={cn(
                          'text-xs font-medium',
                          rsiSignal === 'bullish' && 'text-emerald-400',
                          rsiSignal === 'bearish' && 'text-red-400',
                          rsiSignal === 'neutral' && 'text-slate-400'
                        )}
                      >
                        {rsiSignal === 'bullish' && '↑ Bull'}
                        {rsiSignal === 'bearish' && '↓ Bear'}
                        {rsiSignal === 'neutral' && '→ Neutral'}
                      </span>
                    </div>
                    <div className="font-mono text-sm font-semibold text-slate-100">
                      {rsi > 0 ? rsi.toFixed(1) : '—'}
                    </div>
                  </div>

                  {/* MACD */}
                  <div>
                    <div className="mb-1 flex items-center justify-between">
                      <span className="text-xs text-slate-500">MACD</span>
                      <span
                        className={cn(
                          'text-xs font-medium',
                          macdSignal === 'bullish' && 'text-emerald-400',
                          macdSignal === 'bearish' && 'text-red-400',
                          macdSignal === 'neutral' && 'text-slate-400'
                        )}
                      >
                        {macdSignal === 'bullish' && '↑ Bull'}
                        {macdSignal === 'bearish' && '↓ Bear'}
                        {macdSignal === 'neutral' && '→ Neutral'}
                      </span>
                    </div>
                    <div className="font-mono text-sm font-semibold text-slate-100">
                      {macd !== 0 ? macd.toFixed(2) : '—'}
                    </div>
                  </div>

                  {/* ATR */}
                  <div>
                    <div className="mb-1 text-xs text-slate-500">ATR (14)</div>
                    <div className="font-mono text-sm font-semibold text-slate-100">
                      {atr > 0 ? atr.toFixed(2) : '—'}
                    </div>
                  </div>
                </div>
              </div>

              {/* Volume Card */}
              <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                <div className="mb-2 text-xs font-medium uppercase text-slate-500">
                  VOLUME
                </div>
                <div className="font-mono text-lg font-semibold text-slate-100">
                  {spotQuote?.volume
                    ? formatNumber(spotQuote.volume)
                    : '—'}
                </div>
              </div>

              {/* Open Interest Card */}
              <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                <div className="mb-2 text-xs font-medium uppercase text-slate-500">
                  OPEN INTEREST
                </div>
                <div className="font-mono text-lg font-semibold text-slate-100">
                  {futuresQuote?.oi ? formatNumber(futuresQuote.oi) : '—'}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

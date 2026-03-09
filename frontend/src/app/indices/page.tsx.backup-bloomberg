'use client';

import { useState, useMemo } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Activity,
  BarChart3,
  Clock,
  Volume2,
  Zap,
  AlertCircle,
} from 'lucide-react';
import { useWatchlistSummary, useHistoricalData } from '@/hooks/use-watchlist';
import { formatINR, formatNumber } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import CandlestickChart from '@/components/charts/candlestick-chart';

// Mini chart component for grid
function MiniCandlestickChart({ symbol }: { symbol: string }) {
  const { data } = useHistoricalData(symbol, 7, 'D');

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

  if (chartData.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-slate-600">
        Loading...
      </div>
    );
  }

  return <CandlestickChart data={chartData} height={120} />;
}

// Market depth indicator
function MarketDepth({ bid, ask, ltp }: { bid?: number; ask?: number; ltp: number }) {
  const spread = bid && ask ? ask - bid : 0;
  const spreadPct = bid && ask ? ((ask - bid) / ltp) * 100 : 0;

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-emerald-400">Bid</span>
        <span className="font-mono text-emerald-400">
          {bid ? formatINR(bid) : '—'}
        </span>
      </div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-500">Spread</span>
        <span className="font-mono text-slate-400">
          {spread > 0 ? `${formatINR(spread)} (${spreadPct.toFixed(3)}%)` : '—'}
        </span>
      </div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-red-400">Ask</span>
        <span className="font-mono text-red-400">
          {ask ? formatINR(ask) : '—'}
        </span>
      </div>
    </div>
  );
}

// Technical indicator card
function TechnicalCard({
  label,
  value,
  signal,
}: {
  label: string;
  value: string;
  signal?: 'bullish' | 'bearish' | 'neutral';
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="mb-1 text-xs text-slate-500">{label}</div>
      <div className="flex items-baseline gap-2">
        <div className="font-mono text-sm font-semibold text-slate-100">{value}</div>
        {signal && (
          <div
            className={cn(
              'text-xs font-medium',
              signal === 'bullish' && 'text-emerald-400',
              signal === 'bearish' && 'text-red-400',
              signal === 'neutral' && 'text-slate-400'
            )}
          >
            {signal === 'bullish' && '↑ Bull'}
            {signal === 'bearish' && '↓ Bear'}
            {signal === 'neutral' && '→ Neutral'}
          </div>
        )}
      </div>
    </div>
  );
}

// Main Bloomberg-style panel
function BloombergPanel({ index }: { index: any }) {
  const { name, display_name, spot, futures } = index;

  const spotChange = spot.change_pct ?? 0;
  const isSpotUp = spotChange >= 0;

  const spotLtp = spot.ltp || 0;
  const futuresLtp = futures.ltp || 0;
  const premium = futuresLtp > 0 && spotLtp > 0 ? futuresLtp - spotLtp : 0;
  const premiumPct = spotLtp > 0 && premium !== 0 ? (premium / spotLtp) * 100 : 0;

  // Calculate mock technical indicators (would come from backend)
  const rsi = ((spotLtp % 100) + 50).toFixed(1);
  const rsiSignal = parseFloat(rsi) > 70 ? 'bearish' : parseFloat(rsi) < 30 ? 'bullish' : 'neutral';

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
      {/* Header */}
      <div className="mb-3 flex items-start justify-between border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-lg font-bold text-slate-100">{display_name}</h3>
          <p className="text-xs text-slate-500">{spot.symbol}</p>
        </div>
        <div className="flex items-center gap-2 rounded-full bg-emerald-500/10 px-2 py-1">
          <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
          <span className="text-xs font-medium text-emerald-400">LIVE</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {/* Left: Price Info */}
        <div className="space-y-3">
          {/* Spot Price */}
          <div>
            <div className="mb-1 text-xs text-slate-500">SPOT</div>
            <div className="flex items-baseline gap-2">
              <div className="text-2xl font-bold text-slate-100">
                {formatINR(spotLtp)}
              </div>
              <div
                className={cn(
                  'flex items-center gap-1 text-sm font-semibold',
                  isSpotUp ? 'text-emerald-400' : 'text-red-400'
                )}
              >
                {isSpotUp ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
                {isSpotUp ? '+' : ''}
                {spotChange.toFixed(2)}%
              </div>
            </div>
            <div className="mt-1 grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-slate-500">O:</span>{' '}
                <span className="font-mono text-slate-300">{formatINR(spot.open)}</span>
              </div>
              <div>
                <span className="text-slate-500">H:</span>{' '}
                <span className="font-mono text-slate-300">{formatINR(spot.high)}</span>
              </div>
              <div>
                <span className="text-slate-500">L:</span>{' '}
                <span className="font-mono text-slate-300">{formatINR(spot.low)}</span>
              </div>
              <div>
                <span className="text-slate-500">C:</span>{' '}
                <span className="font-mono text-slate-300">{formatINR(spot.close)}</span>
              </div>
            </div>
          </div>

          {/* Futures */}
          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-2">
            <div className="mb-1 text-xs text-slate-500">FUTURES</div>
            <div className="text-lg font-bold text-slate-100">
              {futuresLtp > 0 ? formatINR(futuresLtp) : '—'}
            </div>
            {futuresLtp > 0 && spotLtp > 0 && (
              <div className="mt-1 text-xs">
                <span className="text-slate-500">Premium:</span>{' '}
                <span
                  className={cn(
                    'font-mono font-medium',
                    premium >= 0 ? 'text-emerald-400' : 'text-red-400'
                  )}
                >
                  {premium >= 0 ? '+' : ''}
                  {formatINR(Math.abs(premium))} ({premium >= 0 ? '+' : ''}
                  {Math.abs(premiumPct).toFixed(2)}%)
                </span>
              </div>
            )}
          </div>

          {/* Market Depth */}
          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-2">
            <div className="mb-2 text-xs font-medium text-slate-400">MARKET DEPTH</div>
            <MarketDepth bid={spot.bid} ask={spot.ask} ltp={spotLtp} />
          </div>
        </div>

        {/* Middle: Mini Chart */}
        <div className="flex flex-col">
          <div className="mb-2 text-xs font-medium text-slate-400">7-DAY CHART</div>
          <div className="flex-1 rounded-lg border border-slate-800 bg-slate-900 p-2">
            <MiniCandlestickChart symbol={spot.symbol} />
          </div>
        </div>

        {/* Right: Technical Indicators & Volume */}
        <div className="space-y-2">
          <div className="mb-2 text-xs font-medium text-slate-400">TECHNICALS</div>
          <TechnicalCard label="RSI (14)" value={rsi} signal={rsiSignal} />
          <TechnicalCard
            label="MACD"
            value={isSpotUp ? '+12.5' : '-8.3'}
            signal={isSpotUp ? 'bullish' : 'bearish'}
          />
          <TechnicalCard label="ATR (14)" value={(spotLtp * 0.012).toFixed(2)} />

          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-2">
            <div className="mb-1 flex items-center gap-1 text-xs text-slate-500">
              <Volume2 className="h-3 w-3" />
              VOLUME
            </div>
            <div className="font-mono text-sm font-semibold text-slate-100">
              {spot.volume ? formatNumber(spot.volume) : '—'}
            </div>
          </div>

          {futures.oi && (
            <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-2">
              <div className="mb-1 flex items-center gap-1 text-xs text-slate-500">
                <Activity className="h-3 w-3" />
                OPEN INTEREST
              </div>
              <div className="font-mono text-sm font-semibold text-slate-100">
                {formatNumber(futures.oi)}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function BloombergIndicesPage() {
  const { data: summary, isLoading, error } = useWatchlistSummary();
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Market stats
  const totalIndices = summary?.indices.length ?? 0;
  const gainers = summary?.indices.filter((i) => (i.spot.change_pct ?? 0) > 0).length ?? 0;
  const losers = summary?.indices.filter((i) => (i.spot.change_pct ?? 0) < 0).length ?? 0;
  const avgChange =
    (summary?.indices.reduce((sum, i) => sum + (i.spot.change_pct ?? 0), 0) ?? 0) /
    (totalIndices || 1);

  if (error) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center">
        <AlertCircle className="mb-4 h-16 w-16 text-red-500" />
        <h3 className="text-xl font-bold text-slate-100">Data Unavailable</h3>
        <p className="mt-2 text-sm text-slate-400">
          Please check your Fyers connection in Settings.
        </p>
      </div>
    );
  }

  if (isLoading || !summary) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-center">
          <Zap className="mx-auto mb-4 h-12 w-12 animate-pulse text-emerald-500" />
          <div className="text-lg font-semibold text-slate-100">Loading Market Data...</div>
        </div>
      </div>
    );
  }

  const currentIndex = summary.indices[selectedIndex];

  return (
    <div className="space-y-4">
      {/* Top Bar - Market Overview */}
      <div className="grid grid-cols-5 gap-3">
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
          <div className="mb-1 flex items-center gap-1 text-xs text-slate-500">
            <Clock className="h-3 w-3" />
            Market Time
          </div>
          <div className="font-mono text-sm font-semibold text-slate-100">
            {new Date().toLocaleTimeString('en-IN', {
              hour: '2-digit',
              minute: '2-digit',
              timeZone: 'Asia/Kolkata',
            })}
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
          <div className="mb-1 text-xs text-slate-500">Indices</div>
          <div className="text-lg font-bold text-slate-100">{totalIndices}</div>
        </div>

        <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
          <div className="mb-1 text-xs text-emerald-400">Gainers</div>
          <div className="text-lg font-bold text-emerald-400">{gainers}</div>
        </div>

        <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-3">
          <div className="mb-1 text-xs text-red-400">Losers</div>
          <div className="text-lg font-bold text-red-400">{losers}</div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
          <div className="mb-1 text-xs text-slate-500">Avg Change</div>
          <div
            className={cn(
              'text-lg font-bold',
              avgChange >= 0 ? 'text-emerald-400' : 'text-red-400'
            )}
          >
            {avgChange >= 0 ? '+' : ''}
            {avgChange.toFixed(2)}%
          </div>
        </div>
      </div>

      {/* Index Selector Tabs */}
      <div className="flex gap-2 overflow-x-auto rounded-lg border border-slate-800 bg-slate-900 p-2">
        {summary.indices.map((index, idx) => {
          const change = index.spot.change_pct ?? 0;
          const isUp = change >= 0;

          return (
            <button
              key={index.name}
              onClick={() => setSelectedIndex(idx)}
              className={cn(
                'flex min-w-[140px] flex-col items-start gap-1 rounded-lg px-3 py-2 transition-all',
                selectedIndex === idx
                  ? 'bg-emerald-600 text-white shadow-lg'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
              )}
            >
              <div className="text-xs font-semibold">{index.display_name}</div>
              <div className="flex items-baseline gap-1">
                <div className="font-mono text-sm">{formatINR(index.spot.ltp)}</div>
                <div
                  className={cn(
                    'text-xs font-medium',
                    selectedIndex === idx
                      ? 'text-white'
                      : isUp
                      ? 'text-emerald-400'
                      : 'text-red-400'
                  )}
                >
                  {isUp ? '+' : ''}
                  {change.toFixed(2)}%
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Main Bloomberg Panel */}
      {currentIndex && <BloombergPanel index={currentIndex} />}

      {/* Bottom: All Indices Grid */}
      <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
        <div className="mb-3 text-sm font-semibold text-slate-400">ALL INDICES</div>
        <div className="grid grid-cols-5 gap-3">
          {summary.indices.map((index) => {
            const change = index.spot.change_pct ?? 0;
            const isUp = change >= 0;

            return (
              <button
                key={index.name}
                onClick={() =>
                  setSelectedIndex(summary.indices.findIndex((i) => i.name === index.name))
                }
                className="rounded-lg border border-slate-800 bg-slate-900 p-3 text-left transition-all hover:border-emerald-500 hover:shadow-lg"
              >
                <div className="mb-1 text-xs text-slate-500">{index.display_name}</div>
                <div className="mb-1 font-mono text-lg font-bold text-slate-100">
                  {formatINR(index.spot.ltp)}
                </div>
                <div
                  className={cn(
                    'flex items-center gap-1 text-xs font-semibold',
                    isUp ? 'text-emerald-400' : 'text-red-400'
                  )}
                >
                  {isUp ? '▲' : '▼'}
                  {isUp ? '+' : ''}
                  {change.toFixed(2)}%
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

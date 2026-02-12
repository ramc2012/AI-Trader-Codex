'use client';

import { useState } from 'react';
import {
  List,
  Download,
  Loader2,
  TrendingUp,
  TrendingDown,
  BarChart3,
  ExternalLink,
  AlertTriangle,
  Database,
} from 'lucide-react';
import Link from 'next/link';
import { AreaChart, Area, ResponsiveContainer } from 'recharts';
import { useWatchlistSymbols, useCollectionStatus, useStartCollection } from '@/hooks/use-watchlist';
import { useAuth } from '@/contexts/auth-context';
import { formatINR, formatNumber, formatDate } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import { Skeleton } from '@/components/ui/skeleton';
import { useOHLC } from '@/hooks/use-ohlc';

const TIMEFRAME_OPTIONS = ['1', '5', '15', '60', 'D', 'W'];
const TIMEFRAME_LABELS: Record<string, string> = {
  '1': '1m',
  '3': '3m',
  '5': '5m',
  '15': '15m',
  '30': '30m',
  '60': '1h',
  D: '1D',
  W: '1W',
  M: '1M',
};

function MiniChart({ symbol }: { symbol: string }) {
  const { data } = useOHLC(symbol, 'D');
  const candles = data?.candles ?? [];
  const chartData = candles.slice(-30).map((c) => ({
    close: c.close,
  }));

  if (chartData.length < 2) {
    return (
      <div className="flex h-16 items-center justify-center text-xs text-slate-600">
        No chart data
      </div>
    );
  }

  const isPositive = chartData[chartData.length - 1].close >= chartData[0].close;
  const color = isPositive ? '#10b981' : '#ef4444';

  return (
    <div className="h-16 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id={`gradient-${symbol}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.3} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="close"
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#gradient-${symbol})`}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function SymbolCard({
  symbol,
  displayName,
  latestPrice,
  priceChangePct,
  dataSummary,
  onCollect,
  isCollecting,
}: {
  symbol: string;
  displayName: string;
  latestPrice: number | null;
  priceChangePct: number | null;
  dataSummary: { timeframe: string; count: number; latest_timestamp: string | null }[];
  onCollect: (timeframe: string) => void;
  isCollecting: boolean;
}) {
  const isPriceUp = (priceChangePct ?? 0) >= 0;
  const TrendIcon = isPriceUp ? TrendingUp : TrendingDown;
  const totalCandles = dataSummary.reduce((sum, d) => sum + d.count, 0);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 transition-all hover:border-slate-700">
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-base font-semibold text-slate-100">
            {displayName}
          </h3>
          <p className="text-xs text-slate-500 font-mono">{symbol}</p>
        </div>
        <Link
          href={`/market?symbol=${encodeURIComponent(symbol)}`}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200"
        >
          <ExternalLink className="h-3 w-3" />
          Chart
        </Link>
      </div>

      {/* Price */}
      <div className="flex items-baseline gap-2 mb-3">
        {latestPrice != null ? (
          <>
            <span className="text-xl font-bold text-slate-100">
              {formatINR(latestPrice)}
            </span>
            {priceChangePct != null && (
              <span
                className={cn(
                  'flex items-center gap-1 text-sm font-medium',
                  isPriceUp ? 'text-emerald-400' : 'text-red-400'
                )}
              >
                <TrendIcon className="h-3.5 w-3.5" />
                {isPriceUp ? '+' : ''}
                {priceChangePct.toFixed(2)}%
              </span>
            )}
          </>
        ) : (
          <span className="text-sm text-slate-500">No price data</span>
        )}
      </div>

      {/* Mini Chart */}
      <MiniChart symbol={symbol} />

      {/* Data Summary */}
      <div className="mt-3 border-t border-slate-800 pt-3">
        <div className="flex items-center gap-2 mb-2">
          <Database className="h-3.5 w-3.5 text-slate-500" />
          <span className="text-xs font-medium text-slate-400">
            Collected Data ({formatNumber(totalCandles)} candles)
          </span>
        </div>
        <div className="space-y-1">
          {dataSummary
            .filter((d) => d.count > 0 || ['D', '5', '15', '60'].includes(d.timeframe))
            .slice(0, 6)
            .map((d) => (
              <div
                key={d.timeframe}
                className="flex items-center justify-between text-xs"
              >
                <span className="text-slate-500 w-8">
                  {TIMEFRAME_LABELS[d.timeframe] ?? d.timeframe}
                </span>
                <span className="text-slate-400">
                  {d.count > 0
                    ? `${formatNumber(d.count)} candles`
                    : 'No data'}
                </span>
                <span className="text-slate-600 text-[11px]">
                  {d.latest_timestamp
                    ? formatDate(d.latest_timestamp)
                    : '-'}
                </span>
                <button
                  onClick={() => onCollect(d.timeframe)}
                  disabled={isCollecting}
                  className="rounded px-1.5 py-0.5 text-[10px] font-medium text-emerald-500 transition-colors hover:bg-emerald-500/10 disabled:opacity-30"
                >
                  {isCollecting ? '...' : 'Collect'}
                </button>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}

export default function WatchlistPage() {
  const { isAuthenticated } = useAuth();
  const { data: symbols, isLoading } = useWatchlistSymbols();
  const { data: collectionStatuses } = useCollectionStatus();
  const startCollection = useStartCollection();

  const [selectedSymbol, setSelectedSymbol] = useState('NSE:NIFTY50-INDEX');
  const [selectedTimeframe, setSelectedTimeframe] = useState('D');
  const [daysBack, setDaysBack] = useState(90);

  const activeCollection = collectionStatuses?.find(
    (s) => s.status === 'collecting'
  );

  const handleCollect = (symbol: string, timeframe: string) => {
    if (!isAuthenticated) return;
    startCollection.mutate({
      symbol,
      timeframe,
      days_back: daysBack,
    });
  };

  const handleBulkCollect = () => {
    if (!isAuthenticated) return;
    startCollection.mutate({
      symbol: selectedSymbol,
      timeframe: selectedTimeframe,
      days_back: daysBack,
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Watchlist</h2>
        <p className="mt-1 text-sm text-slate-400">
          Collected market data overview and data collection controls
        </p>
      </div>

      {/* Collection Controls */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="flex items-center gap-3 mb-4">
          <Download className="h-5 w-5 text-slate-400" />
          <h3 className="text-sm font-medium text-slate-300">
            Data Collection
          </h3>
        </div>

        {!isAuthenticated && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-3">
            <AlertTriangle className="h-4 w-4 shrink-0 text-yellow-400" />
            <span className="text-xs text-yellow-400">
              Connect to Fyers in{' '}
              <Link href="/settings" className="underline hover:text-yellow-300">
                Settings
              </Link>{' '}
              to collect market data
            </span>
          </div>
        )}

        <div className="flex flex-wrap items-end gap-4">
          {/* Symbol selector */}
          <div>
            <label className="mb-1 block text-xs text-slate-500">Symbol</label>
            <select
              value={selectedSymbol}
              onChange={(e) => setSelectedSymbol(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 focus:border-emerald-500 focus:outline-none"
            >
              {(symbols ?? []).map((s) => (
                <option key={s.symbol} value={s.symbol}>
                  {s.display_name}
                </option>
              ))}
              {!symbols?.length && (
                <>
                  <option value="NSE:NIFTY50-INDEX">Nifty 50</option>
                  <option value="NSE:NIFTYBANK-INDEX">Bank Nifty</option>
                  <option value="BSE:SENSEX-INDEX">Sensex</option>
                </>
              )}
            </select>
          </div>

          {/* Timeframe buttons */}
          <div>
            <label className="mb-1 block text-xs text-slate-500">
              Timeframe
            </label>
            <div className="flex gap-1">
              {TIMEFRAME_OPTIONS.map((tf) => (
                <button
                  key={tf}
                  onClick={() => setSelectedTimeframe(tf)}
                  className={cn(
                    'rounded-md px-3 py-2 text-xs font-medium transition-colors',
                    selectedTimeframe === tf
                      ? 'bg-emerald-600 text-white'
                      : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                  )}
                >
                  {TIMEFRAME_LABELS[tf]}
                </button>
              ))}
            </div>
          </div>

          {/* Days back */}
          <div>
            <label className="mb-1 block text-xs text-slate-500">
              Days Back
            </label>
            <input
              type="number"
              value={daysBack}
              onChange={(e) => setDaysBack(Math.max(1, Math.min(730, parseInt(e.target.value) || 90)))}
              min={1}
              max={730}
              className="w-24 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 focus:border-emerald-500 focus:outline-none"
            />
          </div>

          {/* Collect button */}
          <button
            onClick={handleBulkCollect}
            disabled={!isAuthenticated || startCollection.isPending}
            className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
          >
            {startCollection.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            Collect Data
          </button>
        </div>

        {/* Active collection progress */}
        {activeCollection && (
          <div className="mt-4 rounded-lg border border-slate-700 bg-slate-800/50 p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-slate-400">
                Collecting {activeCollection.symbol} ({TIMEFRAME_LABELS[activeCollection.timeframe]})
              </span>
              <span className="text-xs text-emerald-400">
                {activeCollection.progress.toFixed(0)}%
              </span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-slate-700">
              <div
                className="h-1.5 rounded-full bg-emerald-500 transition-all duration-500"
                style={{ width: `${activeCollection.progress}%` }}
              />
            </div>
            <p className="mt-1 text-xs text-slate-500">
              {formatNumber(activeCollection.candles_collected)} candles collected
            </p>
          </div>
        )}

        {/* Collection errors */}
        {collectionStatuses
          ?.filter((s) => s.status === 'failed')
          .map((s) => (
            <div
              key={`${s.symbol}:${s.timeframe}`}
              className="mt-2 rounded-lg border border-red-500/20 bg-red-500/5 p-2 text-xs text-red-400"
            >
              Failed: {s.symbol} ({TIMEFRAME_LABELS[s.timeframe]}){' '}
              {s.error && `- ${s.error}`}
            </div>
          ))}
      </div>

      {/* Symbol Cards Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="rounded-xl border border-slate-800 bg-slate-900 p-5"
            >
              <Skeleton className="h-6 w-32 mb-2" />
              <Skeleton className="h-4 w-48 mb-4" />
              <Skeleton className="h-8 w-24 mb-3" />
              <Skeleton className="h-16 w-full mb-3" />
              <Skeleton className="h-20 w-full" />
            </div>
          ))}
        </div>
      ) : symbols && symbols.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {symbols.map((s) => (
            <SymbolCard
              key={s.symbol}
              symbol={s.symbol}
              displayName={s.display_name}
              latestPrice={s.latest_price}
              priceChangePct={s.price_change_pct}
              dataSummary={s.data_summary}
              onCollect={(tf) => handleCollect(s.symbol, tf)}
              isCollecting={startCollection.isPending}
            />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-xl border border-slate-800 bg-slate-900 p-12">
          <BarChart3 className="h-12 w-12 text-slate-700 mb-4" />
          <h3 className="text-lg font-medium text-slate-400">
            No Data Collected Yet
          </h3>
          <p className="mt-2 text-sm text-slate-500 text-center max-w-md">
            Connect to Fyers and use the collection controls above to start
            downloading historical market data for analysis and backtesting.
          </p>
        </div>
      )}
    </div>
  );
}

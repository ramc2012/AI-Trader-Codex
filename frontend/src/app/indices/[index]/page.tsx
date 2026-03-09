'use client';

import { use, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowLeft,
  TrendingUp,
  TrendingDown,
  Activity,
  BarChart3,
  Loader2,
  ChevronDown,
  DollarSign,
  Percent,
  Shield,
} from 'lucide-react';
import Link from 'next/link';
import {
  useIndexQuote,
  useHistoricalData,
  useOptionChain,
} from '@/hooks/use-watchlist';
import { useAgentEvents } from '@/hooks/use-agent';
import { formatINR, formatNumber } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import { Skeleton } from '@/components/ui/skeleton';
import CandlestickChart from '@/components/charts/candlestick-chart';
import { buildTradeMarkersFromEvents } from '@/lib/trade-markers';

interface PageProps {
  params: Promise<{ index: string }>;
}

// Index symbol mapping
const INDEX_SYMBOLS: Record<string, { spot: string; futures: string; display: string }> = {
  nifty: {
    spot: 'NSE:NIFTY50-INDEX',
    futures: 'NSE:NIFTY25FEBFUT',
    display: 'Nifty 50',
  },
  banknifty: {
    spot: 'NSE:NIFTYBANK-INDEX',
    futures: 'NSE:BANKNIFTY25FEBFUT',
    display: 'Bank Nifty',
  },
  finnifty: {
    spot: 'NSE:FINNIFTY-INDEX',
    futures: 'NSE:FINNIFTY25FEBFUT',
    display: 'Fin Nifty',
  },
  midcpnifty: {
    spot: 'NSE:NIFTYMIDCAP-INDEX',
    futures: 'NSE:MIDCPNIFTY25FEBFUT',
    display: 'Midcap Nifty',
  },
  sensex: {
    spot: 'BSE:SENSEX-INDEX',
    futures: 'BSE:SENSEX25FEBFUT',
    display: 'BSE Sensex',
  },
};

function QuoteCard({ label, value, change }: { label: string; value: string; change?: number }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="mb-1 text-xs text-slate-500">{label}</div>
      <div className="flex items-baseline gap-2">
        <div className="text-lg font-bold text-slate-100">{value}</div>
        {change !== undefined && (
          <div
            className={cn(
              'text-xs font-medium',
              change >= 0 ? 'text-emerald-400' : 'text-red-400'
            )}
          >
            {change >= 0 ? '+' : ''}
            {change.toFixed(2)}%
          </div>
        )}
      </div>
    </div>
  );
}

function GreeksCard({ title, value, icon: Icon }: { title: string; value: string; icon: any }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="rounded-lg bg-slate-800 p-2">
        <Icon className="h-4 w-4 text-slate-400" />
      </div>
      <div>
        <div className="text-xs text-slate-500">{title}</div>
        <div className="font-mono text-sm font-semibold text-slate-100">{value}</div>
      </div>
    </div>
  );
}

export default function IndexDetailPage({ params }: PageProps) {
  const { index: indexParam } = use(params);
  const indexKey = indexParam.toLowerCase();
  const router = useRouter();

  const [timeframe, setTimeframe] = useState<'1' | '5' | '15' | '60' | 'D'>('D');
  const [days, setDays] = useState(30);

  // Get symbols for this index
  const symbols = INDEX_SYMBOLS[indexKey];
  if (!symbols) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-slate-100">Index Not Found</h2>
          <p className="mt-2 text-slate-400">
            The index "{indexParam}" is not available.
          </p>
          <Link
            href="/indices"
            className="mt-4 inline-flex items-center gap-2 text-emerald-400 hover:text-emerald-300"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Indices
          </Link>
        </div>
      </div>
    );
  }

  // Fetch data
  const { data: spotQuote, isLoading: spotLoading } = useIndexQuote(symbols.spot);
  const { data: futuresQuote, isLoading: futuresLoading } = useIndexQuote(symbols.futures);
  const {
    data: historicalData,
    isLoading: historicalLoading,
  } = useHistoricalData(symbols.spot, days, timeframe);
  const { data: optionChain, isLoading: chainLoading } = useOptionChain(
    indexKey.toUpperCase()
  );
  const { data: agentEvents } = useAgentEvents(300, 3000);

  const isLoading = spotLoading || futuresLoading || historicalLoading;

  // Calculate metrics
  const premium = futuresQuote && spotQuote ? futuresQuote.ltp - spotQuote.ltp : 0;
  const premiumPct = spotQuote ? (premium / spotQuote.ltp) * 100 : 0;
  const spotChange = spotQuote?.change_pct ?? 0;
  const isSpotUp = spotChange >= 0;

  // Prepare chart data
  const chartData = historicalData?.data.map((d) => ({
    time: new Date(d.timestamp).getTime() / 1000,
    open: d.open,
    high: d.high,
    low: d.low,
    close: d.close,
    volume: d.volume,
  })) ?? [];
  const tradeMarkers = useMemo(() => {
    if (!chartData.length) return [];
    return buildTradeMarkersFromEvents(
      agentEvents ?? [],
      symbols.spot,
      timeframe,
      chartData[0].time,
      chartData[chartData.length - 1].time,
    );
  }, [agentEvents, chartData, symbols.spot, timeframe]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            href="/indices"
            className="rounded-lg border border-slate-800 p-2 transition-colors hover:border-slate-700"
          >
            <ArrowLeft className="h-5 w-5 text-slate-400" />
          </Link>
          <div>
            <h2 className="text-2xl font-bold text-slate-100">{symbols.display}</h2>
            <p className="mt-0.5 text-sm text-slate-500">
              Spot: {symbols.spot} • Futures: {symbols.futures}
            </p>
          </div>
        </div>

        {/* Real-time indicator */}
        <div className="flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5">
          <div className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
          <span className="text-xs font-medium text-emerald-400">Live</span>
        </div>
      </div>

      {/* Current Price & Stats */}
      {isLoading ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <Skeleton className="mb-4 h-10 w-48" />
          <Skeleton className="h-6 w-32" />
        </div>
      ) : spotQuote ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          {/* Main Price */}
          <div className="mb-6 flex items-baseline gap-4">
            <div className="text-4xl font-bold text-slate-100">
              {formatINR(spotQuote.ltp)}
            </div>
            <div
              className={cn(
                'flex items-center gap-2 text-xl font-semibold',
                isSpotUp ? 'text-emerald-400' : 'text-red-400'
              )}
            >
              {isSpotUp ? (
                <TrendingUp className="h-6 w-6" />
              ) : (
                <TrendingDown className="h-6 w-6" />
              )}
              {isSpotUp ? '+' : ''}
              {spotChange.toFixed(2)}%
              {spotQuote.change && (
                <span className="text-base">
                  ({isSpotUp ? '+' : ''}
                  {formatINR(spotQuote.change)})
                </span>
              )}
            </div>
          </div>

          {/* OHLC Grid */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <QuoteCard label="Open" value={formatINR(spotQuote.open)} />
            <QuoteCard label="High" value={formatINR(spotQuote.high)} />
            <QuoteCard label="Low" value={formatINR(spotQuote.low)} />
            <QuoteCard label="Close" value={formatINR(spotQuote.close)} />
          </div>
        </div>
      ) : null}

      {/* Futures & Volume */}
      {futuresQuote && spotQuote && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
            <div className="mb-3 flex items-center gap-2 text-sm text-slate-500">
              <Activity className="h-4 w-4" />
              Futures Price
            </div>
            <div className="text-2xl font-bold text-slate-100">
              {formatINR(futuresQuote.ltp)}
            </div>
            <div className="mt-2 text-xs text-slate-400">
              Premium:{' '}
              <span
                className={cn(
                  'font-semibold',
                  premium >= 0 ? 'text-emerald-400' : 'text-red-400'
                )}
              >
                {premium >= 0 ? '+' : ''}
                {formatINR(premium)} ({premium >= 0 ? '+' : ''}
                {premiumPct.toFixed(2)}%)
              </span>
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
            <div className="mb-3 flex items-center gap-2 text-sm text-slate-500">
              <BarChart3 className="h-4 w-4" />
              Open Interest
            </div>
            <div className="text-2xl font-bold text-slate-100">
              {formatNumber(futuresQuote.oi || 0)}
            </div>
            <div className="mt-2 text-xs text-slate-400">Futures Contracts</div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
            <div className="mb-3 flex items-center gap-2 text-sm text-slate-500">
              <BarChart3 className="h-4 w-4" />
              Volume
            </div>
            <div className="text-2xl font-bold text-slate-100">
              {formatNumber(spotQuote.volume)}
            </div>
            <div className="mt-2 text-xs text-slate-400">Spot Volume</div>
          </div>
        </div>
      )}

      {/* Chart */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-slate-100">Price Chart</h3>

          {/* Timeframe selector */}
          <div className="flex gap-1">
            {(['1', '5', '15', '60', 'D'] as const).map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={cn(
                  'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                  timeframe === tf
                    ? 'bg-emerald-600 text-white'
                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                )}
              >
                {tf === 'D' ? '1D' : tf === '60' ? '1H' : `${tf}m`}
              </button>
            ))}
          </div>
        </div>

        {historicalLoading ? (
          <div className="flex h-[500px] items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-slate-600" />
          </div>
        ) : chartData.length > 0 ? (
          <CandlestickChart data={chartData} height={500} tradeMarkers={tradeMarkers} />
        ) : (
          <div className="flex h-[500px] items-center justify-center text-slate-500">
            No chart data available
          </div>
        )}
      </div>

      {/* Options Chain Summary */}
      {!chainLoading && optionChain?.data.expiryData && optionChain.data.expiryData.length > 0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h3 className="mb-4 text-lg font-semibold text-slate-100">Options Chain</h3>
          <div className="text-sm text-slate-400">
            {optionChain.data.expiryData.length} expiries available
          </div>
          <Link
            href={`/indices/${indexKey}/options`}
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500"
          >
            View Full Options Chain
            <ChevronDown className="h-4 w-4 rotate-[-90deg]" />
          </Link>
        </div>
      )}

      {/* Last Updated */}
      {spotQuote?.timestamp && (
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-3 text-center">
          <p className="text-xs text-slate-500">
            Last updated:{' '}
            <span className="font-mono text-slate-400">
              {new Date(spotQuote.timestamp).toLocaleString()}
            </span>
          </p>
        </div>
      )}
    </div>
  );
}

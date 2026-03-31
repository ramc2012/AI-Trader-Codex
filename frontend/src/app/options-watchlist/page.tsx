'use client';

import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { 
  List, 
  Search, 
  TrendingUp, 
  TrendingDown, 
  Activity, 
  RefreshCw,
  ArrowUpRight,
  ArrowDownRight,
  Filter
} from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { cn } from '@/lib/utils';
import { formatCurrency, formatNumber } from '@/lib/formatters';
import { Skeleton } from '@/components/ui/skeleton';
import { useTickStream } from '@/hooks/use-tick-stream';

interface ATMOptionMetric {
  symbol: string;
  underlying: string;
  option_type: 'CE' | 'PE';
  strike: number;
  expiry: string;
  market: string;
  ltp?: number;
  oi?: number;
  macd?: number;
  rsi?: number;
}

interface ATMWatchlistResponse {
  timestamp: string;
  results: ATMOptionMetric[];
  is_warmed: boolean;
  is_market_open: boolean;
  is_holiday: boolean;
}

export default function OptionsWatchlistPage() {
  const [search, setSearch] = useState('');
  const [market, setMarket] = useState<'NSE' | 'US' | 'CRYPTO'>('NSE');
  const [typeFilter, setTypeFilter] = useState<'ALL' | 'CE' | 'PE'>('ALL');

  // 1. Fetch the ATM structure (symbols/strikes) for the selected market
  const { data, isLoading, refetch, isFetching } = useQuery<ATMWatchlistResponse>({
    queryKey: ['options-watchlist-atm', market],
    queryFn: () => apiFetch<ATMWatchlistResponse>(`/options-watchlist/atm?market=${market}&limit=209`),
    refetchInterval: 60000, 
    staleTime: 30000,
  });

  // 2. Subscribe to the real-time tick stream for these symbols
  const { ticks, isConnected } = useTickStream();

  // 3. Merge baseline data with live ticks
  const mergedResults = useMemo(() => {
    if (!data?.results) return [];
    
    return data.results.map(item => {
      const liveTick = ticks[item.symbol];
      return {
        ...item,
        ltp: liveTick?.ltp ?? item.ltp ?? 0,
        oi: liveTick?.oi ?? item.oi ?? 0,
        macd: item.macd ?? 0,
        rsi: item.rsi ?? 0,
      };
    });
  }, [data, ticks]);

  const filteredResults = useMemo(() => {
    return mergedResults.filter(item => {
      const matchesSearch = item.underlying.toLowerCase().includes(search.toLowerCase());
      const matchesType = typeFilter === 'ALL' || item.option_type === typeFilter;
      return matchesSearch && matchesType;
    });
  }, [mergedResults, search, typeFilter]);

  const isMarketInactive = data && !data.is_market_open;

  return (
    <div className="space-y-6">
      {isMarketInactive && (
        <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-4 backdrop-blur-sm">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 rounded-full bg-amber-500/10 p-1.5 ring-1 ring-amber-500/20">
              <RefreshCw className="h-4 w-4 text-amber-500 animate-spin-slow" />
            </div>
            <div className="space-y-1">
              <h3 className="text-sm font-bold text-amber-500 flex items-center gap-2">
                Market Closed {data?.is_holiday ? '(Trading Holiday)' : '(After Hours)'}
              </h3>
              <p className="text-xs leading-relaxed text-slate-400">
                The NSE is currently closed. Live price updates (LTP) and Open Interest (OI) are 
                unavailable until the next trading session. Existing ATM resolution is based on 
                the last known spot prices.
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
            <List className="h-6 w-6 text-emerald-400" />
            ATM Options Watchlist
          </h1>
          <div className="flex items-center gap-3">
            <p className="text-sm text-slate-500">
              Real-time ATM strikes for all 209 FNO instruments
            </p>
            {data && !data.is_warmed && (
              <span className="animate-pulse rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-500">
                Warming cache... ({Math.floor(data.results.length / 2)} / 209)
              </span>
            )}
            <div className="flex items-center gap-1.5 ml-1">
              <div className={cn("h-1.5 w-1.5 rounded-full", isConnected ? "bg-emerald-500 animate-pulse" : "bg-slate-600")} />
              <span className="text-[10px] font-medium uppercase tracking-wider text-slate-500">
                {isConnected ? 'Tick Feed' : 'Disconnected'}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900/50 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', (isFetching || (data && !data.is_warmed)) && 'animate-spin')} />
            {data && !data.is_warmed ? 'Syncing...' : 'Refresh'}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4 bg-slate-900/40 p-4 rounded-2xl border border-slate-800">
        <div className="flex items-center gap-1 p-1 rounded-xl bg-slate-950/50 border border-slate-700">
          {(['NSE', 'US', 'CRYPTO'] as const).map(m => (
            <button
              key={m}
              onClick={() => setMarket(m)}
              className={cn(
                "px-5 py-2 rounded-lg text-xs font-bold transition-all flex items-center gap-2",
                market === m 
                  ? m === 'NSE' ? "bg-emerald-500/20 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.2)]"
                    : m === 'US' ? "bg-blue-500/20 text-blue-400 shadow-[0_0_15px_rgba(59,130,246,0.2)]"
                    : "bg-amber-500/20 text-amber-400 shadow-[0_0_15px_rgba(245,158,11,0.2)]"
                  : "text-slate-500 hover:text-slate-300"
              )}
            >
              <Activity className={cn("h-3 w-3", market === m ? "animate-pulse" : "opacity-50")} />
              {m}
            </button>
          ))}
        </div>

        <div className="h-8 w-px bg-slate-800 hidden md:block mx-2" />

        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
          <input
            type="text"
            placeholder={
              market === 'NSE' 
                ? "Search NSE underlying (e.g. RELIANCE, NIFTY)..." 
                : market === 'US' 
                  ? "Search US symbols (e.g. AAPL, NVDA)..."
                  : "Search Crypto pairs (e.g. BTC, ETH)..."
            }
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-xl border border-slate-700 bg-slate-950/50 py-2 pl-10 pr-4 text-sm text-slate-200 focus:border-emerald-500/50 focus:outline-none focus:ring-1 focus:ring-emerald-500/50"
          />
        </div>

        <div className="flex items-center gap-1 p-1 rounded-xl bg-slate-950/50 border border-slate-700">
          {(['ALL', 'CE', 'PE'] as const).map(f => (
            <button
              key={f}
              onClick={() => setTypeFilter(f)}
              className={cn(
                "px-3 py-1 rounded-lg text-xs font-medium transition-all",
                typeFilter === f 
                  ? "bg-emerald-500/20 text-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.1)]" 
                  : "text-slate-500 hover:text-slate-300"
              )}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-[28px] border border-slate-800 bg-slate-900/40 p-1 overflow-hidden backdrop-blur-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-[11px] uppercase tracking-[0.2em] text-slate-500 px-4">
                <th className="py-4 pl-6">Underlying</th>
                <th className="py-4 px-4 text-center">Type</th>
                <th className="py-4 px-4 text-right">Strike</th>
                <th className="py-4 px-4">Expiry</th>
                <th className="py-4 px-4 text-right">LTP</th>
                <th className="py-4 px-4 text-right">OI</th>
                <th className="py-4 px-4 text-center">MACD</th>
                <th className="py-4 px-4 text-center">RSI</th>
                <th className="py-4 pr-6 text-right">Contract</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && filteredResults.length === 0 ? (
                Array.from({ length: 12 }).map((_, i) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td colSpan={9} className="p-4">
                      <Skeleton className="h-6 w-full rounded-lg" />
                    </td>
                  </tr>
                ))
              ) : filteredResults.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-20 text-center text-slate-500">
                    {search ? 'No matching instruments found' : 'Resolving ATM strikes... Please wait.'}
                  </td>
                </tr>
              ) : (
                filteredResults.map((item, idx) => (
                  <tr 
                    key={`${item.symbol}-${idx}`}
                    className="group border-b border-slate-800/50 hover:bg-slate-800/20 transition-colors"
                  >
                    <td className="py-4 pl-6">
                      <div className="font-bold text-slate-100">{item.underlying}</div>
                    </td>
                    <td className="py-4 px-4 text-center">
                      <span className={cn(
                        "rounded-full px-2 py-0.5 text-[10px] font-bold uppercase",
                        item.option_type === 'CE' 
                          ? "bg-emerald-500/10 text-emerald-400" 
                          : "bg-rose-500/10 text-rose-400"
                      )}>
                        {item.option_type}
                      </span>
                    </td>
                    <td className="py-4 px-4 text-right font-mono text-slate-300">
                      {formatNumber(item.strike)}
                    </td>
                    <td className="py-4 px-4 text-xs text-slate-500">
                      {item.expiry}
                    </td>
                    <td className={cn(
                      "py-4 px-4 text-right font-mono font-bold transition-colors duration-500",
                      item.ltp === 0 ? "text-slate-700" : (item.market === 'US' ? "text-blue-300" : item.market === 'CRYPTO' ? "text-amber-300" : "text-emerald-300")
                    )}>
                      {item.ltp ? formatCurrency(item.ltp, item.market === 'NSE' ? 'INR' : 'USD') : '—'}
                    </td>
                    <td className="py-4 px-4 text-right font-mono text-slate-400">
                      {item.oi ? formatNumber(item.oi) : '—'}
                    </td>
                    <td className="py-4 px-4 text-center">
                      <div className="flex items-center justify-center gap-1">
                        <Activity className={cn("h-3 w-3", (item.macd ?? 0) >= 0 ? "text-emerald-500" : "text-rose-500")} />
                        <span className="text-[10px] font-mono text-slate-500">
                          {item.macd?.toFixed(2) || '0.00'}
                        </span>
                      </div>
                    </td>
                    <td className="py-4 px-4 text-center">
                       <span className={cn(
                         "text-xs font-mono",
                         (item.rsi ?? 0) > 70 ? "text-rose-400" : (item.rsi ?? 0) < 30 ? "text-emerald-400" : "text-slate-400"
                       )}>
                         {item.rsi?.toFixed(0) || '—'}
                       </span>
                    </td>
                    <td className="py-4 pr-6 text-right text-[10px] font-mono text-slate-600">
                      {item.symbol}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

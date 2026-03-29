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

interface ATMOptionMetric {
  symbol: string;
  underlying: string;
  option_type: 'CE' | 'PE';
  strike: number;
  expiry: string;
  ltp: number;
  oi: number;
  macd: number;
  rsi: number;
}

interface ATMWatchlistResponse {
  timestamp: string;
  results: ATMOptionMetric[];
}

export default function OptionsWatchlistPage() {
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<'ALL' | 'CE' | 'PE'>('ALL');

  const { data, isLoading, refetch, isFetching } = useQuery<ATMWatchlistResponse>({
    queryKey: ['options-watchlist-atm'],
    queryFn: () => apiFetch<ATMWatchlistResponse>('/options-watchlist/atm?limit=209'),
    refetchInterval: 10000, // Refresh every 10s
  });

  const filteredResults = useMemo(() => {
    if (!data?.results) return [];
    return data.results.filter(item => {
      const matchesSearch = item.underlying.toLowerCase().includes(search.toLowerCase());
      const matchesType = typeFilter === 'ALL' || item.option_type === typeFilter;
      return matchesSearch && matchesType;
    });
  }, [data, search, typeFilter]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
            <List className="h-6 w-6 text-emerald-400" />
            ATM Options Watchlist
          </h1>
          <p className="text-sm text-slate-500">
            Real-time ATM strikes for all 209 FNO instruments
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900/50 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')} />
            Refresh
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4 bg-slate-900/40 p-4 rounded-2xl border border-slate-800">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search underlying (e.g. RELIANCE, NIFTY)..."
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
              {isLoading ? (
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
                    No matching instruments found
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
                    <td className="py-4 px-4 text-right font-mono font-bold text-emerald-300">
                      {formatCurrency(item.ltp, 'INR')}
                    </td>
                    <td className="py-4 px-4 text-right font-mono text-slate-400">
                      {formatNumber(item.oi)}
                    </td>
                    <td className="py-4 px-4 text-center">
                      <div className="flex items-center justify-center gap-1">
                        <Activity className={cn("h-3 w-3", item.macd >= 0 ? "text-emerald-500" : "text-rose-500")} />
                        <span className="text-[10px] font-mono text-slate-500">
                          {item.macd?.toFixed(2) || '0.00'}
                        </span>
                      </div>
                    </td>
                    <td className="py-4 px-4 text-center">
                       <span className={cn(
                         "text-xs font-mono",
                         item.rsi > 70 ? "text-rose-400" : item.rsi < 30 ? "text-emerald-400" : "text-slate-400"
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

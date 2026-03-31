'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch, apiPost } from '@/lib/api';
import type {
  WatchlistSymbol,
  CollectionStatus,
  WatchlistUniverseResponse,
} from '@/types/api';

// Bloomberg-grade watchlist types
export interface IndexSymbol {
  name: string;
  display_name: string;
  spot_symbol: string;
  futures_symbol: string;
  sector: string;
  lot_size: number;
}

export interface MarketData {
  symbol: string;
  name?: string;
  ltp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  oi?: number;
  bid?: number;
  ask?: number;
  change?: number;
  change_pct?: number;
  timestamp?: string;
}

export interface OHLCData {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface HistoricalDataResponse {
  symbol: string;
  resolution: string;
  from_date: string;
  to_date: string;
  count: number;
  data: OHLCData[];
}

export interface OptionGreeks {
  spot: number;
  strike: number;
  time_to_expiry_days: number;
  volatility: number;
  option_type: string;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  rho: number;
}

export interface OptionData {
  symbol: string;
  ltp: number;
  iv: number;
  oi: number;
  volume: number;
}

export interface OptionStrike {
  strike: number;
  ce: OptionData;
  pe: OptionData;
}

export interface OptionExpiry {
  expiry: string;
  strikes: OptionStrike[];
}

export interface OptionChainResponse {
  data: {
    expiryData: OptionExpiry[];
  };
}

export interface WatchlistSummary {
  timestamp: string;
  total_count: number;
  indices: {
    name: string;
    display_name: string;
    spot: MarketData;
    futures: MarketData;
  }[];
}

export interface GlobalUSUnderlying {
  symbol: string;
  name: string;
  price?: number;
  change?: number;
  change_pct?: number;
  volume?: number;
  currency?: string;
  market?: string;
}

export interface GlobalUSOptionFocus extends GlobalUSUnderlying {
  spot?: number;
  expiry?: string | null;
  atm_strike?: number;
  call_last?: number;
  call_bid?: number;
  call_ask?: number;
  call_iv?: number;
  call_oi?: number;
  put_last?: number;
  put_bid?: number;
  put_ask?: number;
  put_iv?: number;
  put_oi?: number;
}

export interface GlobalCryptoItem {
  symbol: string;
  name: string;
  price_usd: number;
  change_pct_24h: number;
  volume_24h: number;
  market_cap: number;
  rank: number;
  source: string;
}

export interface GlobalContinuousWatchlist {
  timestamp: string;
  us_underlyings: GlobalUSUnderlying[];
  us_options: GlobalUSOptionFocus[];
  crypto_top10: GlobalCryptoItem[];
  sources: Record<string, string>;
  errors?: string[];
  stale?: boolean;
  cache_age_seconds?: number | null;
}

// Original hooks
export function useWatchlistSymbols() {
  return useQuery<WatchlistSymbol[]>({
    queryKey: ['watchlist-symbols'],
    queryFn: () => apiFetch<WatchlistSymbol[]>('/watchlist/symbols'),
    refetchInterval: 60000,
    staleTime: 30000,
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useWatchlistUniverse(market?: string, search?: string, enabled = true) {
  return useQuery<WatchlistUniverseResponse>({
    queryKey: ['watchlist-universe', market ?? '', search ?? ''],
    queryFn: () => {
      const params = new URLSearchParams();
      if (market) params.set('market', market);
      if (search) params.set('search', search);
      const suffix = params.size ? `?${params.toString()}` : '';
      return apiFetch<WatchlistUniverseResponse>(`/watchlist/universe${suffix}`);
    },
    enabled,
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useCollectionStatus() {
  return useQuery<CollectionStatus[]>({
    queryKey: ['collection-status'],
    queryFn: () => apiFetch<CollectionStatus[]>('/watchlist/collect/status'),
    refetchInterval: 5000,
    staleTime: 2000,
    refetchOnWindowFocus: false,
  });
}

export function useStartCollection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { symbol: string; timeframe: string; days_back: number }) =>
      apiPost<CollectionStatus>('/watchlist/collect', params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['collection-status'] });
    },
  });
}

// Bloomberg-grade watchlist hooks
export function useIndices() {
  return useQuery<IndexSymbol[]>({
    queryKey: ['watchlist-indices'],
    queryFn: () => apiFetch<IndexSymbol[]>('/watchlist/indices'),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useWatchlistSummary() {
  return useQuery<WatchlistSummary>({
    queryKey: ['watchlist-summary'],
    queryFn: () => apiFetch<WatchlistSummary>('/watchlist/summary'),
    refetchInterval: 30000, // Increased from 15s to 30s
    staleTime: 20000,
    gcTime: 60_000,
    retry: 1,
    retryDelay: 2_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    refetchIntervalInBackground: false, // Don't poll in background
  });
}

export function useGlobalContinuousWatchlist(enabled = true) {
  return useQuery<GlobalContinuousWatchlist>({
    queryKey: ['watchlist-global-continuous'],
    queryFn: () => apiFetch<GlobalContinuousWatchlist>('/watchlist/global/continuous'),
    enabled,
    refetchInterval: 60000, // Increased from 2s to 60s (Global data is less urgent)
    staleTime: 30000,
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    retry: 2,
    retryDelay: 5_000,
  });
}

export function useIndexQuote(symbol: string, enabled = true) {
  return useQuery<MarketData>({
    queryKey: ['watchlist-quote', symbol],
    queryFn: () => apiFetch<MarketData>(`/watchlist/quote/${encodeURIComponent(symbol)}`),
    enabled: enabled && !!symbol,
    refetchInterval: 15000,
    staleTime: 10000,
    gcTime: 60_000,
    retry: 1,
    retryDelay: 1_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    refetchIntervalInBackground: true,
  });
}

export function useHistoricalData(
  symbol: string,
  days = 30,
  resolution = 'D',
  enabled = true
) {
  return useQuery<HistoricalDataResponse>({
    queryKey: ['watchlist-historical', symbol, days, resolution],
    queryFn: () =>
      apiFetch<HistoricalDataResponse>(
        // encodeURIComponent handles colons and slashes in Fyers symbols (e.g. NSE:NIFTY50-INDEX)
        `/watchlist/historical/${encodeURIComponent(symbol)}?days=${days}&resolution=${resolution}`
      ),
    enabled: enabled && !!symbol,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: 1,
  });
}

export function useOptionGreeks(
  spot: number,
  strike: number,
  daysToExpiry: number,
  volatility: number,
  optionType: 'CE' | 'PE',
  enabled = true
) {
  return useQuery<OptionGreeks>({
    queryKey: ['option-greeks', spot, strike, daysToExpiry, volatility, optionType],
    queryFn: () =>
      apiFetch<OptionGreeks>(
        `/watchlist/options/greeks?spot=${spot}&strike=${strike}&days_to_expiry=${daysToExpiry}&volatility=${volatility}&option_type=${optionType}`
      ),
    enabled,
    staleTime: 30 * 1000, // 30 seconds
  });
}

export function useOptionChain(indexName: string, enabled = true) {
  return useQuery<OptionChainResponse>({
    queryKey: ['option-chain', indexName],
    queryFn: () => apiFetch<OptionChainResponse>(`/watchlist/options/chain/${indexName}`),
    enabled,
    refetchInterval: 30_000,
    staleTime: 25_000,
    refetchOnWindowFocus: false,
  });
}

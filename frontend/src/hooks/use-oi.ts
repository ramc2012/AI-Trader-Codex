import { useQuery, keepPreviousData } from '@tanstack/react-query';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface QuadrantSymbol {
  symbol: string;
  ltp: number;
  price_change: number;
  price_change_pct: number;
  oi: number;
  oi_change: number;
  oi_change_pct: number;
  volume: number;
}

export interface OIQuadrants {
  timestamp: string;
  source?: string;
  long_buildup: QuadrantSymbol[];
  short_buildup: QuadrantSymbol[];
  short_covering: QuadrantSymbol[];
  long_unwinding: QuadrantSymbol[];
}

export interface ATMOption {
  symbol: string;
  display_name: string;
  spot: number;
  atm_strike: number;
  ce_ltp: number;
  ce_oi: number;
  ce_iv: number;
  ce_delta: number;
  pe_ltp: number;
  pe_oi: number;
  pe_iv: number;
  pe_delta: number;
  pcr: number;
  straddle_price: number;
}

export interface ATMWatchlist {
  timestamp: string;
  entries: ATMOption[];
}

export interface OITrendingEntry {
  timestamp: string;
  strike: number;
  ce_oi: number;
  pe_oi: number;
  ce_oi_change: number;
  pe_oi_change: number;
  pcr: number;
  max_pain: number;
}

export interface OITrendingData {
  symbol: string;
  expiry: string;
  entries: OITrendingEntry[];
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

export function useOIQuadrants() {
  return useQuery<OIQuadrants>({
    queryKey: ['oi', 'quadrants'],
    queryFn: async () => {
      const res = await fetch('/api/v1/oi/quadrants');
      if (!res.ok) throw new Error('Failed to fetch OI quadrants');
      return res.json();
    },
    refetchInterval: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function useATMWatchlist() {
  return useQuery<ATMWatchlist>({
    queryKey: ['oi', 'atm-watchlist'],
    queryFn: async () => {
      const res = await fetch('/api/v1/oi/atm-watchlist');
      if (!res.ok) throw new Error('Failed to fetch ATM watchlist');
      return res.json();
    },
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });
}

export function useOITrending(symbol: string) {
  return useQuery<OITrendingData>({
    queryKey: ['oi', 'trending', symbol],
    queryFn: async () => {
      const res = await fetch(`/api/v1/oi/trending/${encodeURIComponent(symbol)}`);
      if (!res.ok) throw new Error('Failed to fetch OI trending');
      return res.json();
    },
    enabled: !!symbol,
    refetchInterval: 30_000,
    placeholderData: keepPreviousData,
  });
}

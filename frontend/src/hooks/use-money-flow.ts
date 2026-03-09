import { useQuery, keepPreviousData } from '@tanstack/react-query';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface MoneyFlowStock {
  symbol: string;
  name: string;
  ltp: number;
  change: number;
  change_pct: number;
  volume: number;
  net_flow: number;
  sector: string;
}

export interface MoneyFlowSector {
  sector: string;
  net_flow: number;
  stock_count: number;
  top_gainer: string;
  top_loser: string;
}

export interface MoneyFlowSnapshot {
  timestamp: string;
  source?: string;
  total_net_flow: number;
  top_gainer: MoneyFlowStock;
  top_loser: MoneyFlowStock;
  sectors: MoneyFlowSector[];
  stocks: MoneyFlowStock[];
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useMoneyFlow(endpoint: string = '/api/v1/money-flow/snapshot') {
  return useQuery<MoneyFlowSnapshot>({
    queryKey: ['money-flow', endpoint],
    queryFn: async () => {
      const res = await fetch(endpoint);
      if (!res.ok) throw new Error('Failed to fetch money flow');
      return res.json();
    },
    staleTime: 10_000,
    gcTime: 5 * 60_000,
    refetchInterval: 20_000,
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
  });
}

'use client';

import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { OHLCResponse } from '@/types/api';

export function useOHLC(symbol: string, timeframe: string = '5') {
  return useQuery<OHLCResponse>({
    queryKey: ['ohlc', symbol, timeframe],
    queryFn: () =>
      apiFetch<OHLCResponse>(
        `/ohlc/${encodeURIComponent(symbol)}?timeframe=${timeframe}`
      ),
    enabled: !!symbol,
    refetchInterval: 5000,
    placeholderData: keepPreviousData,
    staleTime: 2000,
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

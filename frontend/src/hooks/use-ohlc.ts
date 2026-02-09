'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { OHLCResponse } from '@/types/api';

export function useOHLC(symbol: string, timeframe: string = '5m') {
  return useQuery<OHLCResponse>({
    queryKey: ['ohlc', symbol, timeframe],
    queryFn: () =>
      apiFetch<OHLCResponse>(
        `/ohlc/${encodeURIComponent(symbol)}?timeframe=${timeframe}`
      ),
    enabled: !!symbol,
    refetchInterval: 15000,
  });
}

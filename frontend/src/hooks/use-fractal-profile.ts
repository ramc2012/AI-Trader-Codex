import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { apiFetch } from '@/lib/api';
import type {
  FractalProfileContextResponse,
  FractalScanResponse,
  FractalWatchlistResponse,
} from '@/types/api';

export function useFractalProfileContext(symbol: string, date?: string) {
  return useQuery<FractalProfileContextResponse>({
    queryKey: ['fractal', 'context', symbol, date],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (date) params.set('date', date);
      const suffix = params.size ? `?${params.toString()}` : '';
      return apiFetch<FractalProfileContextResponse>(
        `/fractal/context/${encodeURIComponent(symbol)}${suffix}`
      );
    },
    enabled: Boolean(symbol),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

export function useFractalScanner(
  symbols?: string[],
  date?: string,
  limit: number = 8,
  minConsecutiveHours: number = 2,
) {
  return useQuery<FractalScanResponse>({
    queryKey: ['fractal', 'scan', symbols?.join(','), date, limit, minConsecutiveHours],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (symbols && symbols.length > 0) params.set('symbols', symbols.join(','));
      if (date) params.set('date', date);
      params.set('limit', String(limit));
      params.set('min_consecutive_hours', String(minConsecutiveHours));
      return apiFetch<FractalScanResponse>(`/fractal/scan?${params.toString()}`);
    },
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

export function useFractalWatchlist(
  symbols?: string[],
  date?: string,
  limit: number = 5,
  minConsecutiveHours: number = 2,
) {
  return useQuery<FractalWatchlistResponse>({
    queryKey: ['fractal', 'watchlist', symbols?.join(','), date, limit, minConsecutiveHours],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (symbols && symbols.length > 0) params.set('symbols', symbols.join(','));
      if (date) params.set('date', date);
      params.set('limit', String(limit));
      params.set('min_consecutive_hours', String(minConsecutiveHours));
      return apiFetch<FractalWatchlistResponse>(`/fractal/watchlist?${params.toString()}`);
    },
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

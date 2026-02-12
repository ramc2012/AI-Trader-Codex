'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch, apiPost } from '@/lib/api';
import type { WatchlistSymbol, CollectionStatus } from '@/types/api';

export function useWatchlistSymbols() {
  return useQuery<WatchlistSymbol[]>({
    queryKey: ['watchlist-symbols'],
    queryFn: () => apiFetch<WatchlistSymbol[]>('/watchlist/symbols'),
    refetchInterval: 15000,
  });
}

export function useCollectionStatus() {
  return useQuery<CollectionStatus[]>({
    queryKey: ['collection-status'],
    queryFn: () => apiFetch<CollectionStatus[]>('/watchlist/collect/status'),
    refetchInterval: 3000,
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

'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { Position } from '@/types/api';

export function usePositions(enabled = true) {
  return useQuery<Position[]>({
    queryKey: ['positions'],
    queryFn: () => apiFetch<Position[]>('/positions'),
    refetchInterval: enabled ? 2500 : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: true,
    staleTime: 1500,
    enabled,
  });
}

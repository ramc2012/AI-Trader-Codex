'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { Position } from '@/types/api';

export function usePositions(enabled = true) {
  return useQuery<Position[]>({
    queryKey: ['positions'],
    queryFn: () => apiFetch<Position[]>('/positions'),
    refetchInterval: enabled ? 30000 : false, // 30s fallback polling
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    staleTime: 5000,
    enabled,
  });
}

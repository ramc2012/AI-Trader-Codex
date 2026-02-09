'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { Position } from '@/types/api';

export function usePositions() {
  return useQuery<Position[]>({
    queryKey: ['positions'],
    queryFn: () => apiFetch<Position[]>('/positions'),
    refetchInterval: 5000,
  });
}

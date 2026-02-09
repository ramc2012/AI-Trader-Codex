'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { SystemHealth } from '@/types/api';

export function useHealth() {
  return useQuery<SystemHealth>({
    queryKey: ['health'],
    queryFn: () => apiFetch<SystemHealth>('/health/system'),
    refetchInterval: 10000,
  });
}

'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { ExecutorSummary } from '@/types/api';

export function useStrategies() {
  return useQuery<ExecutorSummary>({
    queryKey: ['strategies'],
    queryFn: () => apiFetch<ExecutorSummary>('/strategies'),
    refetchInterval: 5000,
  });
}

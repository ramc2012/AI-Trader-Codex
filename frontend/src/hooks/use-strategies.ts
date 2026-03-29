'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { ExecutorSummary } from '@/types/api';

export function useStrategies(enabled = true) {
  return useQuery<ExecutorSummary>({
    queryKey: ['strategies'],
    queryFn: () => apiFetch<ExecutorSummary>('/strategies'),
    refetchInterval: enabled ? 5000 : false,
    enabled,
  });
}

'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { RiskSummary } from '@/types/api';

export function useRiskSummary(enabled = true) {
  return useQuery<RiskSummary>({
    queryKey: ['risk-summary'],
    queryFn: () => apiFetch<RiskSummary>('/risk/summary'),
    refetchInterval: enabled ? 5000 : false,
    enabled,
  });
}

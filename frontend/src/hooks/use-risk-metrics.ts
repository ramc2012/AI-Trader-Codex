'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { RiskMetrics } from '@/types/api';

export function useRiskMetrics() {
  return useQuery<RiskMetrics>({
    queryKey: ['risk-metrics'],
    queryFn: () => apiFetch<RiskMetrics>('/risk/metrics'),
    refetchInterval: 10000,
  });
}

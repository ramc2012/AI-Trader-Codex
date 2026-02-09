'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { PortfolioSummary } from '@/types/api';

export function usePortfolio() {
  return useQuery<PortfolioSummary>({
    queryKey: ['portfolio'],
    queryFn: () => apiFetch<PortfolioSummary>('/portfolio'),
    refetchInterval: 3000,
  });
}

'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { PortfolioSummary, PortfolioInstrumentSummary, PortfolioPeriod } from '@/types/api';

export function usePortfolio(enabled = true) {
  return useQuery<PortfolioSummary>({
    queryKey: ['portfolio'],
    queryFn: () => apiFetch<PortfolioSummary>('/portfolio'),
    refetchInterval: enabled ? 3000 : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
    staleTime: 1500,
  });
}

export function usePortfolioInstruments(period: PortfolioPeriod = 'daily') {
  return useQuery<PortfolioInstrumentSummary>({
    queryKey: ['portfolio', 'instruments', period],
    queryFn: () =>
      apiFetch<PortfolioInstrumentSummary>(
        `/portfolio/instruments?period=${encodeURIComponent(period)}`
      ),
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
    staleTime: 2500,
  });
}

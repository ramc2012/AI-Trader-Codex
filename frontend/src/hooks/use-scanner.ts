'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ScanResult {
  symbol: string;
  display_name: string;
  ltp: number;
  change: number;
  change_pct: number;
  volume: number;
  volume_ratio: number;
  oi: number;
  oi_change: number;
  oi_change_pct: number;
  signal: string;
  signal_color: string;
  signal_priority: number;
}

export interface ScannerResponse {
  results: ScanResult[];
  total: number;
  filter: string;
  note?: string;
  timestamp: string;
}

export interface ScannerFilter {
  id: string;
  label: string;
  description: string;
}

export interface ScannerSignal {
  id: string;
  label: string;
  color: string;
}

export interface ScannerFiltersResponse {
  filters: ScannerFilter[];
  signals: ScannerSignal[];
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

export function useScannerResults(
  filterType: string = 'all',
  minChangePct: number = 0,
  minVolumeRatio: number = 0,
) {
  return useQuery<ScannerResponse>({
    queryKey: ['scanner', 'results', filterType, minChangePct, minVolumeRatio],
    queryFn: () => {
      const params = new URLSearchParams({
        filter_type: filterType,
        min_change_pct: String(minChangePct),
        min_volume_ratio: String(minVolumeRatio),
      });
      return apiFetch<ScannerResponse>(`/scanner/scan?${params}`);
    },
    refetchInterval: 15_000,
  });
}

export function useScannerFilters() {
  return useQuery<ScannerFiltersResponse>({
    queryKey: ['scanner', 'filters'],
    queryFn: () => apiFetch<ScannerFiltersResponse>('/scanner/filters'),
    staleTime: Infinity,
  });
}

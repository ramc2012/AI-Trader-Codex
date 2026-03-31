'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { Alert, AlertCounts } from '@/types/api';

export function useAlerts(enabled = true) {
  return useQuery<Alert[]>({
    queryKey: ['alerts'],
    queryFn: () => apiFetch<Alert[]>('/alerts'),
    refetchInterval: enabled ? 30000 : false, // 30s fallback
    refetchIntervalInBackground: false,
    staleTime: 5000,
    enabled,
  });
}

export function useAlertCounts(enabled = true) {
  return useQuery<AlertCounts>({
    queryKey: ['alert-counts'],
    queryFn: () => apiFetch<AlertCounts>('/alerts/counts'),
    refetchInterval: enabled ? 5000 : false,
    enabled,
  });
}

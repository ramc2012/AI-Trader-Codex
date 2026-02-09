'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { Alert, AlertCounts } from '@/types/api';

export function useAlerts() {
  return useQuery<Alert[]>({
    queryKey: ['alerts'],
    queryFn: () => apiFetch<Alert[]>('/alerts'),
    refetchInterval: 5000,
  });
}

export function useAlertCounts() {
  return useQuery<AlertCounts>({
    queryKey: ['alert-counts'],
    queryFn: () => apiFetch<AlertCounts>('/alerts/counts'),
    refetchInterval: 5000,
  });
}

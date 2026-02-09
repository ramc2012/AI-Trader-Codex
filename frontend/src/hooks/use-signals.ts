'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { Signal } from '@/types/api';

export function useSignals() {
  return useQuery<Signal[]>({
    queryKey: ['signals'],
    queryFn: () => apiFetch<Signal[]>('/signals'),
    refetchInterval: 5000,
  });
}

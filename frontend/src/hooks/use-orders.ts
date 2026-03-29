'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { Order, TradePair } from '@/types/api';

export function useOrders(enabled = true) {
  return useQuery<Order[]>({
    queryKey: ['orders'],
    queryFn: () => apiFetch<Order[]>('/orders'),
    refetchInterval: enabled ? 5000 : false,
    enabled,
  });
}

export function useOrderPairs(enabled = true) {
  return useQuery<TradePair[]>({
    queryKey: ['orders', 'pairs'],
    queryFn: () => apiFetch<TradePair[]>('/orders/pairs'),
    refetchInterval: enabled ? 5000 : false,
    enabled,
  });
}

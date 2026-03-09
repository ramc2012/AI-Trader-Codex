'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';
import type { Order, TradePair } from '@/types/api';

export function useOrders() {
  return useQuery<Order[]>({
    queryKey: ['orders'],
    queryFn: () => apiFetch<Order[]>('/orders'),
    refetchInterval: 5000,
  });
}

export function useOrderPairs() {
  return useQuery<TradePair[]>({
    queryKey: ['orders', 'pairs'],
    queryFn: () => apiFetch<TradePair[]>('/orders/pairs'),
    refetchInterval: 5000,
  });
}

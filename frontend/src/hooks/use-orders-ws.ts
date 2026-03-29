'use client';

import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useWebSocket } from './use-websocket';
import type { Order } from '@/types/api';

export function useOrdersWS() {
  const queryClient = useQueryClient();

  const onMessage = useCallback(
    (data: unknown) => {
      const payload = data as { type: string; orders?: Order[] };
      if (payload.type === 'orders_update' && payload.orders) {
        // Update both the raw order list and the history response
        queryClient.setQueryData(['orders'], payload.orders);
        queryClient.setQueryData(['history', 'orders'], (old: any) => ({
          ...(old || {}),
          orders: payload.orders,
          total: payload.orders?.length ?? 0,
          timestamp: new Date().toISOString()
        }));
      }
    },
    [queryClient]
  );

  return useWebSocket({
    path: '/ws/orders',
    onMessage,
    reconnectInterval: 3000,
    enabled: true,
  });
}

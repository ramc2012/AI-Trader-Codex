'use client';

import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useWebSocket } from './use-websocket';
import type { TradePair } from '@/types/api';

export function useTradesWS() {
  const queryClient = useQueryClient();

  const onMessage = useCallback(
    (data: unknown) => {
      const payload = data as { type: string; trades?: TradePair[] };
      if (payload.type === 'trades_update' && payload.trades) {
        queryClient.setQueryData(['orders', 'pairs'], payload.trades);
      }
    },
    [queryClient]
  );

  return useWebSocket({
    path: '/ws/trades',
    onMessage,
    reconnectInterval: 5000,
    enabled: true,
  });
}

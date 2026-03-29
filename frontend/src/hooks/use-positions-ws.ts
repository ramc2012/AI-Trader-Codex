'use client';

import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useWebSocket } from './use-websocket';
import type { Position } from '@/types/api';

export function usePositionsWS() {
  const queryClient = useQueryClient();

  const onMessage = useCallback(
    (data: unknown) => {
      const payload = data as { type: string; positions?: Position[] };
      if (payload.type === 'positions_update' && payload.positions) {
        // Update the 'positions' query cache directly
        queryClient.setQueryData(['positions'], payload.positions);
      }
    },
    [queryClient]
  );

  return useWebSocket({
    path: '/ws/positions',
    onMessage,
    reconnectInterval: 3000,
    enabled: true,
  });
}

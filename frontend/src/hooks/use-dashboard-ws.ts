'use client';

import { useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useWebSocket } from './use-websocket';
import type { DashboardWSPayload, EquitySnapshot } from '@/types/api';

export function useDashboardWS() {
  const queryClient = useQueryClient();
  const equitySnapshotsRef = useRef<EquitySnapshot[]>([]);

  const onMessage = useCallback(
    (data: unknown) => {
      const payload = data as DashboardWSPayload;
      if (payload.type !== 'dashboard_update') return;

      // Inject WebSocket data directly into React Query cache
      // This makes stat cards update instantly without waiting for polling
      if (payload.portfolio) {
        queryClient.setQueryData(['portfolio'], payload.portfolio);
      }
      if (payload.risk) {
        queryClient.setQueryData(['risk-summary'], payload.risk);
      }
      if (payload.alerts) {
        queryClient.setQueryData(['alert-counts'], payload.alerts);
      }

      // Accumulate equity snapshots for live chart
      if (payload.equity_snapshot) {
        equitySnapshotsRef.current.push(payload.equity_snapshot);
        // Keep last 500 data points
        if (equitySnapshotsRef.current.length > 500) {
          equitySnapshotsRef.current = equitySnapshotsRef.current.slice(-500);
        }
        queryClient.setQueryData(
          ['equity-curve-live'],
          [...equitySnapshotsRef.current]
        );
      }
    },
    [queryClient]
  );

  return useWebSocket({
    path: '/ws/dashboard',
    onMessage,
    reconnectInterval: 3000,
    enabled: true,
  });
}

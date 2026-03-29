'use client';

import { useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useWebSocket } from './use-websocket';
import type { DashboardWSPayload, EquitySnapshot, PortfolioSummary } from '@/types/api';

function isCurrencyAwarePortfolio(value: unknown): value is PortfolioSummary {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Partial<PortfolioSummary>;
  return (
    typeof candidate.position_count === 'number' &&
    typeof candidate.total_pnl === 'number' &&
    typeof candidate.total_pnl_inr === 'number' &&
    typeof candidate.total_market_value_inr === 'number'
  );
}

export function useDashboardWS() {
  const queryClient = useQueryClient();
  const equitySnapshotsRef = useRef<EquitySnapshot[]>([]);

  const onMessage = useCallback(
    (data: unknown) => {
      const payload = data as DashboardWSPayload;
      if (payload.type !== 'dashboard_update') return;

      // Inject WebSocket data directly into React Query cache
      // This makes stat cards update instantly without waiting for polling
      if (isCurrencyAwarePortfolio(payload.portfolio)) {
        queryClient.setQueryData(['portfolio'], payload.portfolio);
      }
      if (payload.risk) {
        queryClient.setQueryData(['risk-summary'], payload.risk);
      }
      if (payload.alerts) {
        queryClient.setQueryData(['alert-counts'], payload.alerts);
      }
      if (payload.strategies) {
        queryClient.setQueryData(['strategies'], payload.strategies);
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

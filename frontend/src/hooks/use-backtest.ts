'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch, apiPost } from '@/lib/api';
import type { BacktestResult } from '@/types/api';

export interface BacktestParams {
  strategy_name: string;
  symbol: string;
  start_date: string;
  end_date: string;
  initial_capital?: number;
}

export function useBacktestResults() {
  return useQuery<BacktestResult[]>({
    queryKey: ['backtest-results'],
    queryFn: () => apiFetch<BacktestResult[]>('/backtest/results'),
    refetchInterval: false,
  });
}

export function useRunBacktest() {
  const queryClient = useQueryClient();

  return useMutation<BacktestResult, Error, BacktestParams>({
    mutationFn: (params) => apiPost<BacktestResult>('/backtest/run', params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['backtest-results'] });
    },
  });
}

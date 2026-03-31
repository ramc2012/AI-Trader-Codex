'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch, apiPost } from '@/lib/api';
import type {
  AgentConfig,
  AgentEvent,
  AgentInspectorResponse,
  AgentStatus,
  StrategyParamsUpdateResponse,
} from '@/types/api';

/** Poll agent status frequently for near real-time control panel updates. */
export function useAgentStatus(enabled = true) {
  return useQuery({
    queryKey: ['agent-status'],
    queryFn: () => apiFetch<AgentStatus>('/agent/status'),
    refetchInterval: enabled ? 30000 : false,
    enabled,
  });
}

/** Fetch recent events with optional polling (used for chart trade markers). */
export function useAgentEvents(limit = 100, refetchInterval: number | false = false) {
  return useQuery({
    queryKey: ['agent-events', limit],
    queryFn: () => apiFetch<AgentEvent[]>(`/agent/events?limit=${limit}`),
    refetchInterval,
    refetchIntervalInBackground: Boolean(refetchInterval),
    refetchOnWindowFocus: Boolean(refetchInterval),
  });
}

/** Fetch available strategy names. */
export function useAvailableStrategies() {
  return useQuery({
    queryKey: ['agent-strategies'],
    queryFn: () => apiFetch<{ strategies: string[] }>('/agent/strategies'),
    staleTime: 60_000,
  });
}

export function useAgentInspector(params: {
  symbol?: string;
  timeframe?: string;
  lookbackBars?: number;
  strategies?: string[];
  enabled?: boolean;
}) {
  const {
    symbol,
    timeframe,
    lookbackBars = 240,
    strategies,
    enabled = true,
  } = params;

  return useQuery<AgentInspectorResponse>({
    queryKey: ['agent-inspector', symbol ?? '', timeframe ?? '', lookbackBars, strategies?.join(',') ?? ''],
    queryFn: async () => {
      const search = new URLSearchParams();
      if (symbol) search.set('symbol', symbol);
      if (timeframe) search.set('timeframe', timeframe);
      search.set('lookback_bars', String(lookbackBars));
      if (strategies && strategies.length > 0) {
        search.set('strategies', strategies.join(','));
      }
      return apiFetch<AgentInspectorResponse>(`/agent/inspector?${search.toString()}`);
    },
    enabled: enabled && Boolean(symbol),
    placeholderData: keepPreviousData,
    staleTime: 5_000,
    refetchOnWindowFocus: false,
  });
}

/** Start the agent with config. */
export function useAgentStart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (config: AgentConfig) =>
      apiPost<{ success: boolean; message: string }>('/agent/start', config),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-status'] });
    },
  });
}

/** Stop the agent. */
export function useAgentStop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiPost<{ success: boolean; message: string }>('/agent/stop', {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-status'] });
    },
  });
}

/** Activate kill switch, flatten positions, and block restarts. */
export function useAgentKillSwitch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiPost<{ success: boolean; message: string }>('/agent/pause', {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-status'] });
    },
  });
}

/** Clear kill switch. Starting remains a separate action. */
export function useAgentResetKillSwitch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiPost<{ success: boolean; message: string }>('/agent/resume', {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-status'] });
    },
  });
}

/** Send a test Telegram message. */
export function useTestTelegram() {
  return useMutation({
    mutationFn: () =>
      apiPost<{ success: boolean; message: string }>('/agent/test-telegram', {}),
  });
}

/** Send on-demand Telegram status snapshot. */
export function useNotifyTelegramStatus() {
  return useMutation({
    mutationFn: () =>
      apiPost<{ success: boolean; message: string }>('/agent/notify-status', {}),
  });
}

/** Send on-demand Telegram fractal scan snapshot. */
export function useNotifyTelegramFractalScan() {
  return useMutation({
    mutationFn: () =>
      apiPost<{ success: boolean; message: string }>('/agent/notify-fractal-scan', {}),
  });
}

/** Enable/disable one strategy at runtime. */
export function useSetAgentStrategy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { strategy: string; enabled: boolean }) =>
      apiPost<{ success: boolean; strategy: string; enabled: boolean; active_strategies: string[] }>(
        '/agent/strategy-controls',
        payload
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-status'] });
      qc.invalidateQueries({ queryKey: ['agent-events'] });
    },
  });
}

/** Update runtime parameters for one strategy. */
export function useUpdateAgentStrategyParams() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { strategy: string; params: Record<string, unknown> }) =>
      apiPost<StrategyParamsUpdateResponse>(`/agent/strategy-parameters/${payload.strategy}`, {
        params: payload.params,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-inspector'] });
      qc.invalidateQueries({ queryKey: ['agent-status'] });
      qc.invalidateQueries({ queryKey: ['strategies'] });
    },
  });
}

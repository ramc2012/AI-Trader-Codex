'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { apiFetch } from '@/lib/api';

export interface OptionSide {
  symbol: string;
  ltp: number;
  oi: number;
  oich: number;
  prev_oi: number;
  iv: number;
  volume: number;
  bid: number;
  ask: number;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
}

export interface OptionStrikeRow {
  strike: number;
  ce: OptionSide;
  pe: OptionSide;
  oi_bar?: {
    ce_ratio: number;
    pe_ratio: number;
  };
  quality?: {
    is_partial: boolean;
  };
}

export interface OptionExpiryBlock {
  expiry: string;
  expiry_ts: number;
  expiry_label: string;
  spot: number;
  total_call_oi: number;
  total_put_oi: number;
  pcr: number;
  strikes: OptionStrikeRow[];
  quality: {
    is_stale: boolean;
    integrity_score: number;
    rows: number;
    partial_rows: number;
    nonzero_oi_rows: number;
    source_latency_ms?: number;
  };
  source_ts: string;
}

export interface OptionChainSnapshot {
  underlying: string;
  fetched_at: string;
  data: {
    expiryData: OptionExpiryBlock[];
  };
  quality: {
    is_stale: boolean;
    integrity_score: number;
    expiries_loaded?: number;
  };
  persisted_rows?: number;
}

export interface OptionCandle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OptionChartResponse {
  symbol: string;
  interval: string;
  count: number;
  candles: OptionCandle[];
}

export interface StraddleResponse {
  underlying: string;
  expiry: string;
  strike: number;
  interval: string;
  ce_symbol: string;
  pe_symbol: string;
  candles: OptionCandle[];
  count: number;
}

export interface OptionAnalyticsResponse {
  underlying: string;
  expiry: string;
  spot: number;
  lot_size: number;
  days_to_expiry: number;
  total_pcr: number;
  total_net_gex: number;
  total_net_dex: number;
  total_net_gamma_exposure: number;
  total_net_delta_exposure: number;
  total_net_theta_exposure: number;
  total_net_vega_exposure: number;
  total_net_vanna_exposure: number;
  total_net_charm_exposure: number;
  total_net_vomma_exposure: number;
  total_net_speed_exposure: number;
  exposures_by_strike: Array<{
    strike: number;
    ce_gamma_exposure: number;
    pe_gamma_exposure: number;
    net_gamma_exposure: number;
    ce_delta_exposure: number;
    pe_delta_exposure: number;
    net_delta_exposure: number;
    net_theta_exposure: number;
    net_vega_exposure: number;
    net_vanna_exposure: number;
    net_charm_exposure: number;
    net_vomma_exposure: number;
    net_speed_exposure: number;
  }>;
  dex_profile: Array<{
    strike: number;
    ce_delta_exposure: number;
    pe_delta_exposure: number;
    net_delta_exposure: number;
  }>;
  oi_buildup: Array<{
    strike: number;
    ce_oi: number;
    pe_oi: number;
    ce_oich: number;
    pe_oich: number;
    net_oich: number;
    label: string;
  }>;
  iv_smile: Array<{
    strike: number;
    ce_iv: number;
    pe_iv: number;
    ce_iv_pct: number;
    pe_iv_pct: number;
  }>;
  term_structure: Array<{
    expiry: string;
    expiry_ts: number;
    days_to_expiry: number;
    pcr: number;
    total_call_oi: number;
    total_put_oi: number;
    atm_straddle: number;
    integrity_score: number;
  }>;
  gex_heatmap: Array<{
    strike: number;
    net_gamma_exposure: number;
    intensity: number;
  }>;
  gamma_convexity: Array<{
    strike: number;
    gamma_convexity: number;
  }>;
}

export function useCanonicalOptionChain(
  underlying: string,
  expiryTs?: number | null,
  strikeCount = 12,
  includeExpiries = 3,
  enabled = true
) {
  return useQuery<OptionChainSnapshot>({
    queryKey: ['options-chain-canonical', underlying, expiryTs, strikeCount, includeExpiries],
    queryFn: () => {
      const params = new URLSearchParams({
        strike_count: String(strikeCount),
        include_expiries: String(includeExpiries),
        persist: 'true',
      });
      if (expiryTs) {
        params.set('expiry_ts', String(expiryTs));
      }
      return apiFetch<OptionChainSnapshot>(
        `/options/chain/${encodeURIComponent(underlying)}?${params.toString()}`
      );
    },
    enabled: Boolean(enabled && underlying),
    refetchInterval: 10_000,
    staleTime: 8_000,
    placeholderData: keepPreviousData,
  });
}

export function useOptionChart(
  symbol: string | null | undefined,
  interval = '15',
  days = 10,
  enabled = true
) {
  return useQuery<OptionChartResponse>({
    queryKey: ['options-chart', symbol, interval, days],
    queryFn: () =>
      apiFetch<OptionChartResponse>(
        `/options/charts/${encodeURIComponent(symbol ?? '')}?interval=${encodeURIComponent(interval)}&days=${days}`
      ),
    enabled: Boolean(enabled && symbol),
    refetchInterval: 30_000,
    staleTime: 25_000,
    placeholderData: keepPreviousData,
  });
}

export function useStraddleChart(
  underlying: string,
  expiryTs: number | null | undefined,
  strike: number | null | undefined,
  interval = '15',
  days = 10,
  enabled = true
) {
  return useQuery<StraddleResponse>({
    queryKey: ['options-straddle', underlying, expiryTs, strike, interval, days],
    queryFn: () => {
      const params = new URLSearchParams({
        interval,
        days: String(days),
      });
      if (expiryTs) {
        params.set('expiry_ts', String(expiryTs));
      }
      if (strike !== null && strike !== undefined) {
        params.set('strike', String(strike));
      }
      return apiFetch<StraddleResponse>(
        `/options/straddle/${encodeURIComponent(underlying)}?${params.toString()}`
      );
    },
    enabled: Boolean(enabled && underlying),
    refetchInterval: 30_000,
    staleTime: 25_000,
    placeholderData: keepPreviousData,
  });
}

export function useOptionsAnalytics(
  underlying: string,
  expiryTs?: number | null,
  enabled = true
) {
  return useQuery<OptionAnalyticsResponse>({
    queryKey: ['options-analytics', underlying, expiryTs],
    queryFn: () => {
      const params = new URLSearchParams();
      if (expiryTs) {
        params.set('expiry_ts', String(expiryTs));
      }
      const queryString = params.toString();
      const suffix = queryString ? `?${queryString}` : '';
      return apiFetch<OptionAnalyticsResponse>(
        `/options/analytics/${encodeURIComponent(underlying)}${suffix}`
      );
    },
    enabled: Boolean(enabled && underlying),
    refetchInterval: 30_000,
    staleTime: 25_000,
    placeholderData: keepPreviousData,
  });
}

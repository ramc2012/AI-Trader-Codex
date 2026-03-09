import { useQuery, keepPreviousData } from '@tanstack/react-query';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface PriceLevel {
  price: number;
  bid: number;
  ask: number;
  delta: number;
  imbalance: boolean | number;
}

export interface FootprintBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  delta: number;
  vwap: number;
  cvd: number;
  levels: PriceLevel[];
  imbalance_count: number;
}

export interface FootprintData {
  symbol: string;
  tick_size: number;
  bar_minutes: number;
  source?: string;
  summary?: Record<string, unknown>;
  footprints: FootprintBar[];
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useFootprint(symbol: string, barMinutes: number = 15, hours: number = 6) {
  return useQuery<FootprintData>({
    queryKey: ['orderflow', 'footprint', symbol, barMinutes, hours],
    queryFn: async () => {
      const params = new URLSearchParams({
        bar_minutes: String(barMinutes),
        hours: String(hours),
        max_levels: '64',
      });
      const res = await fetch(
        `/api/v1/orderflow/footprint/${encodeURIComponent(symbol)}?${params}`
      );
      if (res.status === 404) {
        return {
          symbol,
          tick_size: 0.05,
          bar_minutes: barMinutes,
          source: 'no_data',
          summary: {},
          footprints: [],
        } as FootprintData;
      }
      if (!res.ok) throw new Error('Failed to fetch footprint');
      const payload = (await res.json()) as FootprintData;
      // Normalize API-level imbalance ratio (number) to a rendering boolean.
      payload.footprints = (payload.footprints || []).map((bar) => ({
        ...bar,
        levels: (bar.levels || []).map((lv) => ({
          ...lv,
          imbalance:
            typeof lv.imbalance === 'number' ? lv.imbalance >= 0.3 : Boolean(lv.imbalance),
        })),
      }));
      return payload;
    },
    enabled: !!symbol,
    staleTime: 10_000,
    gcTime: 5 * 60_000,
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
  });
}

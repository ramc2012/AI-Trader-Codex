import { useQuery } from '@tanstack/react-query';

interface RRGGroup {
  label: string;
  benchmark: string;
  count: number;
}

interface RRGPoint {
  symbol: string;
  timestamp: string;
  rs_ratio: number;
  rs_momentum: number;
  quadrant: string;
}

interface RRGData {
  group: string;
  label: string;
  benchmark: string;
  timeframe: string;
  symbols: Record<string, RRGPoint[]>;
}

export function useRRGGroups() {
  return useQuery<Record<string, RRGGroup>>({
    queryKey: ['rrg', 'groups'],
    queryFn: async () => {
      const res = await fetch('/api/v1/rrg/groups');
      if (!res.ok) throw new Error('Failed to fetch RRG groups');
      return res.json();
    },
    staleTime: 60_000 * 5,
  });
}

export function useRRGData(group: string, timeframe: string = '1D', days: number = 90) {
  return useQuery<RRGData>({
    queryKey: ['rrg', 'data', group, timeframe, days],
    queryFn: async () => {
      const params = new URLSearchParams({ group, timeframe, days: String(days) });
      const res = await fetch(`/api/v1/rrg/data?${params}`);
      if (!res.ok) throw new Error('Failed to fetch RRG data');
      return res.json();
    },
    refetchInterval: 60_000,
  });
}

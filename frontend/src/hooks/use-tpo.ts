import { useQuery, keepPreviousData } from '@tanstack/react-query';

interface TPOLevel {
  price: number;
  tpo_count: number;
  letters: string[];
  volume: number;
}

interface TPOProfile {
  date: string;
  poc: number;
  vah: number;
  val: number;
  ib_high: number;
  ib_low: number;
  open: number;
  close: number;
  high: number;
  low: number;
  total_volume: number;
  levels: TPOLevel[];
}

interface MultiTPOResponse {
  symbol: string;
  profiles: TPOProfile[];
}

export function useTPOProfile(symbol: string, date?: string) {
  return useQuery<TPOProfile>({
    queryKey: ['tpo', 'profile', symbol, date],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (date) params.set('date', date);
      const res = await fetch(`/api/v1/tpo/profile/${encodeURIComponent(symbol)}?${params}`);
      if (!res.ok) throw new Error('Failed to fetch TPO profile');
      return res.json();
    },
    enabled: !!symbol,
    placeholderData: keepPreviousData,
  });
}

export function useMultiTPO(symbol: string, days: number = 5) {
  return useQuery<MultiTPOResponse>({
    queryKey: ['tpo', 'multi', symbol, days],
    queryFn: async () => {
      const params = new URLSearchParams({ days: String(days) });
      const res = await fetch(`/api/v1/tpo/multi/${encodeURIComponent(symbol)}?${params}`);
      if (!res.ok) throw new Error('Failed to fetch multi-day TPO');
      return res.json();
    },
    enabled: !!symbol && days > 0,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

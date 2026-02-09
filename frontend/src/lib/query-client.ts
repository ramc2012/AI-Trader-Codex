'use client';

import { QueryClient } from '@tanstack/react-query';

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 2000,
        refetchInterval: 5000,
        retry: 2,
        refetchOnWindowFocus: true,
      },
    },
  });
}

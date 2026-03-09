'use client';

import { QueryClient } from '@tanstack/react-query';

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5000,
        refetchInterval: false,
        retry: 2,
        refetchOnWindowFocus: false,
      },
    },
  });
}

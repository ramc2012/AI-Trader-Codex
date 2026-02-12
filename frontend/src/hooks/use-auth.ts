'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch, apiPost } from '@/lib/api';
import type { AuthStatus, AuthLoginUrl } from '@/types/api';

export function useAuthStatus() {
  return useQuery<AuthStatus>({
    queryKey: ['auth-status'],
    queryFn: () => apiFetch<AuthStatus>('/auth/status'),
    refetchInterval: 60000, // Reduced frequency to 60 seconds to prevent form interference
    retry: 1,
    staleTime: 30000, // Consider data fresh for 30 seconds
  });
}

export function useLoginUrl() {
  return useQuery<AuthLoginUrl>({
    queryKey: ['auth-login-url'],
    queryFn: () => apiFetch<AuthLoginUrl>('/auth/login-url'),
    enabled: false, // Only fetch on demand via refetch()
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<{ message: string }>('/auth/logout', {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['auth-status'] });
    },
  });
}

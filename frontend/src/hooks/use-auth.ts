'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch, apiPost } from '@/lib/api';
import type {
  AuthStatus,
  AuthLoginUrl,
  TokenStatus,
  ManualAuthResponse,
  SaveAndLoginResponse,
  TokenRefreshResponse,
  SavePinResponse,
  AutoRefreshResponse,
  FyersCredentials,
  MarketDataProviders,
  TelegramConfig,
} from '@/types/api';

// =========================================================================
// Auth Status & Login
// =========================================================================

export function useAuthStatus() {
  return useQuery<AuthStatus>({
    queryKey: ['auth-status'],
    queryFn: () => apiFetch<AuthStatus>('/auth/status'),
    refetchInterval: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: true,
    retry: 1,
    staleTime: 60_000,
  });
}

export function useLoginUrl() {
  return useQuery<AuthLoginUrl>({
    queryKey: ['auth-login-url'],
    queryFn: () => apiFetch<AuthLoginUrl>('/auth/login-url'),
    enabled: false,
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<{ message: string }>('/auth/logout', {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['auth-status'] });
      queryClient.invalidateQueries({ queryKey: ['token-status'] });
    },
  });
}

// =========================================================================
// Credentials
// =========================================================================

export function useCredentials() {
  return useQuery<FyersCredentials>({
    queryKey: ['auth-credentials'],
    queryFn: () => apiFetch<FyersCredentials>('/auth/credentials'),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: false,
    retry: 1,
  });
}

export function useSaveAndLogin() {
  const queryClient = useQueryClient();
  return useMutation<SaveAndLoginResponse, Error, { app_id: string; secret_key: string; redirect_uri: string }>({
    mutationFn: (credentials) => apiPost<SaveAndLoginResponse>('/auth/save-and-login', credentials),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['auth-status'] });
      queryClient.invalidateQueries({ queryKey: ['auth-credentials'] });
    },
  });
}

export function useMarketDataProviders() {
  return useQuery<MarketDataProviders>({
    queryKey: ['market-data-providers'],
    queryFn: () => apiFetch<MarketDataProviders>('/auth/market-data-providers'),
    staleTime: 60_000,
  });
}

export function useSaveMarketDataProviders() {
  const queryClient = useQueryClient();
  return useMutation<
    MarketDataProviders,
    Error,
    { finnhub_api_key: string; alphavantage_api_key: string }
  >({
    mutationFn: (payload) =>
      apiPost<MarketDataProviders>('/auth/market-data-providers', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['market-data-providers'] });
    },
  });
}

export function useTelegramConfig() {
  return useQuery<TelegramConfig>({
    queryKey: ['telegram-config'],
    queryFn: () => apiFetch<TelegramConfig>('/auth/telegram'),
    staleTime: 30_000,
  });
}

export function useSaveTelegramConfig() {
  const queryClient = useQueryClient();
  return useMutation<
    TelegramConfig,
    Error,
    { enabled?: boolean; bot_token?: string; chat_id?: string; status_interval_minutes?: number }
  >({
    mutationFn: (payload) => apiPost<TelegramConfig>('/auth/telegram', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['telegram-config'] });
      queryClient.invalidateQueries({ queryKey: ['agent-status'] });
    },
  });
}

// =========================================================================
// Auth Code Submission
// =========================================================================

export function useSubmitAuthCode() {
  const queryClient = useQueryClient();
  return useMutation<ManualAuthResponse, Error, string>({
    mutationFn: (authCode) => apiPost<ManualAuthResponse>('/auth/manual-code', { auth_code: authCode }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['auth-status'] });
      queryClient.invalidateQueries({ queryKey: ['token-status'] });
    },
  });
}

// =========================================================================
// Token Management
// =========================================================================

export function useTokenStatus(enabled: boolean = true) {
  return useQuery<TokenStatus>({
    queryKey: ['token-status'],
    queryFn: () => apiFetch<TokenStatus>('/auth/token-status'),
    enabled,
    refetchInterval: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: 2 * 60 * 1000,
    retry: 1,
  });
}

export function useRefreshToken() {
  const queryClient = useQueryClient();
  return useMutation<TokenRefreshResponse, Error, string>({
    mutationFn: (pin) => apiPost<TokenRefreshResponse>('/auth/refresh', { pin }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['token-status'] });
      queryClient.invalidateQueries({ queryKey: ['auth-status'] });
    },
  });
}

export function useAutoRefresh() {
  const queryClient = useQueryClient();
  return useMutation<AutoRefreshResponse, Error>({
    mutationFn: () => apiPost<AutoRefreshResponse>('/auth/auto-refresh', {}),
    onSuccess: (data) => {
      if (data.refreshed) {
        queryClient.invalidateQueries({ queryKey: ['auth-status'] });
        queryClient.invalidateQueries({ queryKey: ['token-status'] });
      }
    },
  });
}

// =========================================================================
// PIN Management
// =========================================================================

export function useSavePin() {
  const queryClient = useQueryClient();
  return useMutation<SavePinResponse, Error, { pin: string; save_pin: boolean }>({
    mutationFn: ({ pin, save_pin }) => apiPost<SavePinResponse>('/auth/save-pin', { pin, save_pin }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['token-status'] });
    },
  });
}

export function useDeletePin() {
  const queryClient = useQueryClient();
  return useMutation<{ success: boolean; message: string }, Error>({
    mutationFn: () => apiFetch('/auth/pin', { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['token-status'] });
    },
  });
}

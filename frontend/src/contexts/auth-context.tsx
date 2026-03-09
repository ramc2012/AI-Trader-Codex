'use client';

import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { useAuthStatus, useTokenStatus } from '@/hooks/use-auth';
import type { TokenStatus } from '@/types/api';

interface AuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  profile: Record<string, unknown> | null;
  appConfigured: boolean;
  tokenStatus: TokenStatus | null;
  isAutoRefreshing: boolean;
}

const AuthContext = createContext<AuthContextValue>({
  isAuthenticated: false,
  isLoading: true,
  profile: null,
  appConfigured: false,
  tokenStatus: null,
  isAutoRefreshing: false,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const { data, isLoading } = useAuthStatus();
  const appConfigured = data?.app_configured ?? false;
  const { data: tokenStatus } = useTokenStatus(appConfigured);
  const isInitialLoading = isLoading && data === undefined;

  const value: AuthContextValue = useMemo(
    () => ({
      isAuthenticated: data?.authenticated ?? false,
      isLoading: isInitialLoading,
      profile: data?.profile ?? null,
      appConfigured,
      tokenStatus: tokenStatus ?? null,
      isAutoRefreshing: false,
    }),
    [data?.authenticated, data?.profile, appConfigured, isInitialLoading, tokenStatus]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}

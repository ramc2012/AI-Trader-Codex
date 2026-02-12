'use client';

import { createContext, useContext, type ReactNode } from 'react';
import { useAuthStatus } from '@/hooks/use-auth';

interface AuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  profile: Record<string, unknown> | null;
  appConfigured: boolean;
}

const AuthContext = createContext<AuthContextValue>({
  isAuthenticated: false,
  isLoading: true,
  profile: null,
  appConfigured: false,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const { data, isLoading } = useAuthStatus();

  const value: AuthContextValue = {
    isAuthenticated: data?.authenticated ?? false,
    isLoading,
    profile: data?.profile ?? null,
    appConfigured: data?.app_configured ?? false,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}

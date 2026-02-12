'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  Settings,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ExternalLink,
  LogOut,
  Loader2,
  Server,
  Database,
} from 'lucide-react';
import { useAuth } from '@/contexts/auth-context';
import { useLoginUrl, useLogout } from '@/hooks/use-auth';
import { cn } from '@/lib/utils';

export default function SettingsPage() {
  const searchParams = useSearchParams();
  const { isAuthenticated, isLoading, profile, appConfigured } = useAuth();
  const { refetch: fetchLoginUrl, data: loginData, isFetching: fetchingUrl } = useLoginUrl();
  const logoutMutation = useLogout();

  const [authMessage, setAuthMessage] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);

  // Check for auth redirect params
  useEffect(() => {
    const authResult = searchParams.get('auth');
    const error = searchParams.get('error');

    if (authResult === 'success') {
      setAuthMessage({
        type: 'success',
        text: 'Successfully connected to Fyers!',
      });
    } else if (authResult === 'failed') {
      setAuthMessage({
        type: 'error',
        text: error ? `Authentication failed: ${error}` : 'Authentication failed. Please try again.',
      });
    }
  }, [searchParams]);

  const handleConnect = async () => {
    const result = await fetchLoginUrl();
    if (result.data?.url) {
      window.open(result.data.url, '_blank');
    }
  };

  const handleDisconnect = () => {
    logoutMutation.mutate();
    setAuthMessage(null);
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Settings</h2>
        <p className="mt-1 text-sm text-slate-400">
          Manage your broker connection and system configuration
        </p>
      </div>

      {/* Auth redirect message */}
      {authMessage && (
        <div
          className={cn(
            'flex items-center gap-3 rounded-lg border p-4',
            authMessage.type === 'success'
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
              : 'border-red-500/30 bg-red-500/10 text-red-400'
          )}
        >
          {authMessage.type === 'success' ? (
            <CheckCircle className="h-5 w-5 shrink-0" />
          ) : (
            <XCircle className="h-5 w-5 shrink-0" />
          )}
          <p className="text-sm">{authMessage.text}</p>
          <button
            onClick={() => setAuthMessage(null)}
            className="ml-auto text-xs opacity-60 hover:opacity-100"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Fyers API Connection */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="flex items-center gap-3 mb-6">
          <Settings className="h-5 w-5 text-slate-400" />
          <h3 className="text-lg font-semibold text-slate-100">
            Fyers API Connection
          </h3>
        </div>

        {isLoading ? (
          <div className="flex items-center gap-3 py-8">
            <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
            <span className="text-sm text-slate-400">
              Checking connection status...
            </span>
          </div>
        ) : !appConfigured ? (
          /* Not Configured */
          <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 shrink-0 text-yellow-400 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-yellow-400">
                  Fyers API Not Configured
                </p>
                <p className="mt-1 text-sm text-slate-400">
                  To connect to Fyers, set{' '}
                  <code className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-300">
                    FYERS_APP_ID
                  </code>{' '}
                  and{' '}
                  <code className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-300">
                    FYERS_SECRET_KEY
                  </code>{' '}
                  in your <code className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-300">.env</code> file, then restart the backend.
                </p>
              </div>
            </div>
          </div>
        ) : isAuthenticated ? (
          /* Connected */
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <span className="h-3 w-3 rounded-full bg-emerald-500" />
              <span className="text-sm font-medium text-emerald-400">
                Connected
              </span>
            </div>

            {profile && (
              <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
                <h4 className="text-sm font-medium text-slate-300 mb-3">
                  Profile Information
                </h4>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  {!!profile.name && (
                    <div>
                      <span className="text-slate-500">Name</span>
                      <p className="text-slate-200">{String(profile.name)}</p>
                    </div>
                  )}
                  {!!profile.email_id && (
                    <div>
                      <span className="text-slate-500">Email</span>
                      <p className="text-slate-200">{String(profile.email_id)}</p>
                    </div>
                  )}
                  {!!profile.fy_id && (
                    <div>
                      <span className="text-slate-500">Fyers ID</span>
                      <p className="text-slate-200">{String(profile.fy_id)}</p>
                    </div>
                  )}
                  {!!profile.broker && (
                    <div>
                      <span className="text-slate-500">Broker</span>
                      <p className="text-slate-200">{String(profile.broker)}</p>
                    </div>
                  )}
                </div>
              </div>
            )}

            <button
              onClick={handleDisconnect}
              disabled={logoutMutation.isPending}
              className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm font-medium text-red-400 transition-colors hover:bg-red-500/20 disabled:opacity-50"
            >
              {logoutMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <LogOut className="h-4 w-4" />
              )}
              Disconnect from Fyers
            </button>
          </div>
        ) : (
          /* Disconnected */
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <span className="h-3 w-3 rounded-full bg-red-500" />
              <span className="text-sm font-medium text-red-400">
                Disconnected
              </span>
            </div>

            <p className="text-sm text-slate-400">
              Connect your Fyers account to enable live market data collection
              and trading. You&apos;ll be redirected to Fyers to authorize access.
            </p>

            <button
              onClick={handleConnect}
              disabled={fetchingUrl}
              className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
            >
              {fetchingUrl ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ExternalLink className="h-4 w-4" />
              )}
              Connect to Fyers
            </button>
          </div>
        )}
      </div>

      {/* System Info */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="flex items-center gap-3 mb-6">
          <Server className="h-5 w-5 text-slate-400" />
          <h3 className="text-lg font-semibold text-slate-100">
            System Information
          </h3>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
            <div className="flex items-center gap-2 mb-1">
              <Database className="h-4 w-4 text-slate-500" />
              <span className="text-xs text-slate-500">Trading Mode</span>
            </div>
            <span className="rounded-md bg-yellow-500/20 px-2 py-0.5 text-xs font-semibold uppercase text-yellow-400">
              Paper
            </span>
          </div>

          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
            <div className="flex items-center gap-2 mb-1">
              <Server className="h-4 w-4 text-slate-500" />
              <span className="text-xs text-slate-500">Backend</span>
            </div>
            <span className="text-sm text-slate-200">FastAPI v0.1.0</span>
          </div>

          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
            <div className="flex items-center gap-2 mb-1">
              <Database className="h-4 w-4 text-slate-500" />
              <span className="text-xs text-slate-500">Database</span>
            </div>
            <span className="text-sm text-slate-200">TimescaleDB</span>
          </div>
        </div>
      </div>
    </div>
  );
}

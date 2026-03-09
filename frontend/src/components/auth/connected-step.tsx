'use client';

import { useState } from 'react';
import {
  CheckCircle,
  XCircle,
  LogOut,
  Edit3,
  Loader2,
  AlertTriangle,
  Shield,
} from 'lucide-react';
import { useLogout, useRefreshToken, useSavePin } from '@/hooks/use-auth';
import type { TokenStatus } from '@/types/api';
import { cn } from '@/lib/utils';

interface ConnectedStepProps {
  profile: Record<string, unknown> | null;
  tokenStatus: TokenStatus | null;
  onDisconnect: () => void;
  onEditCredentials: () => void;
  showPinPrompt: boolean;
  onPinSaved: () => void;
}

export function ConnectedStep({
  profile,
  tokenStatus,
  onDisconnect,
  onEditCredentials,
  showPinPrompt,
  onPinSaved,
}: ConnectedStepProps) {
  const logoutMutation = useLogout();
  const refreshMutation = useRefreshToken();
  const savePinMutation = useSavePin();

  const [pin, setPin] = useState('');
  const [refreshPin, setRefreshPin] = useState('');
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const isValidPin = (value: string) => /^\d{4,6}$/.test(value);

  const handleDisconnect = () => {
    logoutMutation.mutate(undefined, {
      onSuccess: () => onDisconnect(),
    });
  };

  const handleSavePin = async () => {
    if (!isValidPin(pin)) {
      setMessage({ type: 'error', text: 'Please enter your FYERS PIN' });
      return;
    }

    try {
      const result = await savePinMutation.mutateAsync({ pin, save_pin: true });
      if (result.success) {
        setMessage({ type: 'success', text: 'PIN saved for automatic session refresh' });
        setPin('');
        onPinSaved();
      } else {
        setMessage({ type: 'error', text: result.message });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to save PIN' });
    }
  };

  const handleRefresh = async () => {
    if (!isValidPin(refreshPin)) {
      setMessage({ type: 'error', text: 'Please enter your FYERS PIN' });
      return;
    }

    try {
      const result = await refreshMutation.mutateAsync(refreshPin);
      if (result.success) {
        setMessage({ type: 'success', text: 'Session refreshed successfully!' });
        setRefreshPin('');
      } else {
        setMessage({ type: 'error', text: result.message });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to refresh session' });
    }
  };

  // Profile data may be nested under 'data' key (Fyers API response format)
  const profileData = profile
    ? (profile.data && typeof profile.data === 'object')
      ? (profile.data as Record<string, unknown>)
      : profile
    : null;
  const profileName = profileData?.name || profileData?.display_name;
  const profileEmail = profileData?.email_id;
  const profileFyId = profileData?.fy_id;
  const hasProfile = !!(profileName || profileEmail || profileFyId);

  return (
    <div className="space-y-4">
      {/* Status */}
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
        <span className="text-sm font-medium text-emerald-400">Connected</span>
      </div>

      {/* Profile */}
      {hasProfile && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
          <div className="grid grid-cols-2 gap-3 text-sm">
            {!!profileName && (
              <div>
                <span className="text-xs text-slate-500">Name</span>
                <p className="text-slate-200">{String(profileName)}</p>
              </div>
            )}
            {!!profileEmail && (
              <div>
                <span className="text-xs text-slate-500">Email</span>
                <p className="text-slate-200">{String(profileEmail)}</p>
              </div>
            )}
            {!!profileFyId && (
              <div>
                <span className="text-xs text-slate-500">Fyers ID</span>
                <p className="text-slate-200">{String(profileFyId)}</p>
              </div>
            )}
            <div>
              <span className="text-xs text-slate-500">Broker</span>
              <p className="text-slate-200">Fyers</p>
            </div>
          </div>
        </div>
      )}

      {/* Token Status */}
      {tokenStatus && (
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-3">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-xs text-slate-500">Access Token</span>
              {tokenStatus.access_token_valid ? (
                <CheckCircle className="h-3 w-3 text-emerald-400" />
              ) : (
                <XCircle className="h-3 w-3 text-red-400" />
              )}
            </div>
            <p className="text-xs text-slate-300">
              {tokenStatus.access_token_valid
                ? `${tokenStatus.access_token_expires_in_hours?.toFixed(1)}h remaining`
                : 'Expired'}
            </p>
          </div>

          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-3">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-xs text-slate-500">Refresh Token</span>
              {tokenStatus.refresh_token_valid ? (
                <CheckCircle className="h-3 w-3 text-emerald-400" />
              ) : (
                <XCircle className="h-3 w-3 text-red-400" />
              )}
            </div>
            <p className="text-xs text-slate-300">
              {tokenStatus.refresh_token_valid
                ? `${tokenStatus.refresh_token_expires_in_days?.toFixed(0)}d remaining`
                : 'Expired'}
            </p>
          </div>
        </div>
      )}

      {/* PIN Save Prompt (shown when no PIN saved and not dismissed) */}
      {showPinPrompt && tokenStatus && !tokenStatus.has_saved_pin && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4">
          <div className="flex items-start gap-3 mb-3">
            <Shield className="h-5 w-5 shrink-0 text-emerald-400 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-emerald-400">
                Save your PIN for automatic refresh
              </p>
              <p className="mt-1 text-xs text-slate-400">
                Your trading PIN will be encrypted and stored locally. The app will
                automatically refresh your session daily without manual intervention.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="password"
              inputMode="numeric"
              maxLength={6}
              placeholder="FYERS PIN"
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
              className="flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
            <button
              onClick={handleSavePin}
              disabled={savePinMutation.isPending || !isValidPin(pin)}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              {savePinMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                'Save'
              )}
            </button>
            <button
              onClick={onPinSaved}
              className="text-xs text-slate-500 hover:text-slate-400"
            >
              Skip
            </button>
          </div>
        </div>
      )}

      {/* PIN Saved Indicator */}
      {tokenStatus?.has_saved_pin && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2">
          <CheckCircle className="h-3.5 w-3.5 text-emerald-400" />
          <p className="text-xs text-emerald-400">PIN saved — sessions refresh automatically</p>
        </div>
      )}

      {/* Token Refresh (when access token expired but refresh available) */}
      {tokenStatus && !tokenStatus.access_token_valid && tokenStatus.refresh_token_valid && !tokenStatus.has_saved_pin && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-4">
          <div className="flex items-start gap-3 mb-3">
            <AlertTriangle className="h-5 w-5 shrink-0 text-yellow-400 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-yellow-400">Session Expired</p>
              <p className="mt-1 text-xs text-slate-400">
                Enter your PIN to refresh the session.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="password"
              inputMode="numeric"
              maxLength={6}
              placeholder="FYERS PIN"
              value={refreshPin}
              onChange={(e) => setRefreshPin(e.target.value.replace(/\D/g, ''))}
              className="flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
            <button
              onClick={handleRefresh}
              disabled={refreshMutation.isPending || !isValidPin(refreshPin)}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              {refreshMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                'Refresh'
              )}
            </button>
          </div>
        </div>
      )}

      {/* Message */}
      {message && (
        <p className={cn('text-sm', message.type === 'success' ? 'text-emerald-400' : 'text-red-400')}>
          {message.text}
        </p>
      )}

      {/* Actions */}
      <div className="flex items-center gap-3 pt-2">
        <button
          onClick={handleDisconnect}
          disabled={logoutMutation.isPending}
          className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm font-medium text-red-400 transition-colors hover:bg-red-500/20 disabled:opacity-50"
        >
          {logoutMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <LogOut className="h-4 w-4" />
          )}
          Disconnect
        </button>
        <button
          onClick={onEditCredentials}
          className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-400 transition-colors"
        >
          <Edit3 className="h-3 w-3" />
          Edit Credentials
        </button>
      </div>
    </div>
  );
}

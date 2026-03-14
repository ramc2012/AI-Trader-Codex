'use client';

import { useEffect, useRef, useState } from 'react';
import { ExternalLink, Loader2, CheckCircle, Edit3, ArrowRight } from 'lucide-react';
import { useLoginUrl, useSubmitAuthCode } from '@/hooks/use-auth';
import type { TokenStatus } from '@/types/api';

interface ConnectStepProps {
  loginUrl: string | null;
  tokenStatus: TokenStatus | null;
  onComplete: () => void;
  onEditCredentials: () => void;
}

function extractAuthCode(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) {
    return '';
  }

  // Preserve literal "+" characters from the redirect URL. URLSearchParams
  // would decode them as spaces, which breaks FYERS token exchange.
  const match = trimmed.match(/(?:^|[?&])auth_code=([^&#\s]+)/);
  const rawCode = match?.[1] ?? trimmed;

  try {
    return decodeURIComponent(rawCode.replace(/\+/g, '%2B')).trim().replace(/ /g, '+');
  } catch {
    return rawCode.trim().replace(/ /g, '+');
  }
}

export function ConnectStep({ loginUrl, tokenStatus, onComplete, onEditCredentials }: ConnectStepProps) {
  const { refetch: fetchLoginUrl, isFetching: fetchingUrl } = useLoginUrl();
  const submitAuthCode = useSubmitAuthCode();
  const autoHandledRef = useRef(false);

  const [authCode, setAuthCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleOpenLogin = async () => {
    if (loginUrl) {
      window.open(loginUrl, '_blank');
    } else {
      const result = await fetchLoginUrl();
      if (result.data?.url) {
        window.open(result.data.url, '_blank');
      }
    }
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    const pastedText = e.clipboardData.getData('text');
    if (pastedText.includes('auth_code=') || pastedText.includes('://')) {
      e.preventDefault();
      const extracted = extractAuthCode(pastedText);
      setAuthCode(extracted);
      setError(null);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const code = extractAuthCode(authCode);
    if (!code) {
      setError('Please paste the authorization code');
      return;
    }

    try {
      const result = await submitAuthCode.mutateAsync(code);
      if (result.success) {
        setSuccess(true);
        setTimeout(() => onComplete(), 1000);
      } else {
        setError(result.message || 'Authentication failed');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed');
    }
  };

  useEffect(() => {
    if (autoHandledRef.current || submitAuthCode.isPending || success || typeof window === 'undefined') {
      return;
    }

    const href = window.location.href;
    if (!href.includes('auth_code=')) {
      return;
    }

    autoHandledRef.current = true;
    const code = extractAuthCode(href);
    if (!code) {
      return;
    }

    submitAuthCode.mutate(code, {
      onSuccess: (result) => {
        if (result.success) {
          setSuccess(true);
          setTimeout(() => onComplete(), 1000);
        } else {
          setError(result.message || 'Authentication failed');
        }
      },
      onError: (err) => {
        setError(err instanceof Error ? err.message : 'Authentication failed');
      },
    });
  }, [submitAuthCode, success, onComplete]);

  if (success) {
    return (
      <div className="flex flex-col items-center gap-3 py-8">
        <CheckCircle className="h-10 w-10 text-emerald-400" />
        <p className="text-sm font-medium text-emerald-400">Connected successfully!</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-400">
        Log in to Fyers and paste the authorization code to connect your account.
      </p>

      {tokenStatus?.status_message && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-3 text-xs text-slate-300">
          <p className="font-medium text-slate-200">Broker session status</p>
          <p className="mt-1">{tokenStatus.status_message}</p>
          {tokenStatus.has_access_token && !tokenStatus.has_refresh_token && (
            <p className="mt-1 text-slate-400">
              The saved session has no refresh token, so a full FYERS re-login is required.
            </p>
          )}
        </div>
      )}

      {/* Step 1: Open Fyers Login */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          Step 1: Open Fyers Login
        </label>
        <button
          type="button"
          onClick={handleOpenLogin}
          disabled={fetchingUrl}
          className="w-full flex items-center justify-center gap-2 rounded-lg bg-slate-700 px-4 py-2.5 text-sm font-medium text-slate-200 transition-colors hover:bg-slate-600 disabled:opacity-50"
        >
          {fetchingUrl ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <ExternalLink className="h-4 w-4" />
          )}
          Open Fyers Login
        </button>
      </div>

      {/* Step 2: Paste Auth Code */}
      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Step 2: Paste the code from the URL after login
          </label>
          <input
            type="text"
            value={authCode}
            onChange={(e) => { setAuthCode(e.target.value); setError(null); }}
            onPaste={handlePaste}
            placeholder="Paste the authorization code or full URL here"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 font-mono placeholder-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
          <p className="mt-1 text-xs text-slate-500">
            You can paste the full redirect URL — the code will be extracted automatically
          </p>
        </div>

        {error && (
          <p className="text-sm text-red-400">{error}</p>
        )}

        <button
          type="submit"
          disabled={submitAuthCode.isPending || !authCode.trim()}
          className="w-full flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitAuthCode.isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Connecting...
            </>
          ) : (
            <>
              Connect
              <ArrowRight className="h-4 w-4" />
            </>
          )}
        </button>
      </form>

      <button
        type="button"
        onClick={onEditCredentials}
        className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-400 transition-colors"
      >
        <Edit3 className="h-3 w-3" />
        Edit Credentials
      </button>
    </div>
  );
}

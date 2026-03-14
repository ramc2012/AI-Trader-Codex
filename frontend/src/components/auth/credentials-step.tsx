'use client';

import { useState, useEffect, useRef } from 'react';
import { Loader2, Eye, EyeOff, ExternalLink, ArrowRight } from 'lucide-react';
import { useCredentials, useSaveAndLogin } from '@/hooks/use-auth';

interface CredentialsStepProps {
  onComplete: (loginUrl: string) => void;
}

export function CredentialsStep({ onComplete }: CredentialsStepProps) {
  const { data: existing, isLoading: loadingCreds } = useCredentials();
  const saveAndLogin = useSaveAndLogin();

  const [appId, setAppId] = useState('');
  const [secretKey, setSecretKey] = useState('');
  const [redirectUri, setRedirectUri] = useState(
    'https://trade.fyers.in/api-login/redirect-uri/index.html'
  );
  const [showSecret, setShowSecret] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadedRef = useRef(false);

  // Pre-fill from existing credentials (once)
  useEffect(() => {
    if (loadedRef.current || !existing) return;
    loadedRef.current = true;
    if (existing.app_id) setAppId(existing.app_id);
    if (existing.redirect_uri) setRedirectUri(existing.redirect_uri);
  }, [existing]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!appId.trim() || !secretKey.trim()) {
      setError('App ID and Secret Key are required');
      return;
    }

    try {
      const result = await saveAndLogin.mutateAsync({
        app_id: appId.trim(),
        secret_key: secretKey.trim(),
        redirect_uri: redirectUri.trim(),
      });

      if (result.success && result.login_url) {
        onComplete(result.login_url);
      } else {
        setError(result.message || 'Failed to save credentials');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save credentials');
    }
  };

  if (loadingCreds) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
        <span className="ml-2 text-sm text-slate-400">Loading...</span>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <p className="text-sm text-slate-400">
        Enter your Fyers API credentials to connect your trading account.{' '}
        <a
          href="https://myapi.fyers.in/dashboard"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-emerald-400 hover:text-emerald-300"
        >
          Get credentials
          <ExternalLink className="h-3 w-3" />
        </a>
      </p>
      {existing?.credentials_path && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2 text-xs text-slate-400">
          <p>
            Persisted broker settings file: <span className="font-mono text-slate-300">{existing.credentials_path}</span>
          </p>
          {existing.secret_configured && (
            <p className="mt-1 text-slate-500">A secret key is already stored on the backend. Enter a new one only to replace it.</p>
          )}
        </div>
      )}

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1.5">
          App ID <span className="text-red-400">*</span>
        </label>
        <input
          type="text"
          value={appId}
          onChange={(e) => setAppId(e.target.value)}
          placeholder="e.g., ABC123XYZ-100"
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1.5">
          Secret Key <span className="text-red-400">*</span>
        </label>
        <div className="relative">
          <input
            type={showSecret ? 'text' : 'password'}
            value={secretKey}
            onChange={(e) => setSecretKey(e.target.value)}
            placeholder="Enter your secret key"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 pr-10 text-sm text-slate-100 placeholder-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
          <button
            type="button"
            onClick={() => setShowSecret(!showSecret)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-300"
          >
            {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1.5">
          Redirect URI
        </label>
        <input
          type="text"
          value={redirectUri}
          onChange={(e) => setRedirectUri(e.target.value)}
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        />
        <p className="mt-1 text-xs text-slate-500">
          Must match the redirect URI in your Fyers app settings
        </p>
      </div>

      {error && (
        <p className="text-sm text-red-400">{error}</p>
      )}

      <button
        type="submit"
        disabled={saveAndLogin.isPending || !appId.trim() || !secretKey.trim()}
        className="w-full flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {saveAndLogin.isPending ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Saving...
          </>
        ) : (
          <>
            Save & Continue
            <ArrowRight className="h-4 w-4" />
          </>
        )}
      </button>
    </form>
  );
}

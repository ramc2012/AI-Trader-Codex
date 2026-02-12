'use client';

import { useState } from 'react';
import {
  Key,
  Loader2,
  CheckCircle2,
  XCircle,
  ExternalLink,
  Copy,
  Check,
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface ManualAuthCodeFormProps {
  loginUrl: string;
  onSuccess?: () => void;
  onCancel?: () => void;
}

export function ManualAuthCodeForm({
  loginUrl,
  onSuccess,
  onCancel,
}: ManualAuthCodeFormProps) {
  const [authCode, setAuthCode] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [message, setMessage] = useState('');
  const [copied, setCopied] = useState(false);

  const handleCopyUrl = () => {
    navigator.clipboard.writeText(loginUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSubmit = async () => {
    if (!authCode.trim()) {
      setStatus('error');
      setMessage('Please enter the authorization code');
      return;
    }

    setIsSubmitting(true);
    setStatus('idle');
    setMessage('');

    try {
      const response = await fetch('/api/v1/auth/manual-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auth_code: authCode }),
      });

      const data = await response.json();

      if (data.success) {
        setStatus('success');
        setMessage(data.message);
        setTimeout(() => {
          onSuccess?.();
        }, 1500);
      } else {
        setStatus('error');
        setMessage(data.message || 'Authentication failed');
      }
    } catch (error) {
      setStatus('error');
      setMessage(
        error instanceof Error ? error.message : 'Failed to submit authorization code'
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Instructions */}
      <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-4">
        <h4 className="text-sm font-medium text-blue-400 mb-2">
          📋 Manual Authentication Steps:
        </h4>
        <ol className="list-decimal list-inside space-y-2 text-sm text-slate-300">
          <li>Click "Open Fyers Login" button below</li>
          <li>Log in with your Fyers credentials and authorize</li>
          <li>
            After authorization, you'll see a URL in your browser like:
            <code className="block mt-1 text-xs bg-slate-800 p-2 rounded break-all">
              https://trade.fyers.in/...?auth_code=<span className="text-emerald-400">eyJ0eXAiOiJKV1QiLCJhbGc...</span>&amp;state=...
            </code>
          </li>
          <li>
            <strong className="text-emerald-400">Copy ONLY the token</strong> (the long string after{' '}
            <code className="text-xs bg-slate-800 px-1">auth_code=</code>)
            <br />
            <span className="text-xs text-slate-500 ml-6">
              • Starts with "eyJ"
              <br />• Ends before "&amp;state"
              <br />• Do NOT include "auth_code=" or "&amp;state"
            </span>
          </li>
          <li>Paste the token below and click "Submit"</li>
        </ol>
      </div>

      {/* Login URL */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          Step 1: Open Fyers Login
        </label>
        <div className="flex gap-2">
          <button
            onClick={() => window.open(loginUrl, '_blank')}
            className="flex-1 flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500"
          >
            <ExternalLink className="h-4 w-4" />
            Open Fyers Login
          </button>
          <button
            onClick={handleCopyUrl}
            className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-medium text-slate-300 transition-colors hover:bg-slate-700"
          >
            {copied ? (
              <>
                <Check className="h-4 w-4 text-emerald-400" />
                Copied!
              </>
            ) : (
              <>
                <Copy className="h-4 w-4" />
                Copy URL
              </>
            )}
          </button>
        </div>
      </div>

      {/* Auth Code Input */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          Step 2: Paste Authorization Token
        </label>
        <div className="mb-2 rounded border border-slate-700 bg-slate-800/50 p-2">
          <p className="text-xs text-slate-500 mb-1">Example token format:</p>
          <code className="text-xs text-emerald-400 break-all">
            eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJhcGkuZnllcnMuaW4iLCJpYXQiOjE2...
          </code>
        </div>
        <textarea
          value={authCode}
          onChange={(e) => setAuthCode(e.target.value)}
          placeholder="Paste ONLY the token here (the long string starting with eyJ...)"
          rows={4}
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-slate-100 font-mono placeholder-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        />
        <div className="mt-2 flex items-start gap-2 text-xs text-slate-500">
          <span className="text-emerald-400">✓</span>
          <div>
            <p className="font-medium text-slate-400">Tips:</p>
            <ul className="list-disc list-inside space-y-1 ml-2">
              <li>Copy ONLY the token value, not the entire URL</li>
              <li>Token should start with "eyJ"</li>
              <li>Do NOT include "auth_code=" or "&state=" parts</li>
              <li>Remove any spaces before/after the token</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Status Message */}
      {status !== 'idle' && message && (
        <div
          className={cn(
            'flex items-start gap-3 rounded-lg border p-4',
            status === 'success' && 'border-emerald-500/30 bg-emerald-500/10',
            status === 'error' && 'border-red-500/30 bg-red-500/10'
          )}
        >
          {status === 'success' && (
            <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-400" />
          )}
          {status === 'error' && <XCircle className="h-5 w-5 shrink-0 text-red-400" />}
          <p
            className={cn(
              'text-sm',
              status === 'success' && 'text-emerald-400',
              status === 'error' && 'text-red-400'
            )}
          >
            {message}
          </p>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSubmit}
          disabled={isSubmitting || !authCode.trim()}
          className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSubmitting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Key className="h-4 w-4" />
          )}
          Submit Authorization Code
        </button>

        {onCancel && (
          <button
            onClick={onCancel}
            disabled={isSubmitting}
            className="text-sm text-slate-400 hover:text-slate-300 disabled:opacity-50"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}

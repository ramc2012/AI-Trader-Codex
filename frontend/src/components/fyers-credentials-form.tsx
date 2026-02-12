'use client';

import { useState, useEffect } from 'react';
import {
  Save,
  Loader2,
  Key,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Eye,
  EyeOff,
  ExternalLink,
  HelpCircle,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { ManualAuthCodeForm } from './manual-auth-code-form';

interface FyersCredentialsFormProps {
  onSuccess?: () => void;
  onCancel?: () => void;
  initialData?: {
    appId?: string;
    redirectUri?: string;
  };
}

interface FormData {
  appId: string;
  secretKey: string;
  redirectUri: string;
}

type ValidationStatus = 'idle' | 'validating' | 'valid' | 'invalid';

export function FyersCredentialsForm({
  onSuccess,
  onCancel,
  initialData,
}: FyersCredentialsFormProps) {
  const [formData, setFormData] = useState<FormData>({
    appId: initialData?.appId || '',
    secretKey: '',
    redirectUri: initialData?.redirectUri || 'https://trade.fyers.in/api-login/redirect-uri/index.html',
  });

  const [showSecretKey, setShowSecretKey] = useState(false);
  const [validationStatus, setValidationStatus] = useState<ValidationStatus>('idle');
  const [validationMessage, setValidationMessage] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [loginUrl, setLoginUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Load existing credentials on mount
  useEffect(() => {
    const loadCredentials = async () => {
      try {
        const response = await fetch('/api/v1/auth/credentials');
        if (response.ok) {
          const data = await response.json();
          if (data.app_id && data.redirect_uri) {
            setFormData((prev) => ({
              ...prev,
              appId: data.app_id,
              redirectUri: data.redirect_uri,
            }));
          }
        }
      } catch (error) {
        console.error('Failed to load credentials:', error);
      } finally {
        setIsLoading(false);
      }
    };

    loadCredentials();
  }, []);

  const handleInputChange = (field: keyof FormData, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    // Reset validation when input changes
    if (validationStatus !== 'idle') {
      setValidationStatus('idle');
      setValidationMessage('');
    }
  };

  const handleValidate = async () => {
    if (!formData.appId || !formData.secretKey) {
      setValidationStatus('invalid');
      setValidationMessage('Please fill in all required fields');
      return;
    }

    setValidationStatus('validating');
    setValidationMessage('Validating credentials...');

    try {
      const response = await fetch('/api/v1/auth/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          app_id: formData.appId,
          secret_key: formData.secretKey,
          redirect_uri: formData.redirectUri,
        }),
      });

      const data = await response.json();

      if (data.valid) {
        setValidationStatus('valid');
        setValidationMessage(data.message);
        setLoginUrl(data.login_url || null);
      } else {
        setValidationStatus('invalid');
        setValidationMessage(data.message || 'Validation failed');
      }
    } catch (error) {
      setValidationStatus('invalid');
      setValidationMessage(
        error instanceof Error ? error.message : 'Failed to validate credentials'
      );
    }
  };

  const handleSave = async () => {
    if (!formData.appId || !formData.secretKey) {
      setValidationStatus('invalid');
      setValidationMessage('Please fill in all required fields');
      return;
    }

    setIsSaving(true);

    try {
      const response = await fetch('/api/v1/auth/credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          app_id: formData.appId,
          secret_key: formData.secretKey,
          redirect_uri: formData.redirectUri,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to save credentials');
      }

      // After saving, validate and get login URL
      await handleValidate();

      onSuccess?.();
    } catch (error) {
      setValidationStatus('invalid');
      setValidationMessage(
        error instanceof Error ? error.message : 'Failed to save credentials'
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveAndLogin = async () => {
    if (!formData.appId || !formData.secretKey) {
      setValidationStatus('invalid');
      setValidationMessage('Please fill in all required fields');
      return;
    }

    setIsSaving(true);

    try {
      const response = await fetch('/api/v1/auth/save-and-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          app_id: formData.appId,
          secret_key: formData.secretKey,
          redirect_uri: formData.redirectUri,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Failed to save credentials');
      }

      if (data.success && data.login_url) {
        setValidationStatus('valid');
        setValidationMessage('Credentials saved! Use the manual authentication below.');
        setLoginUrl(data.login_url);
      }
    } catch (error) {
      setValidationStatus('invalid');
      setValidationMessage(
        error instanceof Error ? error.message : 'Failed to save credentials'
      );
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        <span className="ml-3 text-sm text-slate-400">Loading credentials...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Help Text */}
      <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-4">
        <div className="flex items-start gap-3">
          <HelpCircle className="h-5 w-5 shrink-0 text-blue-400 mt-0.5" />
          <div className="text-sm text-slate-300">
            <p className="font-medium text-blue-400 mb-2">
              How to get your Fyers API credentials:
            </p>
            <ol className="list-decimal list-inside space-y-1 text-slate-400">
              <li>Visit the Fyers API portal and create an app</li>
              <li>Copy your App ID and Secret Key from the app dashboard</li>
              <li>
                Add <code className="rounded bg-slate-800 px-1 py-0.5 text-xs">
                  {formData.redirectUri}
                </code> as the redirect URI in your Fyers app settings
              </li>
              <li>Paste your credentials below and click "Save & Login"</li>
            </ol>
            <a
              href="https://myapi.fyers.in/dashboard"
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-flex items-center gap-1 text-blue-400 hover:text-blue-300"
            >
              Open Fyers API Portal
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>
        </div>
      </div>

      {/* Form Fields */}
      <div className="space-y-4">
        {/* App ID */}
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Fyers App ID
            <span className="text-red-400 ml-1">*</span>
          </label>
          <input
            type="text"
            value={formData.appId}
            onChange={(e) => handleInputChange('appId', e.target.value)}
            placeholder="e.g., ABC123XYZ-100"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </div>

        {/* Secret Key */}
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Fyers Secret Key
            <span className="text-red-400 ml-1">*</span>
          </label>
          <div className="relative">
            <input
              type={showSecretKey ? 'text' : 'password'}
              value={formData.secretKey}
              onChange={(e) => handleInputChange('secretKey', e.target.value)}
              placeholder="Enter your secret key"
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 pr-10 text-sm text-slate-100 placeholder-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
            <button
              type="button"
              onClick={() => setShowSecretKey(!showSecretKey)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-300"
            >
              {showSecretKey ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </button>
          </div>
        </div>

        {/* Redirect URI */}
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Redirect URI
          </label>
          <input
            type="text"
            value={formData.redirectUri}
            onChange={(e) => handleInputChange('redirectUri', e.target.value)}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
          <p className="mt-1 text-xs text-slate-500">
            This must match the redirect URI configured in your Fyers app
          </p>
        </div>
      </div>

      {/* Validation Status */}
      {validationStatus !== 'idle' && (
        <div
          className={cn(
            'flex items-start gap-3 rounded-lg border p-4',
            validationStatus === 'validating' && 'border-blue-500/30 bg-blue-500/10',
            validationStatus === 'valid' && 'border-emerald-500/30 bg-emerald-500/10',
            validationStatus === 'invalid' && 'border-red-500/30 bg-red-500/10'
          )}
        >
          {validationStatus === 'validating' && (
            <Loader2 className="h-5 w-5 shrink-0 animate-spin text-blue-400" />
          )}
          {validationStatus === 'valid' && (
            <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-400" />
          )}
          {validationStatus === 'invalid' && (
            <XCircle className="h-5 w-5 shrink-0 text-red-400" />
          )}
          <div className="flex-1">
            <p
              className={cn(
                'text-sm',
                validationStatus === 'validating' && 'text-blue-400',
                validationStatus === 'valid' && 'text-emerald-400',
                validationStatus === 'invalid' && 'text-red-400'
              )}
            >
              {validationMessage}
            </p>
            {validationStatus === 'valid' && loginUrl && (
              <button
                onClick={() => window.open(loginUrl, '_blank')}
                className="mt-2 flex items-center gap-1 text-sm text-emerald-400 hover:text-emerald-300"
              >
                Open Login Page
                <ExternalLink className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSaveAndLogin}
          disabled={isSaving || !formData.appId || !formData.secretKey}
          className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSaving ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          Save & Login
        </button>

        <button
          onClick={handleValidate}
          disabled={
            isSaving ||
            validationStatus === 'validating' ||
            !formData.appId ||
            !formData.secretKey
          }
          className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-medium text-slate-300 transition-colors hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {validationStatus === 'validating' ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Key className="h-4 w-4" />
          )}
          Validate Only
        </button>

        {onCancel && (
          <button
            onClick={onCancel}
            disabled={isSaving}
            className="ml-auto text-sm text-slate-400 hover:text-slate-300 disabled:opacity-50"
          >
            Cancel
          </button>
        )}
      </div>

      {/* Manual Authentication Form */}
      {validationStatus === 'valid' && loginUrl && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
          <h4 className="text-sm font-medium text-slate-300 mb-4">
            Manual Authentication
          </h4>
          <ManualAuthCodeForm
            loginUrl={loginUrl}
            onSuccess={() => {
              setValidationStatus('idle');
              setLoginUrl(null);
              onSuccess?.();
            }}
            onCancel={() => {
              setLoginUrl(null);
              setValidationStatus('idle');
            }}
          />
        </div>
      )}
    </div>
  );
}

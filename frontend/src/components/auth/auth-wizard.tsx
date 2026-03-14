'use client';

import { useState } from 'react';
import { CheckCircle, Loader2 } from 'lucide-react';
import { useAuth } from '@/contexts/auth-context';
import { CredentialsStep } from './credentials-step';
import { ConnectStep } from './connect-step';
import { ConnectedStep } from './connected-step';
import { cn } from '@/lib/utils';

const STEPS = [
  { label: 'Credentials', number: 1 },
  { label: 'Connect', number: 2 },
  { label: 'Connected', number: 3 },
] as const;

export function AuthWizard() {
  const { isAuthenticated, isLoading, appConfigured, profile, tokenStatus, isAutoRefreshing } = useAuth();

  // Allow user to force back to step 1 for editing credentials
  const [forceStep, setForceStep] = useState<number | null>(null);
  const [loginUrl, setLoginUrl] = useState<string | null>(null);
  const [pinPromptDismissed, setPinPromptDismissed] = useState(false);

  // Derive current step from auth state
  let derivedStep: number;
  if (!appConfigured) {
    derivedStep = 1;
  } else if (!isAuthenticated) {
    derivedStep = 2;
  } else {
    derivedStep = 3;
  }

  const currentStep = forceStep ?? derivedStep;

  if (isLoading || isAutoRefreshing) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
        <span className="ml-2 text-sm text-slate-400">
          {isAutoRefreshing ? 'Refreshing session...' : 'Checking connection...'}
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Stepper */}
      <div className="flex items-center gap-0">
        {STEPS.map((step, idx) => {
          const isCompleted = derivedStep > step.number;
          const isCurrent = currentStep === step.number;

          return (
            <div key={step.number} className="flex items-center flex-1 last:flex-none">
              <div className="flex items-center gap-2">
                <div
                  className={cn(
                    'flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold transition-colors',
                    isCompleted
                      ? 'bg-emerald-500 text-white'
                      : isCurrent
                      ? 'bg-emerald-600 text-white ring-2 ring-emerald-500/30'
                      : 'bg-slate-700 text-slate-400'
                  )}
                >
                  {isCompleted ? (
                    <CheckCircle className="h-4 w-4" />
                  ) : (
                    step.number
                  )}
                </div>
                <span
                  className={cn(
                    'text-xs font-medium whitespace-nowrap',
                    isCurrent ? 'text-slate-200' : isCompleted ? 'text-emerald-400' : 'text-slate-500'
                  )}
                >
                  {step.label}
                </span>
              </div>

              {idx < STEPS.length - 1 && (
                <div
                  className={cn(
                    'mx-3 h-px flex-1',
                    derivedStep > step.number ? 'bg-emerald-500/50' : 'bg-slate-700'
                  )}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Step Content */}
      {currentStep === 1 && (
        <CredentialsStep
          onComplete={(url) => {
            setLoginUrl(url);
            setForceStep(null); // Let derived step take over (will be 2 after credentials saved)
          }}
        />
      )}

      {currentStep === 2 && (
        <ConnectStep
          loginUrl={loginUrl}
          tokenStatus={tokenStatus}
          onComplete={() => {
            setForceStep(null);
            setPinPromptDismissed(false);
          }}
          onEditCredentials={() => setForceStep(1)}
        />
      )}

      {currentStep === 3 && (
        <ConnectedStep
          profile={profile}
          tokenStatus={tokenStatus}
          onDisconnect={() => {
            setForceStep(null);
            setPinPromptDismissed(false);
          }}
          onEditCredentials={() => setForceStep(1)}
          showPinPrompt={!pinPromptDismissed}
          onPinSaved={() => setPinPromptDismissed(true)}
        />
      )}
    </div>
  );
}

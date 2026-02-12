'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getCurrentIST } from '@/lib/formatters';
import { useAuth } from '@/contexts/auth-context';
import { cn } from '@/lib/utils';

export function Header() {
  const [time, setTime] = useState<string>('');
  const { isAuthenticated, isLoading: authLoading } = useAuth();

  useEffect(() => {
    setTime(getCurrentIST());
    const interval = setInterval(() => {
      setTime(getCurrentIST());
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="fixed left-60 right-0 top-0 z-30 flex h-16 items-center justify-between border-b border-slate-800 bg-slate-950/80 px-6 backdrop-blur-sm">
      <h1 className="text-lg font-semibold text-slate-100">
        Nifty AI Trader
      </h1>

      <div className="flex items-center gap-4">
        {/* Fyers connection status */}
        <Link
          href="/settings"
          className="flex items-center gap-2 rounded-md px-3 py-1 transition-colors hover:bg-slate-800"
        >
          {authLoading ? (
            <span className="h-2 w-2 animate-pulse rounded-full bg-slate-500" />
          ) : (
            <span
              className={cn(
                'h-2 w-2 rounded-full',
                isAuthenticated ? 'bg-emerald-500' : 'bg-red-500'
              )}
            />
          )}
          <span className="text-xs text-slate-400">
            {authLoading
              ? 'Checking...'
              : isAuthenticated
                ? 'Fyers Connected'
                : 'Fyers Disconnected'}
          </span>
        </Link>

        <span className="rounded-md bg-yellow-500/20 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-yellow-400">
          Paper Mode
        </span>

        <div className="flex items-center gap-2 text-sm text-slate-400">
          <span>IST</span>
          <span className="font-mono text-slate-200">{time}</span>
        </div>
      </div>
    </header>
  );
}

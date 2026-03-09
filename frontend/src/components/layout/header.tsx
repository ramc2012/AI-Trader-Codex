'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getCurrentIST } from '@/lib/formatters';
import { useAuth } from '@/contexts/auth-context';
import { cn } from '@/lib/utils';
import { APP_DISPLAY_NAME } from '@/lib/app-brand';

export function Header() {
  const [time, setTime] = useState<string>(() => getCurrentIST());
  const { isAuthenticated, isLoading: authLoading } = useAuth();

  useEffect(() => {
    const interval = setInterval(() => {
      setTime(getCurrentIST());
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="fixed left-48 right-0 top-0 z-30 flex h-10 items-center justify-between border-b border-slate-800 bg-[#020617]/90 px-4 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <span className="text-[10px] font-mono text-slate-600 uppercase tracking-widest">
          {APP_DISPLAY_NAME}
        </span>
      </div>

      <div className="flex items-center gap-3">
        {/* Fyers status */}
        <Link
          href="/settings"
          className="flex items-center gap-1.5 rounded px-2 py-0.5 transition-colors hover:bg-slate-800"
        >
          {authLoading ? (
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-500" />
          ) : (
            <span
              className={cn(
                'h-1.5 w-1.5 rounded-full',
                isAuthenticated ? 'bg-emerald-500' : 'bg-red-500'
              )}
            />
          )}
          <span className="text-[10px] font-mono text-slate-500">
            {authLoading ? '...' : isAuthenticated ? 'FYERS' : 'OFFLINE'}
          </span>
        </Link>

        <span className="rounded bg-yellow-500/10 px-2 py-0.5 text-[10px] font-mono font-semibold uppercase tracking-wider text-yellow-500/80">
          Paper
        </span>

        <span className="font-mono text-[11px] text-slate-400">{time}</span>
      </div>
    </header>
  );
}

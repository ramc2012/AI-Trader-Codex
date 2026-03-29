'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  List,
  TrendingUp,
  Target,
  Shield,
  Brain,
  Briefcase,
  Activity,
  Settings,
  CandlestickChart,
  BarChart3,
  Zap,
  Radar,
  Landmark,
} from 'lucide-react';
import { useAuth } from '@/contexts/auth-context';
import { getCurrentIST } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import { APP_INSTANCE_LABEL, APP_NAME_BASE } from '@/lib/app-brand';

// ─── Nav config ──────────────────────────────────────────────────────────────

// "Charts" is a special group covering the analytics page and its sub-routes
const CHART_PREFIXES = ['/analytics', '/market', '/market-profile', '/order-flow'];

const NAV_ITEMS = [
  { href: '/',           label: 'Dashboard',  icon: LayoutDashboard, exact: true },
  { href: '/watchlist',  label: 'Watchlist',  icon: List },
  // 'charts' is rendered separately as a direct link
  { href: '/indices/nifty/options', label: 'Options', icon: TrendingUp, matchPrefix: '/indices' },
  { href: '/positions',  label: 'Positions',  icon: Briefcase },
  { href: '/portfolio',  label: 'Portfolio',  icon: BarChart3 },
  { href: '/strategies', label: 'Strategies', icon: Target },
  { href: '/scalping',   label: 'Scalping',   icon: Zap },
  { href: '/swing',      label: 'Swing',      icon: Activity },
  { href: '/positional', label: 'Positional', icon: Landmark },
  { href: '/fno-radar',  label: 'FNO Radar',  icon: Radar },
  { href: '/options-watchlist', label: 'ATM Watchlist', icon: List },
  { href: '/risk',       label: 'Risk',       icon: Shield },
  { href: '/ai-agent',   label: 'AI Agent',   icon: Brain },
  { href: '/monitoring', label: 'Monitoring', icon: Activity },
];

// ─── TopNav ──────────────────────────────────────────────────────────────────

export function TopNav() {
  const pathname = usePathname();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const [time, setTime] = useState(() => getCurrentIST());

  useEffect(() => {
    const t = setInterval(() => setTime(getCurrentIST()), 1000);
    return () => clearInterval(t);
  }, []);

  const isChartsActive = CHART_PREFIXES.some((p) => pathname.startsWith(p));

  const renderNavItem = (item: (typeof NAV_ITEMS)[0]) => {
    const isActive = item.exact
      ? pathname === item.href
      : item.matchPrefix
        ? pathname.startsWith(item.matchPrefix)
        : pathname.startsWith(item.href);
    const Icon = item.icon;

    return (
      <Link
        key={item.href}
        href={item.href}
        className={cn(
          'flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium font-mono transition-colors whitespace-nowrap',
          isActive
            ? 'bg-slate-800 text-emerald-400'
            : 'text-slate-500 hover:bg-slate-900/80 hover:text-slate-300'
        )}
      >
        <Icon className="h-3.5 w-3.5 shrink-0" />
        {item.label}
      </Link>
    );
  };

  return (
    <header className="fixed inset-x-0 top-0 z-40 flex h-11 items-center gap-0 border-b border-slate-800 bg-[#020617]/95 px-3 backdrop-blur-sm">
      {/* Logo */}
      <Link href="/" className="flex shrink-0 items-center gap-1.5 pr-3 border-r border-slate-800 mr-2">
        <TrendingUp className="h-4 w-4 text-emerald-500" />
        <span className="text-sm font-bold font-mono text-slate-200">{APP_NAME_BASE}</span>
        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] font-mono font-semibold text-emerald-300">
          {APP_INSTANCE_LABEL}
        </span>
      </Link>

      {/* Nav items */}
      <nav className="flex flex-1 items-center gap-0.5 overflow-x-auto scrollbar-none">
        {NAV_ITEMS.slice(0, 2).map(renderNavItem)}

        <Link
          href="/analytics?tab=charts"
          className={cn(
            'flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium font-mono transition-colors whitespace-nowrap',
            isChartsActive
              ? 'bg-slate-800 text-emerald-400'
              : 'text-slate-500 hover:bg-slate-900/80 hover:text-slate-300'
          )}
        >
          <CandlestickChart className="h-3.5 w-3.5 shrink-0" />
          Charts
        </Link>

        {NAV_ITEMS.slice(2).map(renderNavItem)}
      </nav>

      {/* Right status strip */}
      <div className="flex shrink-0 items-center gap-2 pl-2 border-l border-slate-800 ml-2">
        {/* Fyers auth status */}
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
                isAuthenticated ? 'bg-emerald-500 shadow-[0_0_4px_#10b981]' : 'bg-red-500'
              )}
            />
          )}
          <span className="text-[10px] font-mono text-slate-500">
            {authLoading ? '…' : isAuthenticated ? 'LIVE' : 'OFFLINE'}
          </span>
        </Link>

        <span className="rounded bg-yellow-500/10 px-2 py-0.5 text-[10px] font-mono font-semibold uppercase tracking-wider text-yellow-400/80">
          Paper
        </span>

        <span className="font-mono text-[11px] text-slate-400 tabular-nums">{time}</span>

        <Link
          href="/settings"
          className="rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-slate-300 transition-colors"
        >
          <Settings className="h-3.5 w-3.5" />
        </Link>
      </div>
    </header>
  );
}

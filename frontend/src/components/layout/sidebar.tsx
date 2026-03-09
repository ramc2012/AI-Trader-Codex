'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  Briefcase,
  Target,
  Shield,
  Activity,
  FlaskConical,
  List,
  Settings,
  TrendingUp,
  BarChart2,
  BarChart3,
  Brain,
  CandlestickChart,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { APP_INSTANCE_LABEL, APP_NAME_BASE } from '@/lib/app-brand';

const navItems = [
  { href: '/',              label: 'Dashboard',  icon: LayoutDashboard },
  { href: '/watchlist',     label: 'Watchlist',   icon: List },
  { href: '/analytics?tab=charts',  label: 'Charts',  icon: CandlestickChart, matchPrefix: '/analytics' },
  { href: '/analytics?tab=profile', label: 'Profile', icon: BarChart3, matchPrefix: '/analytics' },
  { href: '/indices/nifty/options', matchPrefix: '/indices', label: 'Options', icon: TrendingUp },
  { href: '/positions',     label: 'Positions',   icon: Briefcase },
  { href: '/portfolio',     label: 'Portfolio',   icon: BarChart3 },
  { href: '/strategies',    label: 'Strategies',  icon: Target },
  { href: '/risk',          label: 'Risk',        icon: Shield },
  { href: '/analytics?tab=orderflow', label: 'Analytics', icon: BarChart2, matchPrefix: '/analytics' },
  { href: '/backtest',      label: 'Backtest',    icon: FlaskConical },
  { href: '/monitoring',    label: 'Monitoring',  icon: Activity },
  { href: '/ai-agent',      label: 'AI Agent',    icon: Brain },
];

const bottomNavItems = [
  { href: '/settings', label: 'Settings', icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  const renderNavLink = (item: (typeof navItems)[0]) => {
    const matchPrefix = 'matchPrefix' in item ? item.matchPrefix : undefined;
    const isActive =
      item.href === '/'
        ? pathname === '/'
        : matchPrefix
          ? pathname.startsWith(matchPrefix)
          : pathname.startsWith(item.href);
    const Icon = item.icon;

    return (
      <Link
        key={item.href}
        href={item.href}
        className={cn(
          'flex items-center gap-2.5 rounded px-2.5 py-1.5 text-xs font-medium font-mono transition-colors',
          isActive
            ? 'bg-slate-800/80 text-emerald-400'
            : 'text-slate-500 hover:bg-slate-900 hover:text-slate-300'
        )}
      >
        <Icon className="h-3.5 w-3.5 flex-shrink-0" />
        {item.label}
      </Link>
    );
  };

  return (
    <aside className="fixed left-0 top-0 z-40 flex h-screen w-48 flex-col border-r border-slate-800 bg-[#020617]">
      <div className="flex h-10 items-center gap-1.5 border-b border-slate-800 px-4">
        <TrendingUp className="h-4 w-4 text-emerald-500" />
        <span className="text-sm font-bold font-mono text-slate-200">{APP_NAME_BASE}</span>
        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] font-mono font-semibold text-emerald-300">
          {APP_INSTANCE_LABEL}
        </span>
      </div>

      <nav className="flex-1 space-y-0.5 px-2 py-2 overflow-y-auto">
        {navItems.map(renderNavLink)}
      </nav>

      <div className="border-t border-slate-800 px-2 py-1.5">
        {bottomNavItems.map(renderNavLink)}
      </div>
    </aside>
  );
}

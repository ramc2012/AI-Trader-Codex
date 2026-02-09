'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  Briefcase,
  Target,
  Shield,
  CandlestickChart,
  Activity,
  FlaskConical,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const navItems = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/positions', label: 'Positions', icon: Briefcase },
  { href: '/strategies', label: 'Strategies', icon: Target },
  { href: '/risk', label: 'Risk', icon: Shield },
  { href: '/market', label: 'Market', icon: CandlestickChart },
  { href: '/monitoring', label: 'Monitoring', icon: Activity },
  { href: '/backtest', label: 'Backtest', icon: FlaskConical },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 z-40 flex h-screen w-60 flex-col border-r border-slate-800 bg-slate-950">
      <div className="flex h-16 items-center gap-2 border-b border-slate-800 px-6">
        <CandlestickChart className="h-6 w-6 text-emerald-500" />
        <span className="text-lg font-bold text-slate-100">NiftyAI</span>
      </div>

      <nav className="flex-1 space-y-1 px-3 py-4">
        {navItems.map((item) => {
          const isActive =
            item.href === '/'
              ? pathname === '/'
              : pathname.startsWith(item.href);
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-slate-800 text-emerald-400'
                  : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'
              )}
            >
              <Icon className="h-5 w-5" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-slate-800 px-4 py-3">
        <p className="text-xs text-slate-500">Nifty AI Trader v0.1</p>
      </div>
    </aside>
  );
}

'use client';

import { useIndicesWS } from '@/hooks/use-indices-ws';
import { cn } from '@/lib/utils';

// ─── Config ──────────────────────────────────────────────────────────────────

const INDICES = [
  { name: 'NIFTY',      label: 'NIFTY 50' },
  { name: 'BANKNIFTY',  label: 'BANK NIFTY' },
  { name: 'FINNIFTY',   label: 'FIN NIFTY' },
  { name: 'MIDCPNIFTY', label: 'MIDCAP' },
  { name: 'SENSEX',     label: 'SENSEX' },
];

function fmt(n: number) {
  return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pctFmt(n: number) {
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

// ─── TickerStrip ─────────────────────────────────────────────────────────────

export function TickerStrip() {
  const { prices, isConnected } = useIndicesWS(true);

  return (
    <div className="fixed inset-x-0 top-11 z-30 flex h-7 items-center gap-0 border-b border-slate-800/60 bg-slate-950/90 px-3 backdrop-blur-sm overflow-x-auto scrollbar-none">
      {/* WS connection indicator */}
      <span
        className={cn(
          'shrink-0 h-1.5 w-1.5 rounded-full mr-2',
          isConnected ? 'bg-emerald-500' : 'bg-slate-600'
        )}
        title={isConnected ? 'Live tick feed connected' : 'Tick feed disconnected'}
      />

      {/* Index prices */}
      <div className="flex flex-1 items-center gap-0">
        {INDICES.map((idx, i) => {
          const p = prices[idx.name];
          const isUp = (p?.change_pct ?? 0) >= 0;

          return (
            <div
              key={idx.name}
              className={cn(
                'flex items-center gap-2 px-3 text-xs whitespace-nowrap',
                i < INDICES.length - 1 && 'border-r border-slate-800'
              )}
            >
              <span className="font-mono font-semibold text-[11px] text-slate-400">{idx.label}</span>
              {p ? (
                <>
                  <span className="font-mono font-bold text-slate-100">{fmt(p.ltp)}</span>
                  <span
                    className={cn(
                      'font-mono text-[10px] font-medium',
                      isUp ? 'text-emerald-400' : 'text-red-400'
                    )}
                  >
                    {pctFmt(p.change_pct ?? 0)}
                  </span>
                </>
              ) : (
                <span className="font-mono text-[10px] text-slate-600">—</span>
              )}
            </div>
          );
        })}
      </div>

      {/* Right label */}
      <span className="shrink-0 pl-3 border-l border-slate-800 text-[10px] font-mono text-slate-600 uppercase tracking-widest">
        {isConnected ? 'Tick Feed' : 'Polling'}
      </span>
    </div>
  );
}

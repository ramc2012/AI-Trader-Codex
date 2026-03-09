'use client';

import { useMemo } from 'react';
import type { FootprintBar } from '@/hooks/use-orderflow';
import { cn } from '@/lib/utils';

interface FootprintChartProps {
  data: FootprintBar[];
  height?: string;
}

/**
 * Simplified footprint (order-flow) chart rendered with HTML/CSS.
 *
 * Each bar is a vertical column of price levels. Within each level the
 * bid volume is shown as a red bar on the left and the ask volume as a
 * green bar on the right. The delta for the entire bar is printed at the
 * bottom. Imbalanced levels receive a highlighted background.
 */
export function FootprintChart({ data, height = '520px' }: FootprintChartProps) {
  // Determine the global max volume for scaling the width of bid/ask bars.
  const maxVol = useMemo(() => {
    let m = 1;
    for (const bar of data) {
      for (const lvl of bar.levels) {
        if (lvl.bid > m) m = lvl.bid;
        if (lvl.ask > m) m = lvl.ask;
      }
    }
    return m;
  }, [data]);

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60 text-sm text-slate-500"
        style={{ height }}
      >
        No footprint data available
      </div>
    );
  }

  const hasMeaningfulPrints = data.some(
    (bar) =>
      bar.volume > 0 ||
      Math.abs(bar.delta) > 0 ||
      bar.levels.some((lvl) => lvl.bid > 0 || lvl.ask > 0),
  );

  if (!hasMeaningfulPrints) {
    return (
      <div
        className="flex items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60 text-sm text-slate-500"
        style={{ height }}
      >
        Waiting for meaningful order-flow prints
      </div>
    );
  }

  return (
    <div
      className="overflow-x-auto overflow-y-hidden rounded-xl border border-slate-800 bg-slate-900/60"
      style={{ height }}
    >
      <div className="flex h-full min-w-max items-stretch gap-px p-2">
        {data.map((bar, barIdx) => {
          const isBullish = bar.close >= bar.open;
          const sortedLevels = [...bar.levels]
            .filter((lvl) => lvl.bid > 0 || lvl.ask > 0)
            .sort((a, b) => b.price - a.price);
          const timeLabel = formatBarTime(bar.time);

          return (
            <div
              key={barIdx}
              className="flex flex-col"
              style={{ minWidth: 160, maxWidth: 200 }}
            >
              {/* Time header */}
              <div className="mb-1 text-center font-mono text-[10px] text-slate-500">
                {timeLabel}
              </div>

              {/* Price levels */}
              <div className="flex flex-1 flex-col gap-px overflow-y-auto">
                {sortedLevels.length === 0 && (
                  <div className="rounded-sm bg-slate-800/40 px-2 py-1 font-mono text-[10px] text-slate-500">
                    No prints
                  </div>
                )}
                {sortedLevels.map((lvl, lvlIdx) => {
                  const bidPct = (lvl.bid / maxVol) * 100;
                  const askPct = (lvl.ask / maxVol) * 100;
                  const isAtOpen = lvl.price === bar.open;
                  const isAtClose = lvl.price === bar.close;
                  const isImbalance =
                    typeof lvl.imbalance === 'number' ? lvl.imbalance >= 0.3 : Boolean(lvl.imbalance);

                  return (
                    <div
                      key={lvlIdx}
                      className={cn(
                        'group relative flex items-center gap-0.5 rounded-sm px-1 py-px font-mono text-[10px]',
                        isImbalance
                          ? 'bg-amber-500/10 border border-amber-500/30'
                          : 'bg-slate-800/40',
                        isAtOpen && 'ring-1 ring-inset ring-blue-500/40',
                        isAtClose && 'ring-1 ring-inset ring-white/20'
                      )}
                    >
                      {/* Bid bar (left, red) */}
                      <div className="flex w-[45%] items-center justify-end gap-1">
                        <span className="w-8 text-right text-red-400/80">
                          {lvl.bid > 0 ? formatVol(lvl.bid) : ''}
                        </span>
                        <div className="h-2.5 flex-1">
                          <div
                            className="ml-auto h-full rounded-sm bg-red-500/50"
                            style={{ width: `${Math.max(bidPct, lvl.bid > 0 ? 2 : 0)}%` }}
                          />
                        </div>
                      </div>

                      {/* Price label (center) */}
                      <div
                        className={cn(
                          'w-[10%] text-center text-[9px] font-semibold',
                          isAtClose
                            ? isBullish
                              ? 'text-emerald-300'
                              : 'text-red-300'
                            : 'text-slate-400'
                        )}
                      >
                        {lvl.price.toFixed(1)}
                      </div>

                      {/* Ask bar (right, green) */}
                      <div className="flex w-[45%] items-center gap-1">
                        <div className="h-2.5 flex-1">
                          <div
                            className="h-full rounded-sm bg-emerald-500/50"
                            style={{ width: `${Math.max(askPct, lvl.ask > 0 ? 2 : 0)}%` }}
                          />
                        </div>
                        <span className="w-8 text-left text-emerald-400/80">
                          {lvl.ask > 0 ? formatVol(lvl.ask) : ''}
                        </span>
                      </div>

                      {/* Imbalance indicator */}
                      {isImbalance && (
                        <span className="absolute -right-0.5 top-0 h-1.5 w-1.5 rounded-full bg-amber-400" />
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Delta footer */}
              <div
                className={cn(
                  'mt-1 rounded-md py-1 text-center font-mono text-xs font-bold',
                  bar.delta >= 0
                    ? 'bg-emerald-500/10 text-emerald-400'
                    : 'bg-red-500/10 text-red-400'
                )}
              >
                {bar.delta >= 0 ? '+' : ''}
                {formatVol(bar.delta)}
              </div>

              {/* Volume + VWAP */}
              <div className="mt-0.5 flex justify-between px-1 font-mono text-[9px] text-slate-500">
                <span>V: {formatVol(bar.volume)}</span>
                <span>VWAP: {bar.vwap.toFixed(1)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatBarTime(time: string): string {
  try {
    const d = new Date(time);
    return d.toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  } catch {
    return time;
  }
}

function formatVol(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_00_00_000) return `${(v / 1_00_00_000).toFixed(1)}Cr`;
  if (abs >= 1_00_000) return `${(v / 1_00_000).toFixed(1)}L`;
  if (abs >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}

export default FootprintChart;

'use client';

import { useMemo } from 'react';
import { CHART_COLORS } from '@/lib/echarts-theme';

interface TPOLevel {
  price: number;
  tpo_count: number;
  letters: string[];
  volume: number;
}

interface TPOChartProps {
  levels: TPOLevel[];
  poc: number;
  vah: number;
  val: number;
  ibHigh: number;
  ibLow: number;
  height?: string;
}

export function TPOChart({ levels, poc, vah, val, ibHigh, ibLow, height = '500px' }: TPOChartProps) {
  const maxTPO = useMemo(() => Math.max(...levels.map((l) => l.tpo_count), 1), [levels]);

  return (
    <div style={{ height }} className="overflow-y-auto font-mono text-xs">
      {levels.slice().reverse().map((level) => {
        const barWidth = (level.tpo_count / maxTPO) * 100;
        const isPOC = level.price === poc;
        const isVA = level.price >= val && level.price <= vah;
        const isIB = level.price >= ibLow && level.price <= ibHigh;

        let bgClass = '';
        if (isPOC) bgClass = 'bg-amber-500/20';
        else if (isVA) bgClass = 'bg-blue-500/10';

        return (
          <div key={level.price} className={`flex items-center gap-2 py-0.5 px-1 ${bgClass}`}>
            {/* Price label */}
            <span className={`w-16 text-right ${isPOC ? 'text-amber-400 font-bold' : 'text-slate-500'}`}>
              {level.price.toFixed(1)}
            </span>

            {/* IB marker */}
            <span className="w-3 text-center">
              {isIB ? <span className="text-cyan-400">│</span> : ' '}
            </span>

            {/* TPO letters */}
            <div className="flex-1 flex items-center">
              <span
                className={`inline-block ${isPOC ? 'text-amber-300' : isVA ? 'text-blue-300' : 'text-slate-400'}`}
                style={{ minWidth: `${barWidth}%` }}
              >
                {level.letters.join('')}
              </span>
            </div>

            {/* Volume */}
            <span className="w-12 text-right text-slate-600">{level.tpo_count}</span>
          </div>
        );
      })}

      {/* Legend */}
      <div className="flex gap-4 px-2 py-2 mt-2 border-t border-slate-800 text-slate-500">
        <span><span className="text-amber-400">■</span> POC ({poc.toFixed(1)})</span>
        <span><span className="text-blue-400">■</span> Value Area ({val.toFixed(1)} - {vah.toFixed(1)})</span>
        <span><span className="text-cyan-400">│</span> IB ({ibLow.toFixed(1)} - {ibHigh.toFixed(1)})</span>
      </div>
    </div>
  );
}

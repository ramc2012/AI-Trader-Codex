'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Landmark,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  ArrowUpRight,
  ArrowDownRight,
  BarChart3,
  Activity,
  AlertCircle,
  Calendar,
  ArrowRight,
  DollarSign,
  Target,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useStreamingStyle } from '@/hooks/use-streaming-style';
import { usePositions } from '@/hooks/use-positions';
import { formatCurrency } from '@/lib/formatters';

interface PositionalSignal {
  symbol: string;
  direction: string;
  strategy: string;
  crossover: string;
  price: number;
  target: number;
  stop_loss: number;
  ema_fast: number;
  ema_slow: number;
  hold_weeks: number;
  strength: string;
  rrg_quadrant?: string;
  rs?: number;
  momentum?: number;
}

function PositionalRow({ signal }: { signal: PositionalSignal }) {
  const isBullish = signal.direction === 'bullish' || signal.crossover === 'golden';
  return (
    <tr className="hover:bg-slate-800/30 transition-colors border-b border-slate-800/50">
      <td className="px-4 py-3">
        <div className="font-semibold text-sm text-slate-100">{signal.symbol}</div>
        <div className="text-[10px] text-slate-500">{signal.strategy}</div>
      </td>
      <td className="px-4 py-3">
        <span className={cn(
          'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium',
          isBullish
            ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
            : 'bg-red-500/10 text-red-300 border-red-500/20'
        )}>
          {isBullish ? <TrendingUp className="h-2.5 w-2.5" /> : <TrendingDown className="h-2.5 w-2.5" />}
          {signal.crossover === 'golden' ? 'Golden Cross' : signal.crossover === 'death' ? 'Death Cross' :
            signal.rrg_quadrant === 'leading' ? 'RRG Leading' : signal.rrg_quadrant === 'lagging' ? 'RRG Lagging' : signal.direction}
        </span>
      </td>
      <td className="px-4 py-3 text-right font-mono text-sm text-slate-300">₹{signal.price.toFixed(2)}</td>
      <td className="px-4 py-3 text-right">
        <div className="font-mono text-xs text-emerald-400">₹{signal.target.toFixed(2)}</div>
        <div className="font-mono text-xs text-red-400">₹{signal.stop_loss.toFixed(2)}</div>
      </td>
      <td className="px-4 py-3 text-right text-xs">
        {signal.ema_fast > 0 && (
          <div className="text-slate-400">
            EMA {signal.ema_fast.toFixed(0)}/{signal.ema_slow.toFixed(0)}
          </div>
        )}
        {signal.rs && <div className="text-blue-400">RS: {signal.rs.toFixed(1)}</div>}
      </td>
      <td className="px-4 py-3 text-right text-xs text-slate-400">
        <div className="flex items-center justify-end gap-1">
          <Calendar className="h-3 w-3" />
          {signal.hold_weeks}w
        </div>
      </td>
      <td className="px-4 py-3 text-right">
        <span className={cn(
          'rounded-full px-2 py-0.5 text-[10px] font-semibold',
          signal.strength === 'strong' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-blue-500/20 text-blue-300'
        )}>
          {signal.strength.toUpperCase()}
        </span>
      </td>
    </tr>
  );
}

export default function PositionalPage() {
  const { signals: rawSignals, loading, refresh } = useStreamingStyle('positional');
  const { data: allPositions = [] } = usePositions();

  const positionalPositions = allPositions.filter(p => {
    const s = (p.strategy_tag || '').toLowerCase();
    return s.includes('trend') || s.includes('rotation') || s.includes('golden') || s.includes('options');
  });

  const activePnl = positionalPositions.reduce(
    (sum, p) => sum + (p.unrealized_pnl_inr ?? p.unrealized_pnl ?? 0), 
    0
  );

  const signals: PositionalSignal[] = rawSignals.map(s => ({
    symbol: s.symbol,
    direction: s.direction === 'BUY' ? 'bullish' : 'bearish',
    strategy: s.strategy,
    crossover: s.metadata?.crossover || '',
    price: s.price,
    target: s.target,
    stop_loss: s.stop_loss,
    ema_fast: s.metadata?.ema_fast || 0,
    ema_slow: s.metadata?.ema_slow || 0,
    hold_weeks: Math.ceil(s.hold_minutes / (5 * 390)),
    strength: s.strength,
    rrg_quadrant: s.metadata?.rrg_quadrant,
    rs: s.metadata?.rs,
    momentum: s.metadata?.momentum,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-purple-500/10">
            <Landmark className="h-5 w-5 text-purple-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-100">Positional Trades</h1>
            <p className="text-xs text-slate-500">EMA crossover + sector rotation (RRG) • Daily/weekly charts • Multi-week positions</p>
          </div>
        </div>
        <button onClick={refresh} className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors">
          <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} />
          Refresh
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-3">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="flex items-center justify-between mb-1"><span className="text-xs text-slate-500">Signals</span><Activity className="h-4 w-4 text-purple-400" /></div>
          <div className="text-2xl font-bold text-purple-400">{signals.length}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="flex items-center justify-between mb-1"><span className="text-xs text-slate-500">Golden Cross</span><ArrowUpRight className="h-4 w-4 text-emerald-400" /></div>
          <div className="text-2xl font-bold text-emerald-400">{signals.filter(s => s.crossover === 'golden').length}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="flex items-center justify-between mb-1"><span className="text-xs text-slate-500">Death Cross</span><ArrowDownRight className="h-4 w-4 text-red-400" /></div>
          <div className="text-2xl font-bold text-red-400">{signals.filter(s => s.crossover === 'death').length}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="flex items-center justify-between mb-1"><span className="text-xs text-slate-500">RRG Signals</span><BarChart3 className="h-4 w-4 text-blue-400" /></div>
          <div className="text-2xl font-bold text-blue-400">{signals.filter(s => s.rrg_quadrant).length}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="text-xs text-slate-500 mb-1 flex justify-between items-center">
            <span>Active P&L</span>
            <DollarSign className="h-3 w-3 text-slate-500" />
          </div>
          <div className={cn("text-2xl font-bold", activePnl >= 0 ? "text-emerald-400" : "text-red-400")}>
            {formatCurrency(activePnl, 'INR')}
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
        <div className="border-b border-slate-800 p-4">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <Landmark className="h-4 w-4 text-purple-400" />
            Positional Candidates
          </h2>
        </div>
        {loading ? (
          <div>{Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-14 animate-pulse border-b border-slate-800/50 bg-slate-900/40" />)}</div>
        ) : signals.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16">
            <Landmark className="h-10 w-10 text-slate-700 mb-3" />
            <p className="text-sm text-slate-400">No positional signals</p>
            <p className="text-xs text-slate-600 mt-1">Scanning for EMA crossovers and RRG sector rotation</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-left text-slate-500">
                  <th className="px-4 py-2.5 font-medium">Symbol</th>
                  <th className="px-4 py-2.5 font-medium">Signal</th>
                  <th className="px-4 py-2.5 font-medium text-right">Price</th>
                  <th className="px-4 py-2.5 font-medium text-right">Target / SL</th>
                  <th className="px-4 py-2.5 font-medium text-right">Indicators</th>
                  <th className="px-4 py-2.5 font-medium text-right">Hold</th>
                  <th className="px-4 py-2.5 font-medium text-right">Strength</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((s, i) => <PositionalRow key={i} signal={s} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Live Positions */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-800 p-4">
          <div className="flex items-center gap-2">
            <Target className="h-4 w-4 text-blue-400" />
            <h2 className="text-sm font-semibold text-slate-200">Active Positional Trades</h2>
          </div>
        </div>
        <div className="p-4">
          {positionalPositions.length === 0 ? (
            <div className="text-center py-6 text-sm text-slate-500">No active positional positions</div>
          ) : (
            <div className="space-y-2">
              {positionalPositions.map((pos, i) => {
                const pnlInr = pos.unrealized_pnl_inr ?? pos.unrealized_pnl ?? 0;
                return (
                  <div key={i} className="flex flex-wrap items-center justify-between rounded-lg border border-slate-800 bg-slate-900/40 p-3 hover:bg-slate-800/40 transition-colors gap-4">
                    <div className="flex items-center gap-3">
                      <div className="font-semibold text-sm text-slate-100 min-w-[120px]">{pos.symbol}</div>
                      <span className={cn('px-2 py-0.5 rounded text-[10px] uppercase font-bold', String(pos.side).toUpperCase() === 'BUY' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400')}>
                        {pos.side}
                      </span>
                    </div>
                    
                    <div className="flex items-center gap-6 text-xs">
                      <div className="text-slate-400 flex items-center gap-2">
                        <span>{formatCurrency(pos.avg_price, 'INR')}</span>
                        <ArrowRight className="h-3 w-3" />
                        <span className="text-slate-200">{formatCurrency(pos.current_price, 'INR')}</span>
                      </div>
                      
                      <div className={cn("text-right font-mono min-w-[80px]", pnlInr >= 0 ? "text-emerald-400" : "text-red-400")}>
                        {formatCurrency(pnlInr, 'INR')}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-4">
        <div className="flex items-start gap-2">
          <AlertCircle className="h-4 w-4 text-purple-400 mt-0.5 shrink-0" />
          <div className="text-xs text-slate-500 leading-relaxed">
            <strong className="text-slate-400">Strategies:</strong> Trend Following (EMA 50/200 golden/death crossover with weekly confirmation)
            and Sector Rotation (RRG-inspired relative strength analysis). Target 6-8% profit, 3-4% stop loss, 4-8 week holding period.
          </div>
        </div>
      </div>
    </div>
  );
}

'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Activity,
  BarChart3,
  Target,
  Clock,
  AlertCircle,
  ArrowUpRight,
  ArrowDownRight,
  ArrowRight,
  DollarSign,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useStreamingStyle } from '@/hooks/use-streaming-style';
import { usePositions } from '@/hooks/use-positions';
import { formatCurrency } from '@/lib/formatters';

interface SwingCandidate {
  symbol: string;
  direction: string;
  conviction: number;
  strategy: string;
  entry_price: number;
  target: number;
  stop_loss: number;
  strength: string;
  daily_alignment: boolean;
  orderflow_confirmed: boolean;
  consecutive_hours: number;
  hold_days: number;
}

function ConvictionBar({ level }: { level: number }) {
  return (
    <div className="flex items-center gap-1">
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className={cn(
          'h-2 w-3 rounded-sm',
          i <= level
            ? level >= 4 ? 'bg-emerald-400' : level >= 3 ? 'bg-blue-400' : 'bg-slate-500'
            : 'bg-slate-800'
        )} />
      ))}
      <span className="text-[10px] text-slate-500 ml-1">{level}/5</span>
    </div>
  );
}

function CandidateCard({ candidate }: { candidate: SwingCandidate }) {
  const isBullish = candidate.direction === 'bullish';
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 hover:bg-slate-800/40 transition-colors">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className={cn(
            'flex items-center justify-center w-8 h-8 rounded-lg',
            isBullish ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'
          )}>
            {isBullish ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />}
          </div>
          <div>
            <div className="font-semibold text-sm text-slate-100">{candidate.symbol}</div>
            <div className="text-[10px] text-slate-500">{candidate.strategy}</div>
          </div>
        </div>
        <span className={cn(
          'rounded-full border px-2 py-0.5 text-[10px] font-medium',
          isBullish
            ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
            : 'bg-red-500/10 text-red-300 border-red-500/20'
        )}>
          {candidate.direction.toUpperCase()}
        </span>
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-500">Conviction</span>
          <ConvictionBar level={candidate.conviction} />
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-500">Entry</span>
          <span className="font-mono text-slate-300">₹{candidate.entry_price.toFixed(2)}</span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-500">Target / SL</span>
          <span className="font-mono">
            <span className="text-emerald-400">₹{candidate.target.toFixed(2)}</span>
            {' / '}
            <span className="text-red-400">₹{candidate.stop_loss.toFixed(2)}</span>
          </span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-500">Hold Period</span>
          <span className="text-slate-400 flex items-center gap-1">
            <Clock className="h-3 w-3" />{candidate.hold_days} days
          </span>
        </div>
        <div className="flex gap-2 mt-2">
          {candidate.daily_alignment && (
            <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[9px] text-emerald-400">DAILY ALIGNED</span>
          )}
          {candidate.orderflow_confirmed && (
            <span className="rounded bg-blue-500/10 px-1.5 py-0.5 text-[9px] text-blue-400">FLOW CONFIRMED</span>
          )}
          {candidate.consecutive_hours >= 3 && (
            <span className="rounded bg-purple-500/10 px-1.5 py-0.5 text-[9px] text-purple-400">{candidate.consecutive_hours}H MIGRATION</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function SwingPage() {
  const [filter, setFilter] = useState<'all' | 'bullish' | 'bearish'>('all');
  const { signals: rawSignals, loading, refresh } = useStreamingStyle('swing');
  const { data: allPositions = [] } = usePositions();

  const swingPositions = allPositions.filter(p => {
    const s = (p.strategy_tag || '').toLowerCase();
    return s.includes('swing') || s.includes('fractal');
  });

  const activePnl = swingPositions.reduce(
    (sum, p) => sum + (p.unrealized_pnl_inr ?? p.unrealized_pnl ?? 0), 
    0
  );

  const candidates: SwingCandidate[] = rawSignals.map(s => ({
    symbol: s.symbol,
    direction: s.direction === 'BUY' ? 'bullish' : 'bearish',
    strategy: s.strategy,
    conviction: s.metadata?.conviction || (s.strength === 'strong' ? 4 : 3),
    entry_price: s.price,
    target: s.target,
    stop_loss: s.stop_loss,
    strength: s.strength,
    daily_alignment: s.metadata?.daily_alignment || false,
    orderflow_confirmed: s.metadata?.orderflow_confirmed || false,
    consecutive_hours: s.metadata?.consecutive_hours || 0,
    hold_days: Math.ceil(s.hold_minutes / 390),
  }));

  const filtered = filter === 'all' ? candidates : candidates.filter(c => c.direction === filter);
  const bullish = candidates.filter(c => c.direction === 'bullish').length;
  const bearish = candidates.filter(c => c.direction === 'bearish').length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-blue-500/10">
            <BarChart3 className="h-5 w-5 text-blue-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-100">Swing Trading</h1>
            <p className="text-xs text-slate-500">Fractal radar + RSI divergence • 1H-1D charts • Multi-day holds</p>
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
          <div className="text-xs text-slate-500 mb-1">Total Candidates</div>
          <div className="text-2xl font-bold text-blue-400">{candidates.length}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="text-xs text-slate-500 mb-1">Bullish</div>
          <div className="text-2xl font-bold text-emerald-400">{bullish}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="text-xs text-slate-500 mb-1">Bearish</div>
          <div className="text-2xl font-bold text-red-400">{bearish}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="text-xs text-slate-500 mb-1">Avg Conviction</div>
          <div className="text-2xl font-bold text-slate-300">
            {candidates.length > 0 ? (candidates.reduce((s, c) => s + c.conviction, 0) / candidates.length).toFixed(1) : '—'}
          </div>
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

      {/* Filter tabs */}
      <div className="flex gap-1 rounded-xl border border-slate-800 bg-slate-900/60 p-1 w-fit">
        {(['all', 'bullish', 'bearish'] as const).map(f => (
          <button key={f} onClick={() => setFilter(f)} className={cn(
            'rounded-lg px-3 py-1.5 text-xs font-medium transition-colors capitalize',
            filter === f ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200'
          )}>
            {f === 'all' ? `All (${candidates.length})` : f === 'bullish' ? `Bullish (${bullish})` : `Bearish (${bearish})`}
          </button>
        ))}
      </div>

      {/* Candidates */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-48 animate-pulse rounded-xl bg-slate-800/50" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 rounded-xl border border-slate-800 bg-slate-900/60">
          <BarChart3 className="h-10 w-10 text-slate-700 mb-3" />
          <p className="text-sm text-slate-400">No swing candidates found</p>
          <p className="text-xs text-slate-600 mt-1">Scanning for fractal profiles + divergence patterns</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filtered.map((c, i) => <CandidateCard key={i} candidate={c} />)}
        </div>
      )}

      {/* Live Positions */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-800 p-4">
          <div className="flex items-center gap-2">
            <Target className="h-4 w-4 text-blue-400" />
            <h2 className="text-sm font-semibold text-slate-200">Active Swing Trades</h2>
          </div>
        </div>
        <div className="p-4">
          {swingPositions.length === 0 ? (
            <div className="text-center py-6 text-sm text-slate-500">No active swing positions</div>
          ) : (
            <div className="space-y-2">
              {swingPositions.map((pos, i) => {
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
          <AlertCircle className="h-4 w-4 text-blue-400 mt-0.5 shrink-0" />
          <div className="text-xs text-slate-500 leading-relaxed">
            <strong className="text-slate-400">Strategies:</strong> Fractal Swing (market profile TPO analysis with conviction scoring)
            and Divergence Swing (RSI/price divergence detection). Minimum conviction 3/5 required. Signals confirmed
            by daily chart alignment and aggressive order flow.
          </div>
        </div>
      </div>
    </div>
  );
}

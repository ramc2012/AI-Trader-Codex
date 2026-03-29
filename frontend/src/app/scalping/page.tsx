'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Zap,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Activity,
  Clock,
  DollarSign,
  Target,
  AlertCircle,
  ArrowRight,
} from 'lucide-react';
import { cn } from '@/lib/utils';

import { useStreamingStyle, type StyleSignal } from '@/hooks/use-streaming-style';
import { usePositions } from '@/hooks/use-positions';
import { formatCurrency, formatPercent } from '@/lib/formatters';

// Maps StyleSignal back to ScalpSignal for UI rendering (since they are identical here)
type ScalpSignal = StyleSignal;

// ─── Stats Card ──────────────────────────────────────────────────────────────

function StatCard({ label, value, subtext, color, icon: Icon }: {
  label: string; value: string; subtext?: string; color: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-slate-500">{label}</span>
        <Icon className={cn('h-4 w-4', color)} />
      </div>
      <div className={cn('text-2xl font-bold', color)}>{value}</div>
      {subtext && <div className="text-[10px] text-slate-500 mt-1">{subtext}</div>}
    </div>
  );
}

// ─── Signal Row ──────────────────────────────────────────────────────────────

function SignalRow({ signal }: { signal: ScalpSignal }) {
  const isBuy = signal.direction === 'BUY';
  return (
    <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/40 p-3 hover:bg-slate-800/40 transition-colors">
      <div className="flex items-center gap-3">
        <div className={cn(
          'flex items-center justify-center w-8 h-8 rounded-lg',
          isBuy ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'
        )}>
          {isBuy ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
        </div>
        <div>
          <div className="font-semibold text-sm text-slate-100">{signal.symbol}</div>
          <div className="text-[10px] text-slate-500">{signal.strategy} • VWAP: ₹{signal.vwap?.toFixed(1)}</div>
        </div>
      </div>
      <div className="flex items-center gap-4 text-xs">
        <div className="text-right">
          <div className="text-slate-300 font-mono">₹{signal.price?.toFixed(2)}</div>
          <div className="text-slate-500">Vol: {signal.vol_ratio?.toFixed(1)}×</div>
        </div>
        <div className="text-right">
          <div className="text-emerald-400 font-mono">T: ₹{signal.target?.toFixed(2)}</div>
          <div className="text-red-400 font-mono">SL: ₹{signal.stop_loss?.toFixed(2)}</div>
        </div>
        <div className="flex items-center gap-1 text-slate-500">
          <Clock className="h-3 w-3" />
          <span>{signal.hold_minutes}m</span>
        </div>
        <span className={cn(
          'rounded-full px-2 py-0.5 text-[10px] font-semibold',
          signal.strength === 'strong' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-blue-500/20 text-blue-300'
        )}>
          {signal.strength?.toUpperCase()}
        </span>
      </div>
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function ScalpingPage() {
  const { signals, loading, refresh } = useStreamingStyle('scalping');
  const { data: allPositions = [] } = usePositions();

  const scalpPositions = allPositions.filter(p => {
    const s = (p.strategy_tag || '').toLowerCase();
    return s.includes('scalp') || s.includes('vwap');
  });

  const activePnl = scalpPositions.reduce(
    (sum, p) => sum + (p.unrealized_pnl_inr ?? p.unrealized_pnl ?? 0), 
    0
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-yellow-500/10">
            <Zap className="h-5 w-5 text-yellow-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-100">Scalping Dashboard</h1>
            <p className="text-xs text-slate-500">VWAP deviation + volume spike trades • 1-5 min timeframes</p>
          </div>
        </div>
        <button
          onClick={refresh}
          className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
        >
          <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} />
          Refresh
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-3">
        <StatCard label="Active Signals" value={String(signals.length)} color="text-yellow-400" icon={Zap} subtext="VWAP scalper" />
        <StatCard label="Open Positions" value={String(scalpPositions.length)} color="text-blue-400" icon={Target} subtext="Live scalps" />
        <StatCard label="Session P&L" value={formatCurrency(activePnl, 'INR')} color={activePnl >= 0 ? 'text-emerald-400' : 'text-red-400'} icon={DollarSign} subtext="Today scalps" />
        <StatCard label="Win Rate" value="—" color="text-slate-400" icon={Activity} subtext="Calculating…" />
      </div>

      {/* Active Signals */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-800 p-4">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-yellow-400" />
            <h2 className="text-sm font-semibold text-slate-200">Live Scalping Signals</h2>
          </div>
          <span className="rounded-full bg-yellow-500/10 px-2 py-0.5 text-[10px] font-mono text-yellow-400">
            Live Stream (WebSockets)
          </span>
        </div>
        <div className="p-4 space-y-2">
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-16 animate-pulse rounded-lg bg-slate-800/50" />
              ))}
            </div>
          ) : signals.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Zap className="h-10 w-10 text-slate-700 mb-3" />
              <p className="text-sm text-slate-400">No active scalping signals</p>
              <p className="text-xs text-slate-600 mt-1">Waiting for VWAP deviation + volume spike conditions</p>
            </div>
          ) : (
            signals.map((signal, i) => <SignalRow key={i} signal={signal} />)
          )}
        </div>
      </div>

      {/* Live Positions */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-800 p-4">
          <div className="flex items-center gap-2">
            <Target className="h-4 w-4 text-blue-400" />
            <h2 className="text-sm font-semibold text-slate-200">Active Scalp Trades</h2>
          </div>
        </div>
        <div className="p-4">
          {scalpPositions.length === 0 ? (
            <div className="text-center py-6 text-sm text-slate-500">No active scalping positions</div>
          ) : (
            <div className="space-y-2">
              {scalpPositions.map((pos, i) => {
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

      {/* Info */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-4">
        <div className="flex items-start gap-2">
          <AlertCircle className="h-4 w-4 text-blue-400 mt-0.5 shrink-0" />
          <div className="text-xs text-slate-500 leading-relaxed">
            <strong className="text-slate-400">Strategy:</strong> VWAP Scalper monitors 1-3 minute charts for price bounces
            off VWAP bands with volume confirmation (≥1.5× average). Targets 0.2-0.5% profit with 0.15% stop loss.
            Max hold time: 10 minutes.
          </div>
        </div>
      </div>
    </div>
  );
}

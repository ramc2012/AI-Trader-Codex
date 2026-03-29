'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Radar,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Zap,
  Activity,
  Search,
  AlertCircle,
  Filter,
  BarChart3,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWebSocket } from '@/hooks/use-websocket';

interface FnoCandidate {
  symbol: string;
  display_name: string;
  sector: string;
  lot_size: number;
  strike_interval: number;
  ltp: number;
  change_pct: number;
  volume: number;
  volume_ratio: number;
  oi: number;
  oi_change_pct: number;
  signal: string;
  conviction: number;
  direction: string;
}

const SIGNAL_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  strong_breakout:  { bg: 'bg-emerald-500/15', text: 'text-emerald-300', border: 'border-emerald-500/30' },
  breakout:         { bg: 'bg-green-500/10',   text: 'text-green-400',   border: 'border-green-500/20' },
  strong_breakdown: { bg: 'bg-red-500/15',     text: 'text-red-300',     border: 'border-red-500/30' },
  breakdown:        { bg: 'bg-orange-500/10',  text: 'text-orange-400',  border: 'border-orange-500/20' },
  neutral:          { bg: 'bg-slate-500/10',   text: 'text-slate-400',   border: 'border-slate-500/20' },
};

function SignalBadge({ signal }: { signal: string }) {
  const style = SIGNAL_COLORS[signal] ?? SIGNAL_COLORS['neutral'];
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium', style.bg, style.text, style.border)}>
      {signal.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
    </span>
  );
}

function FnoRow({ candidate: c }: { candidate: FnoCandidate }) {
  const isUp = c.change_pct >= 0;
  return (
    <tr className="hover:bg-slate-800/30 transition-colors border-b border-slate-800/50">
      <td className="px-4 py-3">
        <div className="font-semibold text-sm text-slate-100">{c.symbol}</div>
        <div className="text-[10px] text-slate-500">{c.display_name}</div>
      </td>
      <td className="px-4 py-3">
        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">{c.sector}</span>
      </td>
      <td className="px-4 py-3 text-right font-mono text-sm text-slate-300">
        {c.ltp > 0 ? `₹${c.ltp.toFixed(2)}` : '—'}
      </td>
      <td className="px-4 py-3 text-right">
        {c.ltp > 0 ? (
          <span className={cn('font-semibold text-sm', isUp ? 'text-emerald-400' : 'text-red-400')}>
            {isUp ? '+' : ''}{c.change_pct.toFixed(2)}%
          </span>
        ) : '—'}
      </td>
      <td className="px-4 py-3 text-right text-xs text-slate-400">{c.lot_size}</td>
      <td className="px-4 py-3 text-right text-xs text-slate-400">₹{c.strike_interval}</td>
      <td className="px-4 py-3 text-center">
        {c.conviction > 0 && (
          <div className="flex items-center justify-center gap-0.5">
            {[1, 2, 3, 4, 5].map(i => (
              <div key={i} className={cn('h-1.5 w-2 rounded-sm', i <= c.conviction ? 'bg-emerald-400' : 'bg-slate-800')} />
            ))}
          </div>
        )}
      </td>
      <td className="px-4 py-3"><SignalBadge signal={c.signal} /></td>
    </tr>
  );
}

export default function FnoRadarPage() {
  const [candidates, setCandidates] = useState<FnoCandidate[]>([]);
  const [sectors, setSectors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [sectorFilter, setSectorFilter] = useState('all');
  const [signalFilter, setSignalFilter] = useState('all');
  const [total, setTotal] = useState(0);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '300' });
      if (sectorFilter !== 'all') params.set('sector', sectorFilter);
      if (signalFilter !== 'all') params.set('signal', signalFilter);

      const res = await fetch(`/api/v1/fno-radar/scan?${params}`);
      if (res.ok) {
        const data = await res.json();
        setCandidates(data.results || []);
        setSectors(data.sectors || []);
        setTotal(data.total || 0);
      }
    } catch (err) {
      console.error('Failed to fetch FNO radar data:', err);
    } finally {
      setLoading(false);
    }
  }, [sectorFilter, signalFilter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Live streaming overlay
  const { isConnected } = useWebSocket({
    path: '/ws/stream',
    onMessage: useCallback((msg: any) => {
      if (msg.event_type === 'signal_generated' && msg.payload) {
        const payload = msg.payload;
        // Clean up the symbol format
        let rawSymbol = payload.symbol || '';
        if (rawSymbol.startsWith('NSE:')) {
          rawSymbol = rawSymbol.replace('NSE:', '').replace('-EQ', '');
        }

        setCandidates((prev) => {
          const idx = prev.findIndex((c) => c.symbol === rawSymbol);
          if (idx === -1) return prev;

          const next = [...prev];
          const mappedConviction = Math.max(1, Math.min(5, Math.ceil((payload.conviction || 0) / 20)));
          const changed = next[idx];

          next[idx] = {
            ...changed,
            ltp: payload.price || changed.ltp,
            signal: payload.signal_type === 'BUY' ? 'strong_breakout' : 'strong_breakdown',
            conviction: mappedConviction,
            direction: payload.signal_type === 'BUY' ? 'bullish' : 'bearish',
          };
          
          return [next[idx], ...next.filter((_, i) => i !== idx)];
        });
      }
    }, []),
    enabled: true,
    reconnectInterval: 5000,
  });

  const filtered = useMemo(() => {
    if (!search.trim()) return candidates;
    const q = search.toLowerCase();
    return candidates.filter(c => c.symbol.toLowerCase().includes(q) || c.display_name.toLowerCase().includes(q));
  }, [candidates, search]);

  const signalCounts = useMemo(() => ({
    breakouts: candidates.filter(c => c.signal.includes('breakout')).length,
    breakdowns: candidates.filter(c => c.signal.includes('breakdown')).length,
    highConviction: candidates.filter(c => c.conviction >= 4).length,
  }), [candidates]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-orange-500/10">
            <Radar className="h-5 w-5 text-orange-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-100">FNO Radar</h1>
            <p className="text-xs text-slate-500">Scanning all 209 FNO-eligible stocks for positional trade setups</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            {isConnected ? (
              <Wifi className="h-4 w-4 text-emerald-500" />
            ) : (
              <WifiOff className="h-4 w-4 text-slate-600" />
            )}
            <span className={cn('text-xs font-medium', isConnected ? 'text-emerald-400' : 'text-slate-500')}>
              {isConnected ? 'Live' : 'Disconnected'}
            </span>
          </div>
          <button onClick={fetchData} className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors">
            <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} />
            Refresh
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-3">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-center">
          <div className="text-2xl font-bold text-orange-400">{total}</div>
          <div className="text-[11px] text-slate-500 mt-0.5">FNO Stocks</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-center">
          <div className="text-2xl font-bold text-emerald-400">{signalCounts.breakouts}</div>
          <div className="text-[11px] text-slate-500 mt-0.5">Breakouts</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-center">
          <div className="text-2xl font-bold text-red-400">{signalCounts.breakdowns}</div>
          <div className="text-[11px] text-slate-500 mt-0.5">Breakdowns</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-center">
          <div className="text-2xl font-bold text-blue-400">{signalCounts.highConviction}</div>
          <div className="text-[11px] text-slate-500 mt-0.5">High Conviction</div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-1 max-w-xs rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-1.5">
          <Search className="h-3.5 w-3.5 text-slate-500 shrink-0" />
          <input
            type="text"
            placeholder="Search symbol…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 bg-transparent text-xs text-slate-300 placeholder-slate-600 outline-none"
          />
        </div>
        <div className="flex items-center gap-1">
          <Filter className="h-3.5 w-3.5 text-slate-500" />
          <select
            value={sectorFilter}
            onChange={(e) => setSectorFilter(e.target.value)}
            className="rounded-lg border border-slate-800 bg-slate-900/60 px-2 py-1.5 text-xs text-slate-300 outline-none"
          >
            <option value="all">All Sectors</option>
            {sectors.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <select
          value={signalFilter}
          onChange={(e) => setSignalFilter(e.target.value)}
          className="rounded-lg border border-slate-800 bg-slate-900/60 px-2 py-1.5 text-xs text-slate-300 outline-none"
        >
          <option value="all">All Signals</option>
          <option value="strong_breakout">Strong Breakout</option>
          <option value="breakout">Breakout</option>
          <option value="strong_breakdown">Strong Breakdown</option>
          <option value="breakdown">Breakdown</option>
        </select>
        <span className="text-[10px] text-slate-600">{filtered.length} of {total} stocks</span>
      </div>

      {/* Table */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
        {loading ? (
          <div>{Array.from({ length: 10 }).map((_, i) => <div key={i} className="h-12 animate-pulse border-b border-slate-800/50 bg-slate-900/40" />)}</div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16">
            <Radar className="h-10 w-10 text-slate-700 mb-3" />
            <p className="text-sm text-slate-400">No stocks match filters</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-left text-slate-500">
                  <th className="px-4 py-2.5 font-medium">Symbol</th>
                  <th className="px-4 py-2.5 font-medium">Sector</th>
                  <th className="px-4 py-2.5 font-medium text-right">LTP</th>
                  <th className="px-4 py-2.5 font-medium text-right">Change</th>
                  <th className="px-4 py-2.5 font-medium text-right">Lot Size</th>
                  <th className="px-4 py-2.5 font-medium text-right">Strike Int.</th>
                  <th className="px-4 py-2.5 font-medium text-center">Conviction</th>
                  <th className="px-4 py-2.5 font-medium">Signal</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(c => <FnoRow key={c.symbol} candidate={c} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-4">
        <div className="flex items-start gap-2">
          <AlertCircle className="h-4 w-4 text-orange-400 mt-0.5 shrink-0" />
          <div className="text-xs text-slate-500 leading-relaxed">
            <strong className="text-slate-400">FNO Radar</strong> scans all 209 NSE FnO-eligible stocks in real-time.
            Filter by sector, signal type, and conviction. When the broker is authenticated, live LTP, change %, and
            OI data are displayed. Signals are classified based on price movement, fractal profile analysis, and volume patterns.
          </div>
        </div>
      </div>
    </div>
  );
}

'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import {
  Brain,
  ChevronDown,
  ChevronUp,
  Play,
  Send,
  Settings2,
  Shield,
  Square,
  TrendingUp,
  TrendingDown,
  Wifi,
  WifiOff,
  Zap,
  AlertTriangle,
  Activity,
  MessageSquare,
  FlaskConical,
  BarChart2,
  CheckCircle2,
  Clock,
} from 'lucide-react';
import {
  useAgentStatus,
  useAgentStart,
  useAgentKillSwitch,
  useAgentResetKillSwitch,
  useAvailableStrategies,
  useTestTelegram,
  useNotifyTelegramStatus,
  useSetAgentStrategy,
  useAgentEvents,
} from '@/hooks/use-agent';
import { useAgentWS } from '@/hooks/use-agent-ws';
import { useWatchlistUniverse } from '@/hooks/use-watchlist';
import { buildInstrumentOptions } from '@/lib/instrument-universe';
import { cn } from '@/lib/utils';
import type {
  AgentBackendConfig,
  AgentConfig,
  AgentEvent,
  AgentExecutionCoreSnapshot,
} from '@/types/api';

// ─── Helpers ──────────────────────────────────────────────

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function severityColor(severity: string) {
  switch (severity) {
    case 'success':
      return 'border-emerald-500 bg-emerald-500/5';
    case 'warning':
      return 'border-amber-500 bg-amber-500/5';
    case 'error':
      return 'border-red-500 bg-red-500/5';
    default:
      return 'border-slate-600 bg-slate-800/50';
  }
}

function severityDot(severity: string) {
  switch (severity) {
    case 'success':
      return 'bg-emerald-400';
    case 'warning':
      return 'bg-amber-400';
    case 'error':
      return 'bg-red-400';
    default:
      return 'bg-slate-400';
  }
}

function eventIcon(eventType: string) {
  if (eventType.includes('thinking') || eventType.includes('analyzing'))
    return <Brain className="h-4 w-4" />;
  if (eventType.includes('signal') || eventType.includes('market'))
    return <TrendingUp className="h-4 w-4" />;
  if (eventType.includes('risk') || eventType.includes('circuit'))
    return <Shield className="h-4 w-4" />;
  if (eventType.includes('order'))
    return <Send className="h-4 w-4" />;
  if (eventType.includes('position'))
    return <Activity className="h-4 w-4" />;
  if (eventType.includes('error'))
    return <AlertTriangle className="h-4 w-4" />;
  return <Zap className="h-4 w-4" />;
}

function formatBackendName(name: string) {
  switch (name) {
    case 'nats':
      return 'NATS';
    case 'kafka':
      return 'Kafka';
    case 'clickhouse':
      return 'ClickHouse';
    case 'questdb':
      return 'QuestDB';
    default:
      return name.replace(/_/g, ' ');
  }
}

function backendDetail(config?: AgentBackendConfig) {
  if (!config) return 'Not configured';
  return config.url ?? config.bootstrap_servers ?? config.stream_prefix ?? config.topic_prefix ?? 'Configured';
}

function infrastructureBadgeClasses(enabled: boolean) {
  return enabled
    ? 'bg-cyan-900/40 text-cyan-300'
    : 'bg-slate-800 text-slate-400';
}

function executionCoreBadge(snapshot?: AgentExecutionCoreSnapshot) {
  if (!snapshot) {
    return {
      label: 'OFF',
      className: 'bg-slate-800 text-slate-400',
    };
  }
  if (snapshot.reachable) {
    return {
      label: 'LIVE',
      className: 'bg-emerald-900/40 text-emerald-300',
    };
  }
  return {
    label: 'DOWN',
    className: 'bg-red-900/40 text-red-300',
  };
}

const STATE_BADGES: Record<string, { label: string; color: string }> = {
  idle: { label: 'Idle', color: 'bg-slate-600 text-slate-200' },
  running: { label: 'Running', color: 'bg-emerald-600 text-emerald-100' },
  paused: { label: 'Paused', color: 'bg-amber-600 text-amber-100' },
  stopped: { label: 'Stopped', color: 'bg-slate-600 text-slate-200' },
  error: { label: 'Error', color: 'bg-red-600 text-red-100' },
};

const DEFAULT_STRATEGIES = [
  'EMA_Crossover',
  'RSI_Reversal',
  'Supertrend_Breakout',
  'FnO_Swing_Radar',
  'US_Swing_Radar',
  'MP_OrderFlow_Breakout',
  'Fractal_Profile_Breakout',
];
const DEFAULT_EXECUTION_TIMEFRAMES = ['3', '5', '15'];
const DEFAULT_REFERENCE_TIMEFRAMES = ['60', 'D'];
const DEFAULT_NSE_SYMBOLS =
  'NSE:NIFTY50-INDEX,NSE:NIFTYBANK-INDEX,NSE:FINNIFTY-INDEX,NSE:NIFTYMIDCAP50-INDEX,BSE:SENSEX-INDEX,NSE:HDFCBANK-EQ,NSE:ICICIBANK-EQ,NSE:KOTAKBANK-EQ,NSE:AXISBANK-EQ,NSE:SBIN-EQ,NSE:INDUSINDBK-EQ,NSE:BAJFINANCE-EQ,NSE:BAJAJFINSV-EQ,NSE:SHRIRAMFIN-EQ,NSE:HDFCLIFE-EQ,NSE:SBILIFE-EQ,NSE:TCS-EQ,NSE:INFY-EQ,NSE:HCLTECH-EQ,NSE:WIPRO-EQ,NSE:TECHM-EQ,NSE:LTIM-EQ,NSE:RELIANCE-EQ,NSE:ONGC-EQ,NSE:BPCL-EQ,NSE:NTPC-EQ,NSE:POWERGRID-EQ,NSE:COALINDIA-EQ,NSE:HINDUNILVR-EQ,NSE:ITC-EQ,NSE:NESTLEIND-EQ,NSE:BRITANNIA-EQ,NSE:TATACONSUM-EQ,NSE:MARUTI-EQ,NSE:BAJAJ-AUTO-EQ,NSE:HEROMOTOCO-EQ,NSE:EICHERMOT-EQ,NSE:TATAMOTORS-EQ,NSE:MM-EQ,NSE:LT-EQ,NSE:ADANIPORTS-EQ,NSE:BEL-EQ,NSE:TATASTEEL-EQ,NSE:JSWSTEEL-EQ,NSE:HINDALCO-EQ,NSE:GRASIM-EQ,NSE:ULTRACEMCO-EQ,NSE:SUNPHARMA-EQ,NSE:DRREDDY-EQ,NSE:CIPLA-EQ,NSE:DIVISLAB-EQ,NSE:APOLLOHOSP-EQ,NSE:BHARTIARTL-EQ,NSE:ADANIENT-EQ,NSE:ASIANPAINT-EQ,NSE:TITAN-EQ';
const DEFAULT_US_SYMBOLS =
  'US:SPY,US:QQQ,US:DIA,US:IWM,US:AAPL,US:AMZN,US:JPM,US:XOM,US:UNH,US:CAT';

// ─── Event Card ───────────────────────────────────────────

function EventCard({ event }: { event: AgentEvent }) {
  const [expanded, setExpanded] = useState(false);
  const time = new Date(event.timestamp).toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
  const hasMeta = event.metadata && Object.keys(event.metadata).length > 0;

  return (
    <div
      className={`border-l-2 rounded-r-lg px-3 py-2 ${severityColor(event.severity)} transition-colors`}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 text-slate-400">{eventIcon(event.event_type)}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`h-1.5 w-1.5 rounded-full ${severityDot(event.severity)}`} />
            <span className="text-xs text-slate-500">{time}</span>
            <span className="text-sm font-medium text-slate-200 truncate">{event.title}</span>
          </div>
          <p className="text-xs text-slate-400 mt-0.5 whitespace-pre-line">{event.message}</p>
          {hasMeta && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-xs text-slate-500 hover:text-slate-300 mt-1 flex items-center gap-1"
            >
              {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              {expanded ? 'Hide' : 'Details'}
            </button>
          )}
          {expanded && hasMeta && (
            <pre className="text-xs text-slate-500 mt-1 bg-slate-900/50 rounded p-2 overflow-auto max-h-32">
              {JSON.stringify(event.metadata, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

function InfrastructureRow({
  label,
  detail,
  badge,
  badgeClassName,
}: {
  label: string;
  detail: string;
  badge: string;
  badgeClassName: string;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-slate-300">{label}</span>
        <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-semibold', badgeClassName)}>
          {badge}
        </span>
      </div>
      <div className="mt-1 break-all text-[10px] text-slate-500">{detail}</div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────

export default function AIAgentPage() {
  const { data: status } = useAgentStatus();
  const { data: initialEvents } = useAgentEvents(100);
  const { data: strategiesData } = useAvailableStrategies();
  const { data: universe } = useWatchlistUniverse();
  const { events: wsEvents, isConnected, clearEvents } = useAgentWS();
  const startMutation = useAgentStart();
  const killSwitchMutation = useAgentKillSwitch();
  const resetKillSwitchMutation = useAgentResetKillSwitch();
  const telegramMutation = useTestTelegram();
  const notifyStatusMutation = useNotifyTelegramStatus();
  const setStrategyMutation = useSetAgentStrategy();
  const instrumentOptions = useMemo(() => buildInstrumentOptions(universe), [universe]);
  const nseUniverseSymbols = useMemo(
    () => instrumentOptions
      .filter((item) => item.market === 'NSE' || item.market === 'BSE')
      .map((item) => item.value),
    [instrumentOptions],
  );
  const usUniverseSymbols = useMemo(
    () => instrumentOptions.filter((item) => item.market === 'US').map((item) => item.value),
    [instrumentOptions],
  );
  const cryptoUniverseSymbols = useMemo(
    () => instrumentOptions.filter((item) => item.market === 'CRYPTO').map((item) => item.value),
    [instrumentOptions],
  );

  // Config form state
  const [showConfig, setShowConfig] = useState(false);
  const [symbols, setSymbols] = useState(DEFAULT_NSE_SYMBOLS);
  const [usSymbols, setUsSymbols] = useState(DEFAULT_US_SYMBOLS);
  const [cryptoSymbols, setCryptoSymbols] = useState(
    'CRYPTO:BTCUSDT,CRYPTO:ETHUSDT,CRYPTO:BNBUSDT,CRYPTO:SOLUSDT,CRYPTO:XRPUSDT,CRYPTO:ADAUSDT,CRYPTO:DOGEUSDT,CRYPTO:AVAXUSDT,CRYPTO:DOTUSDT,CRYPTO:LINKUSDT'
  );
  const [tradeNSEWhenOpen, setTradeNSEWhenOpen] = useState(true);
  const [tradeUSWhenOpen, setTradeUSWhenOpen] = useState(true);
  const [tradeUSOptions, setTradeUSOptions] = useState(true);
  const [tradeCrypto24x7, setTradeCrypto24x7] = useState(true);
  const [strategies, setStrategies] = useState<string[]>(DEFAULT_STRATEGIES);
  const [scanInterval, setScanInterval] = useState(30);
  const [telegramStatusInterval, setTelegramStatusInterval] = useState(30);
  const [paperMode, setPaperMode] = useState(true);
  const [indiaCapital, setIndiaCapital] = useState(250000);
  const [usCapital, setUsCapital] = useState(250000);
  const [cryptoCapital, setCryptoCapital] = useState(250000);
  const [indiaMaxInstrumentPct, setIndiaMaxInstrumentPct] = useState(25);
  const [usMaxInstrumentPct, setUsMaxInstrumentPct] = useState(20);
  const [cryptoMaxInstrumentPct, setCryptoMaxInstrumentPct] = useState(20);
  const [strategyCapitalBucketEnabled, setStrategyCapitalBucketEnabled] = useState(false);
  const [strategyMaxConcurrentPositions, setStrategyMaxConcurrentPositions] = useState(4);
  const [timeframe, setTimeframe] = useState('5');
  const configHydratedRef = useRef(false);

  const loadWatchlistUniverse = useCallback(() => {
    if (nseUniverseSymbols.length > 0) {
      setSymbols(nseUniverseSymbols.join(','));
    }
    if (usUniverseSymbols.length > 0) {
      setUsSymbols(usUniverseSymbols.join(','));
    }
    if (cryptoUniverseSymbols.length > 0) {
      setCryptoSymbols(cryptoUniverseSymbols.join(','));
    }
  }, [cryptoUniverseSymbols, nseUniverseSymbols, usUniverseSymbols]);

  useEffect(() => {
    if (!status || configHydratedRef.current) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled || configHydratedRef.current) return;
      setSymbols((status.symbols ?? []).join(','));
      setUsSymbols((status.us_symbols ?? []).join(','));
      setCryptoSymbols((status.crypto_symbols ?? []).join(','));
      setTradeNSEWhenOpen(status.trade_nse_when_open ?? (status.symbols ?? []).length > 0);
      setTradeUSWhenOpen(status.trade_us_when_open ?? (status.us_symbols ?? []).length > 0);
      setTradeUSOptions(status.trade_us_options ?? true);
      setTradeCrypto24x7(status.trade_crypto_24x7 ?? (status.crypto_symbols ?? []).length > 0);
      setTelegramStatusInterval(status.telegram_status_interval_minutes ?? 30);
      setIndiaCapital(status.capital_allocations?.NSE?.allocated_capital ?? 250000);
      setUsCapital(status.capital_allocations?.US?.allocated_capital ?? 250000);
      setCryptoCapital(status.capital_allocations?.CRYPTO?.allocated_capital ?? 250000);
      setIndiaMaxInstrumentPct(status.capital_allocations?.NSE?.max_instrument_pct ?? 25);
      setUsMaxInstrumentPct(status.capital_allocations?.US?.max_instrument_pct ?? 20);
      setCryptoMaxInstrumentPct(status.capital_allocations?.CRYPTO?.max_instrument_pct ?? 20);
      setStrategyCapitalBucketEnabled(status.strategy_capital_bucket_enabled ?? false);
      setStrategyMaxConcurrentPositions(status.strategy_max_concurrent_positions ?? 4);
      configHydratedRef.current = true;
    });
    return () => {
      cancelled = true;
    };
  }, [status]);

  // Merge initial REST events with live WS events (dedup by event_id)
  const allEvents = (() => {
    const map = new Map<string, AgentEvent>();
    for (const e of initialEvents ?? []) map.set(e.event_id, e);
    for (const e of wsEvents) map.set(e.event_id, e);
    return Array.from(map.values()).sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );
  })();

  // Auto-scroll feed to bottom
  const feedRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [allEvents.length]);

  const agentState = status?.state ?? 'idle';
  const isRunning = agentState === 'running';
  const isPaused = agentState === 'paused';
  const killSwitchActive = Boolean(status?.emergency_stop);
  const canStart =
    !killSwitchActive && (agentState === 'idle' || agentState === 'stopped' || agentState === 'error');

  const availableStrategies = strategiesData?.strategies ?? Object.keys({
    EMA_Crossover: 1,
    RSI_Reversal: 1,
    MACD_RSI: 1,
    MP_OrderFlow_Breakout: 1,
    Fractal_Profile_Breakout: 1,
    Bollinger_MeanReversion: 1,
    Supertrend_Breakout: 1,
  });

  const handleStart = useCallback(() => {
    const config: AgentConfig = {
      symbols: symbols.split(',').map((s) => s.trim()).filter(Boolean),
      us_symbols: usSymbols.split(',').map((s) => s.trim()).filter(Boolean),
      crypto_symbols: cryptoSymbols.split(',').map((s) => s.trim()).filter(Boolean),
      trade_nse_when_open: tradeNSEWhenOpen,
      trade_us_when_open: tradeUSWhenOpen,
      trade_us_options: tradeUSOptions,
      trade_crypto_24x7: tradeCrypto24x7,
      strategies,
      scan_interval_seconds: scanInterval,
      paper_mode: paperMode,
      india_capital: indiaCapital,
      us_capital: usCapital,
      crypto_capital: cryptoCapital,
      india_max_instrument_pct: indiaMaxInstrumentPct,
      us_max_instrument_pct: usMaxInstrumentPct,
      crypto_max_instrument_pct: cryptoMaxInstrumentPct,
      strategy_capital_bucket_enabled: strategyCapitalBucketEnabled,
      strategy_max_concurrent_positions: strategyMaxConcurrentPositions,
      max_daily_loss_pct: 2.0,
      timeframe,
      execution_timeframes: DEFAULT_EXECUTION_TIMEFRAMES,
      reference_timeframes: DEFAULT_REFERENCE_TIMEFRAMES,
      telegram_status_interval_minutes: telegramStatusInterval,
    };
    clearEvents();
    startMutation.mutate(config);
  }, [
    symbols,
    usSymbols,
    cryptoSymbols,
    tradeNSEWhenOpen,
    tradeUSWhenOpen,
    tradeUSOptions,
    tradeCrypto24x7,
    strategies,
    scanInterval,
    paperMode,
    indiaCapital,
    usCapital,
    cryptoCapital,
    indiaMaxInstrumentPct,
    usMaxInstrumentPct,
    cryptoMaxInstrumentPct,
    strategyCapitalBucketEnabled,
    strategyMaxConcurrentPositions,
    timeframe,
    telegramStatusInterval,
    startMutation,
    clearEvents,
  ]);

  const strategyEnabled = (name: string): boolean => {
    const controls = status?.strategy_controls ?? [];
    const live = controls.find((c) => c.name === name);
    if (live) return Boolean(live.enabled);
    return strategies.includes(name);
  };

  const toggleStrategy = (name: string) => {
    if (isRunning || isPaused) {
      setStrategyMutation.mutate({
        strategy: name,
        enabled: !strategyEnabled(name),
      });
      return;
    }
    setStrategies((prev) =>
      prev.includes(name) ? prev.filter((s) => s !== name) : [...prev, name]
    );
  };

  const badge = STATE_BADGES[agentState] ?? STATE_BADGES.idle;
  const marketStatRows = Object.entries(status?.market_stats ?? {});
  const readinessRows = Object.entries(status?.market_readiness ?? {});
  const strategyStatRows = Object.entries(status?.strategy_stats ?? {}).sort(
    (a, b) => (b[1]?.net_pnl_inr ?? 0) - (a[1]?.net_pnl_inr ?? 0)
  );
  const executionCoreStatus = status?.execution_core_status;
  const hasExecutionCoreSnapshot = Boolean(executionCoreStatus && Object.keys(executionCoreStatus).length > 0);
  const executionCoreHealth = (executionCoreStatus?.health ?? {}) as Record<string, unknown>;
  const executionCoreStats = (executionCoreStatus?.stats ?? {}) as Record<string, unknown>;
  const streamingBackends = Object.entries(status?.streaming_backends ?? {});
  const analyticsBackends = Object.entries(status?.analytics_backends ?? {});
  const optionalServicesEnabled = [...streamingBackends, ...analyticsBackends].filter(([, cfg]) => Boolean(cfg?.enabled)).length;
  const stackProfileLabel =
    optionalServicesEnabled >= 4
      ? 'Complete'
      : optionalServicesEnabled > 0 || status?.execution_backend === 'rust'
        ? 'Hybrid'
        : 'Core';
  const marketPnl = status?.market_pnl_inr ?? Object.fromEntries(
    marketStatRows.map(([market, row]) => [market, Number(row?.net_pnl_inr ?? 0)])
  );
  const totalAllocatedCapitalInr = status?.total_allocated_capital_inr ?? 0;
  const estimatedIndiaPerTradeBudget = strategyCapitalBucketEnabled
    ? Math.min(
        indiaCapital / Math.max(strategies.length, 1) / Math.max(strategyMaxConcurrentPositions, 1),
        indiaCapital * (indiaMaxInstrumentPct / 100)
      )
    : indiaCapital * (indiaMaxInstrumentPct / 100);

  // ── Historical simulation state ─────────────────────────
  const [activeTab, setActiveTab] = useState<'live' | 'simulate'>('live');
  const [simSymbols, setSimSymbols] = useState(DEFAULT_NSE_SYMBOLS);
  const [simTimeframe, setSimTimeframe] = useState('15');
  const [simLookback, setSimLookback] = useState(30);
  const [simStrategies, setSimStrategies] = useState<string[]>(DEFAULT_STRATEGIES);
  const [simCapital, setSimCapital] = useState(250000);
  const [simRiskPct, setSimRiskPct] = useState(0.75);
  const [simSlippageBps, setSimSlippageBps] = useState(2);
  const [simCommission, setSimCommission] = useState(20);
  const [simMaxHoldBars, setSimMaxHoldBars] = useState(12);
  const [simStepBars, setSimStepBars] = useState(5);

  const simulateMutation = useMutation({
    mutationFn: async (body: {
      symbols: string[];
      strategies: string[];
      timeframe: string;
      lookback_days: number;
      capital: number;
      risk_per_trade_pct: number;
      slippage_bps: number;
      commission_per_trade: number;
      max_hold_bars: number;
      step_bars: number;
    }) => {
      const res = await fetch('/api/v1/agent/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    },
  });

  const handleSimulate = () => {
    simulateMutation.mutate({
      symbols: simSymbols.split(',').map((s) => s.trim()).filter(Boolean),
      strategies: simStrategies,
      timeframe: simTimeframe,
      lookback_days: simLookback,
      capital: simCapital,
      risk_per_trade_pct: simRiskPct,
      slippage_bps: simSlippageBps,
      commission_per_trade: simCommission,
      max_hold_bars: simMaxHoldBars,
      step_bars: simStepBars,
    });
  };

  const toggleSimStrategy = (name: string) => {
    setSimStrategies((prev) =>
      prev.includes(name) ? prev.filter((s) => s !== name) : [...prev, name]
    );
  };

  return (
    <div className="flex flex-col gap-4 h-[calc(100vh-2rem)]">
      {/* ── Header / Control Panel ──────────────────────────── */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          {/* Left: Title + Status */}
          <div className="flex items-center gap-3">
            <Brain className="h-6 w-6 text-emerald-400" />
            <h1 className="text-lg font-semibold text-slate-100">AI Trading Agent</h1>
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${badge.color}`}>
              {badge.label}
            </span>
            {isConnected ? (
              <span title="WebSocket connected"><Wifi className="h-4 w-4 text-emerald-400" /></span>
            ) : (
              <span title="WebSocket disconnected"><WifiOff className="h-4 w-4 text-slate-500" /></span>
            )}
          </div>

          {/* Right: Controls */}
          <div className="flex items-center gap-2">
            {killSwitchActive && (
              <button
                onClick={() => resetKillSwitchMutation.mutate()}
                disabled={resetKillSwitchMutation.isPending}
                className="flex items-center gap-1.5 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Shield className="h-4 w-4" />
                Clear Kill Switch
              </button>
            )}
            {canStart && (
              <button
                onClick={handleStart}
                disabled={startMutation.isPending || strategies.length === 0}
                className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Play className="h-4 w-4" />
                Start
              </button>
            )}
            {(isRunning || isPaused) && (
              <button
                onClick={() => killSwitchMutation.mutate()}
                disabled={killSwitchMutation.isPending}
                className="flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-50"
              >
                <Square className="h-4 w-4" />
                Emergency Stop
              </button>
            )}
            <button
              onClick={() => setShowConfig(!showConfig)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium border transition-colors ${
                showConfig
                  ? 'bg-slate-700 border-slate-600 text-slate-200'
                  : 'border-slate-700 text-slate-400 hover:text-slate-200'
              }`}
            >
              <Settings2 className="h-4 w-4" />
              Config
            </button>
            <Link
              href="/ai-agent/inputs"
              className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-400 transition-colors hover:text-slate-200"
            >
              <BarChart2 className="h-4 w-4" />
              Inputs
            </Link>
            <button
              onClick={() => telegramMutation.mutate()}
              disabled={telegramMutation.isPending}
              title="Test Telegram"
              className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-400 hover:text-slate-200 disabled:opacity-50"
            >
              <MessageSquare className="h-4 w-4" />
            </button>
            <button
              onClick={() => notifyStatusMutation.mutate()}
              disabled={notifyStatusMutation.isPending}
              title="Send Status to Telegram"
              className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-400 hover:text-slate-200 disabled:opacity-50"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* ── Config Panel (collapsible) ─────────────────────── */}
        {showConfig && (
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 border-t border-slate-800 pt-4">
            <div className="sm:col-span-2 lg:col-span-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-xs font-medium text-slate-300">Watchlist Universe</div>
                  <div className="mt-1 text-xs text-slate-500">
                    NSE/BSE {nseUniverseSymbols.length} · US {usUniverseSymbols.length} · Crypto {cryptoUniverseSymbols.length}
                  </div>
                </div>
                <button
                  onClick={loadWatchlistUniverse}
                  disabled={isRunning || isPaused || instrumentOptions.length === 0}
                  className="rounded-lg border border-emerald-600/50 bg-emerald-600/10 px-3 py-1.5 text-xs font-medium text-emerald-300 transition-colors hover:border-emerald-500 disabled:opacity-50"
                >
                  Load Full Watchlist
                </button>
              </div>
            </div>

            {/* Symbols */}
            <div>
              <label className="text-xs text-slate-400 mb-1 block">NSE Symbols (comma-separated)</label>
              <input
                type="text"
                value={symbols}
                onChange={(e) => setSymbols(e.target.value)}
                disabled={isRunning || isPaused}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
              />
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">US Symbols (comma-separated)</label>
              <input
                type="text"
                value={usSymbols}
                onChange={(e) => setUsSymbols(e.target.value)}
                disabled={isRunning || isPaused}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
              />
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Crypto Pairs (comma-separated)</label>
              <input
                type="text"
                value={cryptoSymbols}
                onChange={(e) => setCryptoSymbols(e.target.value)}
                disabled={isRunning || isPaused}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
              />
            </div>

            {/* Timeframe */}
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Timeframe (minutes)</label>
              <select
                value={timeframe}
                onChange={(e) => setTimeframe(e.target.value)}
                disabled={isRunning || isPaused}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
              >
                <option value="5">5 min</option>
                <option value="15">15 min</option>
                <option value="30">30 min</option>
                <option value="60">1 hour</option>
              </select>
            </div>

            {/* Scan Interval */}
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Scan Interval (seconds)</label>
              <input
                type="number"
                value={scanInterval}
                onChange={(e) => setScanInterval(Number(e.target.value))}
                min={10}
                max={300}
                disabled={isRunning || isPaused}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
              />
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Telegram Status Interval (min)</label>
              <input
                type="number"
                value={telegramStatusInterval}
                onChange={(e) => setTelegramStatusInterval(Number(e.target.value))}
                min={0}
                max={1440}
                disabled={isRunning || isPaused}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
              />
            </div>

            {/* Capital */}
            <div>
              <label className="text-xs text-slate-400 mb-1 block">India Capital (INR)</label>
              <input
                type="number"
                value={indiaCapital}
                onChange={(e) => setIndiaCapital(Number(e.target.value))}
                min={10000}
                disabled={isRunning || isPaused}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
              />
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">US Capital (USD)</label>
              <input
                type="number"
                value={usCapital}
                onChange={(e) => setUsCapital(Number(e.target.value))}
                min={1000}
                disabled={isRunning || isPaused}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
              />
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Crypto Capital (USD)</label>
              <input
                type="number"
                value={cryptoCapital}
                onChange={(e) => setCryptoCapital(Number(e.target.value))}
                min={1000}
                disabled={isRunning || isPaused}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
              />
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">India Max / Instrument (%)</label>
              <input
                type="number"
                value={indiaMaxInstrumentPct}
                onChange={(e) => setIndiaMaxInstrumentPct(Number(e.target.value))}
                min={1}
                max={100}
                disabled={isRunning || isPaused}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
              />
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">US Max / Instrument (%)</label>
              <input
                type="number"
                value={usMaxInstrumentPct}
                onChange={(e) => setUsMaxInstrumentPct(Number(e.target.value))}
                min={1}
                max={100}
                disabled={isRunning || isPaused}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
              />
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Crypto Max / Instrument (%)</label>
              <input
                type="number"
                value={cryptoMaxInstrumentPct}
                onChange={(e) => setCryptoMaxInstrumentPct(Number(e.target.value))}
                min={1}
                max={100}
                disabled={isRunning || isPaused}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
              />
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
              <div className="text-xs text-slate-400">Total Allocated Capital (INR equiv)</div>
              <div className="mt-2 text-sm font-medium text-slate-200">
                ₹{Math.round(totalAllocatedCapitalInr || (indiaCapital + (usCapital + cryptoCapital) * 83)).toLocaleString('en-IN')}
              </div>
            </div>

            <div className="sm:col-span-2 lg:col-span-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div className="text-xs font-medium uppercase tracking-[0.18em] text-slate-400">
                    Strategy Capital Bucket
                  </div>
                  <p className="mt-1 text-sm text-slate-300">
                    Optional extra throttle that splits each market bucket across enabled strategies and strategy slots before an order can be placed.
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    Estimated India per-trade cap: ₹{Math.round(estimatedIndiaPerTradeBudget).toLocaleString('en-IN')}
                  </p>
                </div>
                <button
                  onClick={() => setStrategyCapitalBucketEnabled((value) => !value)}
                  disabled={isRunning || isPaused}
                  className={`rounded-full px-3 py-1 text-xs font-medium border transition-colors ${
                    strategyCapitalBucketEnabled
                      ? 'border-emerald-600 bg-emerald-600/20 text-emerald-400'
                      : 'border-cyan-600 bg-cyan-600/20 text-cyan-300'
                  } disabled:opacity-50`}
                >
                  {strategyCapitalBucketEnabled ? 'Bucket Enabled' : 'Bucket Disabled'}
                </button>
              </div>

              <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="text-xs text-slate-400 mb-1 block">
                    Max Open Positions / Strategy / Market
                  </label>
                  <input
                    type="number"
                    value={strategyMaxConcurrentPositions}
                    onChange={(e) => setStrategyMaxConcurrentPositions(Number(e.target.value))}
                    min={1}
                    max={20}
                    disabled={isRunning || isPaused || !strategyCapitalBucketEnabled}
                    className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
                  />
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
                  <div className="text-xs text-slate-400">India cap formula</div>
                  <div className="mt-1 text-sm text-slate-200">
                    {strategyCapitalBucketEnabled
                      ? `min(India cap / ${Math.max(strategies.length, 1)} strategies / ${Math.max(strategyMaxConcurrentPositions, 1)} slots, max instrument cap)`
                      : 'Default mode. Uses the full India max-instrument cap without per-strategy splitting.'}
                  </div>
                </div>
              </div>
            </div>

            {/* Paper Mode Toggle */}
            <div className="flex items-center gap-3">
              <label className="text-xs text-slate-400">Mode</label>
              <button
                onClick={() => setPaperMode(!paperMode)}
                disabled={isRunning || isPaused}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  paperMode
                    ? 'bg-blue-600/20 text-blue-400 border border-blue-600'
                    : 'bg-red-600/20 text-red-400 border border-red-600'
                } disabled:opacity-50`}
              >
                {paperMode ? 'Paper Trading' : 'LIVE Trading'}
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-2 sm:col-span-2 lg:col-span-3">
              <span className="text-xs text-slate-400">Trade Sessions</span>
              <button
                onClick={() => setTradeNSEWhenOpen((v) => !v)}
                disabled={isRunning || isPaused}
                className={`rounded-full px-3 py-1 text-xs font-medium border transition-colors ${
                  tradeNSEWhenOpen
                    ? 'border-emerald-600 bg-emerald-600/20 text-emerald-400'
                    : 'border-slate-700 bg-slate-800 text-slate-400'
                } disabled:opacity-50`}
              >
                NSE
              </button>
              <button
                onClick={() => setTradeUSWhenOpen((v) => !v)}
                disabled={isRunning || isPaused}
                className={`rounded-full px-3 py-1 text-xs font-medium border transition-colors ${
                  tradeUSWhenOpen
                    ? 'border-emerald-600 bg-emerald-600/20 text-emerald-400'
                    : 'border-slate-700 bg-slate-800 text-slate-400'
                } disabled:opacity-50`}
              >
                US
              </button>
              <button
                onClick={() => setTradeUSOptions((v) => !v)}
                disabled={isRunning || isPaused || !tradeUSWhenOpen}
                className={`rounded-full px-3 py-1 text-xs font-medium border transition-colors ${
                  tradeUSOptions
                    ? 'border-blue-600 bg-blue-600/20 text-blue-300'
                    : 'border-slate-700 bg-slate-800 text-slate-400'
                } disabled:opacity-50`}
              >
                US OPTIONS
              </button>
              <button
                onClick={() => setTradeCrypto24x7((v) => !v)}
                disabled={isRunning || isPaused}
                className={`rounded-full px-3 py-1 text-xs font-medium border transition-colors ${
                  tradeCrypto24x7
                    ? 'border-emerald-600 bg-emerald-600/20 text-emerald-400'
                    : 'border-slate-700 bg-slate-800 text-slate-400'
                } disabled:opacity-50`}
              >
                CRYPTO 24x7
              </button>
            </div>

            {/* Strategies */}
            <div className="sm:col-span-2 lg:col-span-3">
              <label className="text-xs text-slate-400 mb-2 block">
                Strategies {isRunning || isPaused ? '(live toggle enabled)' : '(pre-start config)'}
              </label>
              <div className="flex flex-wrap gap-2">
                {availableStrategies.map((name) => (
                  <button
                    key={name}
                    onClick={() => toggleStrategy(name)}
                    disabled={setStrategyMutation.isPending}
                    className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors border ${
                      strategyEnabled(name)
                        ? 'bg-emerald-600/20 text-emerald-400 border-emerald-600'
                        : 'bg-slate-800 text-slate-400 border-slate-700 hover:border-slate-600'
                    } disabled:opacity-50`}
                  >
                    {name.replace(/_/g, ' ')}
                  </button>
                ))}
              </div>
              {setStrategyMutation.isError && (
                <p className="mt-2 text-xs text-red-400">
                  {setStrategyMutation.error instanceof Error
                    ? setStrategyMutation.error.message
                    : 'Failed to update strategy state'}
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Tab Bar ─────────────────────────────────────────── */}
      <div className="flex gap-0 border-b border-slate-800 -mb-1">
        <button
          onClick={() => setActiveTab('live')}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
            activeTab === 'live'
              ? 'border-emerald-500 text-emerald-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Zap className="h-3.5 w-3.5" />
          Live Feed
        </button>
        <button
          onClick={() => setActiveTab('simulate')}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
            activeTab === 'simulate'
              ? 'border-violet-500 text-violet-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <FlaskConical className="h-3.5 w-3.5" />
          Historical Test
        </button>
      </div>

      {/* ── Main Content: Feed + Sidebar ─────────────────────── */}
      <div className="flex-1 flex gap-4 min-h-0">

        {/* ── Live Feed Tab ─────────────────────────────────── */}
        {activeTab === 'live' && (
        <div className="flex-1 rounded-xl border border-slate-800 bg-slate-900 flex flex-col min-h-0">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
            <h2 className="text-sm font-medium text-slate-300">Activity Feed</h2>
            <span className="text-xs text-slate-500">{allEvents.length} events</span>
          </div>
          <div ref={feedRef} className="flex-1 overflow-y-auto p-3 space-y-2">
            {allEvents.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-3 text-slate-500">
                <Brain className="h-10 w-10 text-slate-600" />
                <p className="text-sm">No events yet. Start the agent to see live activity.</p>
              </div>
            ) : (
              allEvents.map((event) => <EventCard key={event.event_id} event={event} />)
            )}
          </div>
        </div>
        )}

        {/* ── Historical Simulation Tab ──────────────────────── */}
        {activeTab === 'simulate' && (
        <div className="flex-1 flex flex-col gap-4 min-h-0 overflow-y-auto">
          {/* Config panel */}
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <FlaskConical className="h-4 w-4 text-violet-400" />
                <h2 className="text-sm font-semibold text-slate-200">Historical Strategy Test</h2>
              </div>
              <p className="text-xs text-slate-500">Runs strategies on cached historical OHLC data — no live orders</p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 mb-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Symbols</label>
                <input
                  type="text"
                  value={simSymbols}
                  onChange={(e) => setSimSymbols(e.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-slate-200"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Timeframe</label>
                <select
                  value={simTimeframe}
                  onChange={(e) => setSimTimeframe(e.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                >
                  <option value="5">5m</option>
                  <option value="15">15m</option>
                  <option value="30">30m</option>
                  <option value="60">1h</option>
                  <option value="D">Daily</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Lookback (days)</label>
                <input
                  type="number"
                  value={simLookback}
                  onChange={(e) => setSimLookback(Number(e.target.value))}
                  min={5} max={365}
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Capital (INR)</label>
                <input
                  type="number"
                  value={simCapital}
                  onChange={(e) => setSimCapital(Number(e.target.value))}
                  min={10000}
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Risk / trade %</label>
                <input
                  type="number"
                  value={simRiskPct}
                  onChange={(e) => setSimRiskPct(Number(e.target.value))}
                  min={0.05}
                  max={5}
                  step={0.05}
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Slippage (bps)</label>
                <input
                  type="number"
                  value={simSlippageBps}
                  onChange={(e) => setSimSlippageBps(Number(e.target.value))}
                  min={0}
                  max={100}
                  step={0.5}
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Commission / side</label>
                <input
                  type="number"
                  value={simCommission}
                  onChange={(e) => setSimCommission(Number(e.target.value))}
                  min={0}
                  step={1}
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Max hold bars</label>
                <input
                  type="number"
                  value={simMaxHoldBars}
                  onChange={(e) => setSimMaxHoldBars(Number(e.target.value))}
                  min={1}
                  max={500}
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Step bars</label>
                <input
                  type="number"
                  value={simStepBars}
                  onChange={(e) => setSimStepBars(Number(e.target.value))}
                  min={1}
                  max={50}
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                />
              </div>
            </div>

            <div className="mb-4">
              <label className="text-xs text-slate-400 mb-2 block">Strategies to test</label>
              <div className="flex flex-wrap gap-2">
                {availableStrategies.map((name) => (
                  <button
                    key={name}
                    onClick={() => toggleSimStrategy(name)}
                    className={`rounded-lg px-3 py-1.5 text-xs font-medium border transition-colors ${
                      simStrategies.includes(name)
                        ? 'bg-violet-600/20 text-violet-300 border-violet-600'
                        : 'bg-slate-800 text-slate-400 border-slate-700 hover:border-slate-600'
                    }`}
                  >
                    {name.replace(/_/g, ' ')}
                  </button>
                ))}
              </div>
            </div>

            <button
              onClick={handleSimulate}
              disabled={simulateMutation.isPending || simStrategies.length === 0}
              className="flex items-center gap-2 rounded-lg bg-violet-600 px-5 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {simulateMutation.isPending ? (
                <><Activity className="h-4 w-4 animate-pulse" />Running…</>
              ) : (
                <><FlaskConical className="h-4 w-4" />Run Historical Test</>
              )}
            </button>

            {simulateMutation.isError && (
              <p className="mt-2 text-xs text-red-400">
                Error: {simulateMutation.error instanceof Error ? simulateMutation.error.message : 'Unknown error'}
              </p>
            )}
          </div>

          {/* Results */}
          {simulateMutation.isSuccess && simulateMutation.data && (() => {
            const { signals, summary } = simulateMutation.data;
            return (
              <div className="rounded-xl border border-slate-800 bg-slate-900 flex flex-col min-h-0">
                {/* Summary bar */}
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-0 border-b border-slate-800">
                  {[
                    { icon: BarChart2, label: 'Bars scanned', value: String(summary.bars_scanned), color: 'text-slate-300' },
                    { icon: CheckCircle2, label: 'Total signals', value: String(summary.total_signals), color: 'text-slate-300' },
                    { icon: TrendingUp,  label: 'Buy signals',  value: String(summary.buy_signals),   color: 'text-emerald-400' },
                    { icon: TrendingDown, label: 'Sell signals', value: String(summary.sell_signals),  color: 'text-red-400' },
                    { icon: Activity, label: 'Trades', value: String(summary.total_trades ?? 0), color: 'text-violet-300' },
                    { icon: CheckCircle2, label: 'Win Rate', value: `${summary.win_rate ?? 0}%`, color: 'text-cyan-300' },
                    {
                      icon: summary.net_pnl >= 0 ? TrendingUp : TrendingDown,
                      label: 'Net P&L',
                      value: `${summary.net_pnl >= 0 ? '+' : ''}${summary.net_pnl ?? 0}`,
                      color: summary.net_pnl >= 0 ? 'text-emerald-400' : 'text-red-400',
                    },
                    { icon: Clock,       label: 'Period',        value: `${summary.lookback_days}d ${summary.timeframe}m`, color: 'text-slate-400' },
                  ].map(({ icon: Icon, label, value, color }) => (
                    <div key={label} className="flex flex-col items-center justify-center py-3 px-2 border-r last:border-0 border-slate-800">
                      <Icon className={`h-3.5 w-3.5 mb-1 ${color}`} />
                      <div className={`text-lg font-bold font-mono ${color}`}>{value}</div>
                      <div className="text-[10px] text-slate-500 uppercase tracking-wide">{label}</div>
                    </div>
                  ))}
                </div>

                {/* Signal conversation stream */}
                <div className="flex-1 overflow-y-auto p-4 space-y-2 max-h-[50vh]">
                  {signals.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-12 gap-3">
                      <Brain className="h-8 w-8 text-slate-600" />
                      <p className="text-sm text-slate-400">No actionable signals found in this period.</p>
                      <p className="text-xs text-slate-500">
                        {summary.no_data_symbols?.length > 0
                          ? `No data for: ${summary.no_data_symbols.join(', ')} — ensure cache is warm (Fyers must be authenticated).`
                          : 'Try a longer lookback period or different strategies.'}
                      </p>
                    </div>
                  ) : (
                    signals.map((sig: {
                      timestamp: string; symbol: string; strategy: string;
                      direction: string; strength: string; price: number;
                      stop_loss?: number; target?: number; message: string;
                    }, i: number) => {
                      const isBuy = sig.direction === 'BUY';
                      const ts = new Date(sig.timestamp).toLocaleString('en-IN', {
                        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
                      });
                      return (
                        <div
                          key={i}
                          className={`rounded-lg border px-3 py-2.5 ${
                            isBuy
                              ? 'border-emerald-800/50 bg-emerald-950/40'
                              : 'border-red-800/50 bg-red-950/40'
                          }`}
                        >
                          <div className="flex items-center gap-2 mb-1">
                            {isBuy
                              ? <TrendingUp className="h-3.5 w-3.5 text-emerald-400 flex-shrink-0" />
                              : <TrendingDown className="h-3.5 w-3.5 text-red-400 flex-shrink-0" />
                            }
                            <span className="text-[10px] text-slate-500 font-mono">{ts}</span>
                            <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                              isBuy ? 'bg-emerald-500/20 text-emerald-300' : 'bg-red-500/20 text-red-300'
                            }`}>
                              {sig.direction}
                            </span>
                            <span className="text-[10px] text-slate-500">{sig.strategy.replace(/_/g,' ')}</span>
                            <span className="ml-auto text-[10px] text-slate-600">{sig.symbol.split(':')[1]?.split('-')[0]}</span>
                          </div>
                          <p className="text-xs text-slate-300">{sig.message}</p>
                          {(sig.stop_loss || sig.target) && (
                            <div className="mt-1 flex gap-3 text-[10px] font-mono">
                              {sig.stop_loss && <span className="text-red-400">SL {sig.stop_loss.toFixed(1)}</span>}
                              {sig.target && <span className="text-emerald-400">TGT {sig.target.toFixed(1)}</span>}
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            );
          })()}
        </div>
        )}

        {/* Stats Sidebar */}
        <div className="w-72 shrink-0 rounded-xl border border-slate-800 bg-slate-900 p-4 space-y-4 overflow-y-auto">
          <h2 className="text-sm font-medium text-slate-300">Agent Stats</h2>

          <div className="space-y-3">
            <StatItem label="Status" value={badge.label} />
            <StatItem label="Uptime" value={status ? formatUptime(status.uptime_seconds) : '—'} />
            <StatItem label="Cycle" value={status?.current_cycle?.toString() ?? '0'} />
            <StatItem label="Mode" value={status?.paper_mode !== false ? 'Paper' : 'LIVE'} />

            <div className="border-t border-slate-800 pt-3" />

            <StatItem
              label="Positions"
              value={status?.positions_count?.toString() ?? '0'}
            />
            <StatItem
              label="Daily P&L"
              value={status ? `${status.daily_pnl >= 0 ? '+' : ''}${status.daily_pnl.toLocaleString('en-IN')}` : '—'}
              valueColor={
                status && status.daily_pnl > 0
                  ? 'text-emerald-400'
                  : status && status.daily_pnl < 0
                    ? 'text-red-400'
                    : undefined
              }
            />
            <StatItem label="Signals" value={status?.total_signals?.toString() ?? '0'} />
            <StatItem label="Trades" value={status?.total_trades?.toString() ?? '0'} />

            <div className="mt-2 grid grid-cols-1 gap-2">
              {[
                { key: 'NSE', label: 'India P&L' },
                { key: 'US', label: 'US P&L' },
                { key: 'CRYPTO', label: 'Crypto P&L' },
              ].map(({ key, label }) => {
                const value = Number((marketPnl as Record<string, number>)[key] ?? 0);
                const valueColor =
                  value > 0 ? 'text-emerald-400' : value < 0 ? 'text-red-400' : 'text-slate-400';
                return (
                  <div key={key} className="rounded-lg border border-slate-800 bg-slate-950/40 px-2 py-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] text-slate-400">{label}</span>
                      <span className={`text-[11px] font-medium ${valueColor}`}>
                        {value >= 0 ? '+' : ''}
                        {value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="border-t border-slate-800 pt-3" />

            <div>
              <span className="text-xs text-slate-500">Active Sessions</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {(status?.active_sessions ?? []).map((s) => (
                  <span
                    key={s}
                    className="rounded bg-emerald-900/30 px-2 py-0.5 text-xs text-emerald-300"
                  >
                    {s}
                  </span>
                ))}
                {!(status?.active_sessions?.length) && (
                  <span className="text-xs text-slate-500">None</span>
                )}
              </div>
            </div>

            {readinessRows.length > 0 && (
              <div>
                <span className="text-xs text-slate-500">Market Readiness</span>
                <div className="mt-1 space-y-1">
                  {readinessRows.map(([market, item]) => {
                    const enabled = Boolean(item?.enabled);
                    const open = Boolean(item?.session_open);
                    const ready = Boolean(item?.ready);
                    return (
                      <div
                        key={market}
                        className="flex items-center justify-between rounded border border-slate-800 bg-slate-950/40 px-2 py-1"
                      >
                        <span className="text-[11px] text-slate-300">{market}</span>
                        <span
                          className={cn(
                            'rounded px-1.5 py-0.5 text-[10px] font-semibold',
                            !enabled
                              ? 'bg-slate-800 text-slate-400'
                              : !open
                                ? 'bg-slate-800 text-slate-300'
                                : ready
                                  ? 'bg-emerald-900/40 text-emerald-300'
                                  : 'bg-amber-900/40 text-amber-300'
                          )}
                        >
                          {!enabled ? 'DISABLED' : !open ? 'CLOSED' : ready ? 'READY' : 'WAIT'}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            <div>
              <span className="text-xs text-slate-500">Infrastructure</span>
              <div className="mt-2 space-y-2">
                <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] text-slate-300">Stack Profile</span>
                    <span className="rounded bg-indigo-900/40 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-300">
                      {stackProfileLabel}
                    </span>
                  </div>
                  <div className="mt-1 grid grid-cols-2 gap-1 text-[10px] text-slate-500">
                    <span>Exec {String(status?.execution_backend ?? 'python').toUpperCase()}</span>
                    <span>Transport {String(status?.execution_transport ?? 'inmemory').toUpperCase()}</span>
                    <span>Event-driven {status?.event_driven_enabled ? 'ON' : 'OFF'}</span>
                    <span>
                      Markets {status?.event_driven_markets?.length ? status.event_driven_markets.join(', ') : '—'}
                    </span>
                  </div>
                </div>

                {(status?.execution_backend === 'rust' || hasExecutionCoreSnapshot) && (
                  <InfrastructureRow
                    label="Execution Core"
                    detail={
                      executionCoreStatus?.reachable
                        ? [
                            executionCoreStatus.url ?? 'reachable',
                            typeof executionCoreHealth.nats_connected === 'boolean'
                              ? `NATS ${executionCoreHealth.nats_connected ? 'connected' : 'disconnected'}`
                              : null,
                            typeof executionCoreHealth.signal_candidates === 'number'
                              ? `signals ${String(executionCoreHealth.signal_candidates)}`
                              : null,
                            typeof executionCoreStats.signal_subject === 'string'
                              ? String(executionCoreStats.signal_subject)
                              : null,
                          ].filter(Boolean).join(' • ')
                        : executionCoreStatus?.error ?? executionCoreStatus?.url ?? 'Execution core not reachable'
                    }
                    badge={executionCoreBadge(executionCoreStatus).label}
                    badgeClassName={executionCoreBadge(executionCoreStatus).className}
                  />
                )}

                {streamingBackends.map(([name, config]) => (
                  <InfrastructureRow
                    key={name}
                    label={formatBackendName(name)}
                    detail={backendDetail(config)}
                    badge={config?.enabled ? 'ENABLED' : 'DISABLED'}
                    badgeClassName={infrastructureBadgeClasses(Boolean(config?.enabled))}
                  />
                ))}

                {analyticsBackends.map(([name, config]) => (
                  <InfrastructureRow
                    key={name}
                    label={formatBackendName(name)}
                    detail={
                      config?.database
                        ? `${backendDetail(config)} • db ${config.database}`
                        : backendDetail(config)
                    }
                    badge={config?.enabled ? 'ENABLED' : 'DISABLED'}
                    badgeClassName={infrastructureBadgeClasses(Boolean(config?.enabled))}
                  />
                ))}
              </div>
            </div>

            <div>
              <span className="text-xs text-slate-500">Active Symbols</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {(status?.active_symbols ?? []).map((s) => (
                  <span
                    key={s}
                    className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300"
                  >
                    {s.split(':').pop()?.split('-')[0]}
                  </span>
                ))}
                {!(status?.active_symbols?.length) && (
                  <span className="text-xs text-slate-500">No active symbols</span>
                )}
              </div>
            </div>

            <div>
              <span className="text-xs text-slate-500">NSE Universe</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {(status?.symbols ?? []).map((s) => (
                  <span
                    key={s}
                    className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300"
                  >
                    {s.split(':').pop()?.split('-')[0]}
                  </span>
                ))}
              </div>
            </div>

            <div>
              <span className="text-xs text-slate-500">US Universe</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {(status?.us_symbols ?? []).map((s) => (
                  <span
                    key={s}
                    className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300"
                  >
                    {s.split(':').pop()?.split('-')[0]}
                  </span>
                ))}
              </div>
            </div>

            <div>
              <span className="text-xs text-slate-500">Crypto Universe</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {(status?.crypto_symbols ?? []).map((s) => (
                  <span
                    key={s}
                    className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300"
                  >
                    {s.split(':').pop()?.split('-')[0]}
                  </span>
                ))}
              </div>
            </div>

            <div>
              <span className="text-xs text-slate-500">
                Strategy Controls {isRunning || isPaused ? '(live)' : '(pre-start)'}
              </span>
              <div className="flex flex-wrap gap-1 mt-2">
                {availableStrategies.map((name) => {
                  const enabled = strategyEnabled(name);
                  return (
                    <button
                      key={name}
                      onClick={() => toggleStrategy(name)}
                      disabled={setStrategyMutation.isPending}
                      className={`rounded border px-2 py-0.5 text-xs transition-colors ${
                        enabled
                          ? 'border-emerald-600 bg-emerald-600/20 text-emerald-300'
                          : 'border-slate-700 bg-slate-800 text-slate-400'
                      } disabled:opacity-50`}
                    >
                      {name.replace(/_/g, ' ')}
                    </button>
                  );
                })}
              </div>
            </div>

            {marketStatRows.length > 0 && (
              <div>
                <span className="text-xs text-slate-500">Market Stats (INR)</span>
                <div className="mt-2 space-y-2">
                  {marketStatRows.map(([market, row]) => (
                    <div key={market} className="rounded-lg border border-slate-800 bg-slate-950/40 p-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-medium text-slate-300">{market}</span>
                        <span
                          className={`text-xs font-medium ${
                            (row?.net_pnl_inr ?? 0) > 0
                              ? 'text-emerald-400'
                              : (row?.net_pnl_inr ?? 0) < 0
                                ? 'text-red-400'
                                : 'text-slate-400'
                          }`}
                        >
                          {(row?.net_pnl_inr ?? 0) >= 0 ? '+' : ''}
                          {(row?.net_pnl_inr ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                        </span>
                      </div>
                      <div className="mt-1 grid grid-cols-3 gap-1 text-[10px] text-slate-400">
                        <span>S {row?.signals ?? 0}</span>
                        <span>E {row?.entries ?? 0}</span>
                        <span>C {row?.closed_trades ?? 0}</span>
                      </div>
                      <div className="mt-1 grid grid-cols-2 gap-1 text-[10px] text-slate-500">
                        <span>Win {row?.win_rate_pct ?? 0}%</span>
                        <span>Open {row?.open_positions ?? 0}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {strategyStatRows.length > 0 && (
              <div>
                <span className="text-xs text-slate-500">Strategy Stats (INR)</span>
                <div className="mt-2 space-y-2">
                  {strategyStatRows.slice(0, 8).map(([name, row]) => (
                    <div key={name} className="rounded-lg border border-slate-800 bg-slate-950/40 p-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[11px] text-slate-300 truncate">{name.replace(/_/g, ' ')}</span>
                        <span
                          className={`text-[11px] font-medium ${
                            (row?.net_pnl_inr ?? 0) > 0
                              ? 'text-emerald-400'
                              : (row?.net_pnl_inr ?? 0) < 0
                                ? 'text-red-400'
                                : 'text-slate-400'
                          }`}
                        >
                          {(row?.net_pnl_inr ?? 0) >= 0 ? '+' : ''}
                          {(row?.net_pnl_inr ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                        </span>
                      </div>
                      <div className="mt-1 grid grid-cols-3 gap-1 text-[10px] text-slate-500">
                        <span>S {row?.signals ?? 0}</span>
                        <span>E {row?.entries ?? 0}</span>
                        <span>W {row?.wins ?? 0}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {status?.last_scan_time && (
              <StatItem
                label="Last Scan"
                value={`${new Date(status.last_scan_time).toLocaleTimeString('en-IN', {
                  timeZone: 'Asia/Kolkata',
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
                  hour12: false,
                })} IST`}
              />
            )}

            {status?.error && (
              <div className="rounded-lg border border-red-800 bg-red-900/20 p-2">
                <span className="text-xs text-red-400">{status.error}</span>
              </div>
            )}
          </div>

          {/* Telegram test result */}
          {telegramMutation.isSuccess && (
            <div className="rounded-lg border border-emerald-800 bg-emerald-900/20 p-2">
              <span className="text-xs text-emerald-400">
                {telegramMutation.data?.message}
              </span>
            </div>
          )}
          {telegramMutation.isError && (
            <div className="rounded-lg border border-red-800 bg-red-900/20 p-2">
              <span className="text-xs text-red-400">Telegram test failed</span>
            </div>
          )}
          {notifyStatusMutation.isSuccess && (
            <div className="rounded-lg border border-emerald-800 bg-emerald-900/20 p-2">
              <span className="text-xs text-emerald-400">
                {notifyStatusMutation.data?.message}
              </span>
            </div>
          )}
          {notifyStatusMutation.isError && (
            <div className="rounded-lg border border-red-800 bg-red-900/20 p-2">
              <span className="text-xs text-red-400">Status notification failed</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Stat Item ────────────────────────────────────────────

function StatItem({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-sm font-medium ${valueColor ?? 'text-slate-200'}`}>{value}</span>
    </div>
  );
}

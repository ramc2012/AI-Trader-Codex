'use client';

import { Suspense, useEffect, useState } from 'react';
import {
  Settings,
  Server,
  Database,
  Loader2,
  KeyRound,
  MessageSquare,
  Send,
  X,
  Map,
  LayoutDashboard,
  List,
  CandlestickChart,
  BarChart3,
  TrendingUp,
  Briefcase,
  Target,
  Shield,
  BarChart2,
  FlaskConical,
  Activity,
  Brain,
  ScanSearch,
  Layers,
  ArrowLeftRight,
  DollarSign,
  Bitcoin,
  Clock,
  Radar,
  ExternalLink,
} from 'lucide-react';
import Link from 'next/link';
import { AuthWizard } from '@/components/auth/auth-wizard';
import {
  useMarketDataProviders,
  useSaveMarketDataProviders,
  useSaveTelegramConfig,
  useTelegramConfig,
} from '@/hooks/use-auth';
import { useNotifyTelegramFractalScan, useNotifyTelegramStatus, useTestTelegram } from '@/hooks/use-agent';

// ── Tab types ────────────────────────────────────────────────────────────────
type TabId = 'broker' | 'data' | 'notifications' | 'system' | 'routes';

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: 'broker',        label: 'Broker',         icon: TrendingUp    },
  { id: 'data',          label: 'Data Providers', icon: KeyRound      },
  { id: 'notifications', label: 'Notifications',  icon: MessageSquare },
  { id: 'system',        label: 'System',         icon: Server        },
  { id: 'routes',        label: 'App Routes',     icon: Map           },
];

// ── All app routes for the Routes tab ────────────────────────────────────────
const APP_ROUTES = [
  {
    href: '/',
    label: 'Dashboard',
    icon: LayoutDashboard,
    description: 'Market overview, live positions summary, and quick stats',
    category: 'Core',
  },
  {
    href: '/watchlist',
    label: 'Watchlist',
    icon: List,
    description: 'Track your favourite FnO symbols with live quotes',
    category: 'Core',
  },
  {
    href: '/analytics?tab=charts',
    label: 'Charts',
    icon: CandlestickChart,
    description: 'Multi-timeframe OHLC candlestick charts for any symbol',
    category: 'Analysis',
  },
  {
    href: '/analytics?tab=profile',
    label: 'Market Profile',
    icon: BarChart3,
    description: 'TPO / volume profile — POC, VAH, VAL across timeframes',
    category: 'Analysis',
  },
  {
    href: '/analytics?tab=orderflow',
    label: 'Order Flow',
    icon: BarChart2,
    description: 'Footprint charts, delta, and cumulative delta analysis',
    category: 'Analysis',
  },
  {
    href: '/indices/nifty/options',
    label: 'Options',
    icon: TrendingUp,
    description: 'Live option chain with OI, IV, Greeks for Nifty / BankNifty',
    category: 'Options',
  },
  {
    href: '/oi-dashboard',
    label: 'OI Dashboard',
    icon: Layers,
    description: 'Open interest analysis — PCR, max pain, OI heatmap',
    category: 'Options',
  },
  {
    href: '/scanner',
    label: 'Scanner',
    icon: ScanSearch,
    description: 'Multi-criteria breakout / momentum scanner across FnO universe',
    category: 'Analysis',
  },
  {
    href: '/fno-radar',
    label: 'FnO Radar',
    icon: Radar,
    description: '4-pillar composite scoring: volatility · RRG · profile · OI for ATM options swing trades',
    category: 'Analysis',
    isNew: true,
  },
  {
    href: '/positions',
    label: 'Positions',
    icon: Briefcase,
    description: 'Open positions with real-time P&L and risk metrics',
    category: 'Trading',
  },
  {
    href: '/portfolio',
    label: 'Portfolio',
    icon: BarChart3,
    description: 'Aggregate portfolio view — holdings, exposure, drawdown',
    category: 'Trading',
  },
  {
    href: '/strategies',
    label: 'Strategies',
    icon: Target,
    description: 'Configure and manage rule-based trading strategies',
    category: 'Trading',
  },
  {
    href: '/risk',
    label: 'Risk',
    icon: Shield,
    description: 'Daily loss limits, position sizing rules, and risk dashboard',
    category: 'Trading',
  },
  {
    href: '/backtest',
    label: 'Backtest',
    icon: FlaskConical,
    description: 'Run historical strategy simulations with P&L analytics',
    category: 'Tools',
  },
  {
    href: '/monitoring',
    label: 'Monitoring',
    icon: Activity,
    description: 'System health, data pipeline status, and alerts log',
    category: 'Tools',
  },
  {
    href: '/money-flow',
    label: 'Money Flow',
    icon: DollarSign,
    description: 'Institutional vs retail flow analysis across FII / DII data',
    category: 'Analysis',
  },
  {
    href: '/crypto-flow',
    label: 'Crypto Flow',
    icon: Bitcoin,
    description: 'BTC / global crypto capital flow overlay on India markets',
    category: 'Analysis',
  },
  {
    href: '/history',
    label: 'History',
    icon: Clock,
    description: 'Trade history, execution log, and performance statistics',
    category: 'Tools',
  },
  {
    href: '/ai-agent',
    label: 'AI Agent',
    icon: Brain,
    description: 'Autonomous trading agent — configure, start/stop, monitor',
    category: 'Tools',
  },
  {
    href: '/settings',
    label: 'Settings',
    icon: Settings,
    description: 'Broker connection, API keys, notifications, and app routes',
    category: 'Tools',
  },
];

const ROUTE_CATEGORIES = ['Core', 'Analysis', 'Options', 'Trading', 'Tools'];

// ── Sub-tab components ────────────────────────────────────────────────────────

function BrokerTab() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-xs text-slate-400">
        <p className="font-semibold text-slate-300 mb-1">About Fyers token expiry</p>
        <p>
          Fyers API tokens expire every day. If market data shows offline, re-authenticate here. The token is
          saved locally and reused until it expires. You must reauthenticate each trading day before market open.
        </p>
      </div>
      <AuthWizard />
    </div>
  );
}

function DataProvidersTab() {
  const { data: providers } = useMarketDataProviders();
  const saveProviders = useSaveMarketDataProviders();
  const [finnhubKey, setFinnhubKey] = useState('');
  const [alphaKey, setAlphaKey] = useState('');

  useEffect(() => {
    if (!saveProviders.isSuccess) {
      return;
    }
    setFinnhubKey('');
    setAlphaKey('');
  }, [saveProviders.isSuccess]);

  const handleSave = () => {
    saveProviders.mutate({
      finnhub_api_key: finnhubKey.trim(),
      alphavantage_api_key: alphaKey.trim(),
    });
  };

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-xs text-slate-400">
        <p className="font-semibold text-slate-300 mb-1">US market data providers</p>
        <p>
          Finnhub is the primary source for US intraday candles and quote fallback. Alpha Vantage is the secondary
          fallback for US OHLC and chart history. Both are optional — Indian market data comes directly from Fyers.
        </p>
        {providers?.credentials_path && (
          <p className="mt-2 text-[11px] text-slate-500">
            Persisted in <span className="font-mono">{providers.credentials_path}</span>
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        {/* Finnhub */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-200">Finnhub</p>
              <p className="text-xs text-slate-500">Primary US intraday provider</p>
            </div>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                providers?.finnhub_configured
                  ? 'bg-emerald-500/10 text-emerald-400'
                  : 'bg-slate-700 text-slate-400'
              }`}
            >
              {providers?.finnhub_configured ? 'Configured' : 'Not set'}
            </span>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-400">API Key</label>
            <input
              type="password"
              value={finnhubKey}
              onChange={(e) => setFinnhubKey(e.target.value)}
              placeholder={
                providers?.finnhub_key_preview
                  ? `Saved as ${providers.finnhub_key_preview} — enter to replace`
                  : providers?.finnhub_configured
                  ? 'Configured — enter to replace'
                  : 'Enter Finnhub API key'
              }
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-emerald-600 focus:outline-none"
            />
            {providers?.finnhub_key_preview && (
              <p className="mt-1 text-[11px] text-slate-500">
                Persisted key: <span className="font-mono">{providers.finnhub_key_preview}</span>
              </p>
            )}
          </div>
          <a
            href="https://finnhub.io/dashboard"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-emerald-400 hover:text-emerald-300"
          >
            Get free API key <ExternalLink className="h-3 w-3" />
          </a>
        </div>

        {/* Alpha Vantage */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-200">Alpha Vantage</p>
              <p className="text-xs text-slate-500">Secondary US OHLC fallback</p>
            </div>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                providers?.alphavantage_configured
                  ? 'bg-emerald-500/10 text-emerald-400'
                  : 'bg-slate-700 text-slate-400'
              }`}
            >
              {providers?.alphavantage_configured ? 'Configured' : 'Not set'}
            </span>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-400">API Key</label>
            <input
              type="password"
              value={alphaKey}
              onChange={(e) => setAlphaKey(e.target.value)}
              placeholder={
                providers?.alphavantage_key_preview
                  ? `Saved as ${providers.alphavantage_key_preview} — enter to replace`
                  : providers?.alphavantage_configured
                  ? 'Configured — enter to replace'
                  : 'Enter Alpha Vantage API key'
              }
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-emerald-600 focus:outline-none"
            />
            {providers?.alphavantage_key_preview && (
              <p className="mt-1 text-[11px] text-slate-500">
                Persisted key: <span className="font-mono">{providers.alphavantage_key_preview}</span>
              </p>
            )}
          </div>
          <a
            href="https://www.alphavantage.co/support/#api-key"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-emerald-400 hover:text-emerald-300"
          >
            Get free API key <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saveProviders.isPending || (!finnhubKey.trim() && !alphaKey.trim())}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
        >
          {saveProviders.isPending ? 'Saving…' : 'Save Keys'}
        </button>
        {saveProviders.isSuccess && (
          <span className="text-xs text-emerald-400">Saved — new requests will use the updated providers immediately.</span>
        )}
        {saveProviders.isError && (
          <span className="text-xs text-red-400">
            {saveProviders.error instanceof Error ? saveProviders.error.message : 'Failed to save keys'}
          </span>
        )}
      </div>
    </div>
  );
}

function NotificationsTab() {
  const { data: telegramConfig } = useTelegramConfig();
  const saveTelegram = useSaveTelegramConfig();
  const testTelegram = useTestTelegram();
  const notifyTelegramStatus = useNotifyTelegramStatus();
  const notifyTelegramFractalScan = useNotifyTelegramFractalScan();

  const [telegramBotToken, setTelegramBotToken] = useState('');
  const [telegramChatId, setTelegramChatId] = useState('');
  const [telegramInterval, setTelegramInterval] = useState(telegramConfig?.status_interval_minutes ?? 30);
  const [telegramEnabled, setTelegramEnabled] = useState(telegramConfig?.enabled ?? true);

  const trimmedBotToken = telegramBotToken.trim();
  const getUpdatesUrl = trimmedBotToken
    ? `https://api.telegram.org/bot${trimmedBotToken}/getUpdates`
    : 'https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates';

  const handleSave = () => {
    const payload: { enabled: boolean; bot_token?: string; chat_id?: string; status_interval_minutes: number } = {
      enabled: telegramEnabled,
      status_interval_minutes: Math.max(0, telegramInterval),
    };
    const trimmedChatId = telegramChatId.trim();
    if (trimmedBotToken) payload.bot_token = trimmedBotToken;
    if (trimmedChatId) payload.chat_id = trimmedChatId;
    saveTelegram.mutate(payload);
  };

  const handleClear = () => {
    setTelegramBotToken('');
    setTelegramChatId('');
    saveTelegram.mutate({
      enabled: telegramEnabled,
      bot_token: '',
      chat_id: '',
      status_interval_minutes: Math.max(0, telegramInterval),
    });
  };

  return (
    <div className="space-y-6">
      {/* Status bar */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-xs">
        <span className="text-slate-500 font-medium">Status:</span>
        <span
          className={
            telegramConfig?.active
              ? 'text-emerald-400'
              : telegramConfig?.configured && telegramConfig?.enabled
                ? 'text-amber-300'
                : telegramConfig?.configured
                  ? 'text-slate-400'
                  : 'text-slate-500'
          }
        >
          {telegramConfig?.active
            ? 'Active'
            : telegramConfig?.configured && telegramConfig?.enabled
              ? 'Configured'
              : telegramConfig?.configured
                ? 'Configured (disabled)'
                : 'Not configured'}
        </span>
        <span className="text-slate-600">·</span>
        <span className={telegramConfig?.enabled ? 'text-emerald-400' : 'text-slate-500'}>
          Alerts {telegramConfig?.enabled ? 'on' : 'off'}
        </span>
        <span className="text-slate-600">·</span>
        <span className="text-slate-500">
          Interval: {telegramConfig?.status_interval_minutes ?? telegramInterval} min
        </span>
        {telegramConfig?.last_error && (
          <>
            <span className="text-slate-600">·</span>
            <span className="text-red-400">Last error: {telegramConfig.last_error}</span>
          </>
        )}
        <button
          onClick={() => saveTelegram.mutate({ enabled: !(telegramConfig?.enabled ?? true) })}
          disabled={saveTelegram.isPending || !telegramConfig?.configured}
          className="ml-auto rounded-lg border border-slate-700 bg-slate-800 px-3 py-1 text-slate-300 hover:bg-slate-700 disabled:opacity-40"
        >
          {telegramConfig?.enabled ? 'Disable Alerts' : 'Enable Alerts'}
        </button>
      </div>

      {/* How to guide */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <p className="text-sm font-medium text-slate-200 mb-3">How to set up Telegram alerts</p>
        <ol className="space-y-2 text-xs text-slate-400 list-decimal pl-4">
          <li>
            Open{' '}
            <a href="https://t.me/BotFather" target="_blank" rel="noreferrer" className="text-emerald-400 hover:text-emerald-300">
              BotFather
            </a>{' '}
            in Telegram and run <code className="text-slate-300">/newbot</code>.
          </li>
          <li>Copy the bot token BotFather returns and paste it into the Bot Token field below.</li>
          <li>
            Open a direct chat with your bot and send a message such as <code className="text-slate-300">/start</code>.
          </li>
          <li>
            Open{' '}
            <a
              href={trimmedBotToken ? getUpdatesUrl : 'https://core.telegram.org/bots/api#getupdates'}
              target="_blank"
              rel="noreferrer"
              className="text-emerald-400 hover:text-emerald-300"
            >
              {trimmedBotToken ? 'getUpdates for this bot' : 'Telegram Bot API getUpdates docs'}
            </a>.
          </li>
          <li>
            Find <code className="text-slate-300">chat.id</code> in the JSON. Use that numeric value as the Chat ID. Group
            chat IDs are usually negative.
          </li>
        </ol>
        <p className="mt-3 text-[11px] text-slate-500">
          For group alerts, add the bot to the group and send one message before checking getUpdates.
        </p>
      </div>

      {/* Alerts toggle */}
      <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900 px-4 py-3">
        <div>
          <p className="text-sm font-medium text-slate-100">Automatic alerts</p>
          <p className="text-xs text-slate-500">Disable if only the AWS instance should send Telegram messages.</p>
        </div>
        <button
          type="button"
          onClick={() => setTelegramEnabled((v) => !v)}
          className={
            telegramEnabled
              ? 'rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300'
              : 'rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-medium text-slate-300'
          }
        >
          {telegramEnabled ? 'Enabled' : 'Disabled'}
        </button>
      </div>

      {/* Credentials */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-slate-400">Bot Token</label>
          <input
            type="password"
            value={telegramBotToken}
            onChange={(e) => setTelegramBotToken(e.target.value)}
            placeholder={telegramConfig?.bot_configured ? 'Configured (enter to replace)' : 'Enter bot token'}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-emerald-600 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-400">Chat ID</label>
          <input
            type="text"
            value={telegramChatId}
            onChange={(e) => setTelegramChatId(e.target.value)}
            placeholder={telegramConfig?.chat_configured ? 'Configured (enter to replace)' : 'Enter numeric chat ID'}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-emerald-600 focus:outline-none"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-slate-400">Status Interval (minutes)</label>
          <input
            type="number"
            min={0}
            max={1440}
            value={telegramInterval}
            onChange={(e) => setTelegramInterval(Number(e.target.value))}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 focus:border-emerald-600 focus:outline-none"
          />
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={handleSave}
          disabled={saveTelegram.isPending}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
        >
          {saveTelegram.isPending ? 'Saving…' : 'Save'}
        </button>
        <button
          onClick={handleClear}
          disabled={saveTelegram.isPending}
          className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-200 hover:bg-red-950/70 disabled:opacity-40"
        >
          Clear Credentials
        </button>
        <button
          onClick={() => testTelegram.mutate()}
          disabled={testTelegram.isPending}
          className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700 disabled:opacity-40"
        >
          {testTelegram.isPending ? 'Testing…' : 'Test Message'}
        </button>
        <button
          onClick={() => notifyTelegramStatus.mutate()}
          disabled={notifyTelegramStatus.isPending}
          className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700 disabled:opacity-40"
        >
          <Send className="h-3.5 w-3.5" />
          {notifyTelegramStatus.isPending ? 'Sending…' : 'Send Status'}
        </button>
        <button
          onClick={() => notifyTelegramFractalScan.mutate()}
          disabled={notifyTelegramFractalScan.isPending}
          className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700 disabled:opacity-40"
        >
          <Send className="h-3.5 w-3.5" />
          {notifyTelegramFractalScan.isPending ? 'Sending…' : 'Send Fractal Scan'}
        </button>

        {/* Feedback messages */}
        {saveTelegram.isSuccess && <span className="text-xs text-emerald-400">Saved.</span>}
        {saveTelegram.isError && (
          <span className="text-xs text-red-400">
            {saveTelegram.error instanceof Error ? saveTelegram.error.message : 'Save failed'}
          </span>
        )}
        {testTelegram.isSuccess && (
          <span className={testTelegram.data?.success ? 'text-xs text-emerald-400' : 'text-xs text-red-400'}>
            {testTelegram.data?.message ?? (testTelegram.data?.success ? 'Test sent.' : 'Test failed.')}
          </span>
        )}
        {testTelegram.isError && <span className="text-xs text-red-400">Test failed.</span>}
        {notifyTelegramStatus.isSuccess && (
          <span className={notifyTelegramStatus.data?.success ? 'text-xs text-emerald-400' : 'text-xs text-red-400'}>
            {notifyTelegramStatus.data?.message ?? (notifyTelegramStatus.data?.success ? 'Status sent.' : 'Status send failed.')}
          </span>
        )}
        {notifyTelegramStatus.isError && <span className="text-xs text-red-400">Status send failed.</span>}
        {notifyTelegramFractalScan.isSuccess && (
          <span className={notifyTelegramFractalScan.data?.success ? 'text-xs text-emerald-400' : 'text-xs text-red-400'}>
            {notifyTelegramFractalScan.data?.message ?? (notifyTelegramFractalScan.data?.success ? 'Fractal scan sent.' : 'Fractal scan send failed.')}
          </span>
        )}
        {notifyTelegramFractalScan.isError && <span className="text-xs text-red-400">Fractal scan send failed.</span>}
      </div>
    </div>
  );
}

function SystemTab() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* Trading Mode */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Shield className="h-4 w-4 text-slate-500" />
            <span className="text-xs text-slate-500">Trading Mode</span>
          </div>
          <span className="rounded-md bg-yellow-500/20 px-2 py-0.5 text-xs font-semibold uppercase text-yellow-400">
            Paper
          </span>
          <p className="mt-2 text-[11px] text-slate-600">
            Live trading is disabled. All orders are simulated.
          </p>
        </div>

        {/* Backend */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Server className="h-4 w-4 text-slate-500" />
            <span className="text-xs text-slate-500">Backend</span>
          </div>
          <span className="text-sm text-slate-200">FastAPI v0.1.0</span>
          <p className="mt-2 text-[11px] text-slate-600">Python async REST API + WebSocket</p>
        </div>

        {/* Database */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Database className="h-4 w-4 text-slate-500" />
            <span className="text-xs text-slate-500">Database</span>
          </div>
          <span className="text-sm text-slate-200">TimescaleDB</span>
          <p className="mt-2 text-[11px] text-slate-600">PostgreSQL time-series extension</p>
        </div>

        {/* Cache */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Activity className="h-4 w-4 text-slate-500" />
            <span className="text-xs text-slate-500">Cache</span>
          </div>
          <span className="text-sm text-slate-200">Redis + In-memory OHLC</span>
          <p className="mt-2 text-[11px] text-slate-600">Dual-layer cache for real-time performance</p>
        </div>

        {/* Frontend */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <div className="flex items-center gap-2 mb-2">
            <LayoutDashboard className="h-4 w-4 text-slate-500" />
            <span className="text-xs text-slate-500">Frontend</span>
          </div>
          <span className="text-sm text-slate-200">Next.js 16 · React 19</span>
          <p className="mt-2 text-[11px] text-slate-600">App Router, TailwindCSS, ECharts</p>
        </div>

        {/* Data Source */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <div className="flex items-center gap-2 mb-2">
            <ArrowLeftRight className="h-4 w-4 text-slate-500" />
            <span className="text-xs text-slate-500">Market Data</span>
          </div>
          <span className="text-sm text-slate-200">Fyers API v3</span>
          <p className="mt-2 text-[11px] text-slate-600">NSE/BSE live data, option chains, history</p>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-xs text-slate-500">
        <p className="font-medium text-slate-400 mb-1">Docker Compose stack</p>
        <p>
          The app runs as a Docker Compose stack. Changes to source code require a rebuild:{' '}
          <code className="rounded bg-slate-800 px-1 py-0.5 text-slate-300">
            docker compose build &amp;&amp; docker compose up -d --force-recreate
          </code>
        </p>
      </div>
    </div>
  );
}

function RoutesTab() {
  return (
    <div className="space-y-6">
      <p className="text-xs text-slate-500">
        All pages available in this app. Click any card to navigate directly.
      </p>

      {ROUTE_CATEGORIES.map((category) => {
        const routes = APP_ROUTES.filter((r) => r.category === category);
        return (
          <div key={category}>
            <h4 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500">{category}</h4>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {routes.map((route) => {
                const Icon = route.icon;
                return (
                  <Link
                    key={route.href}
                    href={route.href}
                    className="group flex items-start gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4 hover:border-emerald-700/60 hover:bg-slate-800/60 transition-colors"
                  >
                    <div className="mt-0.5 rounded-lg border border-slate-700 bg-slate-800 p-2 group-hover:border-emerald-700/50 group-hover:bg-slate-700">
                      <Icon className="h-4 w-4 text-slate-400 group-hover:text-emerald-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-slate-200 group-hover:text-emerald-300">
                          {route.label}
                        </span>
                        {'isNew' in route && route.isNew && (
                          <span className="rounded-full bg-emerald-500/20 px-1.5 py-0.5 text-[9px] font-bold uppercase text-emerald-400">
                            New
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 text-[11px] text-slate-500 line-clamp-2 group-hover:text-slate-400">
                        {route.description}
                      </p>
                      <p className="mt-1 text-[10px] font-mono text-slate-600">{route.href}</p>
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Main settings content ─────────────────────────────────────────────────────

function SettingsContent() {
  const [activeTab, setActiveTab] = useState<TabId>('broker');

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Settings</h2>
        <p className="mt-1 text-sm text-slate-400">Manage broker connection, API keys, notifications, and explore the app</p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 rounded-xl border border-slate-800 bg-slate-900/60 p-1">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
                isActive
                  ? 'bg-slate-800 text-emerald-400 shadow-sm'
                  : 'text-slate-500 hover:bg-slate-800/50 hover:text-slate-300'
              }`}
            >
              <Icon className="h-3.5 w-3.5 flex-shrink-0" />
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div>
        {activeTab === 'broker'        && <BrokerTab />}
        {activeTab === 'data'          && <DataProvidersTab />}
        {activeTab === 'notifications' && <NotificationsTab />}
        {activeTab === 'system'        && <SystemTab />}
        {activeTab === 'routes'        && <RoutesTab />}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          <span className="ml-3 text-sm text-slate-400">Loading settings…</span>
        </div>
      }
    >
      <SettingsContent />
    </Suspense>
  );
}

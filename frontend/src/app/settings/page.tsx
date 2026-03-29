'use client';

import { Suspense, useState, useEffect } from 'react';
import { Settings, Server, Database, Loader2, KeyRound, MessageSquare, Send, X, ArrowLeftRight } from 'lucide-react';
import { AuthWizard } from '@/components/auth/auth-wizard';
import {
  useMarketDataProviders,
  useSaveMarketDataProviders,
  useSaveTelegramConfig,
  useTelegramConfig,
} from '@/hooks/use-auth';
import { useNotifyTelegramFractalScan, useNotifyTelegramStatus, useTestTelegram } from '@/hooks/use-agent';

function SettingsContent() {
  const { data: providers } = useMarketDataProviders();
  const saveProviders = useSaveMarketDataProviders();
  const { data: telegramConfig } = useTelegramConfig();
  const saveTelegram = useSaveTelegramConfig();
  const testTelegram = useTestTelegram();
  const notifyTelegramStatus = useNotifyTelegramStatus();
  const notifyTelegramFractalScan = useNotifyTelegramFractalScan();
  const [finnhubKey, setFinnhubKey] = useState('');
  const [alphaKey, setAlphaKey] = useState('');
  const [telegramBotToken, setTelegramBotToken] = useState('');
  const [telegramChatId, setTelegramChatId] = useState('');
  const [telegramInterval, setTelegramInterval] = useState(30);
  const [telegramEnabled, setTelegramEnabled] = useState(true);
  const [telegramDialogOpen, setTelegramDialogOpen] = useState(false);

  // Broker selection state
  const [brokerData, setBrokerData] = useState<any>(null);
  const [brokerSwitching, setBrokerSwitching] = useState(false);

  useEffect(() => {
    fetch('/api/v1/auth/broker').then(r => r.json()).then(setBrokerData).catch(() => {});
  }, [brokerSwitching]);

  const handleSwitchBroker = async (name: string) => {
    setBrokerSwitching(true);
    try {
      await fetch('/api/v1/auth/broker', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ broker: name }),
      });
      const res = await fetch('/api/v1/auth/broker');
      setBrokerData(await res.json());
    } catch {}
    setBrokerSwitching(false);
  };

  const handleSaveProviders = () => {
    saveProviders.mutate({
      finnhub_api_key: finnhubKey.trim(),
      alphavantage_api_key: alphaKey.trim(),
    });
  };

  const handleSaveTelegram = () => {
    const payload: { enabled: boolean; bot_token?: string; chat_id?: string; status_interval_minutes: number } = {
      enabled: telegramEnabled,
      status_interval_minutes: Math.max(0, telegramInterval),
    };
    const trimmedChatId = telegramChatId.trim();
    if (trimmedBotToken) payload.bot_token = trimmedBotToken;
    if (trimmedChatId) payload.chat_id = trimmedChatId;
    saveTelegram.mutate(payload);
  };

  const handleClearTelegram = () => {
    setTelegramBotToken('');
    setTelegramChatId('');
    saveTelegram.mutate({
      enabled: telegramEnabled,
      bot_token: '',
      chat_id: '',
      status_interval_minutes: Math.max(0, telegramInterval),
    });
  };

  const trimmedBotToken = telegramBotToken.trim();
  const getUpdatesUrl = trimmedBotToken
    ? `https://api.telegram.org/bot${trimmedBotToken}/getUpdates`
    : 'https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates';

  const handleOpenTelegramDialog = () => {
    setTelegramEnabled(telegramConfig?.enabled ?? true);
    setTelegramInterval(telegramConfig?.status_interval_minutes ?? 30);
    setTelegramDialogOpen(true);
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Settings</h2>
        <p className="mt-1 text-sm text-slate-400">
          Manage your broker connection and system configuration
        </p>
      </div>

      {/* Broker Selection */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="flex items-center gap-3 mb-4">
          <ArrowLeftRight className="h-5 w-5 text-slate-400" />
          <h3 className="text-lg font-semibold text-slate-100">
            Broker Selection
          </h3>
        </div>
        <p className="mb-4 text-sm text-slate-400">
          Select your active broker. Configure API keys for each broker to enable trading.
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {(brokerData?.brokers ?? [
            { name: 'fyers', display_name: 'Fyers', active: true, configured: false, authenticated: false },
            { name: 'upstox', display_name: 'Upstox', active: false, configured: false, authenticated: false },
            { name: 'fivepaisa', display_name: '5paisa', active: false, configured: false, authenticated: false },
          ]).map((broker: any) => (
            <button
              key={broker.name}
              onClick={() => handleSwitchBroker(broker.name)}
              disabled={brokerSwitching || broker.active}
              className={`rounded-lg border p-4 text-left transition-all ${
                broker.active
                  ? 'border-emerald-500/50 bg-emerald-500/10 ring-1 ring-emerald-500/30'
                  : 'border-slate-700 bg-slate-800/50 hover:border-slate-600 hover:bg-slate-800'
              } disabled:cursor-default`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-slate-100">{broker.display_name}</span>
                {broker.active && (
                  <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-bold uppercase text-emerald-400">
                    Active
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className={broker.configured ? 'text-emerald-400' : 'text-slate-500'}>
                  {broker.configured ? '● Configured' : '○ Not configured'}
                </span>
                <span className={broker.authenticated ? 'text-emerald-400' : 'text-slate-500'}>
                  {broker.authenticated ? '● Auth\'d' : '○ Not auth\'d'}
                </span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Fyers API Connection */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="flex items-center gap-3 mb-6">
          <Settings className="h-5 w-5 text-slate-400" />
          <h3 className="text-lg font-semibold text-slate-100">
            Fyers API Connection
          </h3>
        </div>
        <AuthWizard />
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="mb-4 flex items-center gap-3">
          <MessageSquare className="h-5 w-5 text-slate-400" />
          <h3 className="text-lg font-semibold text-slate-100">Telegram Integration</h3>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span
            className={
              telegramConfig?.active
                ? 'text-emerald-400'
                : telegramConfig?.configured && telegramConfig?.enabled
                  ? 'text-amber-300'
                  : 'text-slate-500'
            }
          >
            {telegramConfig?.active
              ? 'Configured and active'
              : telegramConfig?.configured && telegramConfig?.enabled
                ? 'Configured'
                : telegramConfig?.configured
                  ? 'Configured but disabled'
                : 'Not configured'}
          </span>
          <span className={telegramConfig?.enabled ? 'text-emerald-400' : 'text-slate-500'}>
            Alerts: {telegramConfig?.enabled ? 'On' : 'Off'}
          </span>
          <span className="text-slate-500">
            Interval: {telegramConfig?.status_interval_minutes ?? telegramInterval} min
          </span>
          {telegramConfig?.last_error && (
            <span className="text-red-400">
              Last error: {telegramConfig.last_error}
            </span>
          )}
          <button
            onClick={() => saveTelegram.mutate({ enabled: !(telegramConfig?.enabled ?? true) })}
            disabled={saveTelegram.isPending || !telegramConfig?.configured}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-slate-200 hover:bg-slate-700 disabled:opacity-50"
          >
            {telegramConfig?.enabled ? 'Disable Alerts' : 'Enable Alerts'}
          </button>
          <button
            onClick={handleOpenTelegramDialog}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-slate-200 hover:bg-slate-700"
          >
            Configure Telegram
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="mb-4 flex items-center gap-3">
          <KeyRound className="h-5 w-5 text-slate-400" />
          <h3 className="text-lg font-semibold text-slate-100">US Data Provider Keys</h3>
        </div>
        <p className="mb-4 text-sm text-slate-400">
          Finnhub is now preferred for US intraday candles and quote fallback when configured. Alpha Vantage stays enabled as the slower secondary fallback for US OHLC and chart history.
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs text-slate-400">Finnhub API Key</label>
            <input
              type="password"
              value={finnhubKey}
              onChange={(e) => setFinnhubKey(e.target.value)}
              placeholder={providers?.finnhub_configured ? 'Configured (enter to replace)' : 'Enter FINNHUB key'}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
            />
            <p className="mt-1 text-[11px] text-slate-500">
              Status:{' '}
              <span className={providers?.finnhub_configured ? 'text-emerald-400' : 'text-slate-400'}>
                {providers?.finnhub_configured ? 'Configured' : 'Not configured'}
              </span>
            </p>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-400">Alpha Vantage API Key</label>
            <input
              type="password"
              value={alphaKey}
              onChange={(e) => setAlphaKey(e.target.value)}
              placeholder={providers?.alphavantage_configured ? 'Configured (enter to replace)' : 'Enter ALPHAVANTAGE key'}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
            />
            <p className="mt-1 text-[11px] text-slate-500">
              Status:{' '}
              <span className={providers?.alphavantage_configured ? 'text-emerald-400' : 'text-slate-400'}>
                {providers?.alphavantage_configured ? 'Configured' : 'Not configured'}
              </span>
            </p>
          </div>
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={handleSaveProviders}
            disabled={saveProviders.isPending}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            {saveProviders.isPending ? 'Saving...' : 'Save Provider Keys'}
          </button>
          {saveProviders.isSuccess && (
            <span className="text-xs text-emerald-400">Saved. New scans and chart requests will use the updated providers immediately.</span>
          )}
          {saveProviders.isError && (
            <span className="text-xs text-red-400">
              {saveProviders.error instanceof Error ? saveProviders.error.message : 'Failed to save keys'}
            </span>
          )}
        </div>
      </div>

      {/* System Info */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="flex items-center gap-3 mb-6">
          <Server className="h-5 w-5 text-slate-400" />
          <h3 className="text-lg font-semibold text-slate-100">
            System Information
          </h3>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
            <div className="flex items-center gap-2 mb-1">
              <Database className="h-4 w-4 text-slate-500" />
              <span className="text-xs text-slate-500">Trading Mode</span>
            </div>
            <span className="rounded-md bg-yellow-500/20 px-2 py-0.5 text-xs font-semibold uppercase text-yellow-400">
              Paper
            </span>
          </div>

          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
            <div className="flex items-center gap-2 mb-1">
              <Server className="h-4 w-4 text-slate-500" />
              <span className="text-xs text-slate-500">Backend</span>
            </div>
            <span className="text-sm text-slate-200">FastAPI v0.1.0</span>
          </div>

          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
            <div className="flex items-center gap-2 mb-1">
              <Database className="h-4 w-4 text-slate-500" />
              <span className="text-xs text-slate-500">Database</span>
            </div>
            <span className="text-sm text-slate-200">TimescaleDB</span>
          </div>
        </div>
      </div>

      {telegramDialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-2xl rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
              <div>
                <h3 className="text-base font-semibold text-slate-100">Telegram Configuration</h3>
                <p className="text-xs text-slate-500">Save bot/chat settings and test notifications.</p>
              </div>
              <button
                onClick={() => setTelegramDialogOpen(false)}
                className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-4 px-5 py-4">
              <p className="text-xs text-slate-500">
                Leave token/chat blank to keep existing saved credentials. Use Clear Credentials to remove the saved bot and chat ID.
              </p>

              <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-slate-100">Automatic alerts</p>
                  <p className="text-xs text-slate-500">
                    Disable local alerts if you want only the AWS instance to send Telegram messages.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setTelegramEnabled((current) => !current)}
                  className={telegramEnabled
                    ? 'rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-medium text-emerald-300'
                    : 'rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-medium text-slate-300'}
                >
                  {telegramEnabled ? 'Enabled' : 'Disabled'}
                </button>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
                <p className="text-sm font-medium text-slate-200">How to get Telegram bot token and chat ID</p>
                <ol className="mt-3 space-y-2 text-xs text-slate-400 list-decimal pl-4">
                  <li>
                    Open <a href="https://t.me/BotFather" target="_blank" rel="noreferrer" className="text-emerald-400 hover:text-emerald-300">BotFather</a> in Telegram and run <code>/newbot</code>.
                  </li>
                  <li>
                    Copy the bot token BotFather returns and paste it into the Bot Token field below.
                  </li>
                  <li>
                    Open a direct chat with your bot and send one message such as <code>/start</code>.
                  </li>
                  <li>
                    Open <a href={trimmedBotToken ? getUpdatesUrl : 'https://core.telegram.org/bots/api#getupdates'} target="_blank" rel="noreferrer" className="text-emerald-400 hover:text-emerald-300">{trimmedBotToken ? 'getUpdates for this bot' : 'Telegram Bot API getUpdates docs'}</a>.
                  </li>
                  <li>
                    Find <code>chat.id</code> in the JSON response. Use that numeric value here. Group chat IDs are usually negative.
                  </li>
                </ol>
                <p className="mt-3 text-[11px] text-slate-500">
                  If you are sending alerts to a group, add the bot to that group and send at least one message before checking <code>getUpdates</code>.
                </p>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs text-slate-400">Bot Token</label>
                  <input
                    type="password"
                    value={telegramBotToken}
                    onChange={(e) => setTelegramBotToken(e.target.value)}
                    placeholder={telegramConfig?.bot_configured ? 'Configured (enter to replace)' : 'Enter bot token'}
                    className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-slate-400">Chat ID</label>
                  <input
                    type="text"
                    value={telegramChatId}
                    onChange={(e) => setTelegramChatId(e.target.value)}
                    placeholder={telegramConfig?.chat_configured ? 'Configured (enter to replace)' : 'Enter numeric chat ID'}
                    className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
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
                    className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                  />
                </div>
                <div className="flex items-end">
                  <p className="text-xs text-slate-500">
                    Current: {telegramConfig?.configured ? 'Configured' : 'Not configured'} · Alerts {telegramEnabled ? 'enabled' : 'disabled'}
                  </p>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-t border-slate-800 px-5 py-3">
              <button
                onClick={handleSaveTelegram}
                disabled={saveTelegram.isPending}
                className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
              >
                {saveTelegram.isPending ? 'Saving...' : 'Save'}
              </button>
              <button
                onClick={handleClearTelegram}
                disabled={saveTelegram.isPending}
                className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-200 hover:bg-red-950/70 disabled:opacity-50"
              >
                Clear Credentials
              </button>
              <button
                onClick={() => testTelegram.mutate()}
                disabled={testTelegram.isPending}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700 disabled:opacity-50"
              >
                {testTelegram.isPending ? 'Testing…' : 'Test Message'}
              </button>
              <button
                onClick={() => notifyTelegramStatus.mutate()}
                disabled={notifyTelegramStatus.isPending}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700 disabled:opacity-50"
              >
                <Send className="h-3.5 w-3.5" />
                {notifyTelegramStatus.isPending ? 'Sending…' : 'Send Status'}
              </button>
              <button
                onClick={() => notifyTelegramFractalScan.mutate()}
                disabled={notifyTelegramFractalScan.isPending}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700 disabled:opacity-50"
              >
                <Send className="h-3.5 w-3.5" />
                {notifyTelegramFractalScan.isPending ? 'Sending…' : 'Send Fractal Scan'}
              </button>
              <button
                onClick={() => setTelegramDialogOpen(false)}
                className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800"
              >
                Close
              </button>

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
        </div>
      )}
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          <span className="ml-3 text-sm text-slate-400">Loading settings...</span>
        </div>
      }
    >
      <SettingsContent />
    </Suspense>
  );
}

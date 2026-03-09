'use client';

import type {
  WatchlistUniverseInstrument,
  WatchlistUniverseResponse,
} from '@/types/api';

export interface InstrumentOption {
  value: string;
  label: string;
  market: string;
  exchange: string;
  assetClass: string;
  derivatives: string[];
}

export const DEFAULT_INSTRUMENT_OPTIONS: InstrumentOption[] = [
  { value: 'NSE:NIFTY50-INDEX', label: 'NSE • Nifty 50', market: 'NSE', exchange: 'NSE', assetClass: 'index', derivatives: ['futures', 'options'] },
  { value: 'NSE:NIFTYBANK-INDEX', label: 'NSE • Bank Nifty', market: 'NSE', exchange: 'NSE', assetClass: 'index', derivatives: ['futures', 'options'] },
  { value: 'NSE:FINNIFTY-INDEX', label: 'NSE • Fin Nifty', market: 'NSE', exchange: 'NSE', assetClass: 'index', derivatives: ['futures', 'options'] },
  { value: 'NSE:NIFTYMIDCAP50-INDEX', label: 'NSE • Midcap Nifty', market: 'NSE', exchange: 'NSE', assetClass: 'index', derivatives: ['futures', 'options'] },
  { value: 'BSE:SENSEX-INDEX', label: 'BSE • Sensex', market: 'BSE', exchange: 'BSE', assetClass: 'index', derivatives: ['futures', 'options'] },
  { value: 'US:SPY', label: 'US • SPY', market: 'US', exchange: 'US', assetClass: 'etf', derivatives: ['options'] },
  { value: 'US:QQQ', label: 'US • QQQ', market: 'US', exchange: 'US', assetClass: 'etf', derivatives: ['options'] },
  { value: 'US:DIA', label: 'US • DIA', market: 'US', exchange: 'US', assetClass: 'etf', derivatives: ['options'] },
  { value: 'US:IWM', label: 'US • IWM', market: 'US', exchange: 'US', assetClass: 'etf', derivatives: ['options'] },
  { value: 'US:AAPL', label: 'US • Apple', market: 'US', exchange: 'US', assetClass: 'equity', derivatives: ['options'] },
  { value: 'CRYPTO:BTCUSDT', label: 'CRYPTO • BTC', market: 'CRYPTO', exchange: 'BINANCE', assetClass: 'crypto_spot', derivatives: ['options'] },
  { value: 'CRYPTO:ETHUSDT', label: 'CRYPTO • ETH', market: 'CRYPTO', exchange: 'BINANCE', assetClass: 'crypto_spot', derivatives: ['options'] },
];

function marketRank(market: string): number {
  const token = market.toUpperCase();
  if (token === 'NSE') return 0;
  if (token === 'BSE') return 1;
  if (token === 'US') return 2;
  if (token === 'CRYPTO') return 3;
  return 9;
}

function normalizeOption(item: WatchlistUniverseInstrument): InstrumentOption {
  const market = String(item.market || '').toUpperCase();
  const prefix = market === 'CRYPTO' ? 'CRYPTO' : market || item.exchange || 'MARKET';
  return {
    value: item.symbol,
    label: `${prefix} • ${item.display_name}`,
    market,
    exchange: item.exchange,
    assetClass: item.asset_class,
    derivatives: item.derivatives ?? [],
  };
}

export function buildInstrumentOptions(
  universe?: WatchlistUniverseResponse | null,
): InstrumentOption[] {
  const raw = universe?.items?.length
    ? universe.items.map(normalizeOption)
    : DEFAULT_INSTRUMENT_OPTIONS;
  const deduped = new Map<string, InstrumentOption>();
  for (const item of raw) {
    if (!deduped.has(item.value)) {
      deduped.set(item.value, item);
    }
  }
  return Array.from(deduped.values()).sort((a, b) => {
    const marketDiff = marketRank(a.market) - marketRank(b.market);
    if (marketDiff !== 0) return marketDiff;
    return a.label.localeCompare(b.label);
  });
}

export function filterInstrumentOptions(
  options: InstrumentOption[],
  market: string,
): InstrumentOption[] {
  const token = String(market || 'ALL').toUpperCase();
  if (!token || token === 'ALL') return options;
  return options.filter((item) => item.market === token);
}

export function defaultSymbolForMarket(
  options: InstrumentOption[],
  market: string,
  fallback?: string,
): string {
  const filtered = filterInstrumentOptions(options, market);
  if (fallback && filtered.some((item) => item.value === fallback)) {
    return fallback;
  }
  return filtered[0]?.value ?? options[0]?.value ?? '';
}

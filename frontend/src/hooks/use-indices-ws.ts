'use client';

/**
 * useIndicesWS — real-time LTP updates for all 5 indices via WebSocket.
 *
 * Connects to /ws/ticks/all on the backend which broadcasts every Fyers tick.
 * We map the incoming symbol strings (e.g. "NSE:NIFTY50-INDEX") to short index
 * names (e.g. "NIFTY") so the indices page can overlay live prices on top of
 * the HTTP summary baseline.
 *
 * The hook returns:
 *   prices   — Record<indexName, LivePrice>  (only symbols seen so far)
 *   isConnected — whether the WS is currently open
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { useWebSocket } from './use-websocket';

export interface LivePrice {
  ltp: number;
  change?: number;
  change_pct?: number;
  volume?: number;
  bid?: number;
  ask?: number;
  timestamp?: string;
}

// Map every possible Fyers symbol string → short index name
// Spot symbols, futures prefixes, etc.
const SYMBOL_TO_NAME: Record<string, string> = {
  // Spot
  'NSE:NIFTY50-INDEX':    'NIFTY',
  'NSE:NIFTYBANK-INDEX':  'BANKNIFTY',
  'NSE:FINNIFTY-INDEX':   'FINNIFTY',
  'NSE:NIFTYMIDCAP50-INDEX': 'MIDCPNIFTY',
  'NSE:MIDCPNIFTY-INDEX': 'MIDCPNIFTY',
  'BSE:SENSEX-INDEX':     'SENSEX',
  // Futures root (broker may send the continuous/current month prefix)
  'NSE:NIFTY':            'NIFTY',
  'NSE:BANKNIFTY':        'BANKNIFTY',
  'NSE:FINNIFTY':         'FINNIFTY',
  'NSE:NIFTYMIDCAP50':    'MIDCPNIFTY',
  'NSE:MIDCPNIFTY':       'MIDCPNIFTY',
  'BSE:SENSEX':           'SENSEX',
};

// Longest-first prefix scan prevents accidental matches
// (e.g. NSE:NIFTYBANK... incorrectly matching NSE:NIFTY).
const SYMBOL_PREFIXES = Object.keys(SYMBOL_TO_NAME).sort(
  (a, b) => b.length - a.length
);

/** Attempt to resolve a raw Fyers tick symbol to a known index name. */
function resolveSymbol(raw: string): string | null {
  const normalized = raw.trim().toUpperCase();
  // Exact match first
  if (SYMBOL_TO_NAME[normalized]) return SYMBOL_TO_NAME[normalized];

  // Futures contracts look like "NSE:NIFTY25MAY25FUT" — strip the suffix
  for (const prefix of SYMBOL_PREFIXES) {
    if (normalized.startsWith(prefix)) return SYMBOL_TO_NAME[prefix];
  }

  return null;
}

export interface UseIndicesWSReturn {
  prices: Record<string, LivePrice>;
  isConnected: boolean;
  lastTickAt: number | null;
  tickCount: number;
}

export function useIndicesWS(enabled = true): UseIndicesWSReturn {
  const [prices, setPrices] = useState<Record<string, LivePrice>>({});
  const [lastTickAt, setLastTickAt] = useState<number | null>(null);
  const [tickCount, setTickCount] = useState(0);
  // Keep a ref to the latest prices so we can merge without stale closures
  const pricesRef = useRef<Record<string, LivePrice>>({});
  // Debounce isConnected so brief 1-3s reconnects don't flash "Reconnecting"
  const [stableConnected, setStableConnected] = useState(false);
  const disconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const onMessage = useCallback((raw: unknown) => {
    if (!raw || typeof raw !== 'object') return;
    const msg = raw as Record<string, unknown>;

    // Skip heartbeats
    if (msg.type === 'heartbeat') return;

    const symbol = msg.symbol as string | undefined;
    if (!symbol) return;

    const name = resolveSymbol(symbol);
    if (!name) return;

    // Only update numeric ltp — guard against bad payloads
    const ltp = typeof msg.ltp === 'number' ? msg.ltp : null;
    if (!ltp) return;

    const next: LivePrice = {
      ltp,
      change:     typeof msg.change     === 'number' ? msg.change     : pricesRef.current[name]?.change,
      change_pct: typeof msg.change_pct === 'number' ? msg.change_pct : pricesRef.current[name]?.change_pct,
      volume:     typeof msg.volume     === 'number' ? msg.volume     : pricesRef.current[name]?.volume,
      bid:        typeof msg.bid        === 'number' ? msg.bid        : pricesRef.current[name]?.bid,
      ask:        typeof msg.ask        === 'number' ? msg.ask        : pricesRef.current[name]?.ask,
      timestamp:  typeof msg.timestamp  === 'string' ? msg.timestamp  : new Date().toISOString(),
    };

    pricesRef.current = { ...pricesRef.current, [name]: next };
    setPrices((prev) => ({ ...prev, [name]: next }));
    setLastTickAt(Date.now());
    setTickCount((prev) => prev + 1);
  }, []);

  const { isConnected } = useWebSocket({
    path: '/ws/ticks/all',
    onMessage,
    enabled,
    reconnectInterval: 2000,   // retry every 2 s on drop
  });

  // Debounce: only show as disconnected after 6s of continuous loss.
  // This hides the brief 1-3s reconnects that happen when Fyers resets the socket.
  useEffect(() => {
    if (isConnected) {
      if (disconnectTimerRef.current) {
        clearTimeout(disconnectTimerRef.current);
        disconnectTimerRef.current = null;
      }
      setStableConnected(true);
    } else {
      disconnectTimerRef.current = setTimeout(() => {
        setStableConnected(false);
      }, 6000);
    }
    return () => {
      if (disconnectTimerRef.current) clearTimeout(disconnectTimerRef.current);
    };
  }, [isConnected]);

  return { prices, isConnected: stableConnected, lastTickAt, tickCount };
}

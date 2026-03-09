'use client';

/**
 * useOrderflowWS — real-time footprint bars via WebSocket.
 *
 * Connects to /ws/orderflow/{symbol}?bar_minutes=N which is fed
 * directly from the RealTimeAggregator in the backend. Each tick
 * updates the current bar's price-level bid/ask volumes in ~ms latency.
 *
 * Returns:
 *   bars         — array of FootprintBar (history + live current)
 *   currentBar   — the latest live bar (partial, updating in real-time)
 *   isConnected  — WebSocket connection status
 *   latencyMs    — approximate tick → UI latency in milliseconds
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useWebSocket } from './use-websocket';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface RtPriceLevel {
  bid: number;
  ask: number;
  delta: number;
  total: number;
}

export interface RtFootprintBar {
  symbol: string;
  open_time: string;
  close_time: string;
  bar_minutes: number;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number;
  delta: number;
  /** price (string) → { bid, ask, delta, total } */
  levels: Record<string, RtPriceLevel>;
}

interface OrderflowPayload {
  type: 'orderflow_snapshot' | 'orderflow_update' | 'heartbeat';
  symbol?: string;
  bar_minutes?: number;
  bars?: RtFootprintBar[];
  bar?: RtFootprintBar;
}

// ─── Hook ────────────────────────────────────────────────────────────────────

export function useOrderflowWS(
  symbol: string | null | undefined,
  barMinutes = 5,
  enabled = true
) {
  const [bars, setBars] = useState<RtFootprintBar[]>([]);
  const [currentBar, setCurrentBar] = useState<RtFootprintBar | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const lastTickRef = useRef<number>(0);

  const onMessage = useCallback((data: unknown) => {
    const payload = data as OrderflowPayload;
    const now = Date.now();

    if (payload.type === 'orderflow_snapshot') {
      // Full history on first connect
      if (payload.bars && payload.bars.length > 0) {
        const allBars = [...payload.bars];
        const last = allBars.pop()!;          // last = live current bar
        setBars(allBars);
        setCurrentBar(last);
      }
      return;
    }

    if (payload.type === 'orderflow_update' && payload.bar) {
      const bar = payload.bar;
      setCurrentBar(bar);

      // Compute latency from bar close_time tick boundary
      if (lastTickRef.current > 0) {
        setLatencyMs(now - lastTickRef.current);
      }
      lastTickRef.current = now;
      return;
    }
    // heartbeat — ignore
  }, []);

  const active = Boolean(enabled && symbol);
  useEffect(() => {
    setBars([]);
    setCurrentBar(null);
    setLatencyMs(null);
    lastTickRef.current = 0;
  }, [symbol, barMinutes, active]);

  const ws = useWebSocket({
    path: symbol
      ? `/ws/orderflow/${encodeURIComponent(symbol)}?bar_minutes=${barMinutes}`
      : '/ws/orderflow/__none',
    onMessage,
    reconnectInterval: 2000,
    enabled: active,
  });

  return {
    bars,
    currentBar,
    latencyMs,
    isConnected: ws.isConnected,
  };
}

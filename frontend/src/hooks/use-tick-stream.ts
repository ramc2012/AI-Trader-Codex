'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { useWebSocket, WebSocketMessage } from './use-websocket';

export interface TickData {
  symbol: string;
  ltp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  vtt: number; // Volume
  oi: number;
  oich: number;
  timestamp: string;
}

/**
 * useTickStream - A generic hook for high-performance tick data streaming.
 * Listens to /ws/ticks/all and maintains a local cache of the latest tick for each symbol.
 */
export function useTickStream() {
  const [ticks, setTicks] = useState<Record<string, TickData>>({});
  const ticksRef = useRef<Record<string, TickData>>({});
  const lastUpdateRef = useRef<number>(0);
  const rafRef = useRef<number>(0);

  const onMessage = useCallback((data: WebSocketMessage) => {
    // Expecting tick data from /ws/ticks/all
    // Each message contains ltp, volume, oi, etc.
    if (data.type === 'heartbeat') return;

    const symbol = data.symbol as string;
    if (!symbol) return;

    const tick: TickData = {
      symbol,
      ltp: Number(data.ltp || data.lp || 0),
      open: Number(data.open || data.o || 0),
      high: Number(data.high || data.h || 0),
      low: Number(data.low || data.l || 0),
      close: Number(data.close || data.c || 0),
      vtt: Number(data.vtt || data.v || 0),
      oi: Number(data.oi || 0),
      oich: Number(data.oich || 0),
      timestamp: String(data.timestamp || new Date().toISOString()),
    };

    ticksRef.current[symbol] = tick;

    // Use RequestAnimationFrame to throttle state updates for UI performance
    const now = Date.now();
    if (now - lastUpdateRef.current > 100) { // Max 10 updates per second
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        setTicks({ ...ticksRef.current });
        lastUpdateRef.current = Date.now();
      });
    }
  }, []);

  const { isConnected, reconnect } = useWebSocket({
    path: '/ws/ticks/all',
    onMessage,
  });

  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return { ticks, isConnected, reconnect };
}

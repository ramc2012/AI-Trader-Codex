'use client';

import { useState, useCallback, useEffect } from 'react';
import { useWebSocket } from './use-websocket';

export interface StyleSignal {
  symbol: string;
  direction: 'BUY' | 'SELL';
  strategy: string;
  price: number;
  target: number;
  stop_loss: number;
  strength: string;
  vwap?: number;
  vol_ratio?: number;
  hold_minutes: number;
  timestamp: string;
  metadata?: Record<string, any>;
}

export interface StylePosition {
  symbol: string;
  side: string;
  entry_price: number;
  current_price: number;
  pnl: number;
  pnl_pct: number;
  duration_minutes: number;
}

export function useStreamingStyle(style: 'scalping' | 'swing' | 'positional') {
  const [signals, setSignals] = useState<StyleSignal[]>([]);
  const [positions, setPositions] = useState<StylePosition[]>([]);
  const [loading, setLoading] = useState(true);

  const onMessage = useCallback((message: any) => {
    if (!message) return;

    if (message.type === 'initial_status') {
      const status = message.data;
      
      // Parse signals
      const agentSignals = status.recent_signals || [];
      const filteredSignals = agentSignals
        .filter((s: any) => s.trading_style === style || s.strategy_name?.toLowerCase().includes(style === 'positional' ? 'trend' : style))
        .map((s: any) => ({
          symbol: s.symbol || '',
          direction: s.signal_type === 'buy' ? 'BUY' : 'SELL',
          strategy: s.strategy_name || 'strategy',
          price: s.price || 0,
          target: s.target || 0,
          stop_loss: s.stop_loss || 0,
          strength: s.strength || 'moderate',
          vwap: s.metadata?.vwap || 0,
          vol_ratio: s.metadata?.vol_ratio || 0,
          hold_minutes: s.holding_period_minutes || (style === 'scalping' ? 10 : style === 'swing' ? 60 : 1440),
          timestamp: s.timestamp || new Date().toISOString(),
        }));
      setSignals(filteredSignals.reverse().slice(0, 50)); // Last 50 signals
      
      // We don't have position breakdown by style yet easily via REST, 
      // but if we did, we'd parse it here. For now, empty or global.
      setPositions([]);
      setLoading(false);
    } 
    else if (message.type === 'agent_event') {
      if (message.event_type === 'signal_generated') {
        const meta = message.metadata || {};
        const newSignal: StyleSignal = {
          symbol: meta.symbol || '',
          direction: meta.side === 'buy' ? 'BUY' : 'SELL',
          strategy: meta.strategy || 'strategy',
          price: meta.price || 0,
          target: meta.target || 0,
          stop_loss: meta.stop_loss || 0,
          strength: meta.strength || 'moderate',
          vwap: meta.vwap,
          vol_ratio: meta.vol_ratio,
          hold_minutes: meta.hold_minutes || (style === 'scalping' ? 10 : style === 'swing' ? 60 : 1440),
          timestamp: message.timestamp || new Date().toISOString(),
        };
        
        setSignals(prev => {
          const next = [newSignal, ...prev];
          return next.slice(0, 50);
        });
      }
    }
  }, [style]);

  const { isConnected, reconnect } = useWebSocket({
    path: `/agent/ws/stream?style=${style}`,
    onMessage,
    reconnectInterval: 3000,
  });

  return { 
    signals, 
    positions, 
    loading: loading && !isConnected,
    isConnected,
    refresh: reconnect
  };
}

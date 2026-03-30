'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

function defaultWsBase(): string {
  if (typeof window === 'undefined') {
    return 'ws://localhost:8000/api/v1';
  }
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const host = window.location.hostname;
  const frontendPort = window.location.port || '';
  
  // Map frontend ports to backend ports consistently
  const explicitMap: Record<string, string> = {
    '3000': '8000',
    '80': '8000',
    '3100': '8100',
    '3200': '8000',
    '3201': '8001', // Cloud production port
  };
  
  const mapped = explicitMap[frontendPort];
  // Default to 8000 if no map, or use explicit mapping
  const backendPort = mapped || '8000';
  
  return `${protocol}://${host}:${backendPort}/api/v1`;
}

function resolveWsUrl(path: string): string {
  const wsBase = process.env.NEXT_PUBLIC_WS_URL || defaultWsBase();
  if (wsBase.startsWith('ws://') || wsBase.startsWith('wss://')) {
    return `${wsBase}${path}`;
  }

  if (wsBase.startsWith('/')) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}${wsBase}${path}`;
  }

  return `${wsBase}${path}`;
}

interface UseWebSocketOptions {
  path: string;
  onMessage?: (data: unknown) => void;
  reconnectInterval?: number;
  enabled?: boolean;
}

interface UseWebSocketReturn {
  isConnected: boolean;
  lastMessage: unknown;
  send: (data: unknown) => void;
  reconnect: () => void;
}

export function useWebSocket({
  path,
  onMessage,
  reconnectInterval = 5000,
  enabled = true,
}: UseWebSocketOptions): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectRef = useRef<() => void>(() => {});
  const [isConnected, setIsConnected] = useState(false);
  const lastMessageRef = useRef<unknown>(null);

  const connect = useCallback(() => {
    if (!enabled) return;

    try {
      const ws = new WebSocket(resolveWsUrl(path));
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          lastMessageRef.current = data;
          onMessage?.(data);
        } catch {
          lastMessageRef.current = event.data;
          onMessage?.(event.data);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;

        if (enabled) {
          reconnectTimerRef.current = setTimeout(() => connectRef.current(), reconnectInterval);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      if (enabled) {
        reconnectTimerRef.current = setTimeout(() => connectRef.current(), reconnectInterval);
      }
    }
  }, [path, onMessage, reconnectInterval, enabled]);

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const reconnect = useCallback(() => {
    wsRef.current?.close();
    connect();
  }, [connect]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      wsRef.current?.close();
    };
  }, [connect]);

  return { isConnected, lastMessage: lastMessageRef.current, send, reconnect };
}

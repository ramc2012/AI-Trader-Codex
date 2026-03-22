'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

let runtimeWsBasePromise: Promise<string> | null = null;

function isLocalHost(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1';
}

function sanitizeWsBase(configured: string): string {
  const trimmed = configured.trim();
  if (!trimmed) {
    return '';
  }

  if (typeof window !== 'undefined') {
    // Ignore baked localhost values in production images and fall back to
    // runtime host detection instead.
    const currentHost = window.location.hostname;
    if (
      !isLocalHost(currentHost) &&
      (trimmed.includes('localhost') || trimmed.includes('127.0.0.1'))
    ) {
      return '';
    }
  }

  return trimmed;
}

function configuredWsBase(): string {
  if (typeof document === 'undefined') {
    return '';
  }

  return sanitizeWsBase(document.body.dataset.wsBase || '');
}

function defaultWsBase(): string {
  if (typeof window === 'undefined') {
    return 'ws://localhost:8000/api/v1';
  }
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const host = window.location.hostname;
  const frontendPort = window.location.port || '';
  const explicitMap: Record<string, string> = {
    '3000': '8000',
    '3100': '8000',
    '3200': '8000',
    '3201': '8201',
  };
  const mapped = explicitMap[frontendPort];
  const backendPort = mapped || (frontendPort ? String(Number(frontendPort) + 5000) : '8000');
  return `${protocol}://${host}:${backendPort}/api/v1`;
}

async function runtimeWsBase(): Promise<string> {
  if (typeof window === 'undefined') {
    return '';
  }

  const configured = configuredWsBase();
  if (configured) {
    return configured;
  }

  if (runtimeWsBasePromise === null) {
    runtimeWsBasePromise = (async () => {
      try {
        const response = await fetch('/api/runtime-config', {
          cache: 'no-store',
        });
        if (!response.ok) {
          return '';
        }

        const payload = (await response.json()) as { wsBase?: string };
        return sanitizeWsBase(payload.wsBase || '');
      } catch {
        return '';
      }
    })();
  }

  return runtimeWsBasePromise;
}

function buildWsUrl(wsBase: string, path: string): string {
  if (wsBase.startsWith('ws://') || wsBase.startsWith('wss://')) {
    return `${wsBase}${path}`;
  }

  if (wsBase.startsWith('/')) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}${wsBase}${path}`;
  }

  return `${wsBase}${path}`;
}

async function resolveWsUrl(path: string): Promise<string> {
  const wsBase = (await runtimeWsBase()) || defaultWsBase();
  return buildWsUrl(wsBase, path);
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
  const disposedRef = useRef(false);
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<unknown>(null);

  const connect = useCallback(() => {
    if (!enabled) return;

    void (async () => {
      try {
        const wsUrl = await resolveWsUrl(path);
        if (disposedRef.current || !enabled) {
          return;
        }

        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          setIsConnected(true);
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            setLastMessage(data);
            onMessage?.(data);
          } catch {
            setLastMessage(event.data);
            onMessage?.(event.data);
          }
        };

        ws.onclose = () => {
          setIsConnected(false);
          wsRef.current = null;

          if (enabled && !disposedRef.current) {
            reconnectTimerRef.current = setTimeout(() => connectRef.current(), reconnectInterval);
          }
        };

        ws.onerror = () => {
          ws.close();
        };
      } catch {
        if (enabled && !disposedRef.current) {
          reconnectTimerRef.current = setTimeout(() => connectRef.current(), reconnectInterval);
        }
      }
    })();
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
    disposedRef.current = false;
    connect();

    return () => {
      disposedRef.current = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      wsRef.current?.close();
    };
  }, [connect]);

  return { isConnected, lastMessage, send, reconnect };
}

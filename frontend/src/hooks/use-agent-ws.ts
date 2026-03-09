'use client';

import { useCallback, useState } from 'react';
import { useWebSocket } from './use-websocket';
import type { AgentEvent, AgentWSPayload } from '@/types/api';

const MAX_EVENTS = 500;

/**
 * WebSocket hook for streaming AI agent events.
 * Connects to /ws/agent and accumulates events in state.
 */
export function useAgentWS(enabled = true) {
  const [events, setEvents] = useState<AgentEvent[]>([]);

  const onMessage = useCallback((data: unknown) => {
    const payload = data as AgentWSPayload;
    if (payload.type !== 'agent_event') return;

    const event: AgentEvent = {
      event_id: payload.event_id ?? '',
      event_type: payload.event_type ?? '',
      timestamp: payload.timestamp,
      title: payload.title ?? '',
      message: payload.message ?? '',
      severity: (payload.severity as AgentEvent['severity']) ?? 'info',
      metadata: payload.metadata ?? {},
    };

    setEvents((prev) => {
      const next = [...prev, event];
      return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
    });
  }, []);

  const ws = useWebSocket({
    path: '/ws/agent',
    onMessage,
    reconnectInterval: 3000,
    enabled,
  });

  const clearEvents = useCallback(() => setEvents([]), []);

  return { ...ws, events, clearEvents };
}

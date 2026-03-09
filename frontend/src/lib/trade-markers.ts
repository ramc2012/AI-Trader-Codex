import type { AgentEvent } from '@/types/api';
import type { TradeMarkerInput } from '@/components/charts/candlestick-chart';

function timeframeToSeconds(timeframe: string): number {
  const token = String(timeframe || '').trim().toUpperCase();
  if (token === 'D' || token === '1D') return 86400;
  if (token === 'W' || token === '1W') return 86400 * 7;
  const minutes = Number.parseInt(token, 10);
  if (Number.isFinite(minutes) && minutes > 0) return minutes * 60;
  return 300;
}

function alignToTimeframe(epochSec: number, tfSec: number): number {
  return Math.floor(epochSec / tfSec) * tfSec;
}

function eventMatchesSymbol(event: AgentEvent, symbol: string): boolean {
  const meta = (event.metadata ?? {}) as Record<string, unknown>;
  const direct = String(meta.symbol ?? '').trim();
  const underlying = String(meta.underlying_symbol ?? '').trim();
  return direct === symbol || underlying === symbol;
}

export function buildTradeMarkersFromEvents(
  events: AgentEvent[],
  symbol: string,
  timeframe: string,
  firstEpochSec: number,
  lastEpochSec: number,
): TradeMarkerInput[] {
  if (!events.length || !symbol) return [];
  const tfSec = timeframeToSeconds(timeframe);
  const out: TradeMarkerInput[] = [];

  for (const event of events) {
    if (
      event.event_type !== 'order_placed' &&
      event.event_type !== 'order_filled' &&
      event.event_type !== 'position_opened' &&
      event.event_type !== 'position_closed'
    ) {
      continue;
    }
    if (!eventMatchesSymbol(event, symbol)) {
      continue;
    }

    const epoch = Math.floor(new Date(event.timestamp).getTime() / 1000);
    if (!Number.isFinite(epoch)) continue;
    const aligned = alignToTimeframe(epoch, tfSec);
    if (aligned < firstEpochSec || aligned > (lastEpochSec + tfSec)) {
      continue;
    }

    const meta = (event.metadata ?? {}) as Record<string, unknown>;
    if (event.event_type === 'position_closed') {
      out.push({
        time: aligned,
        type: 'exit',
        pnl: Number(meta.pnl ?? 0),
        text: 'EXIT',
      });
      continue;
    }

    const side = String(meta.side ?? '').toUpperCase() === 'SELL' ? 'SELL' : 'BUY';
    out.push({
      time: aligned,
      type: 'entry',
      side,
      text: side,
    });
  }

  return out.slice(-150);
}

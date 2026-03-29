'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface OrderEntry {
  order_id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  order_type: string;
  product_type: string;
  quantity: number;
  filled_quantity: number;
  remaining_quantity: number;
  limit_price: number;
  stop_price: number;
  fill_price: number;
  status: string;
  status_code: number;
  placed_at: string;
  message: string;
  exchange: string;
  is_amo: boolean;
  tag: string;
}

export interface OrderHistoryResponse {
  orders: OrderEntry[];
  total: number;
  note?: string;
  timestamp: string;
}

export interface TradeEntry {
  trade_id: string;
  order_id: string;
  symbol: string;
  exchange: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  value: number;
  product_type: string;
  order_type: string;
  traded_at: string;
  exchange_order_id: string;
}

export interface TradeHistoryResponse {
  trades: TradeEntry[];
  total: number;
  total_buy_value: number;
  total_sell_value: number;
  net_value: number;
  note?: string;
  timestamp: string;
}

export interface TradingSummaryResponse {
  authenticated: boolean;
  orders?: {
    total: number;
    executed: number;
    cancelled: number;
    pending: number;
    rejected: number;
  };
  trades?: {
    total: number;
    total_buy_value: number;
    total_sell_value: number;
    net_value: number;
  };
  note?: string;
  error?: string;
  timestamp: string;
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

export function useOrderHistory(enabled = true) {
  return useQuery<OrderHistoryResponse>({
    queryKey: ['history', 'orders'],
    queryFn: () => apiFetch<OrderHistoryResponse>('/history/orders'),
    refetchInterval: enabled ? 30_000 : false,
    enabled,
  });
}

export function useTradeHistory(enabled = true) {
  return useQuery<TradeHistoryResponse>({
    queryKey: ['history', 'trades'],
    queryFn: () => apiFetch<TradeHistoryResponse>('/history/trades'),
    refetchInterval: enabled ? 30_000 : false,
    enabled,
  });
}

export function useTradingSummary(enabled = true) {
  return useQuery<TradingSummaryResponse>({
    queryKey: ['history', 'summary'],
    queryFn: () => apiFetch<TradingSummaryResponse>('/history/summary'),
    refetchInterval: enabled ? 60_000 : false,
    enabled,
  });
}

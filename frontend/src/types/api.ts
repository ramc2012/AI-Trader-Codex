export interface Position {
  symbol: string;
  quantity: number;
  side: string;
  avg_price: number;
  current_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  market_value: number;
  strategy_tag: string;
}

export interface Order {
  order_id: string | null;
  symbol: string;
  quantity: number;
  side: string;
  order_type: string;
  product_type: string;
  status: string;
  limit_price: number | null;
  stop_price: number | null;
  fill_price: number | null;
  fill_quantity: number;
  placed_at: string | null;
  filled_at: string | null;
  tag: string;
}

export interface PortfolioSummary {
  position_count: number;
  total_market_value: number;
  total_unrealized_pnl: number;
  total_realized_pnl: number;
  total_pnl: number;
  positions: Record<string, unknown>;
}

export interface ExecutorSummary {
  state: string;
  paper_mode: boolean;
  strategies_count: number;
  enabled_count: number;
  total_signals: number;
  total_trades: number;
  strategies: Record<
    string,
    { enabled: boolean; signals: number; trades: number; pnl: number }
  >;
}

export interface Signal {
  timestamp: string;
  symbol: string;
  signal_type: string;
  strength: string;
  price: number | null;
  stop_loss: number | null;
  target: number | null;
  strategy_name: string;
  metadata: Record<string, unknown>;
}

export interface RiskSummary {
  date: string;
  capital: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  open_positions: number;
  max_open_positions: number;
  daily_loss_limit: number;
  available_risk: number;
  circuit_breaker_triggered: boolean;
  emergency_stop: boolean;
}

export interface RiskMetrics {
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  max_drawdown: number;
  max_drawdown_duration: number;
  var_95: number;
  var_99: number;
  cvar_95: number;
  volatility: number;
  downside_volatility: number;
  profit_factor: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  expectancy: number;
  total_return: number;
  annualized_return: number;
}

export interface SystemHealth {
  overall_status: string;
  checked_at: string;
  components: Record<string, ComponentHealth>;
}

export interface ComponentHealth {
  name: string;
  status: string;
  last_check: string;
  message: string;
  latency_ms: number | null;
}

export interface Alert {
  alert_id: string;
  level: string;
  title: string;
  message: string;
  source: string;
  timestamp: string;
  acknowledged: boolean;
  metadata: Record<string, unknown>;
}

export interface AlertCounts {
  info: number;
  warning: number;
  critical: number;
  emergency: number;
}

export interface BacktestResult {
  id?: number;
  strategy_name: string;
  symbol: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  final_capital: number;
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  profit_factor: number;
  avg_win: number;
  avg_loss: number;
  trades: BacktestTrade[];
}

export interface BacktestTrade {
  entry_time: string;
  exit_time: string | null;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  pnl: number;
  pnl_pct: number;
  exit_reason: string;
}

export interface OHLCCandle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OHLCResponse {
  symbol: string;
  timeframe: string;
  count: number;
  candles: OHLCCandle[];
}

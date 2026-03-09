export interface Position {
  symbol: string;
  market: string;
  market_open: boolean;
  quantity: number;
  side: string;
  order_ids?: string[];
  avg_price: number;
  current_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  realized_pnl?: number;
  market_value: number;
  strategy_tag: string;
  entry_time?: string;
  currency?: string;
  currency_symbol?: string;
  fx_to_inr?: number;
  unrealized_pnl_inr?: number;
  market_value_inr?: number;
  stop_loss?: number | null;
  target?: number | null;
  time_exit_at?: string | null;
  time_left_seconds?: number | null;
  distance_to_stop_pct?: number | null;
  distance_to_target_pct?: number | null;
  progress_to_target_pct?: number | null;
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
  total_market_value_inr?: number;
  total_unrealized_pnl_inr?: number;
  total_realized_pnl_inr?: number;
  total_pnl_inr?: number;
  base_currency?: string;
  usd_inr_rate?: number;
  currency_breakdown?: Record<
    string,
    {
      market_value: number;
      unrealized_pnl: number;
      realized_pnl: number;
      market_value_inr: number;
      unrealized_pnl_inr: number;
      realized_pnl_inr: number;
      currency_symbol: string;
      fx_to_inr: number;
    }
  >;
  market_breakdown?: Record<
    string,
    {
      open_positions: number;
      closed_trades: number;
      market_value_inr: number;
      unrealized_pnl_inr: number;
      realized_pnl_inr: number;
      net_pnl_inr: number;
    }
  >;
  positions: Record<string, unknown>;
}

export type PortfolioPeriod = 'daily' | 'week' | 'month' | 'year';

export interface InstrumentPerformanceRow {
  symbol: string;
  currency: string;
  currency_symbol: string;
  fx_to_inr: number;
  trades: number;
  wins: number;
  losses: number;
  buy_notional: number;
  sell_notional: number;
  realized_pnl: number;
  realized_pnl_inr: number;
  unrealized_pnl: number;
  unrealized_pnl_inr: number;
  net_pnl_inr: number;
  avg_hold_minutes: number;
  last_trade_time?: string | null;
  open_quantity: number;
  open_market_value: number;
  open_market_value_inr: number;
}

export interface PortfolioInstrumentSummary {
  period: PortfolioPeriod;
  from_time: string;
  to_time: string;
  total_instruments: number;
  total_trades: number;
  total_realized_pnl_inr: number;
  total_unrealized_pnl_inr: number;
  total_net_pnl_inr: number;
  rows: InstrumentPerformanceRow[];
}

export interface TradePair {
  pair_id: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  pnl: number;
  pnl_pct: number;
  currency: string;
  currency_symbol: string;
  fx_to_inr: number;
  pnl_inr: number;
  entry_time?: string | null;
  exit_time?: string | null;
  entry_order_id?: string | null;
  exit_order_id?: string | null;
  strategy_tag?: string;
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

// =========================================================================
// Auth Types
// =========================================================================

export interface AuthStatus {
  authenticated: boolean;
  profile: Record<string, unknown> | null;
  app_configured: boolean;
}

export interface AuthLoginUrl {
  url: string;
}

export interface TokenStatus {
  access_token_valid: boolean;
  access_token_expires_in_hours: number | null;
  refresh_token_valid: boolean;
  refresh_token_expires_in_days: number | null;
  needs_full_reauth: boolean;
  has_saved_pin: boolean;
}

export interface ManualAuthResponse {
  success: boolean;
  message: string;
  authenticated: boolean;
}

export interface SaveAndLoginResponse {
  success: boolean;
  message: string;
  login_url?: string;
}

export interface TokenRefreshResponse {
  success: boolean;
  message: string;
  access_token_expires_at: string | null;
  refresh_token_expires_in_days: number | null;
  needs_full_reauth: boolean;
}

export interface SavePinResponse {
  success: boolean;
  message: string;
  pin_saved: boolean;
}

export interface AutoRefreshResponse {
  success: boolean;
  message: string;
  refreshed: boolean;
  needs_full_reauth?: boolean;
}

export interface FyersCredentials {
  app_id: string;
  redirect_uri: string;
  configured: boolean;
}

export interface MarketDataProviders {
  finnhub_configured: boolean;
  alphavantage_configured: boolean;
}

export interface TelegramConfig {
  configured: boolean;
  enabled: boolean;
  bot_configured: boolean;
  chat_configured: boolean;
  active: boolean;
  status_interval_minutes: number;
  last_error?: string | null;
}

// =========================================================================
// Watchlist Types
// =========================================================================

export interface DataSummaryItem {
  timeframe: string;
  count: number;
  latest_timestamp: string | null;
}

export interface WatchlistSymbol {
  symbol: string;
  display_name: string;
  data_summary: DataSummaryItem[];
  latest_price: number | null;
  price_change_pct: number | null;
}

export interface CollectionStatus {
  symbol: string;
  timeframe: string;
  status: 'idle' | 'collecting' | 'completed' | 'failed';
  progress: number;
  candles_collected: number;
  error: string | null;
}

export interface WatchlistUniverseInstrument {
  symbol: string;
  display_name: string;
  market: string;
  exchange: string;
  asset_class: string;
  source: string;
  tradable: boolean;
  derivatives: string[];
}

export interface WatchlistUniverseResponse {
  timestamp: string;
  markets: string[];
  total_count: number;
  items: WatchlistUniverseInstrument[];
}

// =========================================================================
// Dashboard WebSocket Types
// =========================================================================

export interface EquitySnapshot {
  time: string;
  value: number;
}

export interface DashboardWSPayload {
  type: 'dashboard_update';
  timestamp: string;
  portfolio: PortfolioSummary;
  risk: Partial<RiskSummary>;
  alerts: AlertCounts;
  equity_snapshot: EquitySnapshot;
  ws_connections: number;
}

// =========================================================================
// AI Agent Types
// =========================================================================

export interface AgentEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  title: string;
  message: string;
  severity: 'info' | 'success' | 'warning' | 'error';
  metadata: Record<string, unknown>;
}

export interface AgentStatus {
  state: 'idle' | 'running' | 'paused' | 'stopped' | 'error';
  paper_mode: boolean;
  uptime_seconds: number;
  current_cycle: number;
  symbols: string[];
  us_symbols?: string[];
  crypto_symbols?: string[];
  trade_nse_when_open?: boolean;
  trade_us_when_open?: boolean;
  trade_crypto_24x7?: boolean;
  trade_us_options?: boolean;
  active_strategies: string[];
  active_symbols?: string[];
  active_sessions?: string[];
  market_readiness?: Record<
    string,
    {
      enabled: boolean;
      session_open: boolean;
      ready: boolean;
      reason: string;
      auto_refreshed?: boolean;
    }
  >;
  execution_timeframes?: string[];
  reference_timeframes?: string[];
  telegram_status_interval_minutes?: number;
  positions_count: number;
  daily_pnl: number;
  total_signals: number;
  total_trades: number;
  market_pnl_inr?: Record<string, number>;
  market_stats?: Record<
    string,
    {
      signals: number;
      entries: number;
      closed_trades: number;
      wins: number;
      losses: number;
      win_rate_pct: number;
      realized_pnl_inr: number;
      unrealized_pnl_inr: number;
      net_pnl_inr: number;
      open_positions: number;
    }
  >;
  strategy_stats?: Record<
    string,
    {
      signals: number;
      entries: number;
      closed_trades: number;
      wins: number;
      losses: number;
      win_rate_pct: number;
      realized_pnl_inr: number;
      unrealized_pnl_inr: number;
      net_pnl_inr: number;
      open_positions: number;
    }
  >;
  strategy_controls?: Array<{
    name: string;
    enabled: boolean;
  }>;
  last_scan_time: string | null;
  emergency_stop?: boolean;
  error: string | null;
}

export interface AgentConfig {
  symbols: string[];
  us_symbols?: string[];
  crypto_symbols?: string[];
  trade_nse_when_open?: boolean;
  trade_us_when_open?: boolean;
  trade_us_options?: boolean;
  trade_crypto_24x7?: boolean;
  strategies: string[];
  scan_interval_seconds: number;
  paper_mode: boolean;
  capital: number;
  max_daily_loss_pct: number;
  timeframe: string;
  execution_timeframes?: string[];
  reference_timeframes?: string[];
  telegram_status_interval_minutes?: number;
}

export interface AgentInspectorBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface AgentInspectorSignal {
  timestamp: string;
  signal_type: string | null;
  strength: string | null;
  price: number | null;
  stop_loss: number | null;
  target: number | null;
  metadata: Record<string, unknown>;
  on_latest_bar: boolean;
  bars_ago: number | null;
}

export interface AgentStrategySettingField {
  name: string;
  type: 'boolean' | 'integer' | 'number' | 'text';
  required: boolean;
  default: string | number | boolean | null;
  value: string | number | boolean | null;
}

export interface AgentInspectorStrategy {
  name: string;
  enabled: boolean;
  timeframe: string;
  preferred_timeframes: string[];
  algorithm_summary: string;
  ready: boolean;
  bars_available: number;
  min_bars_required: number;
  params: Record<string, unknown>;
  settings_schema: AgentStrategySettingField[];
  indicator_snapshot: Record<string, unknown>;
  latest_signal: AgentInspectorSignal | null;
  error: string | null;
}

export interface AgentInspectorReferenceBias {
  timeframes: Record<string, Record<string, unknown>>;
  bullish_votes: number;
  bearish_votes: number;
  dominant_trend: string;
}

export interface AgentInspectorDataSource {
  fallback_used: boolean;
  source: string;
  requested_timeframe: string;
  resolved_timeframe: string;
  reason: string | null;
  last_session_date: string | null;
}

export interface AgentOptionContractSnapshot {
  symbol: string;
  strike: number;
  expiry: string;
  ltp: number;
  bid: number;
  ask: number;
  oi: number;
  oi_change: number;
  volume: number;
  iv: number | null;
  moneyness: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
}

export interface AgentOptionsAnalytics {
  market: string;
  underlying_symbol: string;
  fetched_at: string | null;
  nearest_expiry: string | null;
  days_to_expiry: number | null;
  spot: number | null;
  lot_size: number;
  pcr: number;
  total_call_oi: number;
  total_put_oi: number;
  call_oi_change: number;
  put_oi_change: number;
  avg_call_iv: number | null;
  avg_put_iv: number | null;
  max_call_oi_strike: number | null;
  max_put_oi_strike: number | null;
  atm_strike: number | null;
  atm_call: AgentOptionContractSnapshot | null;
  atm_put: AgentOptionContractSnapshot | null;
  bullish_call: AgentOptionContractSnapshot | null;
  bearish_put: AgentOptionContractSnapshot | null;
  suggested_side: string;
  selected_contract: AgentOptionContractSnapshot | null;
  chain_quality: Record<string, unknown>;
}

export interface AgentInspectorResponse {
  symbol: string;
  market: string;
  timeframe: string;
  resolved_timeframe: string;
  lookback_bars: number;
  requested_at: string;
  timeframe_active: boolean;
  execution_timeframes: string[];
  reference_timeframes: string[];
  data_source: AgentInspectorDataSource;
  data_window: {
    start: string | null;
    end: string | null;
    bars: number;
  };
  freshness: Record<string, unknown>;
  latest_bar: AgentInspectorBar | null;
  recent_bars: AgentInspectorBar[];
  common_indicators: Record<string, unknown>;
  reference_bias: AgentInspectorReferenceBias;
  options_analytics: AgentOptionsAnalytics | null;
  strategies: AgentInspectorStrategy[];
}

export interface StrategyParamsUpdateResponse {
  success: boolean;
  strategy: string;
  algorithm_summary: string;
  params: Record<string, unknown>;
  settings_schema: AgentStrategySettingField[];
}

export interface AgentWSPayload {
  type: 'agent_event' | 'heartbeat';
  event_id?: string;
  event_type?: string;
  timestamp: string;
  title?: string;
  message?: string;
  severity?: string;
  metadata?: Record<string, unknown>;
}

export interface FractalProfileLevel {
  price: number;
  tpo_count: number;
  periods: string[];
  volume: number;
  single_print: boolean;
}

export interface FractalProfileWindow {
  start: string;
  end: string;
  open: number;
  close: number;
  high: number;
  low: number;
  poc: number;
  vah: number;
  val: number;
  ib_high: number;
  ib_low: number;
  ib_range: number;
  ib_broken_above: boolean;
  ib_broken_below: boolean;
  shape: string;
  single_prints: number[][];
  va_width_pct: number;
  poc_position: number;
  tpo_count_above_poc: number;
  tpo_count_below_poc: number;
  period_count: number;
  tick_size: number;
  levels: FractalProfileLevel[];
}

export interface HourlyFractalProfile extends FractalProfileWindow {
  va_migration_vs_prev: string;
  poc_change_vs_prev: number;
  consecutive_direction_hours: number;
  va_overlap_ratio: number;
}

export interface FractalOptionFlowSummary {
  snapshot_time: string | null;
  nearest_expiry: string | null;
  dominant_side: string;
  call_oi_change: number;
  put_oi_change: number;
  avg_call_iv: number;
  avg_put_iv: number;
  supportive: boolean;
  suggested_contract: string | null;
  suggested_delta: number | null;
}

export interface FractalTradeCandidate {
  symbol: string;
  direction: 'bullish' | 'bearish';
  hourly_shape: string;
  consecutive_migration_hours: number;
  setup_type: 'acceptance_trend' | 'gap_and_go' | 'breakout_drive' | 'balance' | 'exhaustion_watch';
  value_acceptance: 'accepted' | 'fast' | 'balanced' | 'mixed';
  daily_alignment: boolean;
  approaching_single_prints: boolean;
  oi_direction_confirmed: boolean;
  iv_behavior: 'supportive' | 'neutral' | 'adverse';
  aggressive_flow_detected: boolean;
  entry_trigger: number;
  stop_reference: number;
  target_reference: number | null;
  suggested_contract: string | null;
  suggested_delta: number | null;
  conviction: number;
  position_size_multiplier: number;
  adaptive_risk_reward: number;
  exhaustion_warning: boolean;
  rationale: string;
  orderflow_summary: Record<string, unknown>;
  option_flow: FractalOptionFlowSummary | null;
}

export interface FractalAssessment {
  bias: 'bullish' | 'bearish' | 'neutral';
  current_hour_shape: string;
  current_migration: string;
  consecutive_direction_hours: number;
  prior_directional_streak: number;
  daily_shape: string;
  setup_type: 'acceptance_trend' | 'gap_and_go' | 'breakout_drive' | 'balance' | 'exhaustion_watch';
  value_acceptance: 'accepted' | 'fast' | 'balanced' | 'mixed';
  no_trade_reasons: string[];
  exhaustion_warning: boolean;
}

export interface FractalProfileContextResponse {
  symbol: string;
  market: string;
  session_date: string;
  daily_profile: FractalProfileWindow | null;
  prev_day_profile: FractalProfileWindow | null;
  hourly_profiles: HourlyFractalProfile[];
  assessment?: FractalAssessment | null;
  candidate: FractalTradeCandidate | null;
  source_timeframe?: string | null;
  prev_source_timeframe?: string | null;
  error?: string;
}

export interface FractalScanResponse {
  date: string;
  total_symbols: number;
  stages: Record<string, number>;
  candidates: FractalTradeCandidate[];
  generated_at: string;
  published?: boolean;
  channel?: string | null;
}

export interface FractalWatchlistResponse {
  date: string;
  symbols: string[];
  contexts: FractalProfileContextResponse[];
  scan: FractalScanResponse;
  generated_at: string;
}

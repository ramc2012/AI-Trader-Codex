"""Core AI Trading Agent — autonomous strategy execution loop.

Monitors market data, runs registered strategies, validates signals
through the risk manager, and executes orders. Emits real-time events
at every decision point for the live UI and Telegram.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
import json
import math
from numbers import Real
import os
from pathlib import Path
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pandas as pd

from src.agent.events import AgentEvent, AgentEventBus, AgentEventType
from src.config.agent_universe import (
    DEFAULT_AGENT_CRYPTO_SYMBOLS,
    DEFAULT_AGENT_NSE_SYMBOLS,
    DEFAULT_AGENT_US_SYMBOLS,
)
from src.config.constants import INDEX_INSTRUMENTS
from src.config.market_hours import (
    IST,
    MARKET_CLOSE,
    US_EASTERN,
    US_MARKET_CLOSE,
    is_market_open,
    is_us_market_open,
)
from src.config.fno_constants import get_instrument as get_fno_instrument, get_lot_size
from src.config.settings import get_settings
from src.execution.order_manager import (
    BrokerOrderUpdateResult,
    Order,
    OrderManager,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)
from src.execution.position_manager import PositionManager, PositionSide
from src.execution.strategy_executor import StrategyExecutor
from src.integrations.fyers_client import FyersClient
from src.risk.position_sizer import PositionSizer
from src.risk.risk_manager import RiskManager
from src.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType
from src.strategies.directional.bollinger_strategy import BollingerBandStrategy
from src.strategies.directional.ema_crossover import EMACrossoverStrategy
from src.strategies.directional.fractal_profile_strategy import FractalProfileBreakoutStrategy
from src.strategies.directional.macd_strategy import MACDStrategy
from src.strategies.directional.mp_orderflow_strategy import MarketProfileOrderFlowStrategy
from src.strategies.directional.ml_ensemble import MLEnsembleStrategy
from src.strategies.directional.rsi_reversal import RSIReversalStrategy
from src.ml.online.learning_engine import OnlineLearningEngine
from src.ml.online.strategy_performance_tracker import StrategyPerformanceTracker
from src.monitoring.latency import ExecutionLatencyTracker
from src.strategies.directional.supertrend_strategy import SupertrendStrategy
from src.utils.logger import get_logger
from src.utils.market_symbols import parse_currency_context
from src.utils.us_market_data import parse_nasdaq_chart_timestamp, parse_nasdaq_historical_date
from src.watchlist.options_analytics import BlackScholes
from src.watchlist.options_data_service import OptionsDataService

logger = get_logger(__name__)
_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://finance.yahoo.com/",
}
_NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NiftyAITrader/1.0)",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nasdaq.com/",
}
_US_ETF_TICKERS = {"SPY", "QQQ", "IWM", "DIA"}

# Strategy name → class mapping
STRATEGY_REGISTRY: Dict[str, type[BaseStrategy]] = {
    "EMA_Crossover": EMACrossoverStrategy,
    "RSI_Reversal": RSIReversalStrategy,
    "MACD_RSI": MACDStrategy,
    "MP_OrderFlow_Breakout": MarketProfileOrderFlowStrategy,
    "Fractal_Profile_Breakout": FractalProfileBreakoutStrategy,
    "Bollinger_MeanReversion": BollingerBandStrategy,
    "Supertrend_Breakout": SupertrendStrategy,
    "ML_Ensemble": MLEnsembleStrategy,
}


class AgentState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class AgentConfig:
    """Configuration for the trading agent."""

    symbols: List[str] = field(default_factory=lambda: list(DEFAULT_AGENT_NSE_SYMBOLS))
    us_symbols: List[str] = field(default_factory=lambda: list(DEFAULT_AGENT_US_SYMBOLS))
    crypto_symbols: List[str] = field(default_factory=lambda: list(DEFAULT_AGENT_CRYPTO_SYMBOLS))
    trade_nse_when_open: bool = True
    trade_us_when_open: bool = True
    trade_us_options: bool = True
    trade_crypto_24x7: bool = True
    strategies: List[str] = field(
        default_factory=lambda: [
            "EMA_Crossover",
            "RSI_Reversal",
            "Supertrend_Breakout",
            "MP_OrderFlow_Breakout",
            "Fractal_Profile_Breakout",
        ]
    )
    scan_interval_seconds: int = 30
    paper_mode: bool = True
    capital: float = 41_750_000.0
    india_capital: float = 250_000.0
    us_capital: float = 250_000.0
    crypto_capital: float = 250_000.0
    india_max_instrument_pct: float = 25.0
    us_max_instrument_pct: float = 20.0
    crypto_max_instrument_pct: float = 20.0
    max_daily_loss_pct: float = 2.0
    timeframe: str = "5"
    execution_timeframes: List[str] = field(default_factory=lambda: ["3", "5", "15"])
    reference_timeframes: List[str] = field(default_factory=lambda: ["60", "D"])
    event_driven_execution_enabled: bool = False
    event_driven_markets: List[str] = field(default_factory=lambda: ["NSE"])
    event_driven_debounce_ms: int = 1000
    event_driven_batch_size: int = 8
    liberal_bootstrap_enabled: bool = True
    bootstrap_cycles: int = 300
    bootstrap_size_multiplier: float = 2.0
    bootstrap_max_concentration_pct: float = 100.0
    bootstrap_max_open_positions: int = 20
    bootstrap_risk_per_trade_pct: float = 2.0
    option_time_exit_minutes: int = 30
    option_default_stop_loss_pct: float = 10.0
    option_default_target_pct: float = 18.0
    reinforcement_enabled: bool = True
    reinforcement_alpha: float = 0.2
    reinforcement_size_boost_pct: float = 60.0
    strategy_capital_bucket_enabled: bool = True
    strategy_max_concurrent_positions: int = 4
    telegram_status_interval_minutes: int = 30


@dataclass(frozen=True)
class OptionContract:
    """Resolved tradable option contract for one underlying."""

    underlying_symbol: str
    option_symbol: str
    option_type: str
    strike: float
    expiry: str
    ltp: float
    lot_size: int


@dataclass
class OptionExitPlan:
    """Exit controls for an open option position."""

    symbol: str
    underlying_symbol: str
    strategy: str
    quantity: int
    execution_timeframe: str
    entry_price: float
    stop_loss: float
    target: float
    opened_at: datetime
    time_exit_at: datetime
    signal_id: str = ""


@dataclass
class PendingLiveEntryOrder:
    """Locally tracked live entry order awaiting broker fills."""

    order_id: str
    symbol: str
    underlying_symbol: str
    short_name: str
    execution_short_name: str
    quantity: int
    side: OrderSide
    strategy: str
    market: str
    execution_timeframe: str
    entry_price_hint: float
    stop_loss: float
    target: float
    signal_id: str
    option_contract: Optional[OptionContract] = None
    trade_counted: bool = False


@dataclass
class PendingLiveExitOrder:
    """Locally tracked live exit order awaiting broker fills."""

    order_id: str
    symbol: str
    short_name: str
    quantity: int
    reason: str
    avg_price: float
    entry_value: float
    exit_price_hint: float
    plan: Optional[OptionExitPlan] = None


class TradingAgent:
    """Autonomous trading agent that runs strategies and executes trades.

    The agent loop runs as an asyncio background task. It scans market data,
    runs strategies, validates signals, and places orders — all while emitting
    events for the live feed and Telegram.
    """

    def __init__(
        self,
        config: AgentConfig,
        strategy_executor: StrategyExecutor,
        order_manager: OrderManager,
        position_manager: PositionManager,
        risk_manager: RiskManager,
        event_bus: AgentEventBus,
        fyers_client: FyersClient,
        candle_broker: Any | None = None,
        order_event_broker: Any | None = None,
    ) -> None:
        self.config = config
        self.executor = strategy_executor
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.risk_manager = risk_manager
        self.event_bus = event_bus
        self.fyers_client = fyers_client
        self._candle_broker = candle_broker
        self._order_event_broker = order_event_broker
        runtime_settings = get_settings()
        self._runtime_state_path: Path | None = (
            None
            if os.environ.get("PYTEST_CURRENT_TEST")
            else runtime_settings.data_path / "trading_agent_live_runtime.json"
        )
        self.position_sizer = PositionSizer(capital=config.capital)
        self.options_service = OptionsDataService(fyers_client)
        self._spot_to_index_name = {item.spot_symbol: name for name, item in INDEX_INSTRUMENTS.items()}
        self._option_contract_cache: Dict[Tuple[str, str], Tuple[datetime, OptionContract]] = {}
        self._option_contract_cache_ttl = timedelta(seconds=20)
        self._market_data_cache: Dict[Tuple[str, str], Tuple[datetime, pd.DataFrame]] = {}
        self._market_data_cache_ttl = timedelta(seconds=12)
        self._us_intraday_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
        self._us_intraday_cache_ttl = timedelta(seconds=45)
        self._us_daily_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
        self._us_daily_cache_ttl = timedelta(minutes=5)
        self._option_exit_plans: Dict[str, Dict[str, OptionExitPlan]] = {}
        self._strategy_reward_ema: Dict[str, float] = {}
        self._strategy_market_reward_ema: Dict[str, Dict[str, float]] = {}
        self._strategy_reward_counts: Dict[str, int] = {}
        self._strategy_perf_tracker = StrategyPerformanceTracker(
            alpha=config.reinforcement_alpha, data_dir=Path(".")
        )
        self._online_learning_engine: Optional[OnlineLearningEngine] = None
        self._strategy_signal_counts: Dict[str, int] = {}
        self._strategy_trade_counts: Dict[str, int] = {}
        self._market_signal_counts: Dict[str, int] = {}
        self._market_trade_counts: Dict[str, int] = {}
        self._strategy_param_overrides: Dict[str, Dict[str, Any]] = {}
        self._latency_tracker = ExecutionLatencyTracker(
            enabled=runtime_settings.agent_latency_metrics_enabled,
            max_samples=runtime_settings.agent_latency_metrics_window,
        )
        self._event_driven_task: Optional[asyncio.Task[None]] = None
        self._order_event_task: Optional[asyncio.Task[None]] = None
        self._symbol_scan_locks: Dict[str, asyncio.Lock] = {}
        self._pending_live_entries: Dict[str, PendingLiveEntryOrder] = {}
        self._pending_live_exits: Dict[str, PendingLiveExitOrder] = {}

        self.state = AgentState.IDLE
        self._task: Optional[asyncio.Task[None]] = None
        self._started_at: Optional[datetime] = None
        self._cycle_count = 0
        self._total_signals = 0
        self._total_trades = 0
        self._daily_pnl = 0.0
        self._last_scan_time: Optional[datetime] = None
        self._error: Optional[str] = None
        self._eod_summary_sent = False
        self._last_periodic_summary_at: Optional[datetime] = None
        self._active_symbols: List[str] = []
        self._active_sessions: List[str] = []
        self._market_readiness: Dict[str, Dict[str, Any]] = {}
        self._readiness_notified: Dict[str, bool] = {}
        self._warmed_symbols: set[str] = set()
        self._stale_data_keys: set[Tuple[str, str]] = set()
        self._circuit_breaker_notified = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the agent loop as a background task."""
        if self.state == AgentState.RUNNING:
            return

        self.state = AgentState.RUNNING
        self._started_at = datetime.now(tz=IST)
        self._cycle_count = 0
        self._total_signals = 0
        self._total_trades = 0
        self._daily_pnl = 0.0
        self._error = None
        self._eod_summary_sent = False
        self._last_periodic_summary_at = datetime.now(tz=IST)
        self._active_symbols = []
        self._active_sessions = []
        self._market_readiness = {}
        self._readiness_notified = {}
        self._warmed_symbols.clear()
        self._market_data_cache.clear()
        self._us_intraday_cache.clear()
        self._us_daily_cache.clear()
        self._stale_data_keys.clear()
        self._circuit_breaker_notified = False
        self._strategy_signal_counts.clear()
        self._strategy_trade_counts.clear()
        self._market_signal_counts.clear()
        self._market_trade_counts.clear()
        self._pending_live_entries.clear()
        self._pending_live_exits.clear()

        self.order_manager.paper_mode = self.config.paper_mode
        self.executor.paper_mode = self.config.paper_mode
        self.order_manager.set_client(self.fyers_client)
        self._load_live_runtime_state()

        # Register strategies
        self._register_strategies()

        # Start executor
        self.executor.start()

        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.AGENT_STARTED,
            title="AI Agent Started",
            message=(
                f"Mode: {'Paper' if self.config.paper_mode else 'LIVE'} | "
                f"NSE: {', '.join(s.split(':')[-1] for s in self.config.symbols) or 'off'} | "
                f"US: {', '.join(s.split(':')[-1] for s in self.config.us_symbols) or 'off'} | "
                f"Crypto: {', '.join(s.split(':')[-1] for s in self.config.crypto_symbols) or 'off'} | "
                f"Strategies: {', '.join(self.config.strategies)} | "
                f"Exec TFs: {', '.join(self.get_execution_timeframes())} | "
                f"Ref TFs: {', '.join(self.get_reference_timeframes())} | "
                f"Scan: every {self.config.scan_interval_seconds}s"
            ),
            severity="success",
            metadata={
                "paper_mode": self.config.paper_mode,
                "symbols": self.config.symbols,
                "us_symbols": self.config.us_symbols,
                "crypto_symbols": self.config.crypto_symbols,
                "trade_us_options": self.config.trade_us_options,
                "strategies": self.config.strategies,
                "capital": self.config.capital,
                "execution_timeframes": self.get_execution_timeframes(),
                "reference_timeframes": self.get_reference_timeframes(),
            },
        ))

        try:
            await self._init_online_learning()
            if not self.config.paper_mode:
                await self._recover_live_broker_state()
            self._task = asyncio.create_task(self._main_loop())
            if self._candle_broker is not None and self.config.event_driven_execution_enabled:
                self._event_driven_task = asyncio.create_task(self._event_driven_loop())
            if self._order_event_broker is not None and not self.config.paper_mode:
                self._order_event_task = asyncio.create_task(self._order_event_loop())
            logger.info("trading_agent_started", config=self.config.__dict__)
        except Exception as exc:
            self.state = AgentState.ERROR
            self._error = str(exc)
            self.executor.stop()
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.AGENT_ERROR,
                title="Agent Startup Failed",
                message=f"Failed to initialize trading agent: {exc}",
                severity="error",
                metadata={"error": str(exc)},
            ))
            logger.exception("trading_agent_start_failed", error=str(exc))
            raise

    async def stop(self) -> None:
        """Gracefully stop the agent."""
        if self.state in (AgentState.STOPPED, AgentState.IDLE):
            return

        self.state = AgentState.STOPPED
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._event_driven_task and not self._event_driven_task.done():
            self._event_driven_task.cancel()
            try:
                await self._event_driven_task
            except asyncio.CancelledError:
                pass
        self._event_driven_task = None
        if self._order_event_task and not self._order_event_task.done():
            self._order_event_task.cancel()
            try:
                await self._order_event_task
            except asyncio.CancelledError:
                pass
        self._order_event_task = None

        self.executor.stop()
        self._strategy_perf_tracker._persist_state()
        self._persist_live_runtime_state()

        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.AGENT_STOPPED,
            title="AI Agent Stopped",
            message=f"Ran for {self._uptime_str()}. Cycles: {self._cycle_count}. Trades: {self._total_trades}.",
            severity="info",
            metadata={"cycles": self._cycle_count, "trades": self._total_trades, "pnl": self._daily_pnl},
        ))
        logger.info("trading_agent_stopped")

    def _scan_lock(self, symbol: str) -> asyncio.Lock:
        lock = self._symbol_scan_locks.get(symbol)
        if lock is None:
            lock = asyncio.Lock()
            self._symbol_scan_locks[symbol] = lock
        return lock

    def _event_driven_market_enabled(self, market: str) -> bool:
        if not self.config.event_driven_execution_enabled:
            return False
        configured = {str(token or "").strip().upper() for token in self.config.event_driven_markets}
        return str(market or "").strip().upper() in configured

    def _is_event_driven_symbol_eligible(self, symbol: str) -> bool:
        token = str(symbol or "").strip()
        if not token or self.state != AgentState.RUNNING:
            return False
        market = self._symbol_market(token)
        if not self._event_driven_market_enabled(market):
            return False
        if market != "NSE":
            return False
        if token not in self.config.symbols:
            return False
        if token not in self._warmed_symbols:
            return False
        return is_market_open(datetime.now(tz=IST))

    async def _event_driven_loop(self) -> None:
        if self._candle_broker is None:
            return

        queue = self._candle_broker.subscribe("*")
        pending: set[str] = set()
        debounce_seconds = max(float(self.config.event_driven_debounce_ms) / 1000.0, 0.1)
        batch_size = max(int(self.config.event_driven_batch_size), 1)
        last_flush = time.monotonic()

        try:
            while self.state == AgentState.RUNNING:
                if self.state != AgentState.RUNNING:
                    await asyncio.sleep(0.1)
                    continue

                timeout = 5.0
                if pending:
                    timeout = max(debounce_seconds - (time.monotonic() - last_flush), 0.05)

                payload: Optional[Dict[str, Any]] = None
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    payload = None

                if payload is not None:
                    symbol = str(payload.get("symbol", "")).strip()
                    if self._is_event_driven_symbol_eligible(symbol):
                        pending.add(symbol)

                should_flush = bool(pending) and (
                    payload is None
                    or len(pending) >= batch_size
                    or (time.monotonic() - last_flush) >= debounce_seconds
                )
                if not should_flush:
                    continue

                symbols = sorted(pending)[:batch_size]
                pending.difference_update(symbols)
                last_flush = time.monotonic()
                for symbol in symbols:
                    started = time.perf_counter()
                    await self._scan_symbol(symbol, live_only=True)
                    self._latency_tracker.record(
                        "event_driven_symbol_scan_ms",
                        (time.perf_counter() - started) * 1000.0,
                        symbol=symbol,
                    )
        except asyncio.CancelledError:
            raise
        finally:
            self._candle_broker.unsubscribe("*", queue)

    def _symbol_has_pending_live_order(self, symbol: str) -> bool:
        token = str(symbol or "").strip()
        if not token:
            return False
        return any(context.symbol == token for context in self._pending_live_entries.values()) or any(
            context.symbol == token for context in self._pending_live_exits.values()
        )

    @staticmethod
    def _resolved_fill_quantity(value: Any, fallback: int) -> int:
        if isinstance(value, Real) and not isinstance(value, bool):
            quantity = int(value)
        elif isinstance(value, str):
            try:
                quantity = int(float(value))
            except ValueError:
                quantity = 0
        else:
            quantity = 0
        return quantity if quantity > 0 else int(fallback)

    @staticmethod
    def _safe_int(value: Any, fallback: int = 0) -> int:
        try:
            if value in (None, ""):
                return int(fallback)
            return int(float(value))
        except (TypeError, ValueError):
            return int(fallback)

    @staticmethod
    def _safe_float(value: Any, fallback: float | None = None) -> float | None:
        try:
            if value in (None, ""):
                return fallback
            return float(value)
        except (TypeError, ValueError):
            return fallback

    async def _order_event_loop(self) -> None:
        if self._order_event_broker is None:
            return

        queue = self._order_event_broker.subscribe("*")
        try:
            while self.state == AgentState.RUNNING:
                payload = await queue.get()
                await self._handle_broker_execution_event(payload)
        except asyncio.CancelledError:
            raise
        finally:
            self._order_event_broker.unsubscribe("*", queue)

    async def _handle_broker_execution_event(self, payload: Dict[str, Any]) -> None:
        event_kind = str(payload.get("event_kind") or "").strip().lower()
        raw_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload

        if event_kind == "trade":
            result = self.order_manager.apply_broker_trade_update(raw_payload)
        elif event_kind == "order":
            result = self.order_manager.apply_broker_order_update(raw_payload)
        else:
            return

        await self._apply_broker_reconciliation(
            event_kind=event_kind,
            result=result,
        )

    async def _apply_broker_reconciliation(
        self,
        *,
        event_kind: str,
        result: BrokerOrderUpdateResult,
    ) -> None:
        order = result.order
        if order is None or not result.updated:
            return

        order_id = str(order.order_id or "").strip()
        if not order_id:
            return

        if result.fill_delta_quantity > 0 and result.fill_delta_price is not None and result.fill_delta_price > 0:
            entry_context = self._pending_live_entries.get(order_id)
            if entry_context is not None:
                await self._finalize_live_entry_fill(
                    context=entry_context,
                    order=order,
                    fill_quantity=result.fill_delta_quantity,
                    fill_price=float(result.fill_delta_price),
                )
            exit_context = self._pending_live_exits.get(order_id)
            if exit_context is not None:
                await self._finalize_live_exit_fill(
                    context=exit_context,
                    order=order,
                    fill_quantity=result.fill_delta_quantity,
                    fill_price=float(result.fill_delta_price),
                )

        if order.status in (OrderStatus.REJECTED, OrderStatus.CANCELLED, OrderStatus.FAILED):
            entry_context = self._pending_live_entries.pop(order_id, None)
            if entry_context is not None:
                reason = order.rejection_reason or result.message or order.status.value
                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.ORDER_REJECTED,
                    title=f"Order {order.status.value.title()} — {entry_context.short_name}",
                    message=f"Live entry order {order.status.value}. Reason: {reason}.",
                    severity="error" if order.status != OrderStatus.CANCELLED else "warning",
                    metadata={
                        "symbol": entry_context.symbol,
                        "underlying_symbol": entry_context.underlying_symbol,
                        "status": order.status.value,
                        "reason": reason,
                        "order_id": order_id,
                        "strategy": entry_context.strategy,
                    },
                ))

            exit_context = self._pending_live_exits.pop(order_id, None)
            if exit_context is not None:
                reason = order.rejection_reason or result.message or order.status.value
                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.ORDER_REJECTED,
                    title=f"Exit {order.status.value.title()} — {exit_context.short_name}",
                    message=f"Live exit order {order.status.value}. Reason: {reason}.",
                    severity="error" if order.status != OrderStatus.CANCELLED else "warning",
                    metadata={
                        "symbol": exit_context.symbol,
                        "underlying_symbol": (exit_context.plan.underlying_symbol if exit_context.plan else exit_context.symbol),
                        "status": order.status.value,
                        "reason": reason,
                        "order_id": order_id,
                        "strategy": (exit_context.plan.strategy if exit_context.plan else ""),
                    },
                ))
            self._persist_live_runtime_state()
            return

        if order.status == OrderStatus.FILLED:
            self._pending_live_entries.pop(order_id, None)
            self._pending_live_exits.pop(order_id, None)
            self._persist_live_runtime_state()

    async def _finalize_live_entry_fill(
        self,
        *,
        context: PendingLiveEntryOrder,
        order: Order,
        fill_quantity: int,
        fill_price: float,
    ) -> None:
        fill_quantity = max(int(fill_quantity), 0)
        fill_price = float(fill_price or 0.0)
        if fill_quantity <= 0 or fill_price <= 0:
            return

        if not context.trade_counted:
            self._total_trades += 1
            self._strategy_trade_counts[context.strategy] = self._strategy_trade_counts.get(context.strategy, 0) + 1
            self._market_trade_counts[context.market] = self._market_trade_counts.get(context.market, 0) + 1
            context.trade_counted = True

        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.ORDER_FILLED,
            title=(
                f"Order {'Filled' if order.status == OrderStatus.FILLED else 'Partially Filled'} "
                f"— {context.short_name}"
            ),
            message=(
                f"{context.side.name} {fill_quantity} x {context.execution_short_name} @ {fill_price:,.2f}. "
                f"Order: {order.order_id}."
            ),
            severity="success",
            metadata={
                "symbol": context.symbol,
                "underlying_symbol": context.underlying_symbol,
                "side": context.side.name,
                "quantity": fill_quantity,
                "fill_price": fill_price,
                "order_id": order.order_id,
                "strategy": context.strategy,
                "status": order.status.value,
            },
        ))

        realized_before = self.position_manager.total_realized_pnl
        self.position_manager.open_position(
            symbol=context.symbol,
            quantity=fill_quantity,
            side=PositionSide.LONG if context.side == OrderSide.BUY else PositionSide.SHORT,
            price=fill_price,
            strategy_tag=context.strategy,
            order_id=order.order_id or "",
        )
        realized_after = self.position_manager.total_realized_pnl
        realized_delta = realized_after - realized_before
        if abs(realized_delta) > 1e-9:
            self.risk_manager.record_trade_result(realized_delta)

        position = self.position_manager.get_position(context.symbol)
        if position is None:
            self.risk_manager.sync_position_value(context.symbol, 0.0)
        else:
            self.risk_manager.sync_position_value(
                symbol=context.symbol,
                position_value=position.quantity * max(position.current_price or fill_price, fill_price),
            )

        if context.option_contract is not None:
            self._upsert_option_exit_plan(
                symbol=context.symbol,
                underlying_symbol=context.underlying_symbol,
                strategy=context.strategy,
                quantity=fill_quantity,
                execution_timeframe=context.execution_timeframe,
                entry_price=fill_price,
                stop_loss=context.stop_loss,
                target=context.target,
                signal_id=context.signal_id,
            )

        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.POSITION_OPENED,
            title=f"Position Opened — {context.short_name}",
            message=(
                f"{context.side.name} {fill_quantity} x {context.execution_short_name} @ {fill_price:,.2f}. "
                f"SL: {context.stop_loss:,.2f}. Target: {context.target:,.2f}."
            ),
            severity="success",
            metadata={
                "symbol": context.symbol,
                "underlying_symbol": context.underlying_symbol,
                "side": context.side.name,
                "quantity": fill_quantity,
                "entry_price": fill_price,
                "stop_loss": context.stop_loss,
                "target": context.target,
                "order_id": order.order_id,
                "strategy": context.strategy,
                "status": order.status.value,
            },
        ))

    async def _finalize_live_exit_fill(
        self,
        *,
        context: PendingLiveExitOrder,
        order: Order,
        fill_quantity: int,
        fill_price: float,
    ) -> None:
        fill_quantity = max(int(fill_quantity), 0)
        fill_price = float(fill_price or 0.0)
        if fill_quantity <= 0 or fill_price <= 0:
            return

        strategy_tag = context.plan.strategy if context.plan is not None else None
        try:
            realized = self.position_manager.close_position(
                context.symbol,
                fill_price,
                quantity=fill_quantity,
                strategy_tag=strategy_tag,
            )
        except ValueError as exc:
            logger.warning(
                "live_exit_position_mismatch",
                symbol=context.symbol,
                quantity=fill_quantity,
                strategy=strategy_tag,
                error=str(exc),
            )
            self._pending_live_exits.pop(context.order_id, None)
            self._persist_live_runtime_state()
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.AGENT_ERROR,
                title=f"Exit State Mismatch — {context.short_name}",
                message=str(exc),
                severity="warning",
                metadata={
                    "symbol": context.symbol,
                    "strategy": strategy_tag,
                    "reason": context.reason,
                    "quantity": fill_quantity,
                },
            ))
            return

        self.risk_manager.record_trade_result(realized)
        remaining_pos = self.position_manager.get_position(context.symbol)
        if remaining_pos is None:
            self.risk_manager.sync_position_value(context.symbol, 0.0)
        else:
            self.risk_manager.sync_position_value(
                context.symbol,
                remaining_pos.quantity * max(remaining_pos.current_price or fill_price, fill_price),
            )

        remaining_strategy_qty = self._remaining_strategy_position_quantity(
            context.symbol,
            strategy_tag,
        )
        plan_fully_closed = strategy_tag is None or remaining_strategy_qty <= 0
        if strategy_tag is not None:
            self._update_exit_plan_remaining_quantity(
                context.symbol,
                strategy_tag,
                remaining_quantity=remaining_strategy_qty,
            )

        pnl_pct = (realized / max(context.avg_price * fill_quantity, 1e-6)) * 100.0
        if context.plan is not None and plan_fully_closed:
            reinforcement_market = self._symbol_market(
                context.plan.underlying_symbol if context.plan.underlying_symbol else context.symbol
            )
            self._record_reinforcement(context.plan.strategy, pnl_pct, market=reinforcement_market)
            engine = self._online_learning_engine
            if engine is not None and context.plan.signal_id:
                asyncio.ensure_future(
                    engine.label_outcome(
                        signal_id=context.plan.signal_id,
                        pnl_pct=pnl_pct,
                        exit_timestamp=datetime.now(tz=IST),
                    )
                )

        if order.status == OrderStatus.FILLED or plan_fully_closed:
            self._pending_live_exits.pop(context.order_id, None)
            self._persist_live_runtime_state()

        event_type = AgentEventType.POSITION_CLOSED if plan_fully_closed else AgentEventType.POSITION_UPDATE
        title = "Position Closed" if plan_fully_closed else "Position Reduced"
        await self.event_bus.emit(AgentEvent(
            event_type=event_type,
            title=f"{title} — {context.short_name}",
            message=(
                f"Exit: {context.reason}. Qty: {fill_quantity}. "
                f"Entry: {context.avg_price:,.2f} | Exit: {fill_price:,.2f} | "
                f"PnL: {realized:+,.2f} ({pnl_pct:+.2f}%)."
            ),
            severity="success" if realized >= 0 else "warning",
            metadata={
                "symbol": context.symbol,
                "underlying_symbol": (context.plan.underlying_symbol if context.plan is not None else context.symbol),
                "reason": context.reason,
                "quantity": fill_quantity,
                "entry_price": context.avg_price,
                "exit_price": fill_price,
                "pnl": realized,
                "pnl_pct": pnl_pct,
                "strategy": (context.plan.strategy if context.plan else ""),
                "status": order.status.value,
            },
        ))

    async def _recover_live_broker_state(self) -> None:
        if self.config.paper_mode or not self.fyers_client.is_authenticated:
            return
        try:
            orders_raw, trades_raw, positions_raw = await asyncio.gather(
                asyncio.to_thread(self.fyers_client.get_orders),
                asyncio.to_thread(self.fyers_client.get_tradebook),
                asyncio.to_thread(self.fyers_client.get_positions),
            )
        except Exception as exc:
            logger.warning("live_state_recovery_failed", error=str(exc))
            return

        broker_orders = []
        if isinstance(orders_raw, dict):
            broker_orders = orders_raw.get("orderBook") or orders_raw.get("orders") or []

        open_order_ids: set[str] = set()
        for raw in broker_orders:
            if not isinstance(raw, dict):
                continue
            try:
                order = self.order_manager.upsert_broker_order_snapshot(raw)
            except Exception as exc:
                logger.debug("live_order_snapshot_recovery_failed", error=str(exc))
                continue
            if order.status in (OrderStatus.PLACED, OrderStatus.PARTIALLY_FILLED):
                open_order_ids.add(str(order.order_id or ""))

        broker_trades = []
        if isinstance(trades_raw, dict):
            broker_trades = trades_raw.get("tradeBook") or trades_raw.get("trades") or []
        broker_trades.sort(key=lambda row: str(row.get("orderDateTime") or row.get("tradeDate") or ""))
        for raw in broker_trades:
            if not isinstance(raw, dict):
                continue
            order_id = str(raw.get("orderNumber") or raw.get("id") or "").strip()
            if not order_id:
                continue
            if self.order_manager.get_order(order_id) is None:
                try:
                    self.order_manager.upsert_broker_order_snapshot(
                        {
                            "id": order_id,
                            "symbol": raw.get("symbol"),
                            "qty": raw.get("tradedQty") or raw.get("qty"),
                            "filledQty": raw.get("tradedQty") or raw.get("qty"),
                            "tradedPrice": raw.get("tradePrice") or raw.get("tradedPrice"),
                            "status": "COMPLETE",
                            "side": raw.get("side"),
                            "type": raw.get("orderType") or raw.get("type"),
                            "productType": raw.get("productType"),
                            "orderTag": raw.get("orderTag"),
                            "orderDateTime": raw.get("orderDateTime") or raw.get("tradeDate"),
                        }
                    )
                except Exception as exc:
                    logger.debug("live_trade_snapshot_stub_failed", error=str(exc))
                    continue
            try:
                await self._apply_broker_reconciliation(
                    event_kind="trade",
                    result=self.order_manager.apply_broker_trade_update(raw),
                )
            except Exception as exc:
                logger.debug("live_trade_recovery_failed", order_id=order_id, error=str(exc))

        recovered_positions = self._recover_positions_from_broker_payload(positions_raw)
        if recovered_positions:
            self.position_manager.replace_positions(recovered_positions)
            for position in recovered_positions:
                self.risk_manager.sync_position_value(
                    position.symbol,
                    position.quantity * max(position.current_price or position.avg_price, position.avg_price),
                )

        for order_id in list(self._pending_live_entries.keys()):
            if order_id not in open_order_ids and self.order_manager.get_order(order_id) is None:
                self._pending_live_entries.pop(order_id, None)
        for order_id in list(self._pending_live_exits.keys()):
            if order_id not in open_order_ids and self.order_manager.get_order(order_id) is None:
                self._pending_live_exits.pop(order_id, None)

        self._persist_live_runtime_state()
        logger.info(
            "live_state_recovered",
            broker_orders=len(broker_orders),
            broker_trades=len(broker_trades),
            broker_positions=len(recovered_positions),
            pending_entries=len(self._pending_live_entries),
            pending_exits=len(self._pending_live_exits),
        )

    def _recover_positions_from_broker_payload(self, payload: Any) -> List[Any]:
        if not isinstance(payload, dict):
            return []
        rows = payload.get("netPositions") or payload.get("positions") or payload.get("overall") or []
        if not isinstance(rows, list):
            return []
        recovered = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            net_qty = self._safe_int(raw.get("netQty"), fallback=0)
            qty = self._safe_int(raw.get("qty"), fallback=abs(net_qty))
            side_raw = self._safe_int(raw.get("side"), fallback=1)
            quantity = abs(net_qty) if net_qty != 0 else abs(qty)
            if quantity <= 0:
                continue
            side = PositionSide.LONG if (net_qty > 0 or (net_qty == 0 and side_raw >= 0)) else PositionSide.SHORT
            avg_price = self._safe_float(
                raw.get("netAvg"),
                fallback=self._safe_float(raw.get("buyAvg"), fallback=self._safe_float(raw.get("sellAvg"), fallback=0.0)),
            )
            symbol = str(raw.get("symbol") or "").strip()
            if not symbol or avg_price is None or avg_price <= 0:
                continue
            strategy_tag = self._recovered_strategy_tag_for_symbol(symbol)
            order_ids = self._recovered_order_ids_for_symbol(symbol)
            recovered.append(
                PositionManager._deserialize_position(
                    {
                        "symbol": symbol,
                        "quantity": quantity,
                        "side": side.value,
                        "avg_price": avg_price,
                        "current_price": avg_price,
                        "entry_time": None,
                        "strategy_tag": strategy_tag,
                        "order_ids": order_ids,
                        "lots": [
                            {
                                "quantity": quantity,
                                "entry_price": avg_price,
                                "entry_time": None,
                                "strategy_tag": strategy_tag,
                                "order_ids": order_ids,
                            }
                        ],
                    }
                )
            )
        return recovered

    def _recovered_strategy_tag_for_symbol(self, symbol: str) -> str:
        tags = {
            context.strategy
            for context in self._pending_live_entries.values()
            if context.symbol == symbol and context.strategy
        }
        tags.update(
            plan.strategy
            for plan in self._symbol_exit_plans(symbol)
            if plan.strategy and plan.strategy != "MULTI"
        )
        if len(tags) == 1:
            return next(iter(tags))
        if len(tags) > 1:
            return "MULTI"
        for order in self.order_manager.get_orders_by_symbol(symbol):
            if order.tag and not order.tag.startswith("EXIT:"):
                return order.tag
        return ""

    def _recovered_order_ids_for_symbol(self, symbol: str) -> List[str]:
        return [
            str(order.order_id or "")
            for order in self.order_manager.get_orders_by_symbol(symbol)
            if str(order.order_id or "").strip()
        ]

    # ------------------------------------------------------------------
    # Online Learning Initialisation
    # ------------------------------------------------------------------

    async def _init_online_learning(self) -> None:
        """Initialise and load persisted state for the online learning stack."""
        settings = get_settings()
        data_dir = getattr(settings, "data_dir", "data")
        ml_ensemble_strategy = self.get_strategy_instance("ML_Ensemble")
        engine = OnlineLearningEngine(
            ml_ensemble_strategy=ml_ensemble_strategy,
            data_dir=Path(data_dir),
        )
        engine.load_state()
        self._online_learning_engine = engine
        # Re-create tracker with the resolved data_dir so state persists correctly
        self._strategy_perf_tracker = StrategyPerformanceTracker(
            alpha=self.config.reinforcement_alpha, data_dir=Path(data_dir)
        )
        self._strategy_perf_tracker.load_state()
        self._bootstrap_market_learning_state()
        self._strategy_reward_ema = self._strategy_perf_tracker.get_reward_snapshot()
        self._strategy_market_reward_ema = self._strategy_perf_tracker.get_market_reward_snapshot()
        logger.info(
            "online_learning_initialised",
            buffer_size=len(engine._buffer),
            threshold=round(engine._confidence_threshold, 4),
        )

    def _extract_signal_features(
        self,
        df: pd.DataFrame,
        symbol: str,
        signal_metadata: Optional[dict] = None,
    ) -> tuple[list[float], list[str]]:
        """Extract a flat numeric feature vector from the latest candle in df.

        Appends strategy-specific features from signal_metadata when available
        (conviction_score, flow_pressure, poc/value-area metrics for MP_OrderFlow;
        daily_alignment, aggressive_flow, consecutive_hours for Fractal_Profile).

        Returns (features, feature_names). Falls back to empty lists on error.
        """
        try:
            close = float(df["close"].iloc[-1])
            volume = float(df["volume"].iloc[-1]) if "volume" in df.columns else 0.0
            high = float(df["high"].iloc[-1]) if "high" in df.columns else close
            low = float(df["low"].iloc[-1]) if "low" in df.columns else close
            open_ = float(df["open"].iloc[-1]) if "open" in df.columns else close
            candle_range = max(high - low, 1e-9)
            body = abs(close - open_)
            vol_ma = float(df["volume"].tail(20).mean()) if "volume" in df.columns else 0.0
            vol_ratio = volume / max(vol_ma, 1.0)
            close_series = df["close"].astype(float)
            roc5 = float((close_series.iloc[-1] / close_series.iloc[-6] - 1) * 100) if len(close_series) >= 6 else 0.0
            roc20 = float((close_series.iloc[-1] / close_series.iloc[-21] - 1) * 100) if len(close_series) >= 21 else 0.0
            features: list[float] = [close, high, low, open_, volume, candle_range, body, vol_ratio, roc5, roc20]
            names: list[str] = ["close", "high", "low", "open", "volume", "candle_range", "body", "vol_ratio", "roc5", "roc20"]

            # Strategy-specific features extracted from signal metadata.
            # These make the ML model strategy-aware, improving label quality.
            meta = signal_metadata if isinstance(signal_metadata, dict) else {}
            if meta:
                # Shared across MP_OrderFlow and Fractal_Profile
                conviction_raw = float(meta.get("conviction_score", 0) or 0)
                features.append(conviction_raw / 100.0)
                names.append("conviction_score_norm")

                # MP_OrderFlow_Breakout specific
                features.append(float(meta.get("flow_pressure", 0.0) or 0.0))
                names.append("flow_pressure")
                features.append(float(meta.get("poc_distance_atr", 0.0) or 0.0))
                names.append("poc_distance_atr")
                features.append(float(meta.get("value_area_width_pct", 0.0) or 0.0))
                names.append("value_area_width_pct")
                features.append(float(meta.get("volume_ratio", 1.0) or 1.0))
                names.append("volume_ratio_meta")

                # Fractal_Profile_Breakout specific
                features.append(1.0 if meta.get("daily_alignment") else 0.0)
                names.append("daily_alignment")
                features.append(1.0 if meta.get("aggressive_flow_detected") else 0.0)
                names.append("aggressive_flow_detected")
                consec_hours = float(meta.get("consecutive_migration_hours", 0) or 0)
                features.append(min(consec_hours / 5.0, 1.0))
                names.append("consecutive_hours_norm")

            return features, names
        except Exception:
            return [], []

    async def pause(self) -> None:
        """Pause the agent (loop stays alive but skips processing)."""
        if self.state != AgentState.RUNNING:
            return
        self.state = AgentState.PAUSED
        self.executor.pause()
        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.AGENT_PAUSED,
            title="AI Agent Paused",
            message="Agent paused. No new scans or trades will be executed until resumed.",
            severity="warning",
        ))

    async def resume(self) -> None:
        """Resume from paused state."""
        if self.state != AgentState.PAUSED:
            return
        self.state = AgentState.RUNNING
        self.executor.resume()
        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.AGENT_RESUMED,
            title="AI Agent Resumed",
            message="Agent resumed. Scanning and trading active.",
            severity="success",
        ))

    def get_strategy_controls(self) -> List[Dict[str, Any]]:
        """Return toggle state for all known strategies."""
        states = self.executor.get_strategy_states()
        enabled_from_config = set(self.config.strategies)
        controls: List[Dict[str, Any]] = []
        for name in STRATEGY_REGISTRY.keys():
            state = states.get(name)
            enabled = bool(state.enabled) if state is not None else name in enabled_from_config
            controls.append({
                "name": name,
                "enabled": enabled,
            })
        return controls

    def get_capital_allocations(self) -> Dict[str, Dict[str, Any]]:
        """Return market-wise capital allocations in native and INR terms."""
        usd_inr_rate = float(get_settings().usd_inr_reference_rate)
        allocations = {
            "NSE": {
                "market": "NSE",
                "label": "India",
                "currency": "INR",
                "currency_symbol": "₹",
                "fx_to_inr": 1.0,
                "allocated_capital": float(self.config.india_capital),
                "allocated_capital_inr": float(self.config.india_capital),
                "max_instrument_pct": float(self.config.india_max_instrument_pct),
            },
            "US": {
                "market": "US",
                "label": "US",
                "currency": "USD",
                "currency_symbol": "$",
                "fx_to_inr": usd_inr_rate,
                "allocated_capital": float(self.config.us_capital),
                "allocated_capital_inr": float(self.config.us_capital) * usd_inr_rate,
                "max_instrument_pct": float(self.config.us_max_instrument_pct),
            },
            "CRYPTO": {
                "market": "CRYPTO",
                "label": "Crypto",
                "currency": "USD",
                "currency_symbol": "$",
                "fx_to_inr": usd_inr_rate,
                "allocated_capital": float(self.config.crypto_capital),
                "allocated_capital_inr": float(self.config.crypto_capital) * usd_inr_rate,
                "max_instrument_pct": float(self.config.crypto_max_instrument_pct),
            },
        }
        for row in allocations.values():
            max_instrument_pct = float(row["max_instrument_pct"])
            allocated_capital = float(row["allocated_capital"])
            allocated_capital_inr = float(row["allocated_capital_inr"])
            row["max_instrument_capital"] = round(allocated_capital * max_instrument_pct / 100.0, 2)
            row["max_instrument_capital_inr"] = round(allocated_capital_inr * max_instrument_pct / 100.0, 2)
            row["allocated_capital"] = round(allocated_capital, 2)
            row["allocated_capital_inr"] = round(allocated_capital_inr, 2)
        return allocations

    def total_allocated_capital_inr(self) -> float:
        """Return total allocated capital converted to INR."""
        return round(
            sum(float(row.get("allocated_capital_inr", 0.0)) for row in self.get_capital_allocations().values()),
            2,
        )

    def _market_allocation(self, market: str) -> Dict[str, Any]:
        key = str(market or "NSE").upper()
        return self.get_capital_allocations().get(key, self.get_capital_allocations()["NSE"])

    def set_strategy_enabled(self, name: str, enabled: bool) -> bool:
        """Enable/disable a strategy without restarting the agent."""
        if name not in STRATEGY_REGISTRY:
            return False

        if enabled:
            if name not in self.executor._strategies:
                self.executor.register_strategy(name, self.build_strategy(name), enabled=True)
            else:
                self.executor.enable_strategy(name)
            if name not in self.config.strategies:
                self.config.strategies.append(name)
        else:
            if name in self.executor._strategies:
                self.executor.disable_strategy(name)
            self.config.strategies = [item for item in self.config.strategies if item != name]

        # Keep order stable for deterministic UI rendering and timeframe planning.
        enabled_set = set(self.config.strategies)
        self.config.strategies = [item for item in STRATEGY_REGISTRY.keys() if item in enabled_set]
        return True

    def build_strategy(self, name: str) -> BaseStrategy:
        """Instantiate a strategy using any runtime parameter overrides."""
        cls = STRATEGY_REGISTRY.get(name)
        if cls is None:
            raise KeyError(name)
        return cls(**dict(self._strategy_param_overrides.get(name, {})))

    def get_strategy_instance(self, name: str) -> BaseStrategy | None:
        """Return the active instance, or a synthesized one if the agent has not started it yet."""
        strategy = self.executor._strategies.get(name)
        if strategy is not None:
            return strategy
        if name not in STRATEGY_REGISTRY:
            return None
        return self.build_strategy(name)

    def apply_strategy_params(self, name: str, params: Dict[str, Any]) -> BaseStrategy:
        """Validate and apply a full parameter set to a strategy."""
        cls = STRATEGY_REGISTRY.get(name)
        if cls is None:
            raise KeyError(name)

        instance = cls(**dict(params))
        self._strategy_param_overrides[name] = dict(params)
        if name in self.executor._strategies:
            self.executor._strategies[name] = instance
        return instance

    def get_status(self) -> Dict[str, Any]:
        """Return current agent status and metrics."""
        settings = get_settings()
        portfolio = self.position_manager.get_portfolio_summary()
        (
            market_stats,
            strategy_stats,
            strategy_market_stats,
            strategy_instrument_stats,
        ) = self._build_performance_snapshots()
        risk_summary = self.risk_manager.get_risk_summary()
        closed_trades = sum(int(stats.get("closed_trades", 0) or 0) for stats in strategy_stats.values())
        open_trade_entries = int(portfolio.get("position_count", 0) or 0)
        capital_allocations = self.get_capital_allocations()
        market_pnl = {
            market: round(float(stats.get("net_pnl_inr", 0.0)), 2)
            for market, stats in market_stats.items()
        }
        ml_ensemble_live_enabled = "ML_Ensemble" in self.config.strategies
        online_learning_stats = self._online_learning_engine.stats if self._online_learning_engine is not None else {}
        online_learning_stats = {
            **online_learning_stats,
            "strategy_reinforcement_enabled": bool(self.config.reinforcement_enabled),
            "ml_ensemble_live_enabled": ml_ensemble_live_enabled,
            "ml_ensemble_attached": bool(
                ml_ensemble_live_enabled
                and self._online_learning_engine is not None
                and getattr(self._online_learning_engine, "_ensemble", None) is not None
            ),
            "signal_outcome_capture_enabled": bool(
                self._online_learning_engine is not None
            ),
        }
        return {
            "state": self.state.value,
            "paper_mode": self.config.paper_mode,
            "uptime_seconds": (
                datetime.now(tz=IST) - self._started_at
            ).total_seconds() if self._started_at else 0,
            "current_cycle": self._cycle_count,
            "symbols": self.config.symbols,
            "us_symbols": self.config.us_symbols,
            "crypto_symbols": self.config.crypto_symbols,
            "trade_nse_when_open": self.config.trade_nse_when_open,
            "trade_us_when_open": self.config.trade_us_when_open,
            "trade_crypto_24x7": self.config.trade_crypto_24x7,
            "trade_us_options": self.config.trade_us_options,
            "active_strategies": self.config.strategies,
            "active_symbols": self._active_symbols,
            "active_sessions": self._active_sessions,
            "market_readiness": self._market_readiness,
            "execution_timeframes": self.get_execution_timeframes(),
            "reference_timeframes": self.get_reference_timeframes(),
            "event_driven_enabled": bool(self.config.event_driven_execution_enabled),
            "event_driven_markets": [market.upper() for market in self.config.event_driven_markets],
            "event_driven_debounce_ms": int(self.config.event_driven_debounce_ms),
            "event_driven_batch_size": int(self.config.event_driven_batch_size),
            "pending_live_entries": len(self._pending_live_entries),
            "pending_live_exits": len(self._pending_live_exits),
            "execution_backend": settings.execution_core_backend,
            "execution_transport": settings.execution_transport,
            "streaming_backends": {
                "nats": {
                    "enabled": bool(settings.nats_enabled),
                    "url": settings.nats_url,
                    "stream_prefix": settings.nats_stream_prefix,
                },
                "kafka": {
                    "enabled": bool(settings.kafka_enabled),
                    "bootstrap_servers": settings.kafka_bootstrap_servers,
                    "topic_prefix": settings.kafka_topic_prefix,
                },
            },
            "analytics_backends": {
                "clickhouse": {
                    "enabled": bool(settings.clickhouse_enabled),
                    "url": settings.clickhouse_http_url,
                    "database": settings.clickhouse_database,
                },
                "questdb": {
                    "enabled": bool(settings.questdb_enabled),
                    "url": settings.questdb_http_url,
                },
            },
            "execution_latency": self._latency_tracker.snapshot(),
            "telegram_status_interval_minutes": max(int(self.config.telegram_status_interval_minutes), 0),
            "capital_allocations": capital_allocations,
            "total_allocated_capital_inr": self.total_allocated_capital_inr(),
            "positions_count": portfolio.get("position_count", 0),
            # Daily risk state is persisted across agent restarts, unlike the
            # in-memory session counters. Use it for top-level daily totals.
            "daily_pnl": round(float(risk_summary.get("total_pnl", self._daily_pnl) or 0.0), 2),
            "total_signals": self._total_signals,
            "total_trades": closed_trades + open_trade_entries,
            "market_stats": market_stats,
            "market_pnl_inr": market_pnl,
            "strategy_stats": strategy_stats,
            "strategy_market_stats": strategy_market_stats,
            "strategy_instrument_stats": strategy_instrument_stats,
            "strategy_controls": self.get_strategy_controls(),
            "last_scan_time": self._last_scan_time.isoformat() if self._last_scan_time else None,
            "bootstrap_mode_active": self._is_bootstrap_phase(),
            "emergency_stop": bool(self.risk_manager.emergency_stop),
            "online_learning_active": self._online_learning_engine is not None,
            "online_learning_stats": online_learning_stats,
            "strategy_reward_ema": {k: round(v, 4) for k, v in self._strategy_reward_ema.items()},
            "strategy_reward_ema_by_market": {
                strategy: {market: round(value, 4) for market, value in market_rewards.items()}
                for strategy, market_rewards in self._strategy_market_reward_ema.items()
            },
            "error": self._error,
        }

    def _stats_bucket(
        self,
        *,
        market: Optional[str] = None,
        symbol: Optional[str] = None,
        overall: bool = False,
    ) -> Dict[str, Any]:
        allocation = self._market_allocation(market or self._symbol_market(symbol or "NSE:NIFTY50-INDEX"))
        if overall:
            total_capital_inr = self.total_allocated_capital_inr()
            return {
                "signals": 0,
                "entries": 0,
                "closed_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate_pct": 0.0,
                "currency": "INR",
                "currency_symbol": "₹",
                "fx_to_inr": 1.0,
                "allocated_capital": total_capital_inr,
                "allocated_capital_inr": total_capital_inr,
                "max_instrument_pct": 0.0,
                "max_instrument_capital": 0.0,
                "max_instrument_capital_inr": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "net_pnl": 0.0,
                "realized_pnl_inr": 0.0,
                "unrealized_pnl_inr": 0.0,
                "net_pnl_inr": 0.0,
                "open_positions": 0,
                "capital_used": 0.0,
                "capital_used_inr": 0.0,
                "capital_used_pct": 0.0,
                "pnl_pct_on_allocated": 0.0,
            }
        return {
            "signals": 0,
            "entries": 0,
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "currency": allocation["currency"],
            "currency_symbol": allocation["currency_symbol"],
            "fx_to_inr": float(allocation["fx_to_inr"]),
            "allocated_capital": float(allocation["allocated_capital"]),
            "allocated_capital_inr": float(allocation["allocated_capital_inr"]),
            "max_instrument_pct": float(allocation["max_instrument_pct"]),
            "max_instrument_capital": float(allocation["max_instrument_capital"]),
            "max_instrument_capital_inr": float(allocation["max_instrument_capital_inr"]),
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "net_pnl": 0.0,
            "realized_pnl_inr": 0.0,
            "unrealized_pnl_inr": 0.0,
            "net_pnl_inr": 0.0,
            "open_positions": 0,
            "capital_used": 0.0,
            "capital_used_inr": 0.0,
            "capital_used_pct": 0.0,
            "pnl_pct_on_allocated": 0.0,
        }

    @staticmethod
    def _normalize_strategy_tag(tag: Any) -> str:
        token = str(tag or "").strip()
        return token if token else "Unassigned"

    def _enabled_strategy_names(self) -> List[str]:
        return [
            str(control.get("name"))
            for control in self.get_strategy_controls()
            if bool(control.get("enabled"))
        ]

    def _symbol_exit_plans(self, symbol: str) -> List[OptionExitPlan]:
        strategy_map = self._option_exit_plans.get(symbol) or {}
        return list(strategy_map.values())

    def _display_exit_plan(self, symbol: str) -> Optional[OptionExitPlan]:
        plans = self._symbol_exit_plans(symbol)
        if not plans:
            return None
        if len(plans) == 1:
            return plans[0]

        total_qty = sum(max(int(plan.quantity), 0) for plan in plans)
        weighted_entry = sum(float(plan.entry_price) * max(int(plan.quantity), 0) for plan in plans)
        weighted_stop = sum(float(plan.stop_loss) * max(int(plan.quantity), 0) for plan in plans)
        weighted_target = sum(float(plan.target) * max(int(plan.quantity), 0) for plan in plans)
        anchor = plans[0]
        divisor = max(total_qty, 1)
        return OptionExitPlan(
            symbol=symbol,
            underlying_symbol=anchor.underlying_symbol,
            strategy="MULTI",
            quantity=total_qty,
            execution_timeframe=anchor.execution_timeframe,
            entry_price=weighted_entry / divisor,
            stop_loss=weighted_stop / divisor,
            target=weighted_target / divisor,
            opened_at=min(plan.opened_at for plan in plans),
            time_exit_at=min(plan.time_exit_at for plan in plans),
        )

    def _has_exit_plan_for_underlying(self, underlying_symbol: str) -> bool:
        for strategy_map in self._option_exit_plans.values():
            for plan in strategy_map.values():
                if plan.underlying_symbol == underlying_symbol:
                    return True
        return False

    def _remove_exit_plan(self, symbol: str, strategy: Optional[str] = None) -> None:
        if strategy is None:
            self._option_exit_plans.pop(symbol, None)
            self._persist_live_runtime_state()
            return
        strategy_map = self._option_exit_plans.get(symbol)
        if not strategy_map:
            return
        strategy_map.pop(strategy, None)
        if not strategy_map:
            self._option_exit_plans.pop(symbol, None)
        self._persist_live_runtime_state()

    def _remaining_strategy_position_quantity(self, symbol: str, strategy: Optional[str]) -> int:
        if strategy is None:
            position = self.position_manager.get_position(symbol)
            return int(position.quantity) if position is not None else 0
        return sum(
            int(view.quantity)
            for view in self.position_manager.get_position_views(
                symbol=symbol,
                strategy_tag=strategy,
            )
        )

    def _update_exit_plan_remaining_quantity(
        self,
        symbol: str,
        strategy: str,
        *,
        remaining_quantity: int,
    ) -> None:
        strategy_map = self._option_exit_plans.get(symbol)
        if not strategy_map:
            return
        plan = strategy_map.get(strategy)
        if plan is None:
            return
        if remaining_quantity <= 0:
            self._remove_exit_plan(symbol, strategy)
            return
        plan.quantity = int(remaining_quantity)
        self._persist_live_runtime_state()

    def _persist_live_runtime_state(self) -> None:
        if self._runtime_state_path is None:
            return
        if self.config.paper_mode:
            if self._runtime_state_path.exists():
                try:
                    self._runtime_state_path.unlink()
                except OSError:
                    pass
            return

        payload = {
            "pending_live_entries": [
                self._serialize_pending_live_entry(context)
                for context in self._pending_live_entries.values()
            ],
            "pending_live_exits": [
                self._serialize_pending_live_exit(context)
                for context in self._pending_live_exits.values()
            ],
            "option_exit_plans": {
                symbol: {
                    strategy: self._serialize_option_exit_plan(plan)
                    for strategy, plan in strategy_map.items()
                }
                for symbol, strategy_map in self._option_exit_plans.items()
            },
        }
        try:
            self._runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._runtime_state_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            tmp_path.replace(self._runtime_state_path)
        except Exception as exc:
            logger.warning("trading_agent_live_state_persist_failed", error=str(exc))

    def _load_live_runtime_state(self) -> None:
        if self._runtime_state_path is None or self.config.paper_mode or not self._runtime_state_path.exists():
            return
        try:
            payload = json.loads(self._runtime_state_path.read_text(encoding="utf-8"))
            self._pending_live_entries = {}
            for raw in payload.get("pending_live_entries", []):
                context = self._deserialize_pending_live_entry(raw)
                self._pending_live_entries[context.order_id] = context
            self._pending_live_exits = {}
            for raw in payload.get("pending_live_exits", []):
                context = self._deserialize_pending_live_exit(raw)
                self._pending_live_exits[context.order_id] = context
            self._option_exit_plans = {
                symbol: {
                    strategy: self._deserialize_option_exit_plan(plan_payload)
                    for strategy, plan_payload in strategy_map.items()
                }
                for symbol, strategy_map in (payload.get("option_exit_plans") or {}).items()
                if isinstance(strategy_map, dict)
            }
            logger.info(
                "trading_agent_live_state_loaded",
                pending_entries=len(self._pending_live_entries),
                pending_exits=len(self._pending_live_exits),
                exit_plans=len(self._option_exit_plans),
            )
        except Exception as exc:
            logger.warning("trading_agent_live_state_load_failed", error=str(exc))

    @staticmethod
    def _serialize_option_contract(contract: OptionContract) -> dict[str, Any]:
        return {
            "underlying_symbol": contract.underlying_symbol,
            "option_symbol": contract.option_symbol,
            "option_type": contract.option_type,
            "strike": float(contract.strike),
            "expiry": contract.expiry,
            "ltp": float(contract.ltp),
            "lot_size": int(contract.lot_size),
        }

    @staticmethod
    def _deserialize_option_contract(payload: dict[str, Any]) -> OptionContract:
        return OptionContract(
            underlying_symbol=str(payload.get("underlying_symbol") or ""),
            option_symbol=str(payload.get("option_symbol") or ""),
            option_type=str(payload.get("option_type") or ""),
            strike=float(payload.get("strike") or 0.0),
            expiry=str(payload.get("expiry") or ""),
            ltp=float(payload.get("ltp") or 0.0),
            lot_size=int(payload.get("lot_size") or 0),
        )

    @staticmethod
    def _serialize_option_exit_plan(plan: OptionExitPlan) -> dict[str, Any]:
        return {
            "symbol": plan.symbol,
            "underlying_symbol": plan.underlying_symbol,
            "strategy": plan.strategy,
            "quantity": int(plan.quantity),
            "execution_timeframe": plan.execution_timeframe,
            "entry_price": float(plan.entry_price),
            "stop_loss": float(plan.stop_loss),
            "target": float(plan.target),
            "opened_at": plan.opened_at.isoformat(),
            "time_exit_at": plan.time_exit_at.isoformat(),
            "signal_id": plan.signal_id,
        }

    @staticmethod
    def _deserialize_option_exit_plan(payload: dict[str, Any]) -> OptionExitPlan:
        return OptionExitPlan(
            symbol=str(payload.get("symbol") or ""),
            underlying_symbol=str(payload.get("underlying_symbol") or ""),
            strategy=str(payload.get("strategy") or ""),
            quantity=int(payload.get("quantity") or 0),
            execution_timeframe=str(payload.get("execution_timeframe") or ""),
            entry_price=float(payload.get("entry_price") or 0.0),
            stop_loss=float(payload.get("stop_loss") or 0.0),
            target=float(payload.get("target") or 0.0),
            opened_at=datetime.fromisoformat(str(payload.get("opened_at"))),
            time_exit_at=datetime.fromisoformat(str(payload.get("time_exit_at"))),
            signal_id=str(payload.get("signal_id") or ""),
        )

    def _serialize_pending_live_entry(self, context: PendingLiveEntryOrder) -> dict[str, Any]:
        return {
            "order_id": context.order_id,
            "symbol": context.symbol,
            "underlying_symbol": context.underlying_symbol,
            "short_name": context.short_name,
            "execution_short_name": context.execution_short_name,
            "quantity": int(context.quantity),
            "side": context.side.name,
            "strategy": context.strategy,
            "market": context.market,
            "execution_timeframe": context.execution_timeframe,
            "entry_price_hint": float(context.entry_price_hint),
            "stop_loss": float(context.stop_loss),
            "target": float(context.target),
            "signal_id": context.signal_id,
            "trade_counted": bool(context.trade_counted),
            "option_contract": (
                self._serialize_option_contract(context.option_contract)
                if context.option_contract is not None
                else None
            ),
        }

    def _deserialize_pending_live_entry(self, payload: dict[str, Any]) -> PendingLiveEntryOrder:
        option_contract_payload = payload.get("option_contract")
        option_contract = (
            self._deserialize_option_contract(option_contract_payload)
            if isinstance(option_contract_payload, dict)
            else None
        )
        return PendingLiveEntryOrder(
            order_id=str(payload.get("order_id") or ""),
            symbol=str(payload.get("symbol") or ""),
            underlying_symbol=str(payload.get("underlying_symbol") or ""),
            short_name=str(payload.get("short_name") or ""),
            execution_short_name=str(payload.get("execution_short_name") or ""),
            quantity=int(payload.get("quantity") or 0),
            side=OrderSide[str(payload.get("side") or "BUY")],
            strategy=str(payload.get("strategy") or ""),
            market=str(payload.get("market") or ""),
            execution_timeframe=str(payload.get("execution_timeframe") or ""),
            entry_price_hint=float(payload.get("entry_price_hint") or 0.0),
            stop_loss=float(payload.get("stop_loss") or 0.0),
            target=float(payload.get("target") or 0.0),
            signal_id=str(payload.get("signal_id") or ""),
            option_contract=option_contract,
            trade_counted=bool(payload.get("trade_counted")),
        )

    def _serialize_pending_live_exit(self, context: PendingLiveExitOrder) -> dict[str, Any]:
        return {
            "order_id": context.order_id,
            "symbol": context.symbol,
            "short_name": context.short_name,
            "quantity": int(context.quantity),
            "reason": context.reason,
            "avg_price": float(context.avg_price),
            "entry_value": float(context.entry_value),
            "exit_price_hint": float(context.exit_price_hint),
            "plan": (
                self._serialize_option_exit_plan(context.plan)
                if context.plan is not None
                else None
            ),
        }

    def _deserialize_pending_live_exit(self, payload: dict[str, Any]) -> PendingLiveExitOrder:
        plan_payload = payload.get("plan")
        return PendingLiveExitOrder(
            order_id=str(payload.get("order_id") or ""),
            symbol=str(payload.get("symbol") or ""),
            short_name=str(payload.get("short_name") or ""),
            quantity=int(payload.get("quantity") or 0),
            reason=str(payload.get("reason") or ""),
            avg_price=float(payload.get("avg_price") or 0.0),
            entry_value=float(payload.get("entry_value") or 0.0),
            exit_price_hint=float(payload.get("exit_price_hint") or 0.0),
            plan=(
                self._deserialize_option_exit_plan(plan_payload)
                if isinstance(plan_payload, dict)
                else None
            ),
        )

    @staticmethod
    def _to_ist(value: Optional[datetime]) -> datetime:
        if value is None:
            return datetime.min.replace(tzinfo=IST)
        if value.tzinfo is None:
            return value.replace(tzinfo=IST)
        return value.astimezone(IST)

    def _build_closed_trade_pairs(self, usd_inr_rate: float) -> List[Dict[str, Any]]:
        """FIFO-match fills into closed entry/exit pairs for P&L attribution."""
        orders = sorted(
            self.order_manager.get_all_orders(),
            key=lambda order: (
                self._to_ist(order.filled_at or order.placed_at),
                order.order_id or "",
            ),
        )
        open_lots: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        closed_pairs: List[Dict[str, Any]] = []

        for order in orders:
            fill_qty = int(order.fill_quantity or 0)
            fill_price = float(order.fill_price or order.limit_price or order.market_price_hint or 0.0)
            if fill_qty <= 0 or fill_price <= 0:
                continue

            side = order.side.name
            symbol = order.symbol
            remaining = fill_qty
            symbol_lots = open_lots[symbol]

            while remaining > 0 and symbol_lots and symbol_lots[0]["side"] != side:
                entry_lot = symbol_lots[0]
                matched = min(remaining, int(entry_lot["quantity"]))
                remaining -= matched
                entry_lot["quantity"] -= matched

                entry_price = float(entry_lot["price"])
                if str(entry_lot["side"]) == "BUY":
                    pnl_native = (fill_price - entry_price) * matched
                else:
                    pnl_native = (entry_price - fill_price) * matched

                _, _, fx_to_inr = parse_currency_context(symbol, usd_inr_rate=usd_inr_rate)
                closed_pairs.append(
                    {
                        "symbol": symbol,
                        "strategy": self._normalize_strategy_tag(entry_lot.get("tag") or order.tag),
                        "market": self._symbol_market(symbol),
                        "pnl_inr": float(pnl_native) * float(fx_to_inr),
                    }
                )

                if entry_lot["quantity"] <= 0:
                    symbol_lots.pop(0)

            if remaining > 0:
                symbol_lots.append(
                    {
                        "side": side,
                        "quantity": remaining,
                        "price": fill_price,
                        "tag": order.tag,
                    }
                )

        return closed_pairs

    @staticmethod
    def _bucket_native_value(bucket: Dict[str, Any], amount_inr: float) -> float:
        fx_to_inr = max(float(bucket.get("fx_to_inr", 1.0) or 1.0), 1e-6)
        return float(amount_inr) / fx_to_inr

    def _build_performance_snapshots(
        self,
    ) -> Tuple[
        Dict[str, Dict[str, Any]],
        Dict[str, Dict[str, Any]],
        Dict[str, Dict[str, Dict[str, Any]]],
        Dict[str, Dict[str, Dict[str, Any]]],
    ]:
        """Build market-wise and strategy-wise P&L/trade snapshots."""
        settings = get_settings()
        usd_inr_rate = float(settings.usd_inr_reference_rate)

        market_stats: Dict[str, Dict[str, Any]] = {}
        strategy_stats: Dict[str, Dict[str, Any]] = {}
        strategy_market_stats: Dict[str, Dict[str, Dict[str, Any]]] = {}
        strategy_instrument_stats: Dict[str, Dict[str, Dict[str, Any]]] = {}

        def market_bucket(market: str) -> Dict[str, Any]:
            key = str(market or "NSE").upper()
            if key not in market_stats:
                market_stats[key] = self._stats_bucket(market=key)
            return market_stats[key]

        def strategy_bucket(strategy: str) -> Dict[str, Any]:
            key = self._normalize_strategy_tag(strategy)
            if key not in strategy_stats:
                strategy_stats[key] = self._stats_bucket(overall=True)
            return strategy_stats[key]

        def strategy_market_bucket(strategy: str, market: str) -> Dict[str, Any]:
            key = self._normalize_strategy_tag(strategy)
            if key not in strategy_market_stats:
                strategy_market_stats[key] = {}
            market_key = str(market or "NSE").upper()
            if market_key not in strategy_market_stats[key]:
                strategy_market_stats[key][market_key] = self._stats_bucket(market=market_key)
            return strategy_market_stats[key][market_key]

        def strategy_instrument_bucket(strategy: str, symbol: str) -> Dict[str, Any]:
            key = self._normalize_strategy_tag(strategy)
            if key not in strategy_instrument_stats:
                strategy_instrument_stats[key] = {}
            symbol_key = str(symbol or "").strip()
            if symbol_key not in strategy_instrument_stats[key]:
                strategy_instrument_stats[key][symbol_key] = self._stats_bucket(symbol=symbol_key)
            return strategy_instrument_stats[key][symbol_key]

        for market in ("NSE", "US", "CRYPTO"):
            market_bucket(market)
        for strategy in self.config.strategies:
            strategy_bucket(strategy)
            for market in ("NSE", "US", "CRYPTO"):
                strategy_market_bucket(strategy, market)

        for market, count in self._market_signal_counts.items():
            market_bucket(market)["signals"] = int(count)
        for market, count in self._market_trade_counts.items():
            market_bucket(market)["entries"] = int(count)
        for strategy, count in self._strategy_signal_counts.items():
            strategy_bucket(strategy)["signals"] = int(count)
        for strategy, count in self._strategy_trade_counts.items():
            strategy_bucket(strategy)["entries"] = int(count)

        for trade in self.position_manager.get_closed_trades():
            symbol = str(trade.get("symbol") or "")
            market = self._symbol_market(symbol)
            strategy = self._normalize_strategy_tag(trade.get("strategy_tag"))
            _, _, fx_to_inr = parse_currency_context(symbol, usd_inr_rate=usd_inr_rate)
            pnl_inr = float(trade.get("pnl") or 0.0) * float(fx_to_inr)
            buckets = (
                market_bucket(market),
                strategy_bucket(strategy),
                strategy_market_bucket(strategy, market),
                strategy_instrument_bucket(strategy, symbol),
            )
            for bucket in buckets:
                bucket["closed_trades"] += 1
                bucket["entries"] = max(int(bucket["entries"]), int(bucket["closed_trades"]))
                bucket["realized_pnl"] += self._bucket_native_value(bucket, pnl_inr)
                bucket["realized_pnl_inr"] += pnl_inr
                if pnl_inr > 0:
                    bucket["wins"] += 1
                elif pnl_inr < 0:
                    bucket["losses"] += 1

        for position in self.position_manager.get_position_views():
            market = self._symbol_market(position.symbol)
            strategy = self._normalize_strategy_tag(position.strategy_tag)
            _, _, fx_to_inr = parse_currency_context(position.symbol, usd_inr_rate=usd_inr_rate)
            market_value_inr = float(position.market_value) * float(fx_to_inr)
            unrealized_pnl_inr = float(position.unrealized_pnl) * float(fx_to_inr)
            buckets = (
                market_bucket(market),
                strategy_bucket(strategy),
                strategy_market_bucket(strategy, market),
                strategy_instrument_bucket(strategy, position.symbol),
            )
            for bucket in buckets:
                bucket["open_positions"] += 1
                bucket["entries"] = max(int(bucket["entries"]), int(bucket["closed_trades"]) + int(bucket["open_positions"]))
                bucket["capital_used"] += self._bucket_native_value(bucket, market_value_inr)
                bucket["capital_used_inr"] += market_value_inr
                bucket["unrealized_pnl"] += self._bucket_native_value(bucket, unrealized_pnl_inr)
                bucket["unrealized_pnl_inr"] += unrealized_pnl_inr

        all_buckets = (
            list(market_stats.values())
            + list(strategy_stats.values())
            + [bucket for row in strategy_market_stats.values() for bucket in row.values()]
            + [bucket for row in strategy_instrument_stats.values() for bucket in row.values()]
        )

        for bucket in all_buckets:
            closed = int(bucket["closed_trades"])
            wins = int(bucket["wins"])
            bucket["win_rate_pct"] = round((wins / closed) * 100.0, 2) if closed > 0 else 0.0
            bucket["realized_pnl"] = round(float(bucket["realized_pnl"]), 2)
            bucket["unrealized_pnl"] = round(float(bucket["unrealized_pnl"]), 2)
            bucket["realized_pnl_inr"] = round(float(bucket["realized_pnl_inr"]), 2)
            bucket["unrealized_pnl_inr"] = round(float(bucket["unrealized_pnl_inr"]), 2)
            bucket["net_pnl"] = round(
                float(bucket["realized_pnl"]) + float(bucket["unrealized_pnl"]),
                2,
            )
            bucket["net_pnl_inr"] = round(
                float(bucket["realized_pnl_inr"]) + float(bucket["unrealized_pnl_inr"]),
                2,
            )
            bucket["capital_used"] = round(float(bucket["capital_used"]), 2)
            bucket["capital_used_inr"] = round(float(bucket["capital_used_inr"]), 2)
            allocated_capital_inr = float(bucket.get("allocated_capital_inr", 0.0) or 0.0)
            bucket["capital_used_pct"] = round(
                (float(bucket["capital_used_inr"]) / allocated_capital_inr) * 100.0,
                2,
            ) if allocated_capital_inr > 0 else 0.0
            bucket["pnl_pct_on_allocated"] = round(
                (float(bucket["net_pnl_inr"]) / allocated_capital_inr) * 100.0,
                2,
            ) if allocated_capital_inr > 0 else 0.0

        ordered_market_stats: Dict[str, Dict[str, Any]] = {}
        for market in ("NSE", "US", "CRYPTO"):
            if market in market_stats:
                ordered_market_stats[market] = market_stats[market]
        for market in sorted(market_stats.keys()):
            if market not in ordered_market_stats:
                ordered_market_stats[market] = market_stats[market]

        ordered_strategy_stats = {key: strategy_stats[key] for key in sorted(strategy_stats.keys())}
        ordered_strategy_market_stats = {
            key: {
                market: strategy_market_stats[key][market]
                for market in ("NSE", "US", "CRYPTO")
                if market in strategy_market_stats[key]
            }
            for key in sorted(strategy_market_stats.keys())
        }
        ordered_strategy_instrument_stats = {
            key: {
                symbol: strategy_instrument_stats[key][symbol]
                for symbol in sorted(strategy_instrument_stats[key].keys())
            }
            for key in sorted(strategy_instrument_stats.keys())
        }
        return (
            ordered_market_stats,
            ordered_strategy_stats,
            ordered_strategy_market_stats,
            ordered_strategy_instrument_stats,
        )

    # ------------------------------------------------------------------
    # Main Loop
    # ------------------------------------------------------------------

    async def _main_loop(self) -> None:
        """Core agent loop — scans, analyzes, trades, sleeps, repeat."""
        try:
            while self.state in (AgentState.RUNNING, AgentState.PAUSED):
                if self.state == AgentState.PAUSED:
                    await asyncio.sleep(2)
                    continue

                sessions = self._session_snapshot()
                readiness = await self._compute_market_readiness(sessions)
                self._market_readiness = readiness
                await self._emit_readiness_events(readiness)

                active_symbols = self._resolve_active_symbols(
                    sessions=sessions,
                    readiness=readiness,
                )
                self._active_symbols = active_symbols
                self._active_sessions = []
                if (
                    sessions.get("nse", False)
                    and self.config.trade_nse_when_open
                    and readiness.get("NSE", {}).get("ready", False)
                ):
                    self._active_sessions.append("NSE")
                if (
                    sessions.get("us", False)
                    and self.config.trade_us_when_open
                    and readiness.get("US", {}).get("ready", False)
                ):
                    self._active_sessions.append("US")
                if (
                    sessions.get("crypto", False)
                    and self.config.trade_crypto_24x7
                    and readiness.get("CRYPTO", {}).get("ready", False)
                ):
                    self._active_sessions.append("CRYPTO")

                # Send EOD summary once after NSE close.
                if sessions.get("nse", False):
                    self._eod_summary_sent = False
                elif not self._eod_summary_sent and self._cycle_count > 0:
                    await self._generate_daily_summary()
                    self._eod_summary_sent = True

                if not active_symbols:
                    await self.event_bus.emit(AgentEvent(
                        event_type=AgentEventType.MARKET_CLOSED,
                        title="No Active Session",
                        message=(
                            "No enabled market session is currently tradable. "
                            f"NSE: {'open' if sessions['nse'] else 'closed'} | "
                            f"US: {'open' if sessions['us'] else 'closed'} | "
                            f"Crypto: {'open' if sessions['crypto'] else 'closed'}."
                        ),
                        severity="info",
                        metadata={
                            "sessions": sessions,
                            "readiness": readiness,
                            "trade_nse_when_open": self.config.trade_nse_when_open,
                            "trade_us_when_open": self.config.trade_us_when_open,
                            "trade_crypto_24x7": self.config.trade_crypto_24x7,
                        },
                    ))
                    await asyncio.sleep(60)
                    continue

                self._cycle_count += 1
                self._last_scan_time = datetime.now(tz=IST)
                cycle_started = time.perf_counter()

                # Ensure historical data exists for newly active NSE symbols.
                symbols_to_warm = [symbol for symbol in active_symbols if symbol not in self._warmed_symbols]
                if symbols_to_warm:
                    await self._ensure_data_available(symbols_to_warm)
                    self._warmed_symbols.update(symbols_to_warm)

                periodic_scan_symbols = self._periodic_scan_symbols(active_symbols)

                # Scan each symbol
                for symbol in periodic_scan_symbols:
                    await self._scan_symbol(symbol)

                # Check existing positions for exit conditions
                await self._check_exit_conditions()

                # Update daily P&L
                portfolio = self.position_manager.get_portfolio_summary()
                self.risk_manager.update_pnl(
                    float(portfolio.get("total_unrealized_pnl", 0.0)),
                    is_realized=False,
                )
                self._daily_pnl = portfolio.get("total_pnl", 0.0)

                if self.risk_manager.check_circuit_breaker():
                    self._latency_tracker.record(
                        "agent_cycle_ms",
                        (time.perf_counter() - cycle_started) * 1000.0,
                        cycle=self._cycle_count,
                        active_symbols=len(active_symbols),
                        sessions=",".join(self._active_sessions),
                        circuit_breaker=True,
                    )
                    if not self._circuit_breaker_notified:
                        await self.event_bus.emit(AgentEvent(
                            event_type=AgentEventType.CIRCUIT_BREAKER,
                            title="Circuit Breaker Triggered",
                            message=(
                                "Daily loss limit breached. New trades are blocked for this "
                                "session. Agent remains active for monitoring."
                            ),
                            severity="error",
                        ))
                        self._circuit_breaker_notified = True
                    await asyncio.sleep(self.config.scan_interval_seconds)
                    continue
                self._circuit_breaker_notified = False

                # Emit thinking summary
                short_name = lambda s: s.split(":")[-1].split("-")[0]
                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.THINKING,
                    title=f"Cycle {self._cycle_count} Complete",
                    message=(
                        f"Periodic scanned {len(periodic_scan_symbols)} of {len(active_symbols)} active symbols "
                        f"({', '.join(short_name(s) for s in periodic_scan_symbols) or 'event-driven only'}). "
                        f"Open positions: {portfolio.get('position_count', 0)}. "
                        f"Daily P&L: {self._daily_pnl:+,.0f}. "
                        f"Next scan in {self.config.scan_interval_seconds}s."
                    ),
                    severity="info",
                    metadata={
                        "cycle": self._cycle_count,
                        "pnl": self._daily_pnl,
                        "active_symbols": active_symbols,
                        "periodic_scan_symbols": periodic_scan_symbols,
                        "sessions": sessions,
                    },
                ))

                await self._maybe_emit_periodic_summary()
                self._latency_tracker.record(
                    "agent_cycle_ms",
                    (time.perf_counter() - cycle_started) * 1000.0,
                    cycle=self._cycle_count,
                    active_symbols=len(active_symbols),
                    periodic_scans=len(periodic_scan_symbols),
                    sessions=",".join(self._active_sessions),
                    circuit_breaker=False,
                )
                await asyncio.sleep(self.config.scan_interval_seconds)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.state = AgentState.ERROR
            self._error = str(e)
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.AGENT_ERROR,
                title="Agent Error",
                message=f"Unexpected error: {e}",
                severity="error",
                metadata={"error": str(e)},
            ))
            logger.exception("trading_agent_error", error=str(e))

    # ------------------------------------------------------------------
    # Symbol Scan
    # ------------------------------------------------------------------

    def _event_driven_hot_path_timeframe_supported(self, timeframe: str) -> bool:
        token = str(timeframe or "").strip().upper()
        return token in {"1", "3", "5", "15", "60", "D"}

    def _should_use_event_driven_lane(self, symbol: str) -> bool:
        return self._candle_broker is not None and self._is_event_driven_symbol_eligible(symbol)

    def _periodic_scan_symbols(self, active_symbols: List[str]) -> List[str]:
        return [symbol for symbol in active_symbols if not self._should_use_event_driven_lane(symbol)]

    async def _scan_symbol(self, symbol: str, *, live_only: bool = False) -> None:
        async with self._scan_lock(symbol):
            await self._scan_symbol_unlocked(symbol, live_only=live_only)

    async def _scan_symbol_unlocked(self, symbol: str, *, live_only: bool = False) -> None:
        """Run all strategies on a single symbol across execution timeframes."""
        scan_started = time.perf_counter()
        short_name = symbol.split(":")[-1].split("-")[0]
        execution_timeframes = await self._rank_execution_timeframes(
            symbol,
            self.get_execution_timeframes(),
            live_only=live_only,
        )
        trades_before_symbol = self._total_trades
        symbol_market = self._symbol_market(symbol)
        timeframe_frames: Dict[str, pd.DataFrame] = {}
        candidate_signals: List[Dict[str, Any]] = []

        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.MARKET_SCAN,
            title=f"Scanning {short_name}",
            message=(
                f"Fetching candles for {symbol} across "
                f"{', '.join(execution_timeframes)}..."
            ),
            severity="info",
            metadata={"symbol": symbol, "timeframes": execution_timeframes},
        ))

        had_data = False
        for timeframe in execution_timeframes:
            # Fetch market data for execution timeframe
            df = await self._fetch_market_data(symbol, timeframe=timeframe, live_only=live_only)
            if df is None or df.empty:
                continue

            stale_key = (symbol, timeframe)
            fresh, freshness_meta = self._data_freshness(df, timeframe)
            if not fresh:
                if stale_key not in self._stale_data_keys:
                    await self.event_bus.emit(AgentEvent(
                        event_type=AgentEventType.MARKET_DATA_RECEIVED,
                        title=f"Stale Data — {short_name}",
                        message=(
                            f"Latest {timeframe}m candle is stale for {short_name}. "
                            "Skipping this timeframe until fresh data arrives."
                        ),
                        severity="warning",
                        metadata={"symbol": symbol, **freshness_meta},
                    ))
                    self._stale_data_keys.add(stale_key)
                continue
            self._stale_data_keys.discard(stale_key)

            had_data = True
            timeframe_frames[timeframe] = df
            regime_meta = self._market_regime_profile(df, symbol_market)
            ltp = float(df["close"].iloc[-1])
            tf_label = f"{timeframe}m" if timeframe.isdigit() else timeframe
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.MARKET_DATA_RECEIVED,
                title=f"{short_name} LTP ({tf_label}): {ltp:,.2f}",
                message=f"Loaded {len(df)} candles ({tf_label}). Last close: {ltp:,.2f}.",
                severity="info",
                metadata={"symbol": symbol, "ltp": ltp, "candles": len(df), "timeframe": timeframe},
            ))

            # Run strategies and namespace the symbol key with timeframe so
            # dedupe state doesn't suppress valid signals across resolutions.
            results = self.executor.process_data(df, f"{symbol}|{timeframe}")

            for strat_name in self.config.strategies:
                if strat_name not in self.executor._strategies:
                    continue
                if not self._strategy_perf_tracker.is_enabled(strat_name):
                    logger.debug("strategy_skipped_auto_disabled", strategy=strat_name, symbol=symbol)
                    continue

                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.STRATEGY_ANALYZING,
                    title=f"Running {strat_name} ({tf_label})",
                    message=f"Analyzing {short_name} on {tf_label} with {strat_name}...",
                    severity="info",
                    metadata={"symbol": symbol, "strategy": strat_name, "timeframe": timeframe},
                ))

                strategy_signals = [r for r in results if r.get("strategy") == strat_name]
                actionable = [
                    r for r in strategy_signals
                    if isinstance(r.get("signal"), Signal) and r["signal"].is_actionable
                ]

                if not actionable:
                    await self.event_bus.emit(AgentEvent(
                        event_type=AgentEventType.NO_SIGNAL,
                        title=f"{strat_name}: No Signal",
                        message=f"{strat_name} found no actionable signal for {short_name} on {tf_label}. HOLD.",
                        severity="info",
                        metadata={"symbol": symbol, "strategy": strat_name, "timeframe": timeframe},
                    ))
                    continue

                # Process each actionable signal after higher-timeframe confirmation.
                for result in actionable:
                    signal: Signal = result["signal"]
                    sig_meta = signal.metadata if isinstance(signal.metadata, dict) else {}
                    # Fractal_Profile_Breakout encodes daily profile context internally
                    # via daily_alignment + hourly TPO conviction.  When the strategy
                    # itself has already validated the higher timeframe (daily_alignment=True)
                    # AND conviction is high, skip the external EMA-based HTF check to
                    # avoid a double-filter that suppresses valid profile-breakout setups.
                    _fractal_htf_bypass = (
                        strat_name == "Fractal_Profile_Breakout"
                        and sig_meta.get("daily_alignment") is True
                        and float(sig_meta.get("conviction_score", 0) or 0) >= 72
                    )
                    if _fractal_htf_bypass:
                        confirmed = True
                        reference_meta = {
                            "bypassed": "fractal_daily_alignment",
                            "conviction_score": sig_meta.get("conviction_score"),
                            "bullish_votes": 0,
                            "bearish_votes": 0,
                            "dominant_trend": "neutral",
                            "confidence_pct": 0.0,
                        }
                    else:
                        confirmed, reference_meta = await self._confirm_reference_timeframes(
                            symbol=symbol,
                            signal_type=signal.signal_type,
                            live_only=live_only,
                        )
                    if not confirmed:
                        await self.event_bus.emit(AgentEvent(
                            event_type=AgentEventType.NO_SIGNAL,
                            title=f"{strat_name}: HTF Filter Rejected",
                            message=(
                                f"{signal.signal_type.value} on {tf_label} rejected by higher-timeframe "
                                "spot confirmation."
                            ),
                            severity="warning",
                            metadata={
                                "symbol": symbol,
                                "strategy": strat_name,
                                "timeframe": timeframe,
                                "reference": reference_meta,
                            },
                        ))
                        continue

                    if not isinstance(signal.metadata, dict):
                        signal.metadata = {}
                    signal.metadata.update({
                        "execution_timeframe": timeframe,
                        "reference_timeframe_bias": reference_meta,
                        "market_regime": regime_meta,
                    })

                    priority_score = self._signal_priority_score(
                        strat_name,
                        signal,
                        timeframe,
                        regime_meta,
                    )
                    priority_threshold = self._trade_priority_threshold(
                        symbol_market,
                        timeframe,
                        regime_meta,
                    )
                    signal.metadata["trade_priority_score"] = round(priority_score, 2)
                    signal.metadata["trade_priority_threshold"] = round(priority_threshold, 2)

                    if priority_score < priority_threshold:
                        await self.event_bus.emit(AgentEvent(
                            event_type=AgentEventType.NO_SIGNAL,
                            title=f"{strat_name}: Priority Filtered",
                            message=(
                                f"{strat_name} setup on {tf_label} was skipped. "
                                f"Priority {priority_score:.1f} < threshold {priority_threshold:.1f} "
                                f"for {regime_meta.get('regime', 'transition')} regime."
                            ),
                            severity="info",
                            metadata={
                                "symbol": symbol,
                                "strategy": strat_name,
                                "timeframe": timeframe,
                                "priority_score": round(priority_score, 2),
                                "priority_threshold": round(priority_threshold, 2),
                                "regime": regime_meta,
                            },
                        ))
                        continue

                    candidate_signals.append(
                        {
                            "signal": signal,
                            "strategy": strat_name,
                            "timeframe": timeframe,
                            "priority_score": priority_score,
                            "regime": regime_meta,
                            "df": df,
                        }
                    )

        if candidate_signals:
            candidate_signals.sort(
                key=lambda item: (
                    float(item["priority_score"]),
                    self._timeframe_sort_key(str(item["timeframe"])),
                ),
                reverse=True,
            )
            max_candidates = self._max_candidates_per_symbol(
                symbol_market,
                candidate_signals[0]["regime"],
            )
            for index, candidate in enumerate(candidate_signals):
                if index >= max_candidates:
                    await self.event_bus.emit(AgentEvent(
                        event_type=AgentEventType.NO_SIGNAL,
                        title=f"{candidate['strategy']}: Deferred",
                        message=(
                            f"Higher-priority setup already selected for {short_name}. "
                            "This candidate was deferred."
                        ),
                        severity="info",
                        metadata={
                            "symbol": symbol,
                            "strategy": candidate["strategy"],
                            "timeframe": candidate["timeframe"],
                            "priority_score": round(float(candidate["priority_score"]), 2),
                        },
                    ))
                    continue

                before_trade_count = self._total_trades
                self._total_signals += 1
                strat_name = str(candidate["strategy"])
                self._strategy_signal_counts[strat_name] = self._strategy_signal_counts.get(strat_name, 0) + 1
                self._market_signal_counts[symbol_market] = self._market_signal_counts.get(symbol_market, 0) + 1
                await self._process_signal(
                    candidate["signal"],
                    strat_name,
                    short_name,
                    default_symbol=symbol,
                    execution_timeframe=str(candidate["timeframe"]),
                    df_for_signal=candidate.get("df"),
                )
                if self._total_trades > before_trade_count:
                    break

        if had_data and self._is_bootstrap_phase() and self._total_trades == trades_before_symbol and not candidate_signals:
            await self._attempt_bootstrap_exploration(
                symbol=symbol,
                short_name=short_name,
                timeframe_frames=timeframe_frames,
                execution_timeframes=execution_timeframes,
                live_only=live_only,
            )

        if not had_data:
            no_data_message = f"Could not fetch candle data for {symbol}. Skipping."
            if symbol_market == "US":
                no_data_message += (
                    " Yahoo may be rate-limited; configure FINNHUB_API_KEY and/or "
                    "ALPHAVANTAGE_API_KEY for reliable US feed failover."
                )
            elif symbol_market == "CRYPTO":
                no_data_message += (
                    " Configure FINNHUB_API_KEY and/or ALPHAVANTAGE_API_KEY for"
                    " primary crypto feeds; Binance remains only the fallback."
                )
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.MARKET_DATA_RECEIVED,
                title=f"No Data — {short_name}",
                message=no_data_message,
                severity="warning",
                metadata={"symbol": symbol, "timeframes": execution_timeframes},
            ))
        self._latency_tracker.record(
            "symbol_scan_ms",
            (time.perf_counter() - scan_started) * 1000.0,
            symbol=symbol,
            market=symbol_market,
            had_data=had_data,
            traded=self._total_trades > trades_before_symbol,
        )

    async def _confirm_reference_timeframes(
        self,
        symbol: str,
        signal_type: SignalType,
        *,
        live_only: bool = False,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Confirm short-term signals using higher-timeframe spot trend bias."""
        with self._latency_tracker.track(
            "reference_confirm_ms",
            symbol=symbol,
            signal_type=signal_type.value,
        ):
            reference_timeframes = self.get_reference_timeframes()
            bullish_votes = 0
            bearish_votes = 0
            references: Dict[str, Any] = {}

            for timeframe in reference_timeframes:
                df = await self._fetch_market_data(symbol, timeframe=timeframe, live_only=live_only)
                if df is None or df.empty:
                    references[timeframe] = {"trend": "missing"}
                    continue
                fresh, freshness_meta = self._data_freshness(df, timeframe)
                if not fresh:
                    references[timeframe] = {
                        "trend": "stale",
                        **freshness_meta,
                    }
                    continue

                trend, close, ema = self._infer_trend(df)
                references[timeframe] = {
                    "trend": trend,
                    "close": round(close, 2),
                    "ema20": round(ema, 2),
                }

                if trend == "bullish":
                    bullish_votes += 1
                elif trend == "bearish":
                    bearish_votes += 1

            # If reference data is missing entirely, avoid blind execution.
            total_votes = bullish_votes + bearish_votes
            dominant_trend = "neutral"
            if bullish_votes > bearish_votes:
                dominant_trend = "bullish"
            elif bearish_votes > bullish_votes:
                dominant_trend = "bearish"
            confidence_pct = (max(bullish_votes, bearish_votes) / total_votes * 100.0) if total_votes > 0 else 0.0

            if bullish_votes == 0 and bearish_votes == 0:
                return False, {
                    "timeframes": references,
                    "bullish_votes": bullish_votes,
                    "bearish_votes": bearish_votes,
                    "dominant_trend": dominant_trend,
                    "confidence_pct": round(confidence_pct, 2),
                    "reason": "no_reference_bias",
                }

            if signal_type == SignalType.BUY:
                confirmed = bullish_votes > bearish_votes
                if not confirmed and self._is_bootstrap_phase():
                    confirmed = bullish_votes > 0 and bullish_votes >= bearish_votes
            else:
                confirmed = bearish_votes > bullish_votes
                if not confirmed and self._is_bootstrap_phase():
                    confirmed = bearish_votes > 0 and bearish_votes >= bullish_votes

            return confirmed, {
                "timeframes": references,
                "bullish_votes": bullish_votes,
                "bearish_votes": bearish_votes,
                "dominant_trend": dominant_trend,
                "confidence_pct": round(confidence_pct, 2),
                "signal": signal_type.value,
            }

    async def _attempt_bootstrap_exploration(
        self,
        symbol: str,
        short_name: str,
        timeframe_frames: Dict[str, pd.DataFrame],
        execution_timeframes: List[str],
        *,
        live_only: bool = False,
    ) -> None:
        """Enter one exploratory bootstrap trade when no normal trade fired."""
        # Keep one active option position per underlying in bootstrap.
        if self._has_exit_plan_for_underlying(symbol):
            return

        selected_tf = ""
        selected_df: Optional[pd.DataFrame] = None
        for timeframe in execution_timeframes:
            frame = timeframe_frames.get(timeframe)
            if frame is not None and not frame.empty:
                selected_tf = timeframe
                selected_df = frame
                break

        if selected_df is None or not selected_tf:
            return

        exploratory_signal = self._build_bootstrap_signal(selected_df, symbol)
        if exploratory_signal is None:
            return

        confirmed, reference_meta = await self._confirm_reference_timeframes(
            symbol=symbol,
            signal_type=exploratory_signal.signal_type,
            live_only=live_only,
        )
        if not confirmed:
            # If higher-timeframe data is missing, allow exploratory trade
            # during bootstrap using execution-timeframe momentum only.
            if reference_meta.get("reason") != "no_reference_bias":
                return
            reference_meta["bootstrap_override"] = True
            reference_meta["reason"] = "bootstrap_execution_tf_only"

        if not isinstance(exploratory_signal.metadata, dict):
            exploratory_signal.metadata = {}
        exploratory_signal.metadata.update({
            "execution_timeframe": selected_tf,
            "reference_timeframe_bias": reference_meta,
            "bootstrap_exploration": True,
        })

        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.THINKING,
            title=f"Bootstrap Exploration — {short_name}",
            message=(
                f"No fresh crossover/reversal signal on this cycle. "
                f"Taking exploratory setup on {selected_tf}m to accelerate reinforcement learning."
            ),
            severity="warning",
            metadata={
                "symbol": symbol,
                "timeframe": selected_tf,
                "bootstrap_cycle": self._cycle_count,
                "signal_type": exploratory_signal.signal_type.value,
            },
        ))

        self._total_signals += 1
        self._strategy_signal_counts["Bootstrap_Explorer"] = (
            self._strategy_signal_counts.get("Bootstrap_Explorer", 0) + 1
        )
        symbol_market = self._symbol_market(symbol)
        self._market_signal_counts[symbol_market] = self._market_signal_counts.get(symbol_market, 0) + 1
        await self._process_signal(
            exploratory_signal,
            "Bootstrap_Explorer",
            short_name,
            default_symbol=symbol,
            execution_timeframe=selected_tf,
        )

    def _build_bootstrap_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        """Build a momentum-biased exploratory signal for bootstrap learning."""
        closes = pd.to_numeric(df.get("close"), errors="coerce").dropna()
        if len(closes) < 8:
            return None

        now_price = float(closes.iloc[-1])
        if now_price <= 0:
            return None

        ema_fast = float(closes.ewm(span=5, adjust=False).mean().iloc[-1])
        ema_slow = float(closes.ewm(span=13, adjust=False).mean().iloc[-1])
        momentum = now_price - float(closes.iloc[-3])

        signal_type = SignalType.BUY
        if now_price < ema_fast or (ema_fast < ema_slow and momentum < 0):
            signal_type = SignalType.SELL

        # Use a volatility-aware distance for exploratory stop/target.
        volatility = float(closes.pct_change().abs().tail(20).mean())
        risk_pct = min(max(volatility * 1.8, 0.004), 0.02)
        if signal_type == SignalType.BUY:
            stop_loss = now_price * (1.0 - risk_pct)
            target = now_price * (1.0 + (risk_pct * 1.6))
        else:
            stop_loss = now_price * (1.0 + risk_pct)
            target = now_price * (1.0 - (risk_pct * 1.6))

        timestamp = (
            df["timestamp"].iloc[-1]
            if "timestamp" in df.columns and len(df["timestamp"]) > 0
            else datetime.now(tz=IST)
        )

        return Signal(
            timestamp=timestamp,
            symbol=symbol,
            signal_type=signal_type,
            strength=SignalStrength.WEAK,
            price=now_price,
            stop_loss=round(float(stop_loss), 2),
            target=round(float(target), 2),
            strategy_name="Bootstrap_Explorer",
            metadata={
                "bootstrap_exploration": True,
                "ema_fast": round(ema_fast, 2),
                "ema_slow": round(ema_slow, 2),
                "momentum": round(momentum, 2),
                "volatility_pct": round(volatility * 100.0, 3),
            },
        )

    @staticmethod
    def _infer_trend(df: pd.DataFrame) -> Tuple[str, float, float]:
        """Infer higher-timeframe bias from spot closes using EMA20 and slope."""
        closes = pd.to_numeric(df["close"], errors="coerce").dropna()
        if closes.empty:
            return "neutral", 0.0, 0.0

        close = float(closes.iloc[-1])
        if len(closes) < 5:
            start = float(closes.iloc[0])
            if close > start:
                return "bullish", close, close
            if close < start:
                return "bearish", close, close
            return "neutral", close, close

        ema_series = closes.ewm(span=20, adjust=False).mean()
        ema_now = float(ema_series.iloc[-1])
        ema_prev = float(ema_series.iloc[-3]) if len(ema_series) >= 3 else ema_now

        if close >= ema_now and ema_now >= ema_prev:
            return "bullish", close, ema_now
        if close <= ema_now and ema_now <= ema_prev:
            return "bearish", close, ema_now
        return "neutral", close, ema_now

    @staticmethod
    def _timeframe_max_age(timeframe: str) -> timedelta:
        token = str(timeframe or "").strip().upper()
        if token == "D":
            return timedelta(days=3)
        if token == "W":
            return timedelta(days=14)
        if token.isdigit():
            minutes = max(int(token), 1)
            return timedelta(minutes=max(minutes * 3, 6))
        return timedelta(minutes=30)

    @staticmethod
    def _coerce_ist_timestamp(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, pd.Timestamp):
            ts = value.to_pydatetime()
        elif isinstance(value, datetime):
            ts = value
        else:
            parsed = pd.to_datetime(value, errors="coerce")
            if parsed is pd.NaT:
                return None
            ts = parsed.to_pydatetime()
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc).astimezone(IST)
        return ts.astimezone(IST)

    def _data_freshness(self, df: pd.DataFrame, timeframe: str) -> Tuple[bool, Dict[str, Any]]:
        if df is None or df.empty or "timestamp" not in df.columns:
            return False, {"reason": "missing_timestamp"}
        ts = self._coerce_ist_timestamp(df["timestamp"].iloc[-1])
        if ts is None:
            return False, {"reason": "invalid_timestamp"}
        now = datetime.now(tz=IST)
        max_age = self._timeframe_max_age(timeframe)
        age = now - ts
        is_fresh = age <= max_age
        return is_fresh, {
            "last_bar_time": ts.isoformat(),
            "age_seconds": round(max(age.total_seconds(), 0.0), 2),
            "max_age_seconds": round(max_age.total_seconds(), 2),
            "timeframe": timeframe,
        }

    @staticmethod
    def _timeframe_sort_key(timeframe: str) -> int:
        token = str(timeframe or "").strip().upper()
        if token == "D":
            return 24 * 60
        if token == "W":
            return 7 * 24 * 60
        if token == "M":
            return 30 * 24 * 60
        if token.isdigit():
            return max(int(token), 1)
        return 15

    async def _rank_execution_timeframes(
        self,
        symbol: str,
        execution_timeframes: List[str],
        *,
        live_only: bool = False,
    ) -> List[str]:
        ordered: List[str] = []
        seen: set[str] = set()
        for timeframe in execution_timeframes:
            token = str(timeframe or "").strip().upper()
            if not token or token in seen:
                continue
            ordered.append(token)
            seen.add(token)
        if len(ordered) <= 1:
            return ordered

        baseline = "15" if "15" in ordered else ordered[min(len(ordered) - 1, 1)]
        frame = await self._fetch_market_data(symbol, timeframe=baseline, live_only=live_only)
        if frame is None or frame.empty or "close" not in frame.columns:
            return ordered

        closes = pd.to_numeric(frame["close"], errors="coerce").dropna()
        if len(closes) < 20:
            return ordered

        market = self._symbol_market(symbol)
        regime_meta = self._market_regime_profile(frame, market)
        realized_vol = float(regime_meta.get("realized_volatility", 0.0) or 0.0)
        trend = str(regime_meta.get("trend", "neutral"))
        regime = str(regime_meta.get("regime", "transition"))
        ascending = sorted(ordered, key=self._timeframe_sort_key)
        descending = list(reversed(ascending))

        if market == "CRYPTO":
            if regime == "trending":
                return descending[: min(len(descending), 2)]
            if regime == "bracketing":
                return ascending[: min(len(ascending), 2)]
            if realized_vol >= 0.009:
                return descending[: min(len(descending), 2)]
            if trend in {"bullish", "bearish"} and realized_vol >= 0.006:
                return descending[: min(len(descending), 2)]
            if realized_vol <= 0.0035:
                return ascending[: min(len(ascending), 2)]
            return ordered[: min(len(ordered), 2)]

        if regime == "trending":
            return descending[: min(len(descending), 2)]
        if regime == "bracketing":
            return ascending[: min(len(ascending), 2)]
        if trend in {"bullish", "bearish"} and realized_vol >= 0.0045:
            return descending[: min(len(descending), 2)]
        if realized_vol <= 0.0018:
            return ascending[: min(len(ascending), 2)]
        return ordered[: min(len(ordered), 2)]

    # ------------------------------------------------------------------
    # Signal Processing
    # ------------------------------------------------------------------

    async def _process_signal(
        self,
        signal: Signal,
        strat_name: str,
        short_name: str,
        default_symbol: str,
        execution_timeframe: Optional[str] = None,
        df_for_signal: Optional[pd.DataFrame] = None,
    ) -> None:
        """Validate signal through risk, size position, place order."""
        underlying_symbol = signal.symbol or default_symbol
        execution_symbol = underlying_symbol
        option_contract: Optional[OptionContract] = None
        underlying_market = self._symbol_market(underlying_symbol)

        if not isinstance(signal.metadata, dict):
            signal.metadata = {}

        # Assign a UUID to this signal and register features for online learning
        signal_id = str(uuid.uuid4())
        signal.metadata["signal_id"] = signal_id
        if self._online_learning_engine is not None and df_for_signal is not None:
            features, feature_names = self._extract_signal_features(
                df_for_signal,
                signal.symbol or default_symbol,
                signal_metadata=signal.metadata,
            )
            if features:
                self._online_learning_engine.register_signal(
                    signal_id=signal_id,
                    symbol=signal.symbol or default_symbol,
                    strategy=strat_name,
                    features=features,
                    feature_names=feature_names,
                    signal_type=signal.signal_type.value,
                )

        if underlying_market == "NSE" and not self._is_nse_option_symbol(underlying_symbol):
            if not self._is_nse_option_eligible_underlying(underlying_symbol):
                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.ORDER_REJECTED,
                    title=f"Order Rejected — {short_name}",
                    message=(
                        "This NSE setup is not FnO-eligible. The agent only executes long "
                        "call/put options for NSE symbols."
                    ),
                    severity="warning",
                    metadata={
                        "underlying_symbol": underlying_symbol,
                        "strategy": strat_name,
                        "signal_type": signal.signal_type.value,
                    },
                ))
                return
            option_contract = await self._resolve_option_contract(
                underlying_symbol=underlying_symbol,
                signal_type=signal.signal_type,
                spot_hint=float(signal.price or 0.0),
            )
            if option_contract is None:
                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.ORDER_REJECTED,
                    title=f"Order Rejected — {short_name}",
                    message=(
                        "No tradable NSE option contract resolved from the live chain for "
                        f"{short_name}. The agent does not fall back to cash execution."
                    ),
                    severity="error",
                    metadata={
                        "underlying_symbol": underlying_symbol,
                        "strategy": strat_name,
                        "signal_type": signal.signal_type.value,
                    },
                ))
                return
            execution_symbol = option_contract.option_symbol
        elif (
            underlying_market == "US"
            and self._parse_us_option_symbol(self._normalize_us_ticker(underlying_symbol)) is None
        ):
            if not self.config.trade_us_options:
                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.ORDER_REJECTED,
                    title=f"Order Rejected — {short_name}",
                    message="US options routing is disabled, and the agent will not fall back to stock execution.",
                    severity="warning",
                    metadata={
                        "underlying_symbol": underlying_symbol,
                        "strategy": strat_name,
                        "signal_type": signal.signal_type.value,
                    },
                ))
                return
            option_contract = await self._resolve_us_option_contract(
                underlying_symbol=underlying_symbol,
                signal_type=signal.signal_type,
                spot_hint=float(signal.price or 0.0),
            )
            if option_contract is not None:
                execution_symbol = option_contract.option_symbol
            else:
                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.ORDER_REJECTED,
                    title=f"Order Rejected — {short_name}",
                    message=(
                        "Could not resolve a liquid US option contract. "
                        "The agent does not fall back to stock execution."
                    ),
                    severity="error",
                    metadata={
                        "underlying_symbol": underlying_symbol,
                        "strategy": strat_name,
                        "signal_type": signal.signal_type.value,
                    },
                ))
                return

        if option_contract is not None:
            signal.metadata["execution_contract_type"] = "long_option"
            signal.metadata["options_analytics"] = await self.get_options_trade_analytics(
                underlying_symbol=underlying_symbol,
                signal_type=signal.signal_type,
                spot_hint=float(signal.price or 0.0),
            )

        if not self.config.paper_mode and self._symbol_market(execution_symbol) != "NSE":
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.ORDER_REJECTED,
                title=f"Live Order Rejected — {short_name}",
                message=(
                    "Live execution for non-NSE symbols is disabled for this broker setup. "
                    "Use paper mode for US/crypto strategies."
                ),
                severity="warning",
                metadata={
                    "symbol": execution_symbol,
                    "underlying_symbol": underlying_symbol,
                    "market": self._symbol_market(execution_symbol),
                    "paper_mode": self.config.paper_mode,
                },
            ))
            return

        format_price = lambda value: f"{value:,.2f}" if value is not None else "N/A"
        reference_meta = signal.metadata.get("reference_timeframe_bias", {}) if isinstance(signal.metadata, dict) else {}
        execution_short_name = execution_symbol.split(":")[-1]
        contract_note = (
            f" Contract: {execution_short_name} ({option_contract.option_type}, "
            f"strike {option_contract.strike:,.0f}, expiry {option_contract.expiry})."
            if option_contract is not None
            else ""
        )

        execution_market = self._symbol_market(execution_symbol)
        market_allocation = self._market_allocation(execution_market)
        entry_price = float(option_contract.ltp) if option_contract is not None else float(signal.price or 0.0)
        if entry_price <= 0:
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.ORDER_REJECTED,
                title=f"Order Rejected — {short_name}",
                message="Signal has invalid execution price. Skipping execution.",
                severity="error",
                metadata={
                    "underlying_symbol": underlying_symbol,
                    "symbol": execution_symbol,
                    "strategy": strat_name,
                    "entry_price": signal.price,
                    "option_ltp": (option_contract.ltp if option_contract else None),
                },
            ))
            return

        if not self.config.paper_mode and self._symbol_has_pending_live_order(execution_symbol):
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.ORDER_REJECTED,
                title=f"Order Deferred — {short_name}",
                message=(
                    f"A live order for {execution_short_name if 'execution_short_name' in locals() else execution_symbol} "
                    "is still pending broker fills. Skipping duplicate entry."
                ),
                severity="warning",
                metadata={
                    "symbol": execution_symbol,
                    "underlying_symbol": underlying_symbol,
                    "strategy": strat_name,
                    "pending_live_order": True,
                },
            ))
            return

        if option_contract is not None:
            sl_price, target_price = self._derive_option_levels(signal, entry_price)
        else:
            if signal.stop_loss is not None:
                sl_price = float(signal.stop_loss)
            elif signal.signal_type == SignalType.BUY:
                sl_price = entry_price * 0.99
            else:
                sl_price = entry_price * 1.01
            if signal.target is not None:
                target_price = float(signal.target)
            elif signal.signal_type == SignalType.BUY:
                target_price = entry_price * 1.01
            else:
                target_price = entry_price * 0.99

        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.SIGNAL_GENERATED,
            title=f"{signal.signal_type.value} Signal — {short_name}",
            message=(
                f"{strat_name} generated a {signal.strength.value.upper()} {signal.signal_type.value} signal. "
                f"TF: {execution_timeframe or self.config.timeframe}. "
                f"Underlying: {format_price(signal.price)}. "
                f"Execution: {format_price(entry_price)}. "
                f"SL: {format_price(sl_price)}. "
                f"Target: {format_price(target_price)}."
                f"{contract_note}"
            ),
            severity="success",
            metadata={
                "symbol": execution_symbol,
                "underlying_symbol": underlying_symbol,
                "strategy": strat_name,
                "signal_type": signal.signal_type.value,
                "strength": signal.strength.value,
                "price": entry_price,
                "underlying_price": signal.price,
                "stop_loss": sl_price,
                "target": target_price,
                "execution_timeframe": execution_timeframe,
                "reference": reference_meta,
                "option_contract": (
                    {
                        "symbol": option_contract.option_symbol,
                        "type": option_contract.option_type,
                        "strike": option_contract.strike,
                        "expiry": option_contract.expiry,
                        "lot_size": option_contract.lot_size,
                    }
                    if option_contract is not None
                    else None
                ),
            },
        ))

        try:
            self.position_sizer.capital = max(float(market_allocation["allocated_capital"]), 1.0)
            sizing = self.position_sizer.fixed_fractional(
                entry_price=entry_price,
                stop_loss=sl_price,
            )
            quantity = max(int(sizing.quantity), 1)
        except Exception:
            quantity = 1

        reinforcement_mult = self._position_size_multiplier(strat_name, execution_market)
        market_condition_mult = self._market_condition_size_multiplier(signal, execution_timeframe)
        applied_size_mult = reinforcement_mult * market_condition_mult
        if isinstance(signal.metadata, dict):
            signal.metadata["reinforcement_size_multiplier"] = round(reinforcement_mult, 3)
            signal.metadata["market_condition_size_multiplier"] = round(market_condition_mult, 3)
            signal.metadata["applied_position_size_multiplier"] = round(applied_size_mult, 3)
        quantity = max(int(quantity * applied_size_mult), 1)
        if self._is_bootstrap_phase():
            quantity = max(int(quantity * max(self.config.bootstrap_size_multiplier, 1.0)), 1)

        lot_size = option_contract.lot_size if option_contract is not None else 1
        quantity = self._align_quantity_to_lot(quantity, lot_size)

        (
            effective_max_position_size,
            effective_max_risk_per_trade_pct,
            effective_max_open_positions,
            effective_max_concentration_pct,
        ) = self._effective_risk_limits(execution_market)

        # Align quantity with configured risk caps before validation so
        # high-priced symbols are not routinely rejected as over-sized.
        max_position_qty = max(
            int(effective_max_position_size // max(entry_price, 1e-6)),
            1,
        )
        unit_risk = max(abs(entry_price - sl_price), entry_price * 0.001, 1e-6)
        max_trade_risk = float(market_allocation["allocated_capital"]) * effective_max_risk_per_trade_pct
        max_risk_qty = max(int(max_trade_risk // unit_risk), 1)

        if lot_size > 1:
            max_position_lots = int(max_position_qty // lot_size)
            max_risk_lots = int(max_risk_qty // lot_size)
            max_lots = min(max_position_lots, max_risk_lots)
            if max_lots <= 0:
                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.ORDER_REJECTED,
                    title=f"Order Rejected — {short_name}",
                    message=(
                        f"Risk caps cannot fit 1 lot ({lot_size}) for {execution_short_name} "
                        f"at {entry_price:,.2f}."
                    ),
                    severity="warning",
                    metadata={
                        "symbol": execution_symbol,
                        "underlying_symbol": underlying_symbol,
                        "lot_size": lot_size,
                        "entry_price": entry_price,
                        "max_position_qty": max_position_qty,
                        "max_risk_qty": max_risk_qty,
                    },
                ))
                return
            desired_lots = max(quantity // lot_size, 1)
            quantity = max(1, min(desired_lots, max_lots)) * lot_size
        else:
            quantity = max(1, min(quantity, max_position_qty, max_risk_qty))

        strategy_budget = self._strategy_budget_limits(strat_name, execution_symbol)
        priority_score = self._signal_priority_score(
            strat_name,
            signal,
            execution_timeframe or self.config.timeframe,
            signal.metadata.get("market_regime", {}) if isinstance(signal.metadata, dict) else {},
        )
        budget_resolution = self._resolve_trade_budget_cap(
            strategy_budget,
            priority_score=priority_score,
            entry_price=entry_price,
            lot_size=lot_size,
            market=execution_market,
        )
        if isinstance(signal.metadata, dict):
            signal.metadata["strategy_budget"] = {
                "market": execution_market,
                "strategy_budget": round(strategy_budget["strategy_budget"], 2),
                "per_trade_budget": round(strategy_budget["per_trade_budget"], 2),
                "remaining_budget": round(strategy_budget["remaining_budget"], 2),
                "remaining_trade_budget": round(strategy_budget["remaining_trade_budget"], 2),
                "market_budget": round(strategy_budget["market_budget"], 2),
                "market_remaining_budget": round(strategy_budget["market_remaining_budget"], 2),
                "max_instrument_budget": round(strategy_budget["max_instrument_budget"], 2),
                "available_slots": int(strategy_budget["available_slots"]),
                "global_remaining_budget": round(budget_resolution["global_remaining_budget"], 2),
                "borrowed_budget": round(budget_resolution["borrowed_budget"], 2),
                "allow_slot_override": bool(budget_resolution["allow_slot_override"]),
                "priority_score": round(priority_score, 2),
            }

        if strategy_budget["available_slots"] <= 0 and budget_resolution["allow_slot_override"] <= 0:
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.ORDER_REJECTED,
                title=f"Order Rejected — {short_name}",
                message=(
                    f"{strat_name} already uses all {self.config.strategy_max_concurrent_positions} "
                    "strategy budget slots."
                ),
                severity="warning",
                metadata={
                    "symbol": execution_symbol,
                    "underlying_symbol": underlying_symbol,
                    "strategy": strat_name,
                    "budget": strategy_budget,
                },
            ))
            return

        budget_cap = float(budget_resolution["budget_cap"])
        max_budget_qty = max(int(budget_cap // max(entry_price, 1e-6)), 0)
        if lot_size > 1:
            max_budget_qty = (max_budget_qty // lot_size) * lot_size

        if max_budget_qty <= 0:
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.ORDER_REJECTED,
                title=f"Order Rejected — {short_name}",
                message=(
                    f"{strat_name} cannot fit a trade for {execution_short_name} "
                    f"at {entry_price:,.2f} within current capital headroom."
                ),
                severity="warning",
                metadata={
                    "symbol": execution_symbol,
                    "underlying_symbol": underlying_symbol,
                    "strategy": strat_name,
                    "budget": strategy_budget,
                },
            ))
            return

        quantity = min(quantity, max_budget_qty)
        if lot_size > 1:
            if quantity < lot_size:
                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.ORDER_REJECTED,
                    title=f"Order Rejected — {short_name}",
                    message=(
                        f"{strat_name} budget cannot fit 1 lot ({lot_size}) for "
                        f"{execution_short_name} at {entry_price:,.2f}."
                    ),
                    severity="warning",
                    metadata={
                        "symbol": execution_symbol,
                        "underlying_symbol": underlying_symbol,
                        "strategy": strat_name,
                        "budget": strategy_budget,
                    },
                ))
                return
            quantity = self._align_quantity_to_lot(quantity, lot_size)

        execution_side = OrderSide.BUY if option_contract is not None else (
            OrderSide.BUY if signal.signal_type == SignalType.BUY else OrderSide.SELL
        )
        liquidity_constraints = await self._resolve_liquidity_quantity_cap(
            execution_symbol=execution_symbol,
            underlying_symbol=underlying_symbol,
            execution_market=execution_market,
            execution_timeframe=execution_timeframe,
            side=execution_side,
            lot_size=lot_size,
            options_analytics=signal.metadata.get("options_analytics") if isinstance(signal.metadata, dict) else None,
        )
        if isinstance(signal.metadata, dict):
            signal.metadata["liquidity_constraints"] = {
                **liquidity_constraints,
                "requested_quantity": quantity,
            }

        liquidity_cap = liquidity_constraints.get("max_quantity")
        if liquidity_cap is not None:
            liquidity_cap = max(int(liquidity_cap), 0)
            if liquidity_cap <= 0:
                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.ORDER_REJECTED,
                    title=f"Order Rejected — {short_name}",
                    message=(
                        f"Visible liquidity cannot support a realistic fill for {execution_short_name} "
                        "right now. Waiting for deeper volume."
                    ),
                    severity="warning",
                    metadata={
                        "symbol": execution_symbol,
                        "underlying_symbol": underlying_symbol,
                        "strategy": strat_name,
                        "liquidity_constraints": liquidity_constraints,
                    },
                ))
                return

            original_quantity = quantity
            quantity = min(quantity, liquidity_cap)
            if lot_size > 1:
                quantity = (quantity // lot_size) * lot_size
            if quantity <= 0 or (lot_size > 1 and quantity < lot_size):
                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.ORDER_REJECTED,
                    title=f"Order Rejected — {short_name}",
                    message=(
                        f"Available liquidity in {execution_short_name} is below one tradable lot "
                        f"({lot_size}). Skipping this setup."
                    ),
                    severity="warning",
                    metadata={
                        "symbol": execution_symbol,
                        "underlying_symbol": underlying_symbol,
                        "strategy": strat_name,
                        "liquidity_constraints": liquidity_constraints,
                    },
                ))
                return
            if isinstance(signal.metadata, dict):
                signal.metadata["liquidity_constraints"]["applied_quantity"] = quantity
                signal.metadata["liquidity_constraints"]["quantity_reduced"] = quantity < original_quantity

        # Risk validation (after sizing so actual exposure is validated)
        effective_max_position_size_inr = effective_max_position_size * float(market_allocation["fx_to_inr"])
        effective_concentration_pct_total = (
            effective_max_position_size_inr / max(self.total_allocated_capital_inr(), 1.0)
        )
        market_open_positions = self._market_open_position_count(execution_market)
        position_would_increase_count = (
            self.position_manager.get_position(execution_symbol) is None
            and not self._symbol_has_pending_live_order(execution_symbol)
        )
        with self._temporary_risk_overrides(
            max_position_size=effective_max_position_size_inr,
            max_risk_per_trade_pct=effective_max_risk_per_trade_pct,
            max_open_positions=effective_max_open_positions,
            max_concentration_pct=effective_concentration_pct_total,
        ):
            validation = self.risk_manager.validate_trade(
                symbol=execution_symbol,
                side=signal.signal_type.value,
                quantity=quantity,
                entry_price=entry_price,
                stop_loss=sl_price,
                open_positions_override=market_open_positions,
                position_would_increase_count=position_would_increase_count,
            )

        if not validation.is_valid:
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.RISK_CHECK_FAILED,
                title=f"Risk Check Failed — {short_name}",
                message=f"Trade rejected: {validation.reason}. Risk score: {validation.risk_score:.2f}.",
                severity="warning",
                metadata={
                    "symbol": execution_symbol,
                    "underlying_symbol": underlying_symbol,
                    "reason": validation.reason,
                    "risk_score": validation.risk_score,
                    "market_open_positions": market_open_positions,
                    "market_open_position_limit": effective_max_open_positions,
                },
            ))
            return

        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.RISK_CHECK_PASSED,
            title=f"Risk Check Passed — {short_name}",
            message=f"Trade approved. Risk score: {validation.risk_score:.2f}. Proceeding to order placement.",
            severity="success",
                metadata={
                    "symbol": execution_symbol,
                    "underlying_symbol": underlying_symbol,
                    "risk_score": validation.risk_score,
                    "market_open_positions": market_open_positions,
                    "market_open_position_limit": effective_max_open_positions,
                },
            ))

        # Place order. Index directional signals are converted into long options:
        # BUY -> buy CE, SELL -> buy PE.
        side = execution_side
        order = Order(
            symbol=execution_symbol,
            quantity=quantity,
            side=side,
            order_type=OrderType.MARKET,
            product_type=ProductType.INTRADAY,
            market_price_hint=entry_price,
            tag=strat_name,
        )

        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.ORDER_PLACING,
            title=f"Placing {side.name} Order — {short_name}",
            message=(
                f"{side.name} {quantity} units of {execution_short_name} at market. "
                f"Strategy: {strat_name}."
            ),
            severity="info",
            metadata={
                "symbol": execution_symbol,
                "underlying_symbol": underlying_symbol,
                "side": side.name,
                "quantity": quantity,
                "strategy": strat_name,
                "lot_size": lot_size,
                "liquidity": signal.metadata.get("liquidity_constraints") if isinstance(signal.metadata, dict) else None,
            },
        ))

        try:
            with self._latency_tracker.track(
                "order_submit_ms",
                symbol=execution_symbol,
                market=execution_market,
                strategy=strat_name,
            ):
                if self.config.paper_mode:
                    placed = self.order_manager.place_order(order)
                else:
                    placed = await asyncio.to_thread(self.order_manager.place_order, order)

            executed_order = placed.order
            if placed.success and executed_order is not None and executed_order.status in (
                OrderStatus.FILLED,
                OrderStatus.PLACED,
                OrderStatus.PARTIALLY_FILLED,
            ):
                order_id = executed_order.order_id or ""
                if self.config.paper_mode:
                    fill_price = float(executed_order.fill_price or entry_price)
                    await self._finalize_live_entry_fill(
                        context=PendingLiveEntryOrder(
                            order_id=order_id,
                            symbol=execution_symbol,
                            underlying_symbol=underlying_symbol,
                            short_name=short_name,
                            execution_short_name=execution_short_name,
                            quantity=quantity,
                            side=side,
                            strategy=strat_name,
                            market=execution_market,
                            execution_timeframe=execution_timeframe or self.config.timeframe,
                            entry_price_hint=entry_price,
                            stop_loss=sl_price,
                            target=target_price,
                            signal_id=signal_id,
                            option_contract=option_contract,
                        ),
                        order=executed_order,
                        fill_quantity=self._resolved_fill_quantity(executed_order.fill_quantity, quantity),
                        fill_price=fill_price,
                    )
                else:
                    self._pending_live_entries[order_id] = PendingLiveEntryOrder(
                        order_id=order_id,
                        symbol=execution_symbol,
                        underlying_symbol=underlying_symbol,
                        short_name=short_name,
                        execution_short_name=execution_short_name,
                        quantity=quantity,
                        side=side,
                        strategy=strat_name,
                        market=execution_market,
                        execution_timeframe=execution_timeframe or self.config.timeframe,
                        entry_price_hint=entry_price,
                        stop_loss=sl_price,
                        target=target_price,
                        signal_id=signal_id,
                        option_contract=option_contract,
                    )
                    self._persist_live_runtime_state()
                    await self.event_bus.emit(AgentEvent(
                        event_type=AgentEventType.ORDER_PLACED,
                        title=f"Order Submitted — {short_name}",
                        message=(
                            f"{side.name} {quantity} x {execution_short_name}. "
                            "Waiting for broker fill confirmation."
                        ),
                        severity="success",
                        metadata={
                            "symbol": execution_symbol,
                            "underlying_symbol": underlying_symbol,
                            "side": side.name,
                            "quantity": quantity,
                            "stop_loss": sl_price,
                            "target": target_price,
                            "order_id": order_id,
                            "strategy": strat_name,
                            "status": executed_order.status.value,
                        },
                    ))
                    if int(executed_order.fill_quantity or 0) > 0:
                        await self._finalize_live_entry_fill(
                            context=self._pending_live_entries[order_id],
                            order=executed_order,
                            fill_quantity=int(executed_order.fill_quantity),
                            fill_price=float(executed_order.fill_price or entry_price),
                        )
                        if executed_order.status == OrderStatus.FILLED:
                            self._pending_live_entries.pop(order_id, None)
                            self._persist_live_runtime_state()
            else:
                status = executed_order.status.value if executed_order is not None else "rejected"
                reason = (
                    (executed_order.rejection_reason if executed_order is not None else None)
                    or placed.message
                    or "unknown"
                )
                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.ORDER_REJECTED,
                    title=f"Order Rejected — {short_name}",
                    message=f"Order was {status}. Reason: {reason}.",
                    severity="error",
                    metadata={
                        "symbol": execution_symbol,
                        "underlying_symbol": underlying_symbol,
                        "status": status,
                        "reason": reason,
                    },
                ))

        except Exception as e:
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.ORDER_REJECTED,
                title=f"Order Failed — {short_name}",
                message=f"Error placing order: {e}",
                severity="error",
                metadata={
                    "symbol": execution_symbol,
                    "underlying_symbol": underlying_symbol,
                    "error": str(e),
                },
            ))

    def _is_index_symbol(self, symbol: str) -> bool:
        return symbol.endswith("-INDEX") or symbol in self._spot_to_index_name

    def _normalize_nse_underlying_root(self, symbol: str) -> str:
        token = str(symbol or "").strip().upper()
        if not token:
            return ""
        spot_match = self._spot_to_index_name.get(token)
        if spot_match:
            return spot_match
        token = token.split(":", 1)[-1]
        if token.endswith("-EQ"):
            token = token[:-3]
        if token.endswith("-INDEX"):
            token = token[:-6]
        return token

    def _is_nse_option_eligible_underlying(self, symbol: str) -> bool:
        root = self._normalize_nse_underlying_root(symbol)
        return bool(root and get_fno_instrument(root) is not None)

    @staticmethod
    def _is_nse_option_symbol(symbol: str) -> bool:
        token = str(symbol or "").split(":", 1)[-1].strip().upper()
        return token.endswith(("CE", "PE")) and any(ch.isdigit() for ch in token)

    @staticmethod
    def _align_quantity_to_lot(quantity: int, lot_size: int) -> int:
        qty = max(int(quantity), 1)
        if lot_size <= 1:
            return qty
        lots = max(qty // lot_size, 1)
        return lots * lot_size

    @staticmethod
    def _safe_positive_int(value: Any) -> int:
        try:
            parsed = int(float(value or 0))
        except (TypeError, ValueError):
            return 0
        return max(parsed, 0)

    @classmethod
    def _normalize_depth_levels(cls, payload: Any) -> List[Tuple[float, int]]:
        if payload is None:
            return []

        candidates: List[Any]
        if isinstance(payload, list):
            candidates = payload
        elif isinstance(payload, dict):
            if any(
                key in payload
                for key in ("price", "p", "rate", "qty", "quantity", "volume", "size", "orders")
            ):
                candidates = [payload]
            else:
                candidates = list(payload.values())
        else:
            candidates = [payload]

        levels: List[Tuple[float, int]] = []
        for item in candidates:
            price = 0.0
            qty = 0
            if isinstance(item, dict):
                try:
                    price = float(item.get("price") or item.get("p") or item.get("rate") or 0.0)
                except (TypeError, ValueError):
                    price = 0.0
                qty = cls._safe_positive_int(
                    item.get("qty")
                    or item.get("quantity")
                    or item.get("volume")
                    or item.get("size")
                    or item.get("orders")
                )
            elif isinstance(item, (list, tuple)):
                if len(item) >= 2:
                    try:
                        price = float(item[0] or 0.0)
                    except (TypeError, ValueError):
                        price = 0.0
                    qty = cls._safe_positive_int(item[1])
            if qty > 0:
                levels.append((price, qty))
        return levels

    @classmethod
    def _extract_visible_depth_quantity(
        cls,
        depth_response: Dict[str, Any] | None,
        symbol: str,
        side: OrderSide,
    ) -> int:
        if not isinstance(depth_response, dict):
            return 0

        payload: Any = depth_response
        depth_block = depth_response.get("d")
        if isinstance(depth_block, dict):
            payload = depth_block.get(symbol)
            if payload is None and len(depth_block) == 1:
                payload = next(iter(depth_block.values()))
        elif isinstance(depth_response.get(symbol), dict):
            payload = depth_response.get(symbol)

        if not isinstance(payload, dict):
            return 0

        side_keys = (
            ("ask", "asks", "sell", "sells", "offer", "offers")
            if side == OrderSide.BUY
            else ("bid", "bids", "buy", "buys")
        )
        raw_levels = None
        for key in side_keys:
            candidate = payload.get(key)
            if candidate is not None:
                raw_levels = candidate
                break

        levels = cls._normalize_depth_levels(raw_levels)
        visible_qty = sum(qty for _, qty in levels[:3])
        if visible_qty > 0:
            return visible_qty

        fallback_keys = (
            ("totalAskQty", "totSellQty", "sellQty", "askQty", "ask_size")
            if side == OrderSide.BUY
            else ("totalBidQty", "totBuyQty", "buyQty", "bidQty", "bid_size")
        )
        for key in fallback_keys:
            fallback_qty = cls._safe_positive_int(payload.get(key))
            if fallback_qty > 0:
                return fallback_qty
        return 0

    async def _resolve_liquidity_quantity_cap(
        self,
        *,
        execution_symbol: str,
        underlying_symbol: str,
        execution_market: str,
        execution_timeframe: str | None,
        side: OrderSide,
        lot_size: int,
        options_analytics: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        # Keep fills realistic by capping size to a conservative share of traded
        # contract volume, open interest, visible orderbook depth, or recent bar volume.
        details: Dict[str, Any] = {
            "symbol": execution_symbol,
            "underlying_symbol": underlying_symbol,
            "market": execution_market,
            "lot_size": lot_size,
        }
        raw_caps: List[int] = []

        contract_snapshot: Dict[str, Any] | None = None
        if isinstance(options_analytics, dict):
            candidate_order = (
                options_analytics.get("selected_contract"),
                options_analytics.get("bullish_call"),
                options_analytics.get("bearish_put"),
                options_analytics.get("atm_call"),
                options_analytics.get("atm_put"),
            )
            execution_key = str(execution_symbol or "").strip().upper()
            for candidate in candidate_order:
                if not isinstance(candidate, dict):
                    continue
                candidate_symbol = str(candidate.get("symbol") or "").strip().upper()
                if candidate_symbol == execution_key:
                    contract_snapshot = candidate
                    break
                if contract_snapshot is None and candidate_symbol:
                    contract_snapshot = candidate

        if contract_snapshot:
            volume = self._safe_positive_int(contract_snapshot.get("volume"))
            oi = self._safe_positive_int(contract_snapshot.get("oi"))
            details["contract_liquidity"] = {
                "symbol": contract_snapshot.get("symbol"),
                "volume": volume,
                "oi": oi,
                "bid": round(float(contract_snapshot.get("bid") or 0.0), 4),
                "ask": round(float(contract_snapshot.get("ask") or 0.0), 4),
            }
            if volume > 0:
                volume_cap = int(volume * 0.05)
                if lot_size > 1 and volume >= lot_size:
                    volume_cap = max(volume_cap, lot_size)
                if volume_cap > 0:
                    raw_caps.append(volume_cap)
                    details["volume_cap"] = volume_cap
            if oi > 0:
                oi_cap = int(oi * 0.02)
                if lot_size > 1 and oi >= lot_size:
                    oi_cap = max(oi_cap, lot_size)
                if oi_cap > 0:
                    raw_caps.append(oi_cap)
                    details["oi_cap"] = oi_cap

        if execution_market == "NSE":
            try:
                depth_response = await asyncio.to_thread(self.fyers_client.get_market_depth, execution_symbol)
                visible_qty = self._extract_visible_depth_quantity(depth_response, execution_symbol, side)
            except Exception as exc:
                logger.debug("liquidity_depth_fetch_failed", symbol=execution_symbol, error=str(exc))
                visible_qty = 0
            if visible_qty > 0:
                depth_cap = int(visible_qty * 0.25)
                if lot_size > 1 and visible_qty >= lot_size:
                    depth_cap = max(depth_cap, lot_size)
                if depth_cap > 0:
                    raw_caps.append(depth_cap)
                    details["visible_orderbook_qty"] = visible_qty
                    details["orderbook_cap"] = depth_cap

        if not raw_caps:
            frame = await self._fetch_market_data(execution_symbol, execution_timeframe or self.config.timeframe)
            if frame is not None and not frame.empty and "volume" in frame.columns:
                recent_volume = pd.to_numeric(frame["volume"], errors="coerce").dropna().tail(12)
                if not recent_volume.empty:
                    median_bar_volume = self._safe_positive_int(recent_volume.median())
                    if median_bar_volume > 0:
                        bar_cap = int(median_bar_volume * 0.10)
                        if lot_size > 1 and median_bar_volume >= lot_size:
                            bar_cap = max(bar_cap, lot_size)
                        if bar_cap > 0:
                            raw_caps.append(bar_cap)
                            details["median_bar_volume"] = median_bar_volume
                            details["recent_volume_cap"] = bar_cap

        if not raw_caps:
            details["cap_source"] = "none"
            details["max_quantity"] = None
            return details

        raw_cap = min(raw_caps)
        capped_quantity = raw_cap
        if lot_size > 1:
            capped_quantity = (raw_cap // lot_size) * lot_size

        details["cap_source"] = "liquidity"
        details["raw_cap"] = raw_cap
        details["max_quantity"] = capped_quantity
        return details

    def _derive_option_levels(self, signal: Signal, option_entry_price: float) -> Tuple[float, float]:
        """Map underlying signal SL/target into premium-space risk levels."""
        if option_entry_price <= 0:
            return 0.0, 0.0

        default_sl = max(self.config.option_default_stop_loss_pct / 100.0, 0.01)
        default_target = max(self.config.option_default_target_pct / 100.0, 0.01)

        sl_move_pct = default_sl
        if signal.price and signal.stop_loss and signal.price > 0:
            strategy_sl = abs((float(signal.price) - float(signal.stop_loss)) / float(signal.price))
            sl_move_pct = max(strategy_sl, default_sl * 0.8)
        sl_move_pct = min(max(sl_move_pct, 0.03), 0.60)

        target_move_pct = max(default_target, sl_move_pct * 1.2)
        if signal.price and signal.target and signal.price > 0:
            strategy_target = abs((float(signal.target) - float(signal.price)) / float(signal.price))
            target_move_pct = max(target_move_pct, strategy_target)
        target_move_pct = min(max(target_move_pct, 0.05), 2.00)

        stop_loss = max(option_entry_price * (1.0 - sl_move_pct), option_entry_price * 0.50, 0.05)
        target = max(option_entry_price * (1.0 + target_move_pct), option_entry_price * 1.03)
        return stop_loss, target

    def _is_bootstrap_phase(self) -> bool:
        return self.config.liberal_bootstrap_enabled and self._cycle_count <= max(int(self.config.bootstrap_cycles), 1)

    def _effective_risk_limits(self, market: str) -> Tuple[float, float, int, float]:
        allocation = self._market_allocation(market)
        max_position_size = float(allocation["max_instrument_capital"])
        max_risk_per_trade_pct = float(self.risk_manager.config.max_risk_per_trade_pct)
        max_open_positions = int(self.risk_manager.config.max_open_positions)
        max_concentration_pct = float(allocation["max_instrument_pct"]) / 100.0

        if not self._is_bootstrap_phase():
            return (
                max_position_size,
                max_risk_per_trade_pct,
                max_open_positions,
                max_concentration_pct,
            )

        boosted_concentration = min(
            max(max_concentration_pct, self.config.bootstrap_max_concentration_pct / 100.0),
            1.0,
        )
        boosted_risk = max(
            max_risk_per_trade_pct,
            self.config.bootstrap_risk_per_trade_pct / 100.0,
        )
        boosted_open_positions = max(max_open_positions, int(self.config.bootstrap_max_open_positions))
        boosted_position_size = max(
            max_position_size,
            float(allocation["allocated_capital"]) * boosted_concentration,
        )
        return (
            boosted_position_size,
            boosted_risk,
            boosted_open_positions,
            boosted_concentration,
        )

    def _strategy_budget_limits(self, strategy: str, symbol: str) -> Dict[str, float]:
        market = self._symbol_market(symbol)
        allocation = self._market_allocation(market)
        market_budget = float(allocation["allocated_capital"])
        market_remaining_budget = self._market_available_capital(market)
        max_instrument_budget = float(allocation["max_instrument_capital"])

        if not self.config.strategy_capital_bucket_enabled:
            return {
                "market_budget": market_budget,
                "market_remaining_budget": market_remaining_budget,
                "max_instrument_budget": max_instrument_budget,
                "strategy_budget": market_budget,
                "per_trade_budget": max_instrument_budget,
                "remaining_budget": market_remaining_budget,
                "remaining_trade_budget": min(max_instrument_budget, market_remaining_budget),
                "open_positions": 0.0,
                "available_slots": float(max(int(self.config.strategy_max_concurrent_positions), 1)),
            }

        enabled = self._enabled_strategy_names() or list(self.config.strategies)
        strategy_count = max(len(enabled), 1)
        strategy_budget = market_budget / strategy_count
        max_slots = max(int(self.config.strategy_max_concurrent_positions), 1)
        per_trade_budget = min(strategy_budget / max_slots, max_instrument_budget)

        scoped_positions = [
            position for position in self.position_manager.get_positions_by_tag(strategy)
            if self._symbol_market(position.symbol) == market
        ]
        used_budget = 0.0
        open_symbols: set[str] = set()
        current_symbol_exposure = 0.0
        for position in scoped_positions:
            mark = float(position.current_price or position.avg_price or 0.0)
            notional = max(mark, 0.0) * float(position.quantity)
            used_budget += notional
            open_symbols.add(position.symbol)
            if position.symbol == symbol:
                current_symbol_exposure += notional

        remaining_budget = min(max(strategy_budget - used_budget, 0.0), market_remaining_budget)
        remaining_trade_budget = min(max(per_trade_budget - current_symbol_exposure, 0.0), market_remaining_budget)
        available_slots = max(max_slots - len(open_symbols), 0)
        if current_symbol_exposure > 0:
            available_slots = max(available_slots, 1)

        return {
            "market_budget": market_budget,
            "market_remaining_budget": market_remaining_budget,
            "max_instrument_budget": max_instrument_budget,
            "strategy_budget": strategy_budget,
            "per_trade_budget": per_trade_budget,
            "remaining_budget": remaining_budget,
            "remaining_trade_budget": remaining_trade_budget,
            "open_positions": float(len(open_symbols)),
            "available_slots": float(available_slots),
        }

    def _portfolio_used_capital(self) -> float:
        used = 0.0
        for position in self.position_manager.get_all_positions():
            mark = float(position.current_price or position.avg_price or 0.0)
            used += max(mark, 0.0) * float(position.quantity) * float(
                self._market_allocation(self._symbol_market(position.symbol))["fx_to_inr"]
            )
        return used

    def _portfolio_available_capital(self) -> float:
        capital = self.total_allocated_capital_inr()
        return max(capital - self._portfolio_used_capital(), 0.0)

    def _market_used_capital(self, market: str) -> float:
        used = 0.0
        for position in self.position_manager.get_all_positions():
            if self._symbol_market(position.symbol) != str(market or "").upper():
                continue
            mark = float(position.current_price or position.avg_price or 0.0)
            used += max(mark, 0.0) * float(position.quantity)
        return used

    def _market_available_capital(self, market: str) -> float:
        allocation = self._market_allocation(market)
        return max(float(allocation["allocated_capital"]) - self._market_used_capital(market), 0.0)

    def _market_open_position_count(self, market: str) -> int:
        market_key = str(market or "").upper()
        return len(
            {
                position.symbol
                for position in self.position_manager.get_all_positions()
                if self._symbol_market(position.symbol) == market_key and int(position.quantity or 0) > 0
            }
        )

    def _resolve_trade_budget_cap(
        self,
        strategy_budget: Dict[str, float],
        priority_score: float,
        entry_price: float,
        lot_size: int,
        market: str,
    ) -> Dict[str, float]:
        global_remaining = self._market_available_capital(market)
        base_cap = min(
            float(strategy_budget["remaining_budget"]),
            float(strategy_budget["remaining_trade_budget"]),
            global_remaining,
        )
        minimum_trade_notional = max(float(entry_price) * max(int(lot_size), 1), 0.0)
        allow_slot_override = False
        borrowed_budget = 0.0

        if priority_score >= 64.0 and global_remaining >= minimum_trade_notional:
            target_cap = min(
                global_remaining,
                float(strategy_budget["per_trade_budget"]) * (1.35 if priority_score >= 84.0 else 1.1),
            )
            if target_cap > base_cap:
                borrowed_budget = target_cap - base_cap
                base_cap = target_cap
            if float(strategy_budget["available_slots"]) <= 0:
                allow_slot_override = True

        return {
            "budget_cap": max(base_cap, 0.0),
            "global_remaining_budget": max(global_remaining, 0.0),
            "borrowed_budget": max(borrowed_budget, 0.0),
            "allow_slot_override": 1.0 if allow_slot_override else 0.0,
        }

    def _market_regime_profile(self, df: pd.DataFrame, market: str) -> Dict[str, Any]:
        closes = pd.to_numeric(df.get("close"), errors="coerce").dropna()
        highs = pd.to_numeric(df.get("high"), errors="coerce").dropna()
        lows = pd.to_numeric(df.get("low"), errors="coerce").dropna()
        trend, close, ema_now = self._infer_trend(df)
        if len(closes) < 8 or highs.empty or lows.empty:
            return {
                "regime": "transition",
                "trend": trend,
                "realized_volatility": 0.0,
                "efficiency_ratio": 0.0,
                "range_pct": 0.0,
                "close": close,
                "ema20": ema_now,
            }

        window = closes.tail(min(len(closes), 24))
        diff = window.diff().abs().dropna()
        net_move = abs(float(window.iloc[-1]) - float(window.iloc[0]))
        path_move = float(diff.sum() or 0.0)
        efficiency = net_move / max(path_move, 1e-6)
        realized_vol = float(closes.pct_change().abs().tail(min(len(closes) - 1, 20)).mean() or 0.0)
        recent_high = float(highs.tail(min(len(highs), 20)).max() or 0.0)
        recent_low = float(lows.tail(min(len(lows), 20)).min() or 0.0)
        range_pct = (recent_high - recent_low) / max(abs(close), 1e-6) if close else 0.0

        if market == "CRYPTO":
            trend_efficiency = 0.34
            bracket_efficiency = 0.18
            volatility_threshold = 0.009
            bracket_range_cap = 0.045
        else:
            trend_efficiency = 0.30
            bracket_efficiency = 0.16
            volatility_threshold = 0.0045
            bracket_range_cap = 0.022

        if trend in {"bullish", "bearish"} and efficiency >= trend_efficiency:
            regime = "trending"
        elif efficiency <= bracket_efficiency and range_pct <= max(volatility_threshold * 4.0, bracket_range_cap):
            regime = "bracketing"
        elif realized_vol >= volatility_threshold:
            regime = "volatile"
        else:
            regime = "transition"

        return {
            "regime": regime,
            "trend": trend,
            "realized_volatility": round(realized_vol, 6),
            "efficiency_ratio": round(efficiency, 4),
            "range_pct": round(range_pct, 4),
            "close": round(close, 4),
            "ema20": round(ema_now, 4),
        }

    @staticmethod
    def _signal_conviction_score(signal: Signal) -> float:
        metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        for key in ("trade_priority_score", "conviction_score", "conviction"):
            try:
                value = float(metadata.get(key, 0.0))
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        strength_defaults = {
            SignalStrength.WEAK.value: 52.0,
            SignalStrength.MODERATE.value: 68.0,
            SignalStrength.STRONG.value: 84.0,
        }
        return strength_defaults.get(signal.strength.value, 60.0)

    def _market_scoped_reward(self, strategy: str, market: str | None) -> tuple[float, int, float]:
        market_key = str(market or "").strip().upper()
        global_reward = float(self._strategy_reward_ema.get(strategy, 0.0))
        global_trades = int(self._strategy_perf_tracker.get_trade_count(strategy))
        if not market_key:
            return global_reward, global_trades, global_reward

        market_reward = self._strategy_market_reward_ema.get(strategy, {}).get(market_key)
        market_trades = int(
            self._strategy_perf_tracker.get_trade_count(strategy, market=market_key, prefer_market=True)
        )
        if market_reward is None or market_trades <= 0:
            return global_reward, global_trades, global_reward

        if market_trades >= 12:
            blended = (market_reward * 0.8) + (global_reward * 0.2)
        elif market_trades >= 5:
            blended = (market_reward * 0.6) + (global_reward * 0.4)
        else:
            blended = (market_reward * 0.35) + (global_reward * 0.65)
        return blended, market_trades, market_reward

    def _bootstrap_market_learning_state(self) -> None:
        seeded_trades: list[tuple[str, str, float]] = []
        for trade in self.position_manager.get_closed_trades():
            symbol = str(trade.get("symbol") or "").strip()
            strategy = self._normalize_strategy_tag(trade.get("strategy_tag"))
            market = self._symbol_market(symbol)
            entry_price = float(trade.get("entry_price") or 0.0)
            quantity = int(trade.get("quantity") or 0)
            pnl = float(trade.get("pnl") or 0.0)
            entry_notional = entry_price * max(quantity, 0)
            if not strategy or entry_notional <= 0:
                continue
            pnl_pct = (pnl / entry_notional) * 100.0
            seeded_trades.append((strategy, market, pnl_pct))
        if not seeded_trades:
            return
        self._strategy_perf_tracker.seed_market_stats(seeded_trades)

    def _strategy_market_fit_score(
        self,
        strategy: str,
        signal: Signal,
        market: str,
        execution_timeframe: str,
        regime_meta: Dict[str, Any],
    ) -> float:
        metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        regime = str(regime_meta.get("regime", "transition"))
        setup_type = str(metadata.get("setup_type", "") or "")
        value_acceptance = str(metadata.get("value_acceptance", "") or "")
        conviction = self._signal_conviction_score(signal)

        if strategy == "Fractal_Profile_Breakout":
            score = 0.0
            if market in {"NSE", "US"}:
                if regime == "trending":
                    score += 6.0
                elif regime == "bracketing":
                    score -= 10.0
                if setup_type == "acceptance_trend":
                    score += 5.0
                elif setup_type == "gap_and_go" and market == "US":
                    score += 3.0
                if value_acceptance == "accepted":
                    score += 2.0
            elif market == "CRYPTO":
                if regime == "bracketing":
                    score -= 12.0
                if setup_type != "acceptance_trend":
                    score -= 5.0
                if value_acceptance in {"balanced", "mixed"}:
                    score -= 4.0
                if conviction < 78.0:
                    score -= 8.0
            return score

        if strategy == "MP_OrderFlow_Breakout":
            if market == "CRYPTO":
                if conviction >= 78.0 and regime in {"trending", "volatile"}:
                    return 4.0
                if regime == "bracketing":
                    return -8.0
                if conviction < 70.0:
                    return -6.0
                return -2.0
            if market in {"NSE", "US"} and regime == "trending":
                return 3.0

        return 0.0

    def _signal_priority_score(
        self,
        strategy: str,
        signal: Signal,
        execution_timeframe: str,
        regime_meta: Dict[str, Any],
    ) -> float:
        metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        conviction = self._signal_conviction_score(signal)
        market = str(metadata.get("market") or self._symbol_market(signal.symbol or "")).upper()
        reward, market_reward_samples, raw_market_reward = self._market_scoped_reward(strategy, market)
        reward_component = max(min(reward, 12.0), -12.0)

        tf_token = str(execution_timeframe or metadata.get("execution_timeframe") or "").strip().upper()
        regime = str(regime_meta.get("regime", "transition"))
        timeframe_fit = 1.0
        if strategy == "Fractal_Profile_Breakout":
            # Fractal always runs on 3m but its conviction already encodes daily
            # profile context — do not penalise for short timeframe, and give a
            # small edge in all regimes to encourage execution on valid setups.
            timeframe_fit = 1.10
        elif strategy == "MP_OrderFlow_Breakout":
            # MP is designed for 3m–60m.  Honour the momentum of each timeframe.
            timeframe_fit = 1.12 if tf_token in {"5", "15"} else 1.06 if tf_token in {"3", "60"} else 0.90
        elif regime == "trending":
            timeframe_fit = 1.14 if tf_token in {"15", "30", "60", "D"} else 1.0 if tf_token == "5" else 0.72
        elif regime == "bracketing":
            timeframe_fit = 1.12 if tf_token == "5" else 1.04 if tf_token == "3" else 0.78
        elif regime == "volatile":
            timeframe_fit = 1.08 if tf_token in {"15", "5"} else 0.84

        # Conviction from strategy metadata (both Fractal and MP expose this).
        conviction_from_meta = float(metadata.get("conviction_score", 0) or 0)
        conviction_meta_bonus = 8.0 if conviction_from_meta >= 78 else 4.0 if conviction_from_meta >= 65 else 0.0

        reference_meta = metadata.get("reference_timeframe_bias", {})
        vote_component = 0.0
        if isinstance(reference_meta, dict):
            bullish_votes = int(reference_meta.get("bullish_votes", 0) or 0)
            bearish_votes = int(reference_meta.get("bearish_votes", 0) or 0)
            vote_advantage = (
                bullish_votes - bearish_votes
                if signal.signal_type == SignalType.BUY
                else bearish_votes - bullish_votes
            )
            if vote_advantage >= 2:
                vote_component = 8.0
            elif vote_advantage == 1:
                vote_component = 4.0
            elif vote_advantage < 0:
                vote_component = -10.0

        rr_component = 0.0
        try:
            adaptive_rr = float(metadata.get("adaptive_risk_reward", 0.0))
        except (TypeError, ValueError):
            adaptive_rr = 0.0
        if adaptive_rr >= 2.5:
            rr_component = 4.0
        elif adaptive_rr >= 2.0:
            rr_component = 2.0

        if metadata.get("bootstrap_exploration"):
            rr_component -= 10.0

        market_fit_component = self._strategy_market_fit_score(
            strategy,
            signal,
            market,
            execution_timeframe,
            regime_meta,
        )
        if market_reward_samples >= 8:
            reward_component += max(min(raw_market_reward, 8.0), -8.0) * 0.15

        score = (
            (conviction * timeframe_fit)
            + reward_component
            + vote_component
            + rr_component
            + conviction_meta_bonus
            + market_fit_component
        )
        return max(0.0, min(score, 100.0))

    @staticmethod
    def _trade_priority_threshold(
        market: str,
        execution_timeframe: str,
        regime_meta: Dict[str, Any],
    ) -> float:
        tf_token = str(execution_timeframe or "").strip().upper()
        regime = str(regime_meta.get("regime", "transition"))
        threshold = 58.0
        if market in {"NSE", "US"}:
            threshold += 4.0
        if regime == "trending":
            threshold += 10.0 if tf_token == "3" else -4.0 if tf_token in {"15", "30", "60", "D"} else 0.0
        elif regime == "bracketing":
            threshold += 8.0 if tf_token in {"15", "30", "60", "D"} else -3.0 if tf_token == "5" else 0.0
        elif regime == "volatile":
            threshold += 6.0 if tf_token == "3" else -2.0 if tf_token == "15" else 0.0
        if market == "CRYPTO":
            threshold += 2.0
        return max(48.0, min(threshold, 78.0))

    @staticmethod
    def _max_candidates_per_symbol(market: str, regime_meta: Dict[str, Any]) -> int:
        regime = str(regime_meta.get("regime", "transition"))
        if regime == "trending":
            return 2 if market == "CRYPTO" else 1
        if regime == "volatile":
            return 2
        return 1

    def _position_size_multiplier(self, strategy: str, market: str | None = None) -> float:
        if not self.config.reinforcement_enabled:
            return 1.0
        reward, _, _ = self._market_scoped_reward(strategy, market)
        max_boost = max(self.config.reinforcement_size_boost_pct / 100.0, 0.0)
        if max_boost <= 0:
            return 1.0
        # Reward is in PnL% terms. Clamp to avoid unstable size jumps.
        adjustment = max(min(reward / 10.0, max_boost), -max_boost)
        return max(0.25, 1.0 + adjustment)

    def _market_condition_size_multiplier(
        self,
        signal: Signal,
        execution_timeframe: str | None,
    ) -> float:
        metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        multiplier = 1.0

        try:
            strategy_mult = float(metadata.get("position_size_multiplier", 1.0))
        except (TypeError, ValueError):
            strategy_mult = 1.0
        multiplier *= min(max(strategy_mult, 0.7), 1.4)

        try:
            conviction_score = float(metadata.get("conviction_score", 0.0))
        except (TypeError, ValueError):
            conviction_score = 0.0
        if conviction_score >= 84.0:
            multiplier *= 1.12
        elif conviction_score >= 72.0:
            multiplier *= 1.05
        elif conviction_score > 0 and conviction_score < 60.0:
            multiplier *= 0.88

        reference_meta = metadata.get("reference_timeframe_bias", {})
        if isinstance(reference_meta, dict):
            bullish_votes = int(reference_meta.get("bullish_votes", 0) or 0)
            bearish_votes = int(reference_meta.get("bearish_votes", 0) or 0)
            vote_advantage = (
                bullish_votes - bearish_votes
                if signal.signal_type == SignalType.BUY
                else bearish_votes - bullish_votes
            )
            if vote_advantage >= 2:
                multiplier *= 1.12
            elif vote_advantage == 1:
                multiplier *= 1.05
            elif vote_advantage < 0:
                multiplier *= 0.72

        tf_token = str(execution_timeframe or metadata.get("execution_timeframe") or "").strip().upper()
        if tf_token == "3":
            multiplier *= 0.92
        elif tf_token in {"15", "30", "60"}:
            multiplier *= 1.05

        market = self._symbol_market(signal.symbol or "")
        if market == "CRYPTO" and conviction_score < 70.0:
            multiplier *= 0.9
        if metadata.get("bootstrap_exploration"):
            multiplier *= 0.7

        return max(0.35, min(multiplier, 1.75))

    def _record_reinforcement(self, strategy: str, pnl_pct: float, market: str | None = None) -> None:
        if not self.config.reinforcement_enabled:
            return
        reward_ema, was_disabled, market_reward_ema = self._strategy_perf_tracker.record_trade(
            strategy,
            pnl_pct,
            market=market,
        )
        self._strategy_reward_ema[strategy] = reward_ema
        if market:
            market_key = str(market).strip().upper()
            self._strategy_market_reward_ema.setdefault(strategy, {})[market_key] = market_reward_ema
        self._strategy_reward_counts[strategy] = self._strategy_reward_counts.get(strategy, 0) + 1
        if was_disabled:
            logger.warning(
                "strategy_auto_disabled",
                strategy=strategy,
                sharpe=round(self._strategy_perf_tracker._stats[strategy].rolling_sharpe, 3),
            )

    def _resolve_lot_size(self, underlying_symbol: str) -> int:
        root = self._normalize_nse_underlying_root(underlying_symbol)
        if root:
            return max(int(get_lot_size(root)), 1)
        return 1

    @staticmethod
    def _normalize_option_iv(iv_raw: Any) -> float:
        try:
            iv = float(iv_raw)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(iv) or iv <= 0:
            return 0.0
        if iv > 1.0:
            iv /= 100.0
        return min(max(iv, 0.01), 3.0)

    @staticmethod
    def _option_mid_price(side: Dict[str, Any]) -> float:
        last = float(side.get("ltp") or 0.0)
        if last > 0:
            return last
        bid = float(side.get("bid") or 0.0)
        ask = float(side.get("ask") or 0.0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        return max(bid, ask, 0.0)

    def _select_liquid_option_side(
        self,
        strikes: List[Dict[str, Any]],
        side_key: str,
        spot: float,
    ) -> Optional[Dict[str, Any]]:
        best_row: Optional[Dict[str, Any]] = None
        best_score = float("inf")
        for row in strikes:
            strike = float(row.get("strike") or 0.0)
            if strike <= 0:
                continue
            side = row.get(side_key, {})
            if not isinstance(side, dict) or not str(side.get("symbol") or "").strip():
                continue
            ltp = self._option_mid_price(side)
            if ltp <= 0:
                continue
            bid = float(side.get("bid") or 0.0)
            ask = float(side.get("ask") or 0.0)
            distance = abs(strike - spot) if spot > 0 else 0.0
            spread_penalty = abs(ask - bid) if ask > 0 and bid > 0 else ltp * 0.05
            oi_penalty = 0.0 if float(side.get("oi") or 0.0) > 0 else 10_000.0
            volume_penalty = 0.0 if float(side.get("volume") or 0.0) > 0 else 1_000.0
            score = distance + spread_penalty + oi_penalty + volume_penalty
            if score < best_score:
                best_score = score
                best_row = row
        return best_row

    def _option_candidate_snapshot(
        self,
        *,
        side_key: str,
        option_type: str,
        row: Dict[str, Any] | None,
        expiry_iso: str,
        spot: float,
    ) -> Dict[str, Any] | None:
        if row is None:
            return None
        side = row.get(side_key, {})
        if not isinstance(side, dict):
            return None
        strike = float(row.get("strike") or 0.0)
        ltp = self._option_mid_price(side)
        if strike <= 0 or ltp <= 0:
            return None
        iv = self._normalize_option_iv(side.get("iv"))
        days_to_expiry = 0
        try:
            expiry_date = date.fromisoformat(expiry_iso)
            days_to_expiry = max((expiry_date - datetime.now(tz=IST).date()).days, 1)
        except ValueError:
            expiry_date = None
        greeks: Dict[str, Any] = {"delta": None, "gamma": None, "theta": None, "vega": None}
        if spot > 0 and iv > 0 and days_to_expiry > 0:
            try:
                greek_values = BlackScholes.calculate_greeks(
                    spot=spot,
                    strike=strike,
                    time_to_expiry=days_to_expiry / 365.0,
                    volatility=iv,
                    option_type=option_type,
                )
                greeks = {
                    "delta": round(float(greek_values.delta), 4),
                    "gamma": round(float(greek_values.gamma), 6),
                    "theta": round(float(greek_values.theta), 4),
                    "vega": round(float(greek_values.vega), 4),
                }
            except Exception:
                pass
        moneyness = None
        if spot > 0:
            moneyness = round(strike / spot, 4)
        return {
            "symbol": str(side.get("symbol") or ""),
            "strike": round(strike, 4),
            "expiry": expiry_iso,
            "ltp": round(ltp, 4),
            "bid": round(float(side.get("bid") or 0.0), 4),
            "ask": round(float(side.get("ask") or 0.0), 4),
            "oi": int(float(side.get("oi") or 0.0)),
            "oi_change": int(float(side.get("oich") or 0.0)),
            "volume": int(float(side.get("volume") or 0.0)),
            "iv": round(iv, 4) if iv > 0 else None,
            "moneyness": moneyness,
            **greeks,
        }

    async def _fetch_option_chain_payload(
        self,
        underlying_symbol: str,
        strike_count: int = 12,
        include_expiries: int = 2,
    ) -> Optional[Dict[str, Any]]:
        market = self._symbol_market(underlying_symbol)
        try:
            if market == "NSE":
                return await asyncio.to_thread(
                    self.options_service.get_canonical_chain,
                    underlying_symbol,
                    strike_count,
                    None,
                    include_expiries,
                )
            if market == "US":
                from src.api.routes.options import _fetch_us_option_chain_public

                return await _fetch_us_option_chain_public(
                    underlying_symbol,
                    strike_count,
                    include_expiries,
                )
            if market == "CRYPTO":
                from src.api.routes.options import _fetch_crypto_option_chain_public

                return await _fetch_crypto_option_chain_public(
                    underlying_symbol,
                    strike_count,
                    include_expiries,
                )
        except Exception as exc:
            logger.warning("option_chain_payload_error", symbol=underlying_symbol, error=str(exc))
        return None

    async def get_options_trade_analytics(
        self,
        underlying_symbol: str,
        signal_type: SignalType | None = None,
        spot_hint: float = 0.0,
    ) -> Dict[str, Any] | None:
        market = self._symbol_market(underlying_symbol)
        if market not in {"NSE", "US", "CRYPTO"}:
            return None

        chain = await self._fetch_option_chain_payload(underlying_symbol, strike_count=12, include_expiries=2)
        expiry_rows = chain.get("data", {}).get("expiryData", []) if isinstance(chain, dict) else []
        if not expiry_rows:
            return None

        block = expiry_rows[0]
        strikes = block.get("strikes", [])
        if not strikes:
            return None

        spot = float(block.get("spot") or 0.0)
        if spot <= 0 and spot_hint > 0:
            spot = float(spot_hint)
        expiry_iso = str(block.get("expiry") or "")
        call_ivs = [self._normalize_option_iv((row.get("ce") or {}).get("iv")) for row in strikes]
        put_ivs = [self._normalize_option_iv((row.get("pe") or {}).get("iv")) for row in strikes]
        call_ivs = [value for value in call_ivs if value > 0]
        put_ivs = [value for value in put_ivs if value > 0]
        total_call_oi = int(float(block.get("total_call_oi") or 0.0))
        total_put_oi = int(float(block.get("total_put_oi") or 0.0))
        call_oi_change = int(sum(float((row.get("ce") or {}).get("oich") or 0.0) for row in strikes))
        put_oi_change = int(sum(float((row.get("pe") or {}).get("oich") or 0.0) for row in strikes))
        max_call_row = max(strikes, key=lambda row: float((row.get("ce") or {}).get("oi") or 0.0), default=None)
        max_put_row = max(strikes, key=lambda row: float((row.get("pe") or {}).get("oi") or 0.0), default=None)
        atm_row = min(
            strikes,
            key=lambda row: abs(float(row.get("strike") or 0.0) - spot) if spot > 0 else float(row.get("strike") or 0.0),
        )
        call_candidate_row = self._select_liquid_option_side(strikes, "ce", spot)
        put_candidate_row = self._select_liquid_option_side(strikes, "pe", spot)
        suggested_side = "call" if signal_type == SignalType.BUY else "put" if signal_type == SignalType.SELL else "neutral"

        return {
            "market": market,
            "underlying_symbol": underlying_symbol,
            "fetched_at": chain.get("fetched_at"),
            "nearest_expiry": expiry_iso or None,
            "days_to_expiry": max((date.fromisoformat(expiry_iso) - datetime.now(tz=IST).date()).days, 1)
            if expiry_iso
            else None,
            "spot": round(spot, 4) if spot > 0 else None,
            "lot_size": self._resolve_lot_size(underlying_symbol),
            "pcr": round(float(block.get("pcr") or 0.0), 4),
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "call_oi_change": call_oi_change,
            "put_oi_change": put_oi_change,
            "avg_call_iv": round(sum(call_ivs) / len(call_ivs), 4) if call_ivs else None,
            "avg_put_iv": round(sum(put_ivs) / len(put_ivs), 4) if put_ivs else None,
            "max_call_oi_strike": round(float(max_call_row.get("strike") or 0.0), 4) if max_call_row else None,
            "max_put_oi_strike": round(float(max_put_row.get("strike") or 0.0), 4) if max_put_row else None,
            "atm_strike": round(float(atm_row.get("strike") or 0.0), 4),
            "atm_call": self._option_candidate_snapshot(
                side_key="ce",
                option_type="CE",
                row=atm_row,
                expiry_iso=expiry_iso,
                spot=spot,
            ),
            "atm_put": self._option_candidate_snapshot(
                side_key="pe",
                option_type="PE",
                row=atm_row,
                expiry_iso=expiry_iso,
                spot=spot,
            ),
            "bullish_call": self._option_candidate_snapshot(
                side_key="ce",
                option_type="CE",
                row=call_candidate_row,
                expiry_iso=expiry_iso,
                spot=spot,
            ),
            "bearish_put": self._option_candidate_snapshot(
                side_key="pe",
                option_type="PE",
                row=put_candidate_row,
                expiry_iso=expiry_iso,
                spot=spot,
            ),
            "suggested_side": suggested_side,
            "selected_contract": (
                self._option_candidate_snapshot(
                    side_key="ce",
                    option_type="CE",
                    row=call_candidate_row,
                    expiry_iso=expiry_iso,
                    spot=spot,
                )
                if signal_type == SignalType.BUY
                else self._option_candidate_snapshot(
                    side_key="pe",
                    option_type="PE",
                    row=put_candidate_row,
                    expiry_iso=expiry_iso,
                    spot=spot,
                )
                if signal_type == SignalType.SELL
                else None
            ),
            "chain_quality": block.get("quality", {}),
        }

    def _resolve_time_exit_minutes(self, execution_timeframe: str) -> int:
        base_minutes = max(int(self.config.option_time_exit_minutes), 1)
        tf_raw = str(execution_timeframe or "").strip().upper()
        if tf_raw.isdigit():
            tf_minutes = int(tf_raw)
            # Hold at least 3 bars on the execution timeframe.
            return max(base_minutes, tf_minutes * 3)
        return base_minutes

    def _upsert_option_exit_plan(
        self,
        symbol: str,
        underlying_symbol: str,
        strategy: str,
        quantity: int,
        execution_timeframe: str,
        entry_price: float,
        stop_loss: float,
        target: float,
        signal_id: str = "",
    ) -> None:
        now = datetime.now(tz=IST)
        minutes = self._resolve_time_exit_minutes(execution_timeframe)
        strategy_map = self._option_exit_plans.setdefault(symbol, {})
        existing = strategy_map.get(strategy)
        incoming_qty = max(int(quantity), 0)
        if existing is None:
            strategy_map[strategy] = OptionExitPlan(
                symbol=symbol,
                underlying_symbol=underlying_symbol,
                strategy=strategy,
                quantity=incoming_qty,
                execution_timeframe=execution_timeframe,
                entry_price=float(entry_price),
                stop_loss=float(stop_loss),
                target=float(target),
                opened_at=now,
                time_exit_at=now + timedelta(minutes=minutes),
                signal_id=signal_id,
            )
            self._persist_live_runtime_state()
            return

        previous_qty = max(int(existing.quantity), 0)
        total_qty = previous_qty + incoming_qty
        divisor = max(total_qty, 1)
        existing.quantity = total_qty
        existing.execution_timeframe = execution_timeframe
        existing.entry_price = (
            (float(existing.entry_price) * previous_qty)
            + (float(entry_price) * incoming_qty)
        ) / divisor
        existing.stop_loss = (
            (float(existing.stop_loss) * previous_qty)
            + (float(stop_loss) * incoming_qty)
        ) / divisor
        existing.target = (
            (float(existing.target) * previous_qty)
            + (float(target) * incoming_qty)
        ) / divisor
        existing.opened_at = min(existing.opened_at, now)
        existing.time_exit_at = max(existing.time_exit_at, now + timedelta(minutes=minutes))
        self._persist_live_runtime_state()

    @contextmanager
    def _temporary_risk_overrides(
        self,
        *,
        max_position_size: float,
        max_risk_per_trade_pct: float,
        max_open_positions: int,
        max_concentration_pct: float,
    ):
        cfg = self.risk_manager.config
        snapshot = (
            cfg.max_position_size,
            cfg.max_risk_per_trade_pct,
            cfg.max_open_positions,
            cfg.max_concentration_pct,
        )
        cfg.max_position_size = max(float(max_position_size), 1.0)
        cfg.max_risk_per_trade_pct = max(float(max_risk_per_trade_pct), 0.0001)
        cfg.max_open_positions = max(int(max_open_positions), 1)
        cfg.max_concentration_pct = min(max(float(max_concentration_pct), 0.01), 1.0)
        try:
            yield
        finally:
            (
                cfg.max_position_size,
                cfg.max_risk_per_trade_pct,
                cfg.max_open_positions,
                cfg.max_concentration_pct,
            ) = snapshot

    async def _resolve_option_contract(
        self,
        underlying_symbol: str,
        signal_type: SignalType,
        spot_hint: float = 0.0,
    ) -> Optional[OptionContract]:
        """Resolve nearest-liquid NSE index option contract."""
        option_type = "CE" if signal_type == SignalType.BUY else "PE"
        chain_side = "ce" if option_type == "CE" else "pe"
        cache_key = (underlying_symbol, option_type)
        now = datetime.now(tz=IST)
        cached = self._option_contract_cache.get(cache_key)
        if cached is not None:
            cached_at, contract = cached
            if now - cached_at <= self._option_contract_cache_ttl:
                return contract

        try:
            chain = await asyncio.to_thread(
                self.options_service.get_canonical_chain,
                underlying_symbol,
                10,
                None,
                1,
            )
        except Exception as exc:
            logger.warning("option_contract_resolve_error", underlying=underlying_symbol, error=str(exc))
            return None

        expiry_rows = chain.get("data", {}).get("expiryData", [])
        if not expiry_rows:
            return None

        best_contract: Optional[OptionContract] = None
        best_score = float("inf")
        lot_size = self._resolve_lot_size(underlying_symbol)
        for expiry_block in expiry_rows:
            expiry = str(expiry_block.get("expiry", ""))
            spot = float(expiry_block.get("spot") or 0.0)
            if spot <= 0 and spot_hint > 0:
                spot = spot_hint

            for strike_row in expiry_block.get("strikes", []):
                strike = float(strike_row.get("strike") or 0.0)
                if strike <= 0:
                    continue

                side_payload = strike_row.get(chain_side, {})
                option_symbol = str(side_payload.get("symbol") or "").strip()
                if not option_symbol:
                    continue

                ltp = float(side_payload.get("ltp") or 0.0)
                if ltp <= 0:
                    bid = float(side_payload.get("bid") or 0.0)
                    ask = float(side_payload.get("ask") or 0.0)
                    if bid > 0 and ask > 0:
                        ltp = (bid + ask) / 2.0
                    else:
                        ltp = max(bid, ask, 0.0)
                if ltp <= 0:
                    continue

                oi = int(float(side_payload.get("oi") or 0.0))
                volume = int(float(side_payload.get("volume") or 0.0))
                distance = abs(strike - spot) if spot > 0 else 0.0
                liquidity_penalty = 0.0
                if oi <= 0:
                    liquidity_penalty += 10_000.0
                if volume <= 0:
                    liquidity_penalty += 1_000.0
                score = distance + liquidity_penalty
                if score < best_score:
                    best_score = score
                    best_contract = OptionContract(
                        underlying_symbol=underlying_symbol,
                        option_symbol=option_symbol,
                        option_type=option_type,
                        strike=strike,
                        expiry=expiry,
                        ltp=ltp,
                        lot_size=lot_size,
                    )

        if best_contract is not None:
            self._option_contract_cache[cache_key] = (now, best_contract)

        return best_contract

    _US_OPTION_SYMBOL_RE = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")

    @classmethod
    def _parse_us_option_symbol(cls, contract_symbol: str) -> Optional[Dict[str, Any]]:
        token = str(contract_symbol or "").strip().upper()
        match = cls._US_OPTION_SYMBOL_RE.match(token)
        if match is None:
            return None
        root, yymmdd, cp_flag, strike_raw = match.groups()
        try:
            expiry = datetime.strptime(yymmdd, "%y%m%d").replace(tzinfo=timezone.utc)
            strike = int(strike_raw) / 1000.0
        except Exception:
            return None
        return {
            "root": root,
            "expiry": expiry,
            "expiry_unix": int(expiry.timestamp()),
            "option_type": "CALL" if cp_flag == "C" else "PUT",
            "strike": strike,
            "contract_symbol": token,
        }

    @staticmethod
    def _parse_nasdaq_number(value: Any) -> float:
        raw = str(value or "").strip().replace("$", "").replace(",", "").replace("%", "")
        if raw in {"", "--", "N/A", "None"}:
            return 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _parse_nasdaq_last_trade(last_trade: Any) -> float:
        text = str(last_trade or "")
        match = re.search(r"\$([0-9][0-9,]*(?:\.[0-9]+)?)", text)
        if match:
            return TradingAgent._parse_nasdaq_number(match.group(1))
        for token in re.findall(r"([0-9][0-9,]*(?:\.[0-9]+)?)", text):
            if "." not in token:
                continue
            price = TradingAgent._parse_nasdaq_number(token)
            if price > 0:
                return price
        return 0.0

    @staticmethod
    def _parse_nasdaq_expiry(expiry_raw: Any, fallback_year: Optional[int] = None) -> Optional[datetime]:
        text = str(expiry_raw or "").strip()
        if not text:
            return None

        parsed: Optional[datetime] = None
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%b %d", "%B %d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None

        if parsed.year == 1900:
            year = fallback_year or datetime.now(tz=IST).year
            parsed = parsed.replace(year=year)
            if parsed.date() < datetime.now(tz=IST).date() - timedelta(days=30):
                parsed = parsed.replace(year=year + 1)
        return parsed

    @staticmethod
    def _nasdaq_contract_symbol_from_drilldown(
        drilldown_url: Any,
        ticker: str,
        option_type: str,
    ) -> str:
        token = str(drilldown_url or "").strip()
        if not token:
            return ""
        suffix = token.rsplit("/", 1)[-1].split("---")[-1].upper()
        if re.fullmatch(r"[A-Z]{1,6}\d{6}[CP]\d{8}", suffix):
            return suffix
        if re.fullmatch(r"\d{6}[CP]\d{8}", suffix):
            return f"{ticker}{suffix}"
        # Sometimes the side can be missing in drilldown payload; force it.
        cp_flag = "C" if option_type == "CALL" else "P"
        if re.fullmatch(r"\d{6}\d{8}", suffix):
            return f"{ticker}{suffix[:6]}{cp_flag}{suffix[6:]}"
        return ""

    @staticmethod
    def _build_occ_option_symbol(ticker: str, expiry: datetime, option_type: str, strike: float) -> str:
        cp_flag = "C" if option_type == "CALL" else "P"
        strike_code = max(int(round(strike * 1000)), 1)
        return f"{ticker}{expiry.strftime('%y%m%d')}{cp_flag}{strike_code:08d}"

    async def _resolve_us_option_contract(
        self,
        underlying_symbol: str,
        signal_type: SignalType,
        spot_hint: float = 0.0,
    ) -> Optional[OptionContract]:
        """Resolve nearest-liquid US option contract from Yahoo options chain."""
        ticker = self._normalize_us_ticker(underlying_symbol)
        if not ticker:
            return None

        option_type = "CALL" if signal_type == SignalType.BUY else "PUT"
        cache_key = (f"US:{ticker}", option_type)
        now = datetime.now(tz=IST)
        cached = self._option_contract_cache.get(cache_key)
        if cached is not None:
            cached_at, contract = cached
            if now - cached_at <= self._option_contract_cache_ttl:
                return contract

        timeout = httpx.Timeout(8.0, connect=4.0)
        endpoint = f"https://query2.finance.yahoo.com/v7/finance/options/{ticker}"
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=_YAHOO_HEADERS) as http:
                res = await http.get(endpoint)
                if res.status_code >= 400:
                    return await self._resolve_us_option_contract_nasdaq(
                        underlying_symbol=underlying_symbol,
                        signal_type=signal_type,
                        spot_hint=spot_hint,
                    )
                payload = res.json()
        except Exception as exc:
            logger.warning("us_option_contract_resolve_error", underlying=underlying_symbol, error=str(exc))
            return await self._resolve_us_option_contract_nasdaq(
                underlying_symbol=underlying_symbol,
                signal_type=signal_type,
                spot_hint=spot_hint,
            )

        chain = payload.get("optionChain", {}) if isinstance(payload, dict) else {}
        results = chain.get("result", []) if isinstance(chain, dict) else []
        if not results:
            return None
        result = results[0] if isinstance(results[0], dict) else {}

        quote = result.get("quote", {}) if isinstance(result, dict) else {}
        spot = float(quote.get("regularMarketPrice") or 0.0)
        if spot <= 0 and spot_hint > 0:
            spot = spot_hint

        options_blocks = result.get("options", []) if isinstance(result, dict) else []
        expiry_dates = result.get("expirationDates", []) if isinstance(result, dict) else []
        option_rows: List[Dict[str, Any]] = []

        if options_blocks and isinstance(options_blocks[0], dict):
            side_key = "calls" if option_type == "CALL" else "puts"
            option_rows = [
                row for row in options_blocks[0].get(side_key, [])
                if isinstance(row, dict)
            ]

        # If the default payload omitted the desired side, fetch the nearest expiry explicitly.
        if not option_rows and expiry_dates:
            nearest_expiry = None
            for raw_expiry in expiry_dates:
                try:
                    expiry_ts = int(raw_expiry)
                except (TypeError, ValueError):
                    continue
                if nearest_expiry is None:
                    nearest_expiry = expiry_ts
                if expiry_ts >= int(datetime.now(tz=timezone.utc).timestamp()):
                    nearest_expiry = expiry_ts
                    break
            if nearest_expiry is not None:
                try:
                    async with httpx.AsyncClient(timeout=timeout) as http:
                        res = await http.get(endpoint, params={"date": nearest_expiry})
                        if res.status_code < 400:
                            payload = res.json()
                            chain = payload.get("optionChain", {}) if isinstance(payload, dict) else {}
                            results = chain.get("result", []) if isinstance(chain, dict) else []
                            if results and isinstance(results[0], dict):
                                blocks = results[0].get("options", [])
                                if blocks and isinstance(blocks[0], dict):
                                    side_key = "calls" if option_type == "CALL" else "puts"
                                    option_rows = [
                                        row for row in blocks[0].get(side_key, [])
                                        if isinstance(row, dict)
                                    ]
                except Exception as exc:
                    logger.warning(
                        "us_option_contract_expiry_fetch_failed",
                        underlying=underlying_symbol,
                        error=str(exc),
                    )

        if not option_rows:
            return await self._resolve_us_option_contract_nasdaq(
                underlying_symbol=underlying_symbol,
                signal_type=signal_type,
                spot_hint=spot_hint,
            )

        best_contract: Optional[OptionContract] = None
        best_score = float("inf")
        for row in option_rows:
            strike = float(row.get("strike") or 0.0)
            if strike <= 0:
                continue
            contract_symbol = str(row.get("contractSymbol") or "").strip().upper()
            if not contract_symbol:
                continue
            ltp = float(row.get("lastPrice") or 0.0)
            if ltp <= 0:
                bid = float(row.get("bid") or 0.0)
                ask = float(row.get("ask") or 0.0)
                if bid > 0 and ask > 0:
                    ltp = (bid + ask) / 2.0
                else:
                    ltp = max(bid, ask, 0.0)
            if ltp <= 0:
                continue

            oi = int(float(row.get("openInterest") or 0.0))
            volume = int(float(row.get("volume") or 0.0))
            distance = abs(strike - spot) if spot > 0 else 0.0
            liquidity_penalty = 0.0
            if oi <= 0:
                liquidity_penalty += 10_000.0
            if volume <= 0:
                liquidity_penalty += 1_000.0
            score = distance + liquidity_penalty
            if score < best_score:
                best_score = score
                parsed = self._parse_us_option_symbol(contract_symbol)
                expiry_label = (
                    parsed["expiry"].astimezone(timezone.utc).strftime("%Y-%m-%d")
                    if parsed is not None
                    else datetime.utcfromtimestamp(int(row.get("expiration") or 0)).strftime("%Y-%m-%d")
                    if row.get("expiration")
                    else ""
                )
                best_contract = OptionContract(
                    underlying_symbol=underlying_symbol,
                    option_symbol=f"US:{contract_symbol}",
                    option_type=option_type,
                    strike=strike,
                    expiry=expiry_label,
                    ltp=ltp,
                    lot_size=100,
                )

        if best_contract is not None:
            self._option_contract_cache[cache_key] = (now, best_contract)
            return best_contract
        return await self._resolve_us_option_contract_nasdaq(
            underlying_symbol=underlying_symbol,
            signal_type=signal_type,
            spot_hint=spot_hint,
        )

    async def _resolve_us_option_contract_nasdaq(
        self,
        underlying_symbol: str,
        signal_type: SignalType,
        spot_hint: float = 0.0,
    ) -> Optional[OptionContract]:
        """Resolve US options using Nasdaq option chain when Yahoo is unavailable."""
        ticker = self._normalize_us_ticker(underlying_symbol)
        if not ticker:
            return None
        option_type = "CALL" if signal_type == SignalType.BUY else "PUT"
        cache_key = (f"US:{ticker}", option_type)
        now = datetime.now(tz=IST)
        cached = self._option_contract_cache.get(cache_key)
        if cached is not None:
            cached_at, contract = cached
            if now - cached_at <= self._option_contract_cache_ttl:
                return contract

        timeout = httpx.Timeout(10.0, connect=4.0)
        endpoint = f"https://api.nasdaq.com/api/quote/{ticker}/option-chain"
        payload: dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=_NASDAQ_HEADERS) as http:
                for assetclass in (
                    "etf" if ticker in _US_ETF_TICKERS else "stocks",
                    "stocks",
                    "etf",
                ):
                    res = await http.get(endpoint, params={"assetclass": assetclass})
                    if res.status_code >= 400:
                        continue
                    raw = res.json()
                    data = raw.get("data", {}) if isinstance(raw, dict) else {}
                    if isinstance(data, dict) and data:
                        payload = raw
                        break
        except Exception as exc:
            logger.warning("us_option_contract_nasdaq_error", underlying=underlying_symbol, error=str(exc))
            return None

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict) or not data:
            return None

        spot = float(spot_hint)
        if spot <= 0:
            spot = self._parse_nasdaq_last_trade(data.get("lastTrade"))
        if spot <= 0:
            primary = data.get("primaryData", {}) if isinstance(data.get("primaryData"), dict) else {}
            spot = self._parse_nasdaq_number(primary.get("lastSalePrice"))

        table = data.get("table", {}) if isinstance(data.get("table"), dict) else {}
        rows = table.get("rows", []) if isinstance(table.get("rows"), list) else []
        if not rows:
            return None

        best_contract: Optional[OptionContract] = None
        best_score = float("inf")
        group_expiry: Optional[datetime] = None
        side_prefix = "c_" if option_type == "CALL" else "p_"
        for row in rows:
            if not isinstance(row, dict):
                continue

            strike = self._parse_nasdaq_number(row.get("strike"))
            if strike <= 0:
                group_candidate = self._parse_nasdaq_expiry(row.get("expirygroup"))
                if group_candidate is not None:
                    group_expiry = group_candidate
                continue

            expiry = self._parse_nasdaq_expiry(
                row.get("expiryDate"),
                fallback_year=(group_expiry.year if group_expiry is not None else None),
            )
            if expiry is None:
                expiry = group_expiry
            if expiry is None:
                continue

            last = self._parse_nasdaq_number(row.get(f"{side_prefix}Last"))
            bid = self._parse_nasdaq_number(row.get(f"{side_prefix}Bid"))
            ask = self._parse_nasdaq_number(row.get(f"{side_prefix}Ask"))
            ltp = last if last > 0 else ((bid + ask) / 2.0 if bid > 0 and ask > 0 else max(bid, ask, 0.0))
            if ltp <= 0:
                continue

            oi = int(self._parse_nasdaq_number(row.get(f"{side_prefix}Openinterest")))
            volume = int(self._parse_nasdaq_number(row.get(f"{side_prefix}Volume")))
            distance = abs(strike - spot) if spot > 0 else 0.0
            dte_penalty = max((expiry.date() - datetime.now(tz=IST).date()).days, 0) * 0.20
            liquidity_penalty = 0.0
            if oi <= 0:
                liquidity_penalty += 10_000.0
            if volume <= 0:
                liquidity_penalty += 1_000.0
            score = distance + dte_penalty + liquidity_penalty
            if score >= best_score:
                continue

            contract_symbol = self._nasdaq_contract_symbol_from_drilldown(
                row.get("drillDownURL"),
                ticker=ticker,
                option_type=option_type,
            )
            if not contract_symbol:
                contract_symbol = self._build_occ_option_symbol(
                    ticker=ticker,
                    expiry=expiry,
                    option_type=option_type,
                    strike=strike,
                )

            best_score = score
            best_contract = OptionContract(
                underlying_symbol=underlying_symbol,
                option_symbol=f"US:{contract_symbol}",
                option_type=option_type,
                strike=strike,
                expiry=expiry.strftime("%Y-%m-%d"),
                ltp=ltp,
                lot_size=100,
            )

        if best_contract is not None:
            self._option_contract_cache[cache_key] = (now, best_contract)
        return best_contract

    # ------------------------------------------------------------------
    # Data Fetching
    # ------------------------------------------------------------------

    def _session_snapshot(self) -> Dict[str, bool]:
        now = datetime.now(tz=IST)
        return {
            "nse": is_market_open(now),
            "us": is_us_market_open(now),
            "crypto": True,  # Crypto market is 24x7.
        }

    @staticmethod
    def _dedupe_symbols(symbols: List[str]) -> List[str]:
        ordered: List[str] = []
        seen: set[str] = set()
        for symbol in symbols:
            token = str(symbol or "").strip()
            if not token:
                continue
            if token in seen:
                continue
            seen.add(token)
            ordered.append(token)
        return ordered

    def _configured_symbol_universe(self) -> List[str]:
        return self._dedupe_symbols(
            self.config.symbols + self.config.us_symbols + self.config.crypto_symbols
        )

    @staticmethod
    def _normalize_us_ticker(symbol: str) -> str:
        return str(symbol or "").split(":")[-1].strip().upper()

    @staticmethod
    def _normalize_crypto_pair(symbol: str) -> str:
        pair = str(symbol or "").split(":")[-1].strip().upper()
        pair = pair.replace("/", "").replace("-", "")
        if pair.endswith("USD") and not pair.endswith("USDT"):
            pair = f"{pair}T"
        if pair.isalpha() and len(pair) <= 6:
            pair = f"{pair}USDT"
        return pair

    def _symbol_market(self, symbol: str) -> str:
        token = str(symbol or "").strip().upper()
        if not token:
            return "NSE"
        if token.startswith("CRYPTO:"):
            return "CRYPTO"
        if token.startswith(("US:", "NASDAQ:", "NYSE:", "AMEX:")):
            return "US"
        if token.startswith("NSE:") or token.endswith("-INDEX"):
            return "NSE"
        if token.endswith("USDT") and ":" not in token:
            return "CRYPTO"

        us_roots = {self._normalize_us_ticker(s) for s in self.config.us_symbols}
        crypto_roots = {self._normalize_crypto_pair(s) for s in self.config.crypto_symbols}
        if self._normalize_us_ticker(token) in us_roots:
            return "US"
        if self._normalize_crypto_pair(token) in crypto_roots:
            return "CRYPTO"
        return "NSE"

    def _resolve_active_symbols(
        self,
        sessions: Dict[str, bool],
        readiness: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[str]:
        active: List[str] = []
        for symbol in self._configured_symbol_universe():
            market = self._symbol_market(symbol)
            market_ready = True
            if readiness is not None:
                market_ready = bool(readiness.get(market, {}).get("ready", True))
            if market == "NSE" and self.config.trade_nse_when_open and sessions.get("nse", False):
                if market_ready:
                    active.append(symbol)
            elif market == "US" and self.config.trade_us_when_open and sessions.get("us", False):
                if market_ready:
                    active.append(symbol)
            elif market == "CRYPTO" and self.config.trade_crypto_24x7 and sessions.get("crypto", False):
                if market_ready:
                    active.append(symbol)
        return active

    async def _compute_market_readiness(self, sessions: Dict[str, bool]) -> Dict[str, Dict[str, Any]]:
        """Compute tradability readiness per market for the current cycle."""
        readiness: Dict[str, Dict[str, Any]] = {}

        # NSE readiness depends on auth when market session is open.
        nse_enabled = bool(self.config.trade_nse_when_open and self.config.symbols)
        nse_open = bool(sessions.get("nse", False))
        nse_auth = bool(getattr(self.fyers_client, "is_authenticated", False))
        auto_refreshed = False
        if nse_enabled and nse_open and not nse_auth:
            refresh_fn = getattr(self.fyers_client, "try_auto_refresh_with_saved_pin", None)
            if callable(refresh_fn):
                try:
                    auto_refreshed = bool(await asyncio.to_thread(refresh_fn, False))
                    nse_auth = bool(getattr(self.fyers_client, "is_authenticated", False))
                except Exception as exc:
                    logger.warning("nse_readiness_refresh_error", error=str(exc))
        nse_ready = (not nse_enabled) or (not nse_open) or nse_auth
        if not nse_enabled:
            nse_reason = "disabled"
        elif not nse_open:
            nse_reason = "session_closed"
        elif nse_auth:
            nse_reason = "authenticated"
        else:
            nse_reason = "broker_auth_unavailable"
        readiness["NSE"] = {
            "enabled": nse_enabled,
            "session_open": nse_open,
            "ready": nse_ready,
            "reason": nse_reason,
            "auto_refreshed": auto_refreshed,
        }

        us_enabled = bool(self.config.trade_us_when_open and self.config.us_symbols)
        us_open = bool(sessions.get("us", False))
        us_ready = (not us_enabled) or (not us_open) or bool(self.config.us_symbols)
        if not us_enabled:
            us_reason = "disabled"
        elif not us_open:
            us_reason = "session_closed"
        elif self.config.us_symbols:
            us_reason = "provider_fallback_enabled"
        else:
            us_reason = "no_symbols"
        readiness["US"] = {
            "enabled": us_enabled,
            "session_open": us_open,
            "ready": us_ready,
            "reason": us_reason,
        }

        crypto_enabled = bool(self.config.trade_crypto_24x7 and self.config.crypto_symbols)
        crypto_open = bool(sessions.get("crypto", False))
        crypto_ready = (not crypto_enabled) or (not crypto_open) or bool(self.config.crypto_symbols)
        if not crypto_enabled:
            crypto_reason = "disabled"
        elif not crypto_open:
            crypto_reason = "session_closed"
        elif self.config.crypto_symbols:
            crypto_reason = "binance_feed_enabled"
        else:
            crypto_reason = "no_symbols"
        readiness["CRYPTO"] = {
            "enabled": crypto_enabled,
            "session_open": crypto_open,
            "ready": crypto_ready,
            "reason": crypto_reason,
        }

        return readiness

    async def _emit_readiness_events(self, readiness: Dict[str, Dict[str, Any]]) -> None:
        """Emit one-shot readiness transition events for tradable sessions."""
        for market in ("NSE", "US", "CRYPTO"):
            payload = readiness.get(market, {})
            enabled = bool(payload.get("enabled", False))
            session_open = bool(payload.get("session_open", False))
            ready = bool(payload.get("ready", False))

            # Alert only when this market is expected to trade now.
            if not enabled or not session_open:
                self._readiness_notified[market] = False
                continue

            if ready:
                if self._readiness_notified.get(market, False):
                    await self.event_bus.emit(AgentEvent(
                        event_type=AgentEventType.RISK_CHECK_PASSED,
                        title=f"{market} Ready",
                        message=f"{market} market is tradable again.",
                        severity="success",
                        metadata={"market": market, **payload},
                    ))
                self._readiness_notified[market] = False
                continue

            if not self._readiness_notified.get(market, False):
                await self.event_bus.emit(AgentEvent(
                    event_type=AgentEventType.RISK_CHECK_FAILED,
                    title=f"{market} Not Ready",
                    message=(
                        f"{market} session is open but trading is blocked "
                        f"({payload.get('reason', 'unknown')})."
                    ),
                    severity="warning",
                    metadata={"market": market, **payload},
                ))
                self._readiness_notified[market] = True

    async def _fetch_market_data_from_memory(
        self,
        symbol: str,
        timeframe: str,
    ) -> Optional[pd.DataFrame]:
        from src.data.ohlc_cache import get_ohlc_cache

        tf = str(timeframe or self.config.timeframe).strip().upper()
        now = datetime.now(tz=IST)
        require_live_bars = self._requires_live_bars(self._symbol_market(symbol), tf, now)
        stale_candidate: Optional[pd.DataFrame] = None

        def remember_stale(frame: Optional[pd.DataFrame]) -> None:
            nonlocal stale_candidate
            if frame is None or frame.empty or "timestamp" not in frame.columns:
                return
            if stale_candidate is None:
                stale_candidate = frame.copy(deep=False)
                return
            candidate_ts = self._coerce_ist_timestamp(frame["timestamp"].iloc[-1])
            existing_ts = self._coerce_ist_timestamp(stale_candidate["timestamp"].iloc[-1])
            if candidate_ts is not None and (existing_ts is None or candidate_ts > existing_ts):
                stale_candidate = frame.copy(deep=False)

        cache = get_ohlc_cache()
        cached = cache.as_dataframe(symbol, tf, limit=500)
        if not cached.empty:
            df_cached = cached.reset_index()
            if "timestamp" not in df_cached.columns and "index" in df_cached.columns:
                df_cached = df_cached.rename(columns={"index": "timestamp"})
            df_cached["symbol"] = symbol
            fresh, _ = self._data_freshness(df_cached, tf)
            if fresh:
                self._market_data_cache[(symbol, tf)] = (now, df_cached)
                return df_cached
            if not require_live_bars:
                remember_stale(df_cached)

        cache_key = (symbol, tf)
        local_cached = self._market_data_cache.get(cache_key)
        if local_cached is not None:
            _, cached_df = local_cached
            fresh, _ = self._data_freshness(cached_df, tf)
            if fresh:
                return cached_df.copy(deep=False)
            if not require_live_bars:
                remember_stale(cached_df)

        return stale_candidate.copy(deep=False) if stale_candidate is not None else None

    async def _fetch_market_data(
        self,
        symbol: str,
        timeframe: Optional[str] = None,
        *,
        live_only: bool = False,
    ) -> Optional[pd.DataFrame]:
        """Fetch recent OHLC candles for NSE/US/Crypto symbols."""
        tf = str(timeframe or self.config.timeframe).strip().upper()
        market = self._symbol_market(symbol)
        with self._latency_tracker.track(
            "market_data_fetch_ms",
            symbol=symbol,
            market=market,
            timeframe=tf,
        ):
            try:
                memory_frame = await self._fetch_market_data_from_memory(symbol, tf)
                if memory_frame is not None and not memory_frame.empty:
                    fresh, _ = self._data_freshness(memory_frame, tf)
                    if fresh:
                        return memory_frame
                if live_only and self._event_driven_hot_path_timeframe_supported(tf):
                    return memory_frame

                now = datetime.now(tz=IST)
                require_live_bars = self._requires_live_bars(market, tf, now)
                stale_candidate = memory_frame.copy(deep=False) if memory_frame is not None else None

                # In-process cache to avoid repeated external API fetches
                # within a single scan cycle across strategies/timeframes.
                cache_key = (symbol, tf)
                local_cached = self._market_data_cache.get(cache_key)
                if local_cached is not None:
                    cached_at, cached_df = local_cached
                    if now - cached_at <= self._market_data_cache_ttl:
                        fresh, _ = self._data_freshness(cached_df, tf)
                        if fresh:
                            return cached_df.copy(deep=False)
                        if not require_live_bars and stale_candidate is None:
                            stale_candidate = cached_df.copy(deep=False)

                # TimescaleDB fallback before external broker calls. This reduces
                # FYERS rate pressure during live NSE sessions if the background
                # collectors already persisted the latest bars.
                db_df = await self._fetch_database_market_data(symbol, tf)
                if db_df is not None and not db_df.empty:
                    fresh, _ = self._data_freshness(db_df, tf)
                    if fresh:
                        self._market_data_cache[cache_key] = (now, db_df)
                        return db_df
                    if not require_live_bars:
                        if stale_candidate is None:
                            stale_candidate = db_df.copy(deep=False)
                        else:
                            candidate_ts = self._coerce_ist_timestamp(db_df["timestamp"].iloc[-1])
                            existing_ts = self._coerce_ist_timestamp(stale_candidate["timestamp"].iloc[-1])
                            if candidate_ts is not None and (existing_ts is None or candidate_ts > existing_ts):
                                stale_candidate = db_df.copy(deep=False)

                # Market-specific primary source.
                if market == "US":
                    us_df = await self._fetch_us_market_data(symbol, tf)
                    if us_df is not None and not us_df.empty:
                        self._market_data_cache[cache_key] = (now, us_df)
                        return us_df
                elif market == "CRYPTO":
                    crypto_df = await self._fetch_crypto_market_data(symbol, tf)
                    if crypto_df is not None and not crypto_df.empty:
                        self._market_data_cache[cache_key] = (now, crypto_df)
                        return crypto_df

                # Broker fallback (NSE + any symbol supported by broker).
                fyers_df = await self._fetch_fyers_market_data(symbol, tf)
                if fyers_df is not None and not fyers_df.empty:
                    self._market_data_cache[cache_key] = (now, fyers_df)
                    return fyers_df

                # Last fallback for US/crypto in case primary source failed transiently.
                if market == "US":
                    us_df = await self._fetch_us_market_data(symbol, tf)
                    if us_df is not None and not us_df.empty:
                        self._market_data_cache[cache_key] = (now, us_df)
                        return us_df
                    return stale_candidate.copy(deep=False) if stale_candidate is not None else None
                if market == "CRYPTO":
                    crypto_df = await self._fetch_crypto_market_data(symbol, tf)
                    if crypto_df is not None and not crypto_df.empty:
                        self._market_data_cache[cache_key] = (now, crypto_df)
                        return crypto_df
                    return stale_candidate.copy(deep=False) if stale_candidate is not None else None
                if stale_candidate is not None:
                    self._market_data_cache[cache_key] = (now, stale_candidate)
                    return stale_candidate.copy(deep=False)
                return None
            except Exception as e:
                logger.warning("fetch_market_data_error", symbol=symbol, timeframe=tf, error=str(e))
                return None

    def _requires_live_bars(self, market: str, timeframe: str, now: Optional[datetime] = None) -> bool:
        token = str(timeframe or "").strip().upper()
        if token in {"D", "W", "M"}:
            return False

        current = now or datetime.now(tz=IST)
        market_key = str(market or "").upper()
        if market_key == "NSE":
            return is_market_open(current)
        if market_key == "US":
            return is_us_market_open(current)
        if market_key == "CRYPTO":
            return True
        return False

    async def _fetch_database_market_data(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Load recent candles from TimescaleDB when available."""
        try:
            from src.database.connection import get_session
            from src.database.operations import get_ohlc_candles

            token = str(timeframe or "").strip().upper()
            days_back = {
                "1": 7,
                "3": 14,
                "5": 21,
                "15": 45,
                "30": 60,
                "60": 90,
                "D": 365,
                "W": 730,
                "M": 1825,
            }.get(token, 30)
            end = datetime.now(tz=timezone.utc).replace(tzinfo=None)
            start = (datetime.now(tz=timezone.utc) - timedelta(days=days_back)).replace(tzinfo=None)

            async with get_session() as session:
                rows = await get_ohlc_candles(
                    session,
                    symbol,
                    token,
                    start,
                    end,
                    limit=500,
                )

            if not rows:
                return None

            payload: List[Dict[str, Any]] = []
            for row in rows:
                ts = row.timestamp
                if ts is None:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc).astimezone(IST)
                else:
                    ts = ts.astimezone(IST)
                payload.append(
                    {
                        "timestamp": ts,
                        "open": float(row.open),
                        "high": float(row.high),
                        "low": float(row.low),
                        "close": float(row.close),
                        "volume": int(row.volume),
                        "symbol": symbol,
                    }
                )

            if not payload:
                return None
            return pd.DataFrame(payload).sort_values("timestamp").reset_index(drop=True)
        except Exception as exc:
            logger.warning("fetch_database_market_data_error", symbol=symbol, timeframe=timeframe, error=str(exc))
            return None

    async def _fetch_fyers_market_data(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        if not self.fyers_client.is_authenticated:
            refresh_fn = getattr(self.fyers_client, "try_auto_refresh_with_saved_pin", None)
            if callable(refresh_fn):
                try:
                    await asyncio.to_thread(refresh_fn, False)
                except Exception as exc:
                    logger.warning("fyers_market_data_refresh_error", symbol=symbol, error=str(exc))
        if not self.fyers_client.is_authenticated:
            return None
        end = datetime.now(tz=IST)
        days_back = {
            "1": 7,
            "3": 14,
            "5": 21,
            "15": 45,
            "30": 60,
            "60": 90,
            "D": 365,
            "W": 730,
            "M": 1825,
        }.get(timeframe, 30)
        start = end - pd.Timedelta(days=days_back)

        raw = await asyncio.to_thread(
            lambda: self.fyers_client.get_history(
                symbol=symbol,
                resolution=timeframe,
                range_from=start.strftime("%Y-%m-%d"),
                range_to=end.strftime("%Y-%m-%d"),
            )
        )
        candles = raw.get("candles", []) if isinstance(raw, dict) else []
        if not candles:
            return None

        rows = []
        for row in candles:
            if len(row) < 6:
                continue
            rows.append({
                "timestamp": datetime.fromtimestamp(int(row[0]), tz=IST),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": int(row[5]),
                "symbol": symbol,
            })
        if not rows:
            return None
        return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)

    @staticmethod
    def _yahoo_interval_range(timeframe: str) -> Tuple[str, str]:
        mapping = {
            "1": ("1m", "7d"),
            "2": ("2m", "7d"),
            "3": ("5m", "10d"),
            "5": ("5m", "30d"),
            "15": ("15m", "60d"),
            "30": ("30m", "60d"),
            "60": ("60m", "6mo"),
            "90": ("90m", "6mo"),
            "D": ("1d", "2y"),
            "W": ("1wk", "5y"),
        }
        return mapping.get(timeframe, ("15m", "60d"))

    @staticmethod
    def _resample_ohlcv(df: pd.DataFrame, timeframe: str, symbol: str) -> Optional[pd.DataFrame]:
        token = str(timeframe or "").strip().upper()
        if df is None or df.empty:
            return None
        if token in {"1", "1M", "1MIN"}:
            out = df.copy(deep=False)
            out["symbol"] = symbol
            return out.sort_values("timestamp").reset_index(drop=True)

        if token == "D":
            rule = "1D"
        elif token == "W":
            rule = "1W"
        elif token.isdigit():
            rule = f"{max(int(token), 1)}min"
        else:
            rule = "15min"

        tmp = df.copy(deep=False)
        tmp = tmp.sort_values("timestamp").set_index("timestamp")
        grouped = (
            tmp[["open", "high", "low", "close", "volume"]]
            .resample(rule)
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna(subset=["open", "high", "low", "close"])
        )
        if grouped.empty:
            return None
        grouped = grouped.reset_index()
        grouped["symbol"] = symbol
        return grouped.sort_values("timestamp").reset_index(drop=True)

    async def _fetch_us_yahoo_ohlcv(self, ticker: str, interval: str, period: str, symbol: str) -> Optional[pd.DataFrame]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        timeout = httpx.Timeout(8.0, connect=4.0)
        payload: Dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=_YAHOO_HEADERS) as http:
                res = await http.get(url, params={"interval": interval, "range": period})
                if res.status_code < 400:
                    payload = res.json()
                else:
                    logger.warning(
                        "fetch_us_market_data_yahoo_http_error",
                        symbol=symbol,
                        ticker=ticker,
                        status_code=res.status_code,
                    )
        except Exception as exc:
            logger.warning("fetch_us_market_data_yahoo_failed", symbol=symbol, error=str(exc))
            return None

        chart = payload.get("chart", {}) if isinstance(payload, dict) else {}
        results = chart.get("result", []) if isinstance(chart, dict) else []
        if not results or not isinstance(results[0], dict):
            return None
        result = results[0]
        timestamps = result.get("timestamp", []) or []
        indicators = result.get("indicators", {})
        quote_rows = indicators.get("quote", []) if isinstance(indicators, dict) else []
        if not quote_rows or not isinstance(quote_rows[0], dict):
            return None
        quote = quote_rows[0]
        opens = quote.get("open", []) or []
        highs = quote.get("high", []) or []
        lows = quote.get("low", []) or []
        closes = quote.get("close", []) or []
        volumes = quote.get("volume", []) or []

        rows = []
        for idx, ts in enumerate(timestamps):
            if idx >= len(opens) or idx >= len(highs) or idx >= len(lows) or idx >= len(closes):
                continue
            o = opens[idx]
            h = highs[idx]
            l = lows[idx]
            c = closes[idx]
            if o is None or h is None or l is None or c is None:
                continue
            vol = volumes[idx] if idx < len(volumes) and volumes[idx] is not None else 0
            rows.append({
                "timestamp": datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(IST),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(vol),
                "symbol": symbol,
            })
        if not rows:
            return None
        return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)

    async def _fetch_us_finnhub_ohlcv(self, ticker: str, resolution: str, span_seconds: int, symbol: str) -> Optional[pd.DataFrame]:
        settings = get_settings()
        token = str(settings.finnhub_api_key or "").strip()
        if not token:
            return None
        now_utc = datetime.now(tz=timezone.utc)
        end_ts = int(now_utc.timestamp())
        start_ts = end_ts - max(span_seconds, 86_400)
        timeout = httpx.Timeout(8.0, connect=4.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as http:
                res = await http.get(
                    "https://finnhub.io/api/v1/stock/candle",
                    params={
                        "symbol": ticker,
                        "resolution": resolution,
                        "from": start_ts,
                        "to": end_ts,
                        "token": token,
                    },
                )
                if res.status_code >= 400:
                    logger.warning(
                        "fetch_us_market_data_finnhub_http_error",
                        symbol=symbol,
                        ticker=ticker,
                        status_code=res.status_code,
                    )
                    return None
                payload = res.json()
        except Exception as exc:
            logger.warning("fetch_us_market_data_finnhub_failed", symbol=symbol, error=str(exc))
            return None

        if not isinstance(payload, dict) or payload.get("s") != "ok":
            return None
        opens = payload.get("o", []) or []
        highs = payload.get("h", []) or []
        lows = payload.get("l", []) or []
        closes = payload.get("c", []) or []
        volumes = payload.get("v", []) or []
        timestamps = payload.get("t", []) or []

        rows = []
        for idx, ts in enumerate(timestamps):
            if idx >= len(opens) or idx >= len(highs) or idx >= len(lows) or idx >= len(closes):
                continue
            o = opens[idx]
            h = highs[idx]
            l = lows[idx]
            c = closes[idx]
            if o is None or h is None or l is None or c is None:
                continue
            vol = volumes[idx] if idx < len(volumes) and volumes[idx] is not None else 0
            rows.append({
                "timestamp": datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(IST),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(vol),
                "symbol": symbol,
            })
        if not rows:
            return None
        return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)

    async def _fetch_us_nasdaq_ohlcv(
        self,
        ticker: str,
        symbol: str,
        *,
        daily: bool = False,
    ) -> Optional[pd.DataFrame]:
        assetclass = "etf" if ticker in _US_ETF_TICKERS else "stocks"
        timeout = httpx.Timeout(8.0, connect=4.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=_NASDAQ_HEADERS) as http:
                if daily:
                    to_date = datetime.now(tz=IST).date()
                    from_date = to_date - timedelta(days=730)
                    res = await http.get(
                        f"https://api.nasdaq.com/api/quote/{ticker}/historical",
                        params={
                            "assetclass": assetclass,
                            "fromdate": from_date.strftime("%Y-%m-%d"),
                            "todate": to_date.strftime("%Y-%m-%d"),
                            "limit": 365,
                        },
                    )
                    if res.status_code >= 400:
                        logger.warning(
                            "fetch_us_market_data_nasdaq_historical_http_error",
                            symbol=symbol,
                            ticker=ticker,
                            status_code=res.status_code,
                        )
                        return None
                    payload = res.json()
                    data = payload.get("data", {}) if isinstance(payload, dict) else {}
                    trades_table = data.get("tradesTable", {}) if isinstance(data, dict) else {}
                    history_rows = trades_table.get("rows", []) if isinstance(trades_table, dict) else []
                    rows: list[dict[str, Any]] = []
                    for row in reversed(history_rows):
                        if not isinstance(row, dict):
                            continue
                        try:
                            timestamp = parse_nasdaq_historical_date(row.get("date"))
                            if timestamp is None:
                                continue
                            rows.append(
                                {
                                    "timestamp": timestamp,
                                    "open": float(str(row.get("open", "0")).replace("$", "").replace(",", "")),
                                    "high": float(str(row.get("high", "0")).replace("$", "").replace(",", "")),
                                    "low": float(str(row.get("low", "0")).replace("$", "").replace(",", "")),
                                    "close": float(str(row.get("close", "0")).replace("$", "").replace(",", "")),
                                    "volume": float(str(row.get("volume", "0")).replace(",", "")),
                                    "symbol": symbol,
                                }
                            )
                        except (TypeError, ValueError):
                            continue
                    if not rows:
                        return None
                    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)

                res = await http.get(
                    f"https://api.nasdaq.com/api/quote/{ticker}/chart",
                    params={"assetclass": assetclass},
                )
                if res.status_code >= 400:
                    logger.warning(
                        "fetch_us_market_data_nasdaq_chart_http_error",
                        symbol=symbol,
                        ticker=ticker,
                        status_code=res.status_code,
                    )
                    return None
                payload = res.json()
        except Exception as exc:
            logger.warning("fetch_us_market_data_nasdaq_failed", symbol=symbol, error=str(exc))
            return None

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        chart_rows = data.get("chart", []) if isinstance(data, dict) else []
        time_as_of = data.get("timeAsOf") if isinstance(data, dict) else None
        rows: list[dict[str, Any]] = []
        for row in chart_rows:
            if not isinstance(row, dict):
                continue
            try:
                ts = parse_nasdaq_chart_timestamp(row, time_as_of=time_as_of)
                price = float(row.get("y"))
            except (TypeError, ValueError):
                continue
            if ts is None:
                continue
            rows.append(
                {
                    "timestamp": ts,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 0.0,
                    "symbol": symbol,
                }
            )
        if not rows:
            return None
        return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)

    async def _fetch_us_alphavantage_ohlcv(
        self,
        ticker: str,
        interval: str,
        symbol: str,
        *,
        daily: bool = False,
    ) -> Optional[pd.DataFrame]:
        settings = get_settings()
        token = str(settings.alphavantage_api_key or "").strip()
        if not token:
            return None

        params: Dict[str, Any] = {
            "symbol": ticker,
            "apikey": token,
            "outputsize": "full",
        }
        if daily:
            params["function"] = "TIME_SERIES_DAILY_ADJUSTED"
        else:
            params["function"] = "TIME_SERIES_INTRADAY"
            params["interval"] = interval

        timeout = httpx.Timeout(8.0, connect=4.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as http:
                res = await http.get(
                    "https://www.alphavantage.co/query",
                    params=params,
                )
                if res.status_code >= 400:
                    logger.warning(
                        "fetch_us_market_data_alphavantage_http_error",
                        symbol=symbol,
                        ticker=ticker,
                        status_code=res.status_code,
                    )
                    return None
                payload = res.json()
        except Exception as exc:
            logger.warning("fetch_us_market_data_alphavantage_failed", symbol=symbol, error=str(exc))
            return None

        if not isinstance(payload, dict):
            return None
        if payload.get("Error Message"):
            logger.warning(
                "fetch_us_market_data_alphavantage_error",
                symbol=symbol,
                ticker=ticker,
                error=str(payload.get("Error Message")),
            )
            return None
        if payload.get("Note"):
            logger.warning(
                "fetch_us_market_data_alphavantage_throttled",
                symbol=symbol,
                ticker=ticker,
                note=str(payload.get("Note")),
            )
            return None

        if daily:
            series_key = "Time Series (Daily)"
        else:
            series_key = f"Time Series ({interval})"
        series = payload.get(series_key)
        if not isinstance(series, dict) or not series:
            return None

        rows: List[Dict[str, Any]] = []
        for raw_ts, raw_row in series.items():
            if not isinstance(raw_row, dict):
                continue
            try:
                if daily:
                    parsed = datetime.strptime(str(raw_ts), "%Y-%m-%d").replace(
                        tzinfo=US_EASTERN
                    )
                else:
                    parsed = datetime.strptime(str(raw_ts), "%Y-%m-%d %H:%M:%S").replace(
                        tzinfo=US_EASTERN
                    )
                timestamp = parsed.astimezone(IST)
                o = float(raw_row.get("1. open"))
                h = float(raw_row.get("2. high"))
                l = float(raw_row.get("3. low"))
                c = float(raw_row.get("4. close"))
                v = float(raw_row.get("5. volume", 0.0))
            except Exception:
                continue

            rows.append({
                "timestamp": timestamp,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "symbol": symbol,
            })

        if not rows:
            return None
        return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)

    async def _fetch_us_intraday_base(self, symbol: str, ticker: str) -> Optional[pd.DataFrame]:
        now = datetime.now(tz=IST)
        cached = self._us_intraday_cache.get(ticker)
        if cached is not None:
            cached_at, cached_df = cached
            if now - cached_at <= self._us_intraday_cache_ttl:
                return cached_df.copy(deep=False)

        settings = get_settings()
        prefer_finnhub = bool(str(settings.finnhub_api_key or "").strip())

        frame: Optional[pd.DataFrame] = None
        if prefer_finnhub:
            frame = await self._fetch_us_finnhub_ohlcv(
                ticker=ticker,
                resolution="1",
                span_seconds=7 * 24 * 3600,
                symbol=symbol,
            )
        if frame is None or frame.empty or self._us_intraday_frame_is_stale(frame):
            frame = await self._fetch_us_alphavantage_ohlcv(
                ticker=ticker,
                interval="1min",
                symbol=symbol,
                daily=False,
            )
        if frame is None or frame.empty or self._us_intraday_frame_is_stale(frame):
            frame = await self._fetch_us_yahoo_ohlcv(ticker=ticker, interval="1m", period="7d", symbol=symbol)
        if frame is None or frame.empty or self._us_intraday_frame_is_stale(frame):
            frame = await self._fetch_us_nasdaq_ohlcv(ticker=ticker, symbol=symbol, daily=False)
        if frame is None or frame.empty or self._us_intraday_frame_is_stale(frame):
            frame = await self._fetch_us_finnhub_ohlcv(
                ticker=ticker,
                resolution="1",
                span_seconds=7 * 24 * 3600,
                symbol=symbol,
            )
        if frame is None or frame.empty:
            return None
        self._us_intraday_cache[ticker] = (now, frame)
        return frame.copy(deep=False)

    @staticmethod
    def _us_session_is_open_now(now: Optional[datetime] = None) -> bool:
        current = (now or datetime.now(tz=IST)).astimezone(US_EASTERN)
        if current.weekday() >= 5:
            return False
        session_open = current.replace(hour=9, minute=30, second=0, microsecond=0)
        session_close = current.replace(hour=16, minute=0, second=0, microsecond=0)
        return session_open <= current <= session_close

    def _us_intraday_frame_is_stale(self, frame: Optional[pd.DataFrame], timeframe_minutes: int = 1) -> bool:
        if frame is None or frame.empty or not self._us_session_is_open_now():
            return False
        if "timestamp" not in frame.columns:
            return False
        ts = self._coerce_ist_timestamp(frame["timestamp"].iloc[-1])
        if ts is None:
            return False
        max_age = timedelta(minutes=max(timeframe_minutes * 3, 20))
        return (datetime.now(tz=IST) - ts) > max_age

    async def _fetch_us_daily_base(self, symbol: str, ticker: str) -> Optional[pd.DataFrame]:
        now = datetime.now(tz=IST)
        cached = self._us_daily_cache.get(ticker)
        if cached is not None:
            cached_at, cached_df = cached
            if now - cached_at <= self._us_daily_cache_ttl:
                return cached_df.copy(deep=False)

        settings = get_settings()
        prefer_finnhub = bool(str(settings.finnhub_api_key or "").strip())

        frame: Optional[pd.DataFrame] = None
        if prefer_finnhub:
            frame = await self._fetch_us_finnhub_ohlcv(
                ticker=ticker,
                resolution="D",
                span_seconds=2 * 365 * 24 * 3600,
                symbol=symbol,
            )
        if frame is None or frame.empty:
            frame = await self._fetch_us_alphavantage_ohlcv(
                ticker=ticker,
                interval="60min",
                symbol=symbol,
                daily=True,
            )
        if frame is None or frame.empty:
            frame = await self._fetch_us_yahoo_ohlcv(ticker=ticker, interval="1d", period="2y", symbol=symbol)
        if frame is None or frame.empty:
            frame = await self._fetch_us_nasdaq_ohlcv(ticker=ticker, symbol=symbol, daily=True)
        if frame is None or frame.empty:
            frame = await self._fetch_us_finnhub_ohlcv(
                ticker=ticker,
                resolution="D",
                span_seconds=2 * 365 * 24 * 3600,
                symbol=symbol,
            )
        if frame is None or frame.empty:
            return None
        self._us_daily_cache[ticker] = (now, frame)
        return frame.copy(deep=False)

    async def _fetch_us_market_data(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        ticker = self._normalize_us_ticker(symbol)
        if not ticker:
            return None
        token = str(timeframe or "").strip().upper()
        if token in {"D", "W"}:
            base = await self._fetch_us_daily_base(symbol=symbol, ticker=ticker)
        else:
            base = await self._fetch_us_intraday_base(symbol=symbol, ticker=ticker)
        if base is None or base.empty:
            return await self._fetch_us_market_data_nasdaq(symbol, timeframe)
        return self._resample_ohlcv(base, timeframe=timeframe, symbol=symbol)

    async def _fetch_us_market_data_nasdaq(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        ticker = self._normalize_us_ticker(symbol)
        if not ticker:
            return None
        token = str(timeframe or "").strip().upper()
        if token in {"D", "W"}:
            frame = await self._fetch_us_nasdaq_ohlcv(ticker=ticker, symbol=symbol, daily=True)
        else:
            frame = await self._fetch_us_nasdaq_ohlcv(ticker=ticker, symbol=symbol, daily=False)
        if frame is None or frame.empty:
            return None
        return self._resample_ohlcv(frame, timeframe=timeframe, symbol=symbol)

    @staticmethod
    def _binance_interval(timeframe: str) -> str:
        mapping = {
            "1": "1m",
            "3": "3m",
            "5": "5m",
            "15": "15m",
            "30": "30m",
            "60": "1h",
            "120": "2h",
            "240": "4h",
            "D": "1d",
        }
        return mapping.get(timeframe, "15m")

    async def _fetch_crypto_market_data(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        from src.api.routes.market_data import _fetch_crypto_ohlc

        candles = await _fetch_crypto_ohlc(symbol, timeframe, 500)
        if not candles:
            return None
        rows = []
        for candle in candles:
            rows.append({
                "timestamp": candle.timestamp.astimezone(IST),
                "open": float(candle.open),
                "high": float(candle.high),
                "low": float(candle.low),
                "close": float(candle.close),
                "volume": float(candle.volume),
                "symbol": symbol,
            })
        if not rows:
            return None
        return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)

    async def _fetch_live_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Fetch latest LTPs across NSE, US, and crypto providers."""
        if not symbols:
            return {}

        nse_symbols: List[str] = []
        us_symbols: List[str] = []
        crypto_symbols: List[str] = []
        for symbol in symbols:
            market = self._symbol_market(symbol)
            if market == "US":
                us_symbols.append(symbol)
            elif market == "CRYPTO":
                crypto_symbols.append(symbol)
            else:
                nse_symbols.append(symbol)

        prices: Dict[str, float] = {}

        if nse_symbols:
            if not self.fyers_client.is_authenticated:
                refresh_fn = getattr(self.fyers_client, "try_auto_refresh_with_saved_pin", None)
                if callable(refresh_fn):
                    try:
                        await asyncio.to_thread(refresh_fn, False)
                    except Exception as exc:
                        logger.warning("fetch_live_prices_refresh_error", market="nse", error=str(exc))
            if self.fyers_client.is_authenticated:
                try:
                    raw = await asyncio.to_thread(lambda: self.fyers_client.get_quotes(nse_symbols))
                except Exception as exc:
                    logger.warning("fetch_live_prices_error", market="nse", error=str(exc), symbols=nse_symbols)
                else:
                    rows = raw.get("d", []) if isinstance(raw, dict) else []
                    for row in rows:
                        payload = row.get("v", {}) if isinstance(row, dict) else {}
                        symbol = str(payload.get("symbol") or row.get("n") or "").strip()
                        ltp_raw = payload.get("lp")
                        try:
                            ltp = float(ltp_raw)
                        except (TypeError, ValueError):
                            continue
                        if symbol and ltp > 0:
                            prices[symbol] = ltp

        if us_symbols:
            prices.update(await self._fetch_us_live_prices(us_symbols))

        if crypto_symbols:
            prices.update(await self._fetch_crypto_live_prices(crypto_symbols))

        return prices

    async def _fetch_us_live_prices(self, symbols: List[str]) -> Dict[str, float]:
        ticker_to_symbol = {
            self._normalize_us_ticker(symbol): symbol
            for symbol in symbols
            if self._normalize_us_ticker(symbol)
        }
        tickers = sorted(ticker_to_symbol.keys())
        if not tickers:
            return {}
        payload: Dict[str, Any] = {}
        timeout = httpx.Timeout(8.0, connect=4.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=_YAHOO_HEADERS) as http:
                res = await http.get(
                    "https://query1.finance.yahoo.com/v7/finance/quote",
                    params={"symbols": ",".join(tickers)},
                )
                if res.status_code < 400:
                    payload = res.json()
        except Exception as exc:
            logger.warning("fetch_live_prices_error", market="us_yahoo", error=str(exc), symbols=tickers)

        prices: Dict[str, float] = {}
        rows = (
            payload.get("quoteResponse", {}).get("result", [])
            if isinstance(payload, dict)
            else []
        )
        seen: set[str] = set()
        for row in rows:
            symbol = str((row or {}).get("symbol") or "").strip().upper()
            ltp_raw = (row or {}).get("regularMarketPrice")
            try:
                ltp = float(ltp_raw)
            except (TypeError, ValueError):
                continue
            if symbol and ltp > 0:
                mapped = ticker_to_symbol.get(symbol, f"US:{symbol}")
                prices[mapped] = ltp
                seen.add(symbol)

        # Yahoo quote endpoint often omits OCC option symbols and can be
        # blocked in containerized environments.
        missing = [ticker for ticker in tickers if ticker not in seen]
        underlying_missing = [ticker for ticker in missing if self._parse_us_option_symbol(ticker) is None]
        if underlying_missing:
            fallback_prices = await self._fetch_us_live_prices_nasdaq(underlying_missing)
            for ticker, ltp in fallback_prices.items():
                mapped = ticker_to_symbol.get(ticker)
                if mapped and ltp > 0:
                    prices[mapped] = ltp
                    seen.add(ticker)

        missing = [ticker for ticker in tickers if ticker not in seen]
        if missing:
            async with httpx.AsyncClient(timeout=timeout, headers=_YAHOO_HEADERS) as http:
                tasks = [
                    asyncio.create_task(self._fetch_us_option_quote(http, contract))
                    for contract in missing
                    if self._parse_us_option_symbol(contract) is not None
                ]
                if tasks:
                    option_quotes = await asyncio.gather(*tasks, return_exceptions=True)
                    for quote in option_quotes:
                        if isinstance(quote, Exception) or not isinstance(quote, tuple):
                            continue
                        contract, price = quote
                        mapped = ticker_to_symbol.get(contract)
                        if mapped and price > 0:
                            prices[mapped] = price
        return prices

    async def _fetch_us_live_prices_nasdaq(self, tickers: List[str]) -> Dict[str, float]:
        if not tickers:
            return {}

        timeout = httpx.Timeout(8.0, connect=4.0)
        out: Dict[str, float] = {}
        async with httpx.AsyncClient(timeout=timeout, headers=_NASDAQ_HEADERS) as http:
            tasks = [
                asyncio.create_task(
                    http.get(
                        f"https://api.nasdaq.com/api/quote/{ticker}/info",
                        params={"assetclass": "etf" if ticker in _US_ETF_TICKERS else "stocks"},
                    )
                )
                for ticker in tickers
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

        for ticker, response in zip(tickers, responses):
            if isinstance(response, Exception):
                continue
            if response.status_code >= 400:
                continue
            payload = response.json() if response.content else {}
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            primary = data.get("primaryData", {}) if isinstance(data.get("primaryData"), dict) else {}
            price = self._parse_nasdaq_number(primary.get("lastSalePrice"))
            if price <= 0:
                price = self._parse_nasdaq_number(data.get("lastSalePrice"))
            if price > 0:
                out[ticker] = price
        return out

    async def _fetch_us_option_quote(
        self,
        http: httpx.AsyncClient,
        contract_symbol: str,
    ) -> Optional[Tuple[str, float]]:
        parsed = self._parse_us_option_symbol(contract_symbol)
        if parsed is None:
            return None

        try:
            res = await http.get(
                f"https://query2.finance.yahoo.com/v7/finance/options/{parsed['root']}",
                params={"date": parsed["expiry_unix"]},
            )
            if res.status_code >= 400:
                return await self._fetch_us_option_quote_nasdaq(parsed)
            payload = res.json()
        except Exception:
            return await self._fetch_us_option_quote_nasdaq(parsed)

        chain = payload.get("optionChain", {}) if isinstance(payload, dict) else {}
        results = chain.get("result", []) if isinstance(chain, dict) else []
        if not results or not isinstance(results[0], dict):
            return await self._fetch_us_option_quote_nasdaq(parsed)
        options_blocks = results[0].get("options", [])
        if not options_blocks or not isinstance(options_blocks[0], dict):
            return await self._fetch_us_option_quote_nasdaq(parsed)
        side_key = "calls" if parsed["option_type"] == "CALL" else "puts"
        rows = options_blocks[0].get(side_key, [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("contractSymbol") or "").strip().upper() != parsed["contract_symbol"]:
                continue
            last_price = float(row.get("lastPrice") or 0.0)
            if last_price > 0:
                return parsed["contract_symbol"], last_price
            bid = float(row.get("bid") or 0.0)
            ask = float(row.get("ask") or 0.0)
            if bid > 0 and ask > 0:
                return parsed["contract_symbol"], (bid + ask) / 2.0
            return parsed["contract_symbol"], max(bid, ask, 0.0)
        return await self._fetch_us_option_quote_nasdaq(parsed)

    async def _fetch_us_option_quote_nasdaq(
        self,
        parsed: Dict[str, Any],
    ) -> Optional[Tuple[str, float]]:
        ticker = str(parsed.get("root") or "").upper()
        if not ticker:
            return None

        timeout = httpx.Timeout(10.0, connect=4.0)
        endpoint = f"https://api.nasdaq.com/api/quote/{ticker}/option-chain"
        payload: Dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=_NASDAQ_HEADERS) as http:
                for assetclass in (
                    "etf" if ticker in _US_ETF_TICKERS else "stocks",
                    "stocks",
                    "etf",
                ):
                    res = await http.get(endpoint, params={"assetclass": assetclass})
                    if res.status_code >= 400:
                        continue
                    raw = res.json()
                    data = raw.get("data", {}) if isinstance(raw, dict) else {}
                    if isinstance(data, dict) and data:
                        payload = raw
                        break
        except Exception:
            return None

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        table = data.get("table", {}) if isinstance(data.get("table"), dict) else {}
        rows = table.get("rows", []) if isinstance(table.get("rows"), list) else []
        if not rows:
            return None

        target_expiry = parsed["expiry"].astimezone(IST).date() if isinstance(parsed.get("expiry"), datetime) else None
        target_strike = float(parsed.get("strike") or 0.0)
        target_side = "c_" if parsed.get("option_type") == "CALL" else "p_"
        best_price = 0.0
        best_score = float("inf")
        group_expiry: Optional[datetime] = None

        for row in rows:
            if not isinstance(row, dict):
                continue
            strike = self._parse_nasdaq_number(row.get("strike"))
            if strike <= 0:
                group_candidate = self._parse_nasdaq_expiry(row.get("expirygroup"))
                if group_candidate is not None:
                    group_expiry = group_candidate
                continue

            expiry = self._parse_nasdaq_expiry(
                row.get("expiryDate"),
                fallback_year=(group_expiry.year if group_expiry is not None else None),
            )
            if expiry is None:
                expiry = group_expiry
            if expiry is None:
                continue

            side_last = self._parse_nasdaq_number(row.get(f"{target_side}Last"))
            side_bid = self._parse_nasdaq_number(row.get(f"{target_side}Bid"))
            side_ask = self._parse_nasdaq_number(row.get(f"{target_side}Ask"))
            price = side_last if side_last > 0 else ((side_bid + side_ask) / 2.0 if side_bid > 0 and side_ask > 0 else max(side_bid, side_ask, 0.0))
            if price <= 0:
                continue

            expiry_date = expiry.date()
            score = abs(strike - target_strike)
            if target_expiry is not None:
                score += abs((expiry_date - target_expiry).days) * 100.0
            if score < best_score:
                best_score = score
                best_price = price

        if best_price <= 0:
            return None
        return str(parsed["contract_symbol"]), best_price

    async def _fetch_crypto_live_prices(self, symbols: List[str]) -> Dict[str, float]:
        unique_symbols = []
        seen: set[str] = set()
        for symbol in symbols:
            token = str(symbol or "").strip().upper()
            if not token or token in seen:
                continue
            unique_symbols.append(token)
            seen.add(token)
        if not unique_symbols:
            return {}

        from src.api.routes.market_data import _fetch_crypto_quote_snapshot

        prices: Dict[str, float] = {}
        quotes = await asyncio.gather(
            *[_fetch_crypto_quote_snapshot(symbol) for symbol in unique_symbols],
            return_exceptions=True,
        )
        for symbol, quote in zip(unique_symbols, quotes):
            if isinstance(quote, Exception):
                logger.warning("fetch_live_prices_error", market="crypto", symbol=symbol, error=str(quote))
                continue
            if not isinstance(quote, dict):
                continue
            try:
                price = float(quote.get("ltp"))
            except (TypeError, ValueError):
                continue
            if price > 0:
                prices[symbol] = price
        return prices

    async def _close_position(
        self,
        symbol: str,
        short_name: str,
        current_price: float,
        reason: str,
        plan: Optional[OptionExitPlan] = None,
    ) -> None:
        """Close an open position through order manager then book realized PnL."""
        pos_obj = self.position_manager.get_position(symbol)
        if pos_obj is None or pos_obj.quantity <= 0:
            self._remove_exit_plan(symbol, plan.strategy if plan is not None else None)
            return

        eligible_qty = int(pos_obj.quantity)
        if plan is not None:
            eligible_qty = sum(
                int(view.quantity)
                for view in self.position_manager.get_position_views(
                    symbol=symbol,
                    strategy_tag=plan.strategy,
                )
            )
            if eligible_qty <= 0:
                logger.warning(
                    "stale_exit_plan_removed",
                    symbol=symbol,
                    strategy=plan.strategy,
                    plan_qty=int(plan.quantity),
                )
                self._remove_exit_plan(symbol, plan.strategy)
                return

        if current_price <= 0:
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.ORDER_REJECTED,
                title=f"Exit Failed — {short_name}",
                message=f"Cannot close position on {reason}: invalid LTP.",
                severity="error",
                metadata={"symbol": symbol, "reason": reason, "price": current_price},
            ))
            return

        qty = int(plan.quantity) if plan is not None else eligible_qty
        qty = max(min(qty, eligible_qty), 1)
        avg_price = float(plan.entry_price) if plan is not None else float(pos_obj.avg_price)
        entry_value = max(avg_price * qty, 1e-6)
        if not self.config.paper_mode and self._symbol_has_pending_live_order(symbol):
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.ORDER_REJECTED,
                title=f"Exit Deferred — {short_name}",
                message="A live broker order for this symbol is still pending. Waiting before sending another exit.",
                severity="warning",
                metadata={"symbol": symbol, "reason": reason, "pending_live_order": True},
            ))
            return
        close_side = OrderSide.SELL if pos_obj.side == PositionSide.LONG else OrderSide.BUY
        order = Order(
            symbol=symbol,
            quantity=qty,
            side=close_side,
            order_type=OrderType.MARKET,
            product_type=ProductType.INTRADAY,
            market_price_hint=current_price,
            tag=f"EXIT:{plan.strategy if plan else 'system'}",
        )

        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.ORDER_PLACING,
            title=f"Closing Position — {short_name}",
            message=f"{close_side.name} {qty} units for {reason}.",
            severity="warning" if reason in {"stop_loss", "time_exit", "eod_exit"} else "info",
            metadata={
                "symbol": symbol,
                "underlying_symbol": (plan.underlying_symbol if plan is not None else symbol),
                "reason": reason,
                "quantity": qty,
            },
        ))

        if self.config.paper_mode:
            placed = self.order_manager.place_order(order)
        else:
            placed = await asyncio.to_thread(self.order_manager.place_order, order)
        executed = placed.order
        if not placed.success or executed is None or executed.status not in (
            OrderStatus.FILLED,
            OrderStatus.PLACED,
            OrderStatus.PARTIALLY_FILLED,
        ):
            status = executed.status.value if executed is not None else "rejected"
            reject_reason = (
                (executed.rejection_reason if executed is not None else None)
                or placed.message
                or "unknown"
            )
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.ORDER_REJECTED,
                title=f"Exit Rejected — {short_name}",
                message=f"Exit {status}. Reason: {reject_reason}.",
                severity="error",
                metadata={"symbol": symbol, "reason": reason, "status": status, "reject_reason": reject_reason},
            ))
            return

        if self.config.paper_mode:
            await self._finalize_live_exit_fill(
                context=PendingLiveExitOrder(
                    order_id=str(executed.order_id or ""),
                    symbol=symbol,
                    short_name=short_name,
                    quantity=qty,
                    reason=reason,
                    avg_price=avg_price,
                    entry_value=entry_value,
                    exit_price_hint=current_price,
                    plan=plan,
                ),
                order=executed,
                fill_quantity=self._resolved_fill_quantity(executed.fill_quantity, qty),
                fill_price=float(executed.fill_price or current_price),
            )
        else:
            order_id = str(executed.order_id or "")
            self._pending_live_exits[order_id] = PendingLiveExitOrder(
                order_id=order_id,
                symbol=symbol,
                short_name=short_name,
                quantity=qty,
                reason=reason,
                avg_price=avg_price,
                entry_value=entry_value,
                exit_price_hint=current_price,
                plan=plan,
            )
            self._persist_live_runtime_state()
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.ORDER_PLACED,
                title=f"Exit Submitted — {short_name}",
                message=f"{close_side.name} {qty} units submitted. Waiting for broker fill confirmation.",
                severity="success",
                metadata={
                    "symbol": symbol,
                    "underlying_symbol": (plan.underlying_symbol if plan is not None else symbol),
                    "reason": reason,
                    "quantity": qty,
                    "order_id": order_id,
                    "status": executed.status.value,
                },
            ))
            if int(executed.fill_quantity or 0) > 0:
                await self._finalize_live_exit_fill(
                    context=self._pending_live_exits[order_id],
                    order=executed,
                    fill_quantity=int(executed.fill_quantity),
                    fill_price=float(executed.fill_price or current_price),
                )
                if executed.status == OrderStatus.FILLED:
                    self._pending_live_exits.pop(order_id, None)
                    self._persist_live_runtime_state()

    # ------------------------------------------------------------------
    # Exit Condition Checks
    # ------------------------------------------------------------------

    async def _check_exit_conditions(self) -> None:
        """Check open positions for stop-loss, target, or time-based exits."""
        positions = self.position_manager.get_all_positions()
        if not positions:
            self._option_exit_plans.clear()
            return

        # Keep plan map consistent with currently open symbols.
        open_symbols = {p.symbol for p in positions}
        for symbol in list(self._option_exit_plans.keys()):
            if symbol not in open_symbols:
                self._remove_exit_plan(symbol)

        # Refresh position marks from broker quotes before exit checks.
        await self.refresh_position_marks([p.symbol for p in positions])

        # Check if near market close and enforce EOD liquidation buffer.
        now = datetime.now(tz=IST)
        eod_buffer_minutes = max(int(self.risk_manager.config.time_based_exit_minutes), 1)

        for pos_obj in self.position_manager.get_all_positions():
            symbol = pos_obj.symbol
            short_name = symbol.split(":")[-1].split("-")[0]
            quantity = int(pos_obj.quantity)
            avg_price = float(pos_obj.avg_price)
            current_price = float(pos_obj.current_price)
            unrealized_pnl = float(pos_obj.unrealized_pnl)
            unrealized_pnl_pct = float(pos_obj.unrealized_pnl_pct)
            side = str(pos_obj.side.value).upper()

            # Time-based exit near market close
            if self._should_force_eod_exit(symbol, now, eod_buffer_minutes):
                symbol_plans = self._symbol_exit_plans(symbol)
                if symbol_plans:
                    for plan in symbol_plans:
                        await self._close_position(
                            symbol=symbol,
                            short_name=short_name,
                            current_price=current_price,
                            reason="eod_exit",
                            plan=plan,
                        )
                else:
                    await self._close_position(
                        symbol=symbol,
                        short_name=short_name,
                        current_price=current_price,
                        reason="eod_exit",
                        plan=None,
                    )
                continue

            symbol_plans = self._symbol_exit_plans(symbol)
            if not symbol_plans and not self._is_index_symbol(symbol):
                # Recover exit control for carry-forward option positions that
                # may exist after process restarts.
                for view in self.position_manager.get_position_views(symbol=symbol):
                    self._upsert_option_exit_plan(
                        symbol=symbol,
                        underlying_symbol=symbol,
                        strategy=view.strategy_tag or "carry_forward",
                        quantity=int(view.quantity),
                        execution_timeframe=self.config.timeframe,
                        entry_price=float(view.avg_price),
                        stop_loss=max(
                            float(view.avg_price)
                            * (1.0 - (self.config.option_default_stop_loss_pct / 100.0)),
                            0.05,
                        ),
                        target=float(view.avg_price)
                        * (1.0 + (self.config.option_default_target_pct / 100.0)),
                    )
                symbol_plans = self._symbol_exit_plans(symbol)

            triggered = False
            if current_price > 0:
                for plan in list(symbol_plans):
                    reason: Optional[str] = None
                    if current_price <= plan.stop_loss:
                        reason = "stop_loss"
                    elif current_price >= plan.target:
                        reason = "target"
                    elif now >= plan.time_exit_at:
                        reason = "time_exit"

                    if reason is not None:
                        await self._close_position(
                            symbol=symbol,
                            short_name=short_name,
                            current_price=current_price,
                            reason=reason,
                            plan=plan,
                        )
                        triggered = True
                if triggered:
                    continue

            plan = self._display_exit_plan(symbol)

            time_left_sec = 0
            if plan is not None:
                time_left_sec = max(int((plan.time_exit_at - now).total_seconds()), 0)

            # Emit position update
            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.POSITION_UPDATE,
                title=f"Position: {short_name}",
                message=(
                    f"Side: {side} | Qty: {quantity} | "
                    f"Avg: {avg_price:,.2f} | "
                    f"P&L: {unrealized_pnl:+,.0f} ({unrealized_pnl_pct:+.1f}%)"
                    + (
                        f" | SL: {plan.stop_loss:,.2f} | Target: {plan.target:,.2f} "
                        f"| Time Left: {time_left_sec}s"
                        if plan is not None
                        else ""
                    )
                ),
                severity="success" if unrealized_pnl >= 0 else "warning",
                metadata={
                    "symbol": symbol,
                    "quantity": quantity,
                    "side": side,
                    "avg_price": avg_price,
                    "current_price": current_price,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                    "exit_plan": (
                        {
                            "stop_loss": plan.stop_loss,
                            "target": plan.target,
                            "time_exit_at": plan.time_exit_at.isoformat(),
                            "time_left_seconds": time_left_sec,
                            "strategy": plan.strategy,
                        }
                        if plan is not None
                        else None
                    ),
                },
            ))

    async def refresh_position_marks(self, symbols: Optional[List[str]] = None) -> Dict[str, float]:
        """Refresh current marks for open positions using live multi-market quotes."""
        target_symbols = symbols
        if target_symbols is None:
            target_symbols = [p.symbol for p in self.position_manager.get_all_positions()]
        if not target_symbols:
            return {}

        prices = await self._fetch_live_prices(target_symbols)
        for symbol, price in prices.items():
            try:
                px = float(price)
            except (TypeError, ValueError):
                continue
            if px > 0:
                self.position_manager.update_price(symbol, px)
        return prices

    def _should_force_eod_exit(self, symbol: str, now_ist: datetime, buffer_minutes: int) -> bool:
        market = self._symbol_market(symbol)
        if market == "CRYPTO":
            return False
        if market == "US":
            us_now = now_ist.astimezone(US_EASTERN)
            if us_now.weekday() > 4:
                return False
            us_close = datetime.combine(us_now.date(), US_MARKET_CLOSE, tzinfo=US_EASTERN)
            return us_now >= (us_close - timedelta(minutes=buffer_minutes))

        nse_close = datetime.combine(now_ist.date(), MARKET_CLOSE, tzinfo=IST)
        return now_ist >= (nse_close - timedelta(minutes=buffer_minutes))

    # ------------------------------------------------------------------
    # Daily Summary
    # ------------------------------------------------------------------

    async def _generate_daily_summary(self) -> None:
        """Emit end-of-day summary event."""
        portfolio = self.position_manager.get_portfolio_summary()
        risk_summary = self.risk_manager.get_risk_summary()

        total_trades = risk_summary.get("total_trades", self._total_trades)
        winning = risk_summary.get("winning_trades", 0)
        losing = risk_summary.get("losing_trades", 0)
        win_rate = (winning / total_trades * 100) if total_trades > 0 else 0

        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.DAILY_SUMMARY,
            title=f"Daily Summary — {datetime.now(tz=IST).strftime('%Y-%m-%d')}",
            message=(
                f"Total Trades: {total_trades} ({winning}W / {losing}L)\n"
                f"Win Rate: {win_rate:.1f}%\n"
                f"Realized P&L: {risk_summary.get('realized_pnl', 0):+,.0f}\n"
                f"Available Risk: {risk_summary.get('available_risk', 0):,.0f}"
            ),
            severity="success" if self._daily_pnl >= 0 else "warning",
            metadata={
                "total_trades": total_trades,
                "winning_trades": winning,
                "losing_trades": losing,
                "win_rate": round(win_rate, 1),
                "realized_pnl": risk_summary.get("realized_pnl", 0),
                "available_risk": risk_summary.get("available_risk", 0),
            },
        ))

    async def send_status_notification(self, reason: str = "on_demand") -> None:
        """Emit an immediate status-summary event for Telegram/WebSocket."""
        await self._emit_status_summary(reason=reason)

    async def _maybe_emit_periodic_summary(self) -> None:
        """Emit periodic status summaries for Telegram notifications."""
        interval_minutes = max(int(self.config.telegram_status_interval_minutes), 0)
        if interval_minutes <= 0:
            return

        now = datetime.now(tz=IST)
        last_sent = self._last_periodic_summary_at
        if last_sent is not None and (now - last_sent) < timedelta(minutes=interval_minutes):
            return

        await self._emit_status_summary(reason="periodic")
        self._last_periodic_summary_at = now

    async def _emit_status_summary(self, reason: str = "periodic") -> None:
        """Emit a compact trade/position status summary event."""
        portfolio = self.position_manager.get_portfolio_summary()
        risk_summary = self.risk_manager.get_risk_summary()
        pnl_total = float(portfolio.get("total_pnl", 0.0))
        positions = int(portfolio.get("position_count", 0))
        realized = float(risk_summary.get("realized_pnl", 0.0))
        unrealized = float(portfolio.get("total_unrealized_pnl", 0.0))
        interval = max(int(self.config.telegram_status_interval_minutes), 0)
        position_summary = self.position_manager.format_position_summary(max_items=4)

        await self.event_bus.emit(AgentEvent(
            event_type=AgentEventType.DAILY_SUMMARY,
            title="Agent Status Update",
            message=(
                f"State: {self.state.value.upper()} | "
                f"Cycle: {self._cycle_count} | "
                f"Signals: {self._total_signals} | Trades: {self._total_trades}\n"
                f"Open Positions: {positions} | "
                f"Realized: {realized:+,.2f} | "
                f"Unrealized: {unrealized:+,.2f} | "
                f"Total: {pnl_total:+,.2f}\n"
                f"Sessions: {', '.join(self._active_sessions) or 'NONE'} | "
                f"NSE: {'READY' if self._market_readiness.get('NSE', {}).get('ready') else 'WAIT'} | "
                f"Crypto: {'READY' if self._market_readiness.get('CRYPTO', {}).get('ready') else 'WAIT'} | "
                f"Mode: {'PAPER' if self.config.paper_mode else 'LIVE'} | "
                f"TS: {datetime.now(tz=IST).strftime('%H:%M:%S IST')}\n"
                f"Positions:\n{position_summary}"
            ),
            severity="success" if pnl_total >= 0 else "warning",
            metadata={
                "reason": reason,
                "cycle": self._cycle_count,
                "signals": self._total_signals,
                "trades": self._total_trades,
                "positions": positions,
                "realized_pnl": round(realized, 2),
                "unrealized_pnl": round(unrealized, 2),
                "total_pnl": round(pnl_total, 2),
                "active_sessions": list(self._active_sessions),
                "active_symbols": list(self._active_symbols),
                "market_readiness": self._market_readiness,
                "telegram_status_interval_minutes": interval,
            },
        ))

    # ------------------------------------------------------------------
    # Data Intelligence
    # ------------------------------------------------------------------

    # Strategy → optimal timeframes mapping.  The agent uses multiple
    # resolutions per strategy to build higher-conviction signals.
    STRATEGY_TIMEFRAMES: Dict[str, List[str]] = {
        "EMA_Crossover":           ["5", "15", "60", "D"],
        "RSI_Reversal":            ["3", "5", "15", "60"],
        "MACD_RSI":                ["5", "15", "60", "D"],
        "MP_OrderFlow_Breakout":   ["3", "5", "15", "60"],
        "Fractal_Profile_Breakout":["3"],
        "Bollinger_MeanReversion": ["3", "5", "15"],
        "Supertrend_Breakout":     ["5", "15", "60"],
        "ML_Ensemble":             ["5", "15", "60", "D"],
    }

    @staticmethod
    def _sort_timeframes(values: set[str]) -> List[str]:
        order = {"D": 10_000, "W": 20_000, "M": 30_000}
        return sorted(values, key=lambda t: int(t) if t.isdigit() else order.get(t, 40_000))

    def get_execution_timeframes(self) -> List[str]:
        """Execution timeframes used for short-term signal generation."""
        configured = [tf.strip().upper() for tf in self.config.execution_timeframes if tf.strip()]
        if configured:
            return self._sort_timeframes(set(configured))
        return self._sort_timeframes({self.config.timeframe})

    def get_reference_timeframes(self) -> List[str]:
        """Higher-timeframe references used to confirm short-term signals."""
        configured = [tf.strip().upper() for tf in self.config.reference_timeframes if tf.strip()]
        return self._sort_timeframes(set(configured or ["60", "D"]))

    def get_required_timeframes(self) -> List[str]:
        """Determine which timeframes the active strategies require."""
        tfs: set[str] = set()
        tfs.update(self.get_execution_timeframes())
        tfs.update(self.get_reference_timeframes())
        tfs.add(self.config.timeframe)
        for strat in self.config.strategies:
            tfs.update(self.STRATEGY_TIMEFRAMES.get(strat, [self.config.timeframe]))
        return self._sort_timeframes(tfs)

    async def _ensure_data_available(self, symbols: Optional[List[str]] = None) -> None:
        """Trigger data collection for symbols/timeframes the agent needs.

        Delegates to the auto_collector so the agent doesn't block its
        own scan loop with long backfills.
        """
        try:
            from src.data.auto_collector import collect_symbol_data

            required_tfs = self.get_required_timeframes()
            target_symbols = symbols or self.config.symbols
            nse_symbols = [
                symbol for symbol in target_symbols
                if self._symbol_market(symbol) == "NSE"
            ]
            if not nse_symbols:
                return
            if not self.fyers_client.is_authenticated:
                refresh_fn = getattr(self.fyers_client, "try_auto_refresh_with_saved_pin", None)
                if callable(refresh_fn):
                    try:
                        await asyncio.to_thread(refresh_fn, False)
                    except Exception as exc:
                        logger.warning("data_intelligence_refresh_error", error=str(exc))
            if not self.fyers_client.is_authenticated:
                logger.warning("data_intelligence_skipped_not_authenticated")
                return

            await self.event_bus.emit(AgentEvent(
                event_type=AgentEventType.THINKING,
                title="Data Intelligence",
                message=(
                    f"Ensuring data for {len(nse_symbols)} NSE symbols "
                    f"across {len(required_tfs)} timeframes ({', '.join(required_tfs)})."
                ),
                severity="info",
                metadata={"timeframes": required_tfs, "symbols": nse_symbols},
            ))

            for symbol in nse_symbols:
                for tf in required_tfs:
                    days = {"D": 365, "60": 90, "15": 45, "5": 20, "3": 14, "1": 7}.get(tf, 30)
                    await collect_symbol_data(self.fyers_client, symbol, tf, days)
                    await asyncio.sleep(0.3)

        except Exception as e:
            logger.warning("data_intelligence_error", error=str(e))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _register_strategies(self) -> None:
        """Instantiate and register strategies with the executor."""
        for name in self.config.strategies:
            cls = STRATEGY_REGISTRY.get(name)
            if cls is None:
                logger.warning("unknown_strategy", name=name)
                continue
            instance = self.build_strategy(name)
            self.executor.register_strategy(name, instance, enabled=True)

    def _uptime_str(self) -> str:
        if not self._started_at:
            return "0s"
        delta = datetime.now(tz=IST) - self._started_at
        total_sec = int(delta.total_seconds())
        hours, remainder = divmod(total_sec, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        if minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

"""Strategy performance tracker with rolling Sharpe, win-rate, and auto-disable.

Replaces the in-memory ``_strategy_reward_ema`` dict in the trading agent with a
persisted, statistically-sound tracker. Each strategy accumulates up to REWARD_WINDOW
(50) recent trade P&L values, and the rolling annualised Sharpe ratio is computed to
decide whether to auto-disable an underperforming strategy.

State is saved to disk after every trade so it survives agent restarts.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

REWARD_WINDOW: int = 50          # rolling window for Sharpe / win-rate
AUTO_DISABLE_MIN_TRADES: int = 20  # minimum trades before auto-disable can trigger
AUTO_DISABLE_SHARPE: float = -0.5  # Sharpe threshold below which strategy is disabled
_STATE_FILENAME = "strategy_performance_state.json"
_STATE_VERSION = 2


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class StrategyStats:
    """Per-strategy rolling performance statistics."""

    strategy: str
    trades: deque = field(default_factory=lambda: deque(maxlen=REWARD_WINDOW))
    reward_ema: float = 0.0
    enabled: bool = True
    disabled_reason: str = ""

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for p in self.trades if p > 0) / len(self.trades)

    @property
    def rolling_sharpe(self) -> float:
        """Annualised Sharpe ratio on the rolling window (0.0 when insufficient data)."""
        n = len(self.trades)
        if n < 5:
            return 0.0
        vals = list(self.trades)
        mean = sum(vals) / n
        variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std == 0.0:
            return 0.0
        return (mean / std) * math.sqrt(252)

    @property
    def should_auto_disable(self) -> bool:
        return self.trade_count >= AUTO_DISABLE_MIN_TRADES and self.rolling_sharpe < AUTO_DISABLE_SHARPE

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "trades": list(self.trades),
            "reward_ema": self.reward_ema,
            "enabled": self.enabled,
            "disabled_reason": self.disabled_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategyStats:
        stats = cls(strategy=data["strategy"])
        stats.trades = deque(data.get("trades", []), maxlen=REWARD_WINDOW)
        stats.reward_ema = float(data.get("reward_ema", 0.0))
        stats.enabled = bool(data.get("enabled", True))
        stats.disabled_reason = str(data.get("disabled_reason", ""))
        return stats


# ── Tracker ───────────────────────────────────────────────────────────────────

class StrategyPerformanceTracker:
    """Tracks per-strategy rolling performance and auto-disables poor performers.

    Replaces ``TradingAgent._strategy_reward_ema`` with a stateful, disk-persisted
    equivalent.  The EMA is still computed (for backward compatibility with position
    sizing), but Sharpe-driven auto-disable is the primary new capability.

    Args:
        alpha:    EMA smoothing factor (same as ``AgentConfig.reinforcement_alpha``).
        data_dir: Directory where ``strategy_performance_state.json`` is written.
    """

    def __init__(self, alpha: float, data_dir: Path) -> None:
        self._alpha = max(0.01, min(float(alpha), 1.0))
        self._state_path = Path(data_dir) / _STATE_FILENAME
        self._stats: dict[str, StrategyStats] = {}
        self._market_stats: dict[str, dict[str, StrategyStats]] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def record_trade(
        self,
        strategy: str,
        pnl_pct: float,
        market: str | None = None,
    ) -> tuple[float, bool, float]:
        """Record a closed trade outcome for a strategy.

        Args:
            strategy: Strategy name (e.g. ``"EMA_Crossover"``).
            pnl_pct:  Realised P&L as percentage of position value.

        Returns:
            ``(new_reward_ema, was_just_disabled, market_reward_ema)`` — the
            global EMA stays in sync with the existing position-sizing logic,
            while ``market_reward_ema`` tracks strategy performance inside the
            specific market bucket (when provided).
        """
        stats = self._get_or_create(strategy)
        market_key = self._normalize_market(market)
        global_reward_ema, was_just_disabled = self._apply_trade(stats, pnl_pct, strategy=strategy)

        market_reward_ema = global_reward_ema
        if market_key:
            market_stats = self._get_or_create_market(strategy, market_key)
            market_reward_ema, _ = self._apply_trade(
                market_stats,
                pnl_pct,
                strategy=strategy,
                market=market_key,
                allow_disable=False,
            )

        self._persist_state()
        return global_reward_ema, was_just_disabled, market_reward_ema

    def is_enabled(self, strategy: str) -> bool:
        """Return whether a strategy is allowed to generate signals."""
        return self._get_or_create(strategy).enabled

    def re_enable(self, strategy: str) -> None:
        """Manually re-enable a strategy and reset its rolling trade window."""
        stats = self._get_or_create(strategy)
        stats.enabled = True
        stats.disabled_reason = ""
        stats.trades.clear()  # fresh slate — old trades caused the disable
        self._persist_state()
        logger.info("strategy_re_enabled", strategy=strategy)

    def get_reward_ema(
        self,
        strategy: str,
        market: str | None = None,
        *,
        prefer_market: bool = False,
    ) -> float:
        market_key = self._normalize_market(market)
        if prefer_market and market_key:
            stats = self._get_market_stats(strategy, market_key)
            if stats is not None:
                return stats.reward_ema
        return self._get_or_create(strategy).reward_ema

    def get_trade_count(
        self,
        strategy: str,
        market: str | None = None,
        *,
        prefer_market: bool = False,
    ) -> int:
        market_key = self._normalize_market(market)
        if prefer_market and market_key:
            stats = self._get_market_stats(strategy, market_key)
            if stats is not None:
                return stats.trade_count
        return self._get_or_create(strategy).trade_count

    def get_reward_snapshot(self) -> dict[str, float]:
        return {name: round(stats.reward_ema, 6) for name, stats in self._stats.items()}

    def get_market_reward_snapshot(self) -> dict[str, dict[str, float]]:
        return {
            strategy: {
                market: round(stats.reward_ema, 6)
                for market, stats in sorted(markets.items())
            }
            for strategy, markets in sorted(self._market_stats.items())
        }

    def has_market_stats(self) -> bool:
        return any(markets for markets in self._market_stats.values())

    def seed_market_stats(self, trades: list[tuple[str, str, float]]) -> None:
        self._market_stats = {}
        for strategy, market, pnl_pct in trades:
            strategy_key = str(strategy or "").strip()
            market_key = self._normalize_market(market)
            if not strategy_key or not market_key:
                continue
            market_stats = self._get_or_create_market(strategy_key, market_key)
            self._apply_trade(
                market_stats,
                float(pnl_pct),
                strategy=strategy_key,
                market=market_key,
                allow_disable=False,
            )
        self._persist_state()

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                **stats.to_dict(),
                "rolling_sharpe": round(stats.rolling_sharpe, 4),
                "win_rate": round(stats.win_rate, 4),
                "trade_count": stats.trade_count,
                "markets": {
                    market: {
                        **market_stats.to_dict(),
                        "rolling_sharpe": round(market_stats.rolling_sharpe, 4),
                        "win_rate": round(market_stats.win_rate, 4),
                        "trade_count": market_stats.trade_count,
                    }
                    for market, market_stats in sorted(self._market_stats.get(name, {}).items())
                },
            }
            for name, stats in self._stats.items()
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def load_state(self) -> None:
        """Load persisted state from disk (call once at agent startup)."""
        if not self._state_path.exists():
            logger.debug("strategy_perf_state_not_found", path=str(self._state_path))
            return
        try:
            data = json.loads(self._state_path.read_text())
            for name, sdict in data.get("strategies", {}).items():
                self._stats[name] = StrategyStats.from_dict(sdict)
            for name, markets in data.get("strategy_markets", {}).items():
                market_map: dict[str, StrategyStats] = {}
                for market, sdict in markets.items():
                    market_map[self._normalize_market(market)] = StrategyStats.from_dict(sdict)
                if market_map:
                    self._market_stats[name] = market_map
            logger.info(
                "strategy_perf_state_loaded",
                strategies=list(self._stats.keys()),
                path=str(self._state_path),
            )
        except Exception as exc:
            logger.warning("strategy_perf_state_load_failed", error=str(exc))

    def _persist_state(self) -> None:
        """Atomically write state to disk."""
        payload: dict[str, Any] = {
            "version": _STATE_VERSION,
            "strategies": {name: s.to_dict() for name, s in self._stats.items()},
            "strategy_markets": {
                name: {market: stats.to_dict() for market, stats in markets.items()}
                for name, markets in self._market_stats.items()
            },
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=self._state_path.parent, suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, self._state_path)
        except Exception as exc:
            logger.error("strategy_perf_state_save_failed", error=str(exc))
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_or_create(self, strategy: str) -> StrategyStats:
        if strategy not in self._stats:
            self._stats[strategy] = StrategyStats(strategy=strategy)
        return self._stats[strategy]

    def _get_or_create_market(self, strategy: str, market: str) -> StrategyStats:
        market_key = self._normalize_market(market)
        if strategy not in self._market_stats:
            self._market_stats[strategy] = {}
        if market_key not in self._market_stats[strategy]:
            self._market_stats[strategy][market_key] = StrategyStats(strategy=strategy)
        return self._market_stats[strategy][market_key]

    def _get_market_stats(self, strategy: str, market: str) -> StrategyStats | None:
        market_key = self._normalize_market(market)
        return self._market_stats.get(strategy, {}).get(market_key)

    @staticmethod
    def _normalize_market(market: str | None) -> str:
        return str(market or "").strip().upper()

    def _apply_trade(
        self,
        stats: StrategyStats,
        pnl_pct: float,
        *,
        strategy: str,
        market: str | None = None,
        allow_disable: bool = True,
    ) -> tuple[float, bool]:
        was_enabled_before = stats.enabled

        stats.reward_ema = (1.0 - self._alpha) * stats.reward_ema + self._alpha * pnl_pct
        stats.trades.append(pnl_pct)

        was_just_disabled = False
        if allow_disable and was_enabled_before and stats.should_auto_disable:
            stats.enabled = False
            stats.disabled_reason = (
                f"rolling_sharpe={stats.rolling_sharpe:.2f} < {AUTO_DISABLE_SHARPE} "
                f"after {stats.trade_count} trades"
            )
            was_just_disabled = True
            logger.warning(
                "strategy_auto_disabled",
                strategy=strategy,
                market=market,
                rolling_sharpe=round(stats.rolling_sharpe, 3),
                win_rate=round(stats.win_rate, 3),
                trade_count=stats.trade_count,
            )

        return stats.reward_ema, was_just_disabled

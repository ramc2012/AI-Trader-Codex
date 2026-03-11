"""Fractal Market Profile breakout strategy.

Uses the hourly 3-minute profile sequence as the execution trigger and the
nested daily profile as the context filter. The strategy is intentionally
selective: it only trades when hourly value migration, daily alignment, and
order-flow proxies all point in the same direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd

from src.analysis.fractal_profile import (
    DailyFractalContext,
    HourlyProfile,
    TradeCandidate,
    build_daily_fractal_context,
    build_trade_candidate,
)
from src.config.market_hours import IST, US_EASTERN
from src.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class _SelectedFractalCandidate:
    candidate: TradeCandidate
    active_hour: HourlyProfile


@dataclass(frozen=True)
class _MarketFractalRules:
    min_conviction: int
    min_consecutive_hours: int
    entry_tolerance_bps: float
    entry_tolerance_ticks: float
    max_stop_pct: float
    risk_reward: float
    allow_soft_flow: bool = False


class FractalProfileBreakoutStrategy(BaseStrategy):
    """Trade nested profile continuation only on clean 3-minute structure."""

    name = "Fractal_Profile_Breakout"

    def __init__(
        self,
        *,
        min_bars: int = 60,
        min_session_bars: int = 24,
        max_bar_minutes: float = 4.1,
        min_conviction: int = 68,
        min_consecutive_hours: int = 2,
        entry_tolerance_bps: float = 6.0,
        entry_tolerance_ticks: float = 1.0,
        max_stop_pct: float = 2.5,
        risk_reward: float = 1.8,
    ) -> None:
        self.min_bars = min_bars
        self.min_session_bars = min_session_bars
        self.max_bar_minutes = max_bar_minutes
        self.min_conviction = min_conviction
        self.min_consecutive_hours = min_consecutive_hours
        self.entry_tolerance_bps = entry_tolerance_bps
        self.entry_tolerance_ticks = entry_tolerance_ticks
        self.max_stop_pct = max_stop_pct / 100.0
        self.risk_reward = risk_reward

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        frame = self._normalize_frame(data)
        if frame is None or len(frame) < self.min_bars:
            return []

        symbol, market = self._infer_symbol_and_market(frame)
        if not symbol or market not in {"NSE", "US", "CRYPTO"}:
            return []

        if self._median_bar_minutes(frame) > self.max_bar_minutes:
            return []

        session_date, current_session, prev_session = self._split_sessions(frame, market)
        if session_date is None or len(current_session) < self.min_session_bars:
            return []

        orderflow_summary = self._build_orderflow_summary(current_session)
        context = build_daily_fractal_context(
            symbol=symbol,
            market=market,
            session_date=session_date,
            current_day_candles=current_session.to_dict("records"),
            prev_day_candles=prev_session.to_dict("records"),
            orderflow_summary=orderflow_summary,
        )
        if context is None:
            return []

        selected = self._select_candidate(context, orderflow_summary)
        if selected is None:
            return []

        candidate = selected.candidate
        active_hour = selected.active_hour
        rules = self._rules_for_candidate(market, candidate, active_hour)
        if not candidate.daily_alignment:
            return []
        if candidate.consecutive_migration_hours < rules.min_consecutive_hours:
            return []
        if candidate.conviction < rules.min_conviction:
            return []
        if (
            not candidate.aggressive_flow_detected
            and not rules.allow_soft_flow
            and candidate.conviction < (rules.min_conviction + 3)
        ):
            return []

        price = float(frame["close"].iloc[-1])
        prev_price = float(frame["close"].iloc[-2])
        if price <= 0:
            return []

        tolerance = max(
            float(context.daily_profile.tick_size) * rules.entry_tolerance_ticks,
            price * (rules.entry_tolerance_bps / 10_000.0),
        )

        timestamp = frame["timestamp"].iloc[-1]
        signal_time = timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else timestamp

        if candidate.direction == "bullish":
            triggered = price >= (candidate.entry_trigger - tolerance) and prev_price < (candidate.entry_trigger + tolerance)
            risk = price - float(candidate.stop_reference)
            if not triggered or risk <= 0:
                return []
            if (risk / price) > rules.max_stop_pct:
                return []
            target_rr = float(candidate.adaptive_risk_reward or rules.risk_reward)
            target = float(candidate.target_reference) if candidate.target_reference is not None else price + (risk * target_rr)
            if target <= price:
                target = price + (risk * target_rr)
            signal_type = SignalType.BUY
        else:
            triggered = price <= (candidate.entry_trigger + tolerance) and prev_price > (candidate.entry_trigger - tolerance)
            risk = float(candidate.stop_reference) - price
            if not triggered or risk <= 0:
                return []
            if (risk / price) > rules.max_stop_pct:
                return []
            target_rr = float(candidate.adaptive_risk_reward or rules.risk_reward)
            target = float(candidate.target_reference) if candidate.target_reference is not None else price - (risk * target_rr)
            if target >= price:
                target = price - (risk * target_rr)
            signal_type = SignalType.SELL

        strength = self._strength(candidate.conviction)
        signal = Signal(
            timestamp=signal_time,
            symbol=symbol,
            signal_type=signal_type,
            strength=strength,
            price=round(price, 2),
            stop_loss=round(float(candidate.stop_reference), 2),
            target=round(float(target), 2),
            strategy_name=self.name,
            metadata={
                "market": market,
                "conviction": candidate.conviction,
                "direction": candidate.direction,
                "hourly_shape": candidate.hourly_shape,
                "consecutive_migration_hours": candidate.consecutive_migration_hours,
                "setup_type": candidate.setup_type,
                "value_acceptance": candidate.value_acceptance,
                "daily_alignment": candidate.daily_alignment,
                "aggressive_flow_detected": candidate.aggressive_flow_detected,
                "entry_trigger": round(float(candidate.entry_trigger), 4),
                "stop_reference": round(float(candidate.stop_reference), 4),
                "target_reference": None if candidate.target_reference is None else round(float(candidate.target_reference), 4),
                "position_size_multiplier": round(float(candidate.position_size_multiplier), 3),
                "adaptive_risk_reward": round(float(candidate.adaptive_risk_reward), 3),
                "exhaustion_warning": bool(candidate.exhaustion_warning),
                "rationale": candidate.rationale,
                "daily_shape": context.daily_profile.shape,
                "daily_poc": round(float(context.daily_profile.poc), 4),
                "daily_vah": round(float(context.daily_profile.vah), 4),
                "daily_val": round(float(context.daily_profile.val), 4),
                "active_hour_start": active_hour.start.isoformat(),
                "active_hour_shape": active_hour.shape,
                "active_hour_vah": round(float(active_hour.vah), 4),
                "active_hour_val": round(float(active_hour.val), 4),
                "active_hour_poc": round(float(active_hour.poc), 4),
                "active_hour_periods": int(active_hour.period_count),
                "active_hour_overlap_ratio": round(float(active_hour.va_overlap_ratio), 4),
                "market_rule_profile": {
                    "market": market,
                    "min_conviction": int(rules.min_conviction),
                    "min_consecutive_hours": int(rules.min_consecutive_hours),
                    "entry_tolerance_bps": round(float(rules.entry_tolerance_bps), 2),
                    "entry_tolerance_ticks": round(float(rules.entry_tolerance_ticks), 2),
                    "max_stop_pct": round(float(rules.max_stop_pct) * 100.0, 2),
                    "risk_reward": round(float(rules.risk_reward), 3),
                    "allow_soft_flow": bool(rules.allow_soft_flow),
                },
                "orderflow_summary": dict(candidate.orderflow_summary),
            },
        )

        logger.debug(
            "fractal_profile_signal_generated",
            symbol=symbol,
            market=market,
            direction=signal.signal_type.value,
            price=signal.price,
            conviction=candidate.conviction,
            active_hour_start=active_hour.start.isoformat(),
        )
        return [signal]

    @staticmethod
    def _strength(conviction: int) -> SignalStrength:
        if conviction >= 82:
            return SignalStrength.STRONG
        if conviction >= 68:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK

    @staticmethod
    def _to_ist_naive(value: Any) -> pd.Timestamp | pd.NaT:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return pd.NaT
        if getattr(ts, "tzinfo", None) is not None:
            return ts.tz_convert(IST).tz_localize(None)
        return ts

    def _normalize_frame(self, data: pd.DataFrame) -> pd.DataFrame | None:
        if data is None or data.empty or "timestamp" not in data.columns:
            return None

        frame = data.copy()
        frame["timestamp"] = frame["timestamp"].apply(self._to_ist_naive)
        for column in ("open", "high", "low", "close"):
            frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
        if "volume" in frame.columns:
            frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
        else:
            frame["volume"] = 0.0
        frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
        if frame.empty:
            return None
        return frame.sort_values("timestamp").reset_index(drop=True)

    @staticmethod
    def _infer_symbol_and_market(frame: pd.DataFrame) -> tuple[str, str]:
        symbol = ""
        if "symbol" in frame.columns and not frame["symbol"].dropna().empty:
            symbol = str(frame["symbol"].dropna().iloc[-1]).strip()
        if not symbol:
            return "", ""

        venue = symbol.split(":")[0].upper()
        if venue in {"NSE", "BSE"}:
            return symbol, "NSE"
        if venue == "US":
            return symbol, "US"
        if venue == "CRYPTO":
            return symbol, "CRYPTO"
        return symbol, ""

    @staticmethod
    def _median_bar_minutes(frame: pd.DataFrame) -> float:
        if len(frame) < 3:
            return 999.0
        diffs = frame["timestamp"].diff().dropna().dt.total_seconds().div(60.0)
        if diffs.empty:
            return 999.0
        return float(diffs.tail(30).median())

    @staticmethod
    def _session_key(timestamp: pd.Timestamp, market: str) -> date:
        if market == "US":
            eastern = timestamp.replace(tzinfo=IST).astimezone(US_EASTERN)
            return eastern.date()
        if market == "CRYPTO":
            return timestamp.date()
        return timestamp.date()

    def _split_sessions(
        self,
        frame: pd.DataFrame,
        market: str,
    ) -> tuple[datetime | None, pd.DataFrame, pd.DataFrame]:
        tmp = frame.copy()
        tmp["session_key"] = tmp["timestamp"].apply(lambda ts: self._session_key(ts, market))
        sessions = sorted(tmp["session_key"].dropna().unique())
        if not sessions:
            return None, pd.DataFrame(), pd.DataFrame()

        current_key = sessions[-1]
        prev_key = sessions[-2] if len(sessions) > 1 else None
        current_session = tmp[tmp["session_key"] == current_key].drop(columns=["session_key"])
        prev_session = (
            tmp[tmp["session_key"] == prev_key].drop(columns=["session_key"])
            if prev_key is not None
            else pd.DataFrame(columns=current_session.columns)
        )
        session_date = datetime.combine(current_key, time(0, 0))
        return session_date, current_session.reset_index(drop=True), prev_session.reset_index(drop=True)

    @staticmethod
    def _build_orderflow_summary(frame: pd.DataFrame) -> dict[str, Any]:
        recent = frame.tail(18).copy()
        bodies = recent["close"] - recent["open"]
        direction = bodies.apply(lambda value: 1.0 if value > 0 else (-1.0 if value < 0 else 0.0))
        signed_volume = direction * recent["volume"].clip(lower=0.0)
        total_volume = float(recent["volume"].sum())
        positive_volume = float(recent.loc[bodies > 0, "volume"].sum())
        delta_total = float(signed_volume.sum())
        latest_delta = float(signed_volume.tail(5).sum())
        avg_buying_pressure = positive_volume / max(total_volume, 1.0)
        imbalance_ratio = abs(delta_total) / max(total_volume, 1.0)
        delta_trend = "flat"
        if delta_total > total_volume * 0.08:
            delta_trend = "up"
        elif delta_total < -(total_volume * 0.08):
            delta_trend = "down"
        return {
            "delta_trend": delta_trend,
            "avg_buying_pressure": avg_buying_pressure,
            "latest_delta": latest_delta,
            "imbalance_ratio": imbalance_ratio,
        }

    def _rules_for_candidate(
        self,
        market: str,
        candidate: TradeCandidate,
        active_hour: HourlyProfile,
    ) -> _MarketFractalRules:
        min_conviction = int(self.min_conviction)
        min_consecutive_hours = int(self.min_consecutive_hours)
        entry_tolerance_bps = float(self.entry_tolerance_bps)
        entry_tolerance_ticks = float(self.entry_tolerance_ticks)
        max_stop_pct = float(self.max_stop_pct)
        risk_reward = float(self.risk_reward)
        allow_soft_flow = False

        market_key = str(market or "").upper()
        if market_key == "US":
            min_conviction = max(min_conviction - 4, 60)
            min_consecutive_hours = max(min_consecutive_hours - 1, 1)
            entry_tolerance_bps = max(entry_tolerance_bps, 8.0)
            entry_tolerance_ticks = max(entry_tolerance_ticks, 2.0)
            max_stop_pct = max(max_stop_pct, 0.028)
            risk_reward = max(risk_reward, 1.9)
            allow_soft_flow = candidate.setup_type in {"acceptance_trend", "gap_and_go"}
        elif market_key == "CRYPTO":
            min_conviction = max(min_conviction + 4, 72)
            min_consecutive_hours = max(min_consecutive_hours, 2)
            entry_tolerance_bps = max(entry_tolerance_bps, 12.0)
            entry_tolerance_ticks = max(entry_tolerance_ticks, 2.0)
            max_stop_pct = min(max_stop_pct, 0.018)
            risk_reward = min(max(risk_reward, 1.55), 1.75)
        else:
            min_conviction = max(min_conviction - 2, 64)
            entry_tolerance_bps = max(entry_tolerance_bps, 7.0)
            risk_reward = max(risk_reward, 1.85)
            allow_soft_flow = candidate.setup_type == "acceptance_trend"

        if candidate.setup_type == "acceptance_trend":
            min_conviction -= 4 if market_key in {"NSE", "US"} else 0
        elif candidate.setup_type == "gap_and_go":
            min_conviction -= 2 if market_key == "US" else 0
            min_conviction += 4 if market_key == "CRYPTO" else 0
        elif candidate.setup_type == "breakout_drive" and market_key == "CRYPTO":
            min_conviction += 6

        if candidate.value_acceptance == "accepted":
            min_conviction -= 2
        elif candidate.value_acceptance == "balanced":
            min_conviction += 4 if market_key == "CRYPTO" else 2
        elif candidate.value_acceptance == "mixed" and market_key == "CRYPTO":
            min_conviction += 2

        if active_hour.va_overlap_ratio >= 0.35 and market_key in {"NSE", "US"}:
            min_conviction -= 2
            if market_key == "US":
                min_consecutive_hours = max(min_consecutive_hours - 1, 1)

        if candidate.consecutive_migration_hours >= 3 and market_key in {"NSE", "US"}:
            min_conviction -= 2

        floor = 68 if market_key == "CRYPTO" else 58 if market_key == "US" else 60
        return _MarketFractalRules(
            min_conviction=max(int(min_conviction), floor),
            min_consecutive_hours=max(int(min_consecutive_hours), 1),
            entry_tolerance_bps=entry_tolerance_bps,
            entry_tolerance_ticks=entry_tolerance_ticks,
            max_stop_pct=max_stop_pct,
            risk_reward=risk_reward,
            allow_soft_flow=allow_soft_flow,
        )

    def _select_candidate(
        self,
        context: DailyFractalContext,
        orderflow_summary: dict[str, Any],
    ) -> _SelectedFractalCandidate | None:
        candidate = context.candidate
        active_hour = context.hourly_profiles[-1] if context.hourly_profiles else None
        if candidate is not None and active_hour is not None:
            return _SelectedFractalCandidate(candidate=candidate, active_hour=active_hour)

        if len(context.hourly_profiles) <= 1:
            return None

        last_hour = context.hourly_profiles[-1]
        if last_hour.period_count >= 8:
            return None

        trimmed_profiles = context.hourly_profiles[:-1]
        fallback_candidate = build_trade_candidate(
            symbol=context.symbol,
            daily_profile=context.daily_profile,
            hourly_profiles=trimmed_profiles,
            prev_day_profile=context.prev_day_profile,
            orderflow_summary=orderflow_summary,
            option_flow=None,
        )
        if fallback_candidate is None:
            return None
        return _SelectedFractalCandidate(candidate=fallback_candidate, active_hour=trimmed_profiles[-1])

    def __repr__(self) -> str:
        return (
            f"<FractalProfileBreakoutStrategy(min_conviction={self.min_conviction}, "
            f"min_consecutive_hours={self.min_consecutive_hours}, "
            f"entry_tolerance_bps={self.entry_tolerance_bps})>"
        )

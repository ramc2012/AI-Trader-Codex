"""Market Profile + Orderflow breakout strategy.

Combines:
- Market Profile structure (POC / VAH / VAL)
- Volume-delta proxy from candle bodies (orderflow pressure)
- ATR risk framing for stop/target

Designed for fast intraday execution windows (3m/5m/15m).
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd

from src.analysis.indicators import ATR
from src.analysis.order_flow import OrderFlowAnalyzer
from src.analysis.tpo_engine import compute_tpo_profile
from src.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class _ProfileCandle:
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: int


class MarketProfileOrderFlowStrategy(BaseStrategy):
    """Breakout strategy using Market Profile levels + orderflow pressure."""

    name = "MP_OrderFlow_Breakout"

    def __init__(
        self,
        profile_lookback: int = 90,
        delta_lookback: int = 10,
        atr_period: int = 14,
        breakout_buffer_pct: float = 0.06,
        risk_reward: float = 1.8,
        min_volume_ratio: float = 1.05,
        min_imbalance_ratio: float = 0.08,
        conviction_floor: float = 58.0,
        crypto_breakout_buffer_pct: float = 0.10,
        crypto_flow_threshold: float = 0.14,
    ) -> None:
        self.profile_lookback = profile_lookback
        self.delta_lookback = delta_lookback
        self.atr_period = atr_period
        self.breakout_buffer_pct = breakout_buffer_pct / 100.0
        self.risk_reward = risk_reward
        self.min_volume_ratio = min_volume_ratio
        self.min_imbalance_ratio = min_imbalance_ratio
        self.conviction_floor = conviction_floor
        self.crypto_breakout_buffer_pct = crypto_breakout_buffer_pct / 100.0
        self.crypto_flow_threshold = crypto_flow_threshold
        self._atr = ATR(period=atr_period)

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        min_rows = max(self.atr_period + 5, self.profile_lookback // 2)
        if len(data) < min_rows:
            return []

        frame = data.copy()
        for col in ("open", "high", "low", "close", "volume"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
        if len(frame) < min_rows:
            return []

        symbol = str(data.get("symbol", [""])[0]) if "symbol" in data.columns else ""
        market = self._market_of_symbol(symbol)
        bar_minutes = self._infer_bar_minutes(frame)
        recent = frame.tail(self.profile_lookback)
        profile_candles: list[_ProfileCandle] = []
        for _, row in recent.iterrows():
            ts = row.get("timestamp")
            if ts is None:
                ts = row.name
            ts = pd.to_datetime(ts)
            profile_candles.append(
                _ProfileCandle(
                    timestamp=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["volume"]),
                )
            )

        profile = compute_tpo_profile(profile_candles, tick_size=None, value_area_pct=0.70)
        if profile is None:
            return []

        closes = recent["close"].astype(float)
        opens = recent["open"].astype(float)
        highs = recent["high"].astype(float)
        lows = recent["low"].astype(float)
        volumes = recent["volume"].astype(float).clip(lower=0.0)

        # Orderflow proxy: candle body direction × traded volume.
        body_sign = (closes - opens).apply(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0))
        delta_proxy = body_sign * volumes
        delta_bias = float(delta_proxy.tail(self.delta_lookback).sum())
        total_recent_volume = float(volumes.tail(self.delta_lookback).sum())
        flow_pressure = delta_bias / max(total_recent_volume, 1.0)
        avg_recent_volume = float(volumes.tail(max(self.delta_lookback, 3)).mean() or 0.0)
        latest_volume = float(volumes.iloc[-1] or 0.0)
        volume_ratio = latest_volume / max(avg_recent_volume, 1.0)

        price = float(closes.iloc[-1])
        prev_price = float(closes.iloc[-2])
        vwap = float((closes * volumes).sum() / max(float(volumes.sum()), 1.0))

        atr_series = self._atr.calculate(closes, high=highs, low=lows)
        atr_value = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else max(price * 0.0025, 0.5)

        orderflow_summary = self._orderflow_summary(recent, bar_minutes)
        avg_buy_pressure = float(orderflow_summary.get("avg_buying_pressure", 0.5))
        imbalance_ratio = float(orderflow_summary.get("imbalance_ratio", 0.0))
        latest_delta = float(orderflow_summary.get("latest_delta", 0.0))
        delta_trend = str(orderflow_summary.get("delta_trend", "flat"))
        stacked_levels = int(orderflow_summary.get("stacked_levels", 0))

        buffer_pct = self.breakout_buffer_pct
        flow_threshold = 0.10
        conviction_floor = self.conviction_floor
        min_volume_ratio = self.min_volume_ratio
        min_imbalance_ratio = self.min_imbalance_ratio
        if market == "CRYPTO":
            buffer_pct = max(self.breakout_buffer_pct, self.crypto_breakout_buffer_pct)
            flow_threshold = max(flow_threshold, self.crypto_flow_threshold)
            conviction_floor = max(conviction_floor, 64.0)
            min_volume_ratio = max(min_volume_ratio, 1.12)
            min_imbalance_ratio = max(min_imbalance_ratio, 0.10)
        elif bar_minutes <= 3:
            conviction_floor = max(conviction_floor, 62.0)
            min_volume_ratio = max(min_volume_ratio, 1.08)

        up_trigger = float(profile.vah) * (1.0 + buffer_pct)
        down_trigger = float(profile.val) * (1.0 - buffer_pct)
        buy_breakout = price > up_trigger and prev_price <= up_trigger
        sell_breakout = price < down_trigger and prev_price >= down_trigger
        upward_momentum = price > float(closes.iloc[-3])
        downward_momentum = price < float(closes.iloc[-3])
        buy_reclaim = (
            price >= float(profile.vah) * (1.0 - (buffer_pct * 0.5))
            and flow_pressure > (flow_threshold + 0.02)
            and upward_momentum
        )
        sell_reject = (
            price <= float(profile.val) * (1.0 + (buffer_pct * 0.5))
            and flow_pressure < -(flow_threshold + 0.02)
            and downward_momentum
        )

        buy_orderflow_ok = (
            delta_bias > 0
            and flow_pressure >= flow_threshold
            and avg_buy_pressure >= 0.53
            and latest_delta >= 0
            and delta_trend != "down"
            and imbalance_ratio >= min_imbalance_ratio
            and volume_ratio >= min_volume_ratio
        )
        sell_orderflow_ok = (
            delta_bias < 0
            and flow_pressure <= -flow_threshold
            and avg_buy_pressure <= 0.47
            and latest_delta <= 0
            and delta_trend != "up"
            and imbalance_ratio >= min_imbalance_ratio
            and volume_ratio >= min_volume_ratio
        )

        poc = float(profile.poc)
        vah = float(profile.vah)
        val = float(profile.val)
        value_area_width = abs(vah - val)
        value_area_width_pct = value_area_width / max(price, 1.0)
        poc_distance_atr = abs(price - poc) / max(atr_value, 1e-6)

        buy_ok = (buy_breakout or buy_reclaim) and buy_orderflow_ok and price >= vwap and price >= poc
        sell_ok = (sell_breakout or sell_reject) and sell_orderflow_ok and price <= vwap and price <= poc

        if not buy_ok and not sell_ok:
            return []

        conviction_score = self._conviction_score(
            market=market,
            buy_ok=buy_ok,
            sell_ok=sell_ok,
            breakout=buy_breakout or sell_breakout,
            reclaim=buy_reclaim or sell_reject,
            flow_pressure=flow_pressure,
            volume_ratio=volume_ratio,
            imbalance_ratio=imbalance_ratio,
            stacked_levels=stacked_levels,
            avg_buy_pressure=avg_buy_pressure,
            delta_trend=delta_trend,
            price=price,
            vwap=vwap,
            value_area_width_pct=value_area_width_pct,
            poc_distance_atr=poc_distance_atr,
        )
        if conviction_score < conviction_floor:
            return []

        if conviction_score >= 78:
            strength = SignalStrength.STRONG
        elif conviction_score >= 64:
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK

        signal_type = SignalType.BUY if buy_ok else SignalType.SELL
        adaptive_risk_reward = self._adaptive_risk_reward(market, conviction_score)
        if signal_type == SignalType.BUY:
            stop_loss = min(poc, price - (atr_value * 1.15))
            risk = max(price - stop_loss, atr_value * 0.6)
            target = price + (risk * adaptive_risk_reward)
        else:
            stop_loss = max(poc, price + (atr_value * 1.15))
            risk = max(stop_loss - price, atr_value * 0.6)
            target = price - (risk * adaptive_risk_reward)

        ts_raw = recent["timestamp"].iloc[-1] if "timestamp" in recent.columns else recent.index[-1]
        timestamp = pd.to_datetime(ts_raw).to_pydatetime()

        signal = Signal(
            timestamp=timestamp,
            symbol=symbol,
            signal_type=signal_type,
            strength=strength,
            price=round(price, 2),
            stop_loss=round(float(stop_loss), 2),
            target=round(float(target), 2),
            strategy_name=self.name,
            metadata={
                "poc": round(poc, 2),
                "vah": round(vah, 2),
                "val": round(val, 2),
                "vwap": round(vwap, 2),
                "delta_bias": round(delta_bias, 2),
                "flow_pressure": round(flow_pressure, 4),
                "atr": round(atr_value, 2),
                "market": market,
                "bar_minutes": bar_minutes,
                "volume_ratio": round(volume_ratio, 3),
                "conviction_score": round(conviction_score, 1),
                "position_size_multiplier": round(self._size_multiplier(conviction_score), 3),
                "adaptive_risk_reward": round(adaptive_risk_reward, 3),
                "value_area_width_pct": round(value_area_width_pct, 4),
                "poc_distance_atr": round(poc_distance_atr, 4),
                "orderflow_summary": {
                    "avg_buying_pressure": round(avg_buy_pressure, 4),
                    "imbalance_ratio": round(imbalance_ratio, 4),
                    "latest_delta": round(latest_delta, 2),
                    "delta_trend": delta_trend,
                    "stacked_levels": stacked_levels,
                },
            },
        )

        logger.debug(
            "signals_generated",
            strategy=self.name,
            direction=signal.signal_type.value,
            price=signal.price,
            poc=profile.poc,
            vah=profile.vah,
            val=profile.val,
            delta_bias=delta_bias,
        )
        return [signal]

    def __repr__(self) -> str:
        return (
            f"<MarketProfileOrderFlowStrategy(lookback={self.profile_lookback}, "
            f"delta_lookback={self.delta_lookback}, atr_period={self.atr_period})>"
        )

    @staticmethod
    def _market_of_symbol(symbol: str) -> str:
        token = str(symbol or "").upper().strip()
        if token.startswith("CRYPTO:"):
            return "CRYPTO"
        if token.startswith(("US:", "NASDAQ:", "NYSE:", "AMEX:")):
            return "US"
        return "NSE"

    @staticmethod
    def _infer_bar_minutes(frame: pd.DataFrame) -> int:
        timestamps = pd.to_datetime(frame.get("timestamp"), errors="coerce").dropna()
        if len(timestamps) < 2:
            return 5
        diffs = timestamps.diff().dropna()
        if diffs.empty:
            return 5
        median_seconds = float(diffs.dt.total_seconds().median())
        if not math.isfinite(median_seconds) or median_seconds <= 0:
            return 5
        return max(int(round(median_seconds / 60.0)), 1)

    def _orderflow_summary(self, frame: pd.DataFrame, bar_minutes: int) -> dict[str, float | int | str]:
        try:
            analyzer = OrderFlowAnalyzer.from_dataframe(frame)
            footprints = analyzer.build_footprints(
                frame[["timestamp", "open", "high", "low", "close", "volume"]].to_dict("records"),
                bar_minutes=max(bar_minutes, 1),
            )
            if not footprints:
                return {
                    "avg_buying_pressure": 0.5,
                    "imbalance_ratio": 0.0,
                    "latest_delta": 0.0,
                    "delta_trend": "flat",
                    "stacked_levels": 0,
                }
            return analyzer.summarize(footprints[-max(self.delta_lookback, 3):])
        except Exception:
            return {
                "avg_buying_pressure": 0.5,
                "imbalance_ratio": 0.0,
                "latest_delta": 0.0,
                "delta_trend": "flat",
                "stacked_levels": 0,
            }

    def _conviction_score(
        self,
        *,
        market: str,
        buy_ok: bool,
        sell_ok: bool,
        breakout: bool,
        reclaim: bool,
        flow_pressure: float,
        volume_ratio: float,
        imbalance_ratio: float,
        stacked_levels: int,
        avg_buy_pressure: float,
        delta_trend: str,
        price: float,
        vwap: float,
        value_area_width_pct: float,
        poc_distance_atr: float,
    ) -> float:
        score = 35.0
        if buy_ok or sell_ok:
            score += 10.0
        if breakout:
            score += 16.0
        elif reclaim:
            score += 10.0
        score += min(abs(flow_pressure) * 110.0, 18.0)
        score += min(max(volume_ratio - 1.0, 0.0) * 20.0, 14.0)
        score += min(imbalance_ratio * 100.0, 14.0)
        score += min(stacked_levels * 1.5, 8.0)
        if delta_trend in {"up", "down"}:
            score += 4.0
        if price >= vwap and avg_buy_pressure > 0.5:
            score += 3.0
        if price <= vwap and avg_buy_pressure < 0.5:
            score += 3.0
        if value_area_width_pct <= 0.012:
            score += 4.0
        if poc_distance_atr >= 0.35:
            score += 4.0
        if market == "CRYPTO":
            score -= 4.0
            if value_area_width_pct <= 0.02:
                score += 2.0
        return max(0.0, min(score, 100.0))

    def _adaptive_risk_reward(self, market: str, conviction_score: float) -> float:
        reward = self.risk_reward
        if conviction_score >= 82:
            reward += 0.35
        elif conviction_score >= 72:
            reward += 0.15
        if market == "CRYPTO":
            reward = max(reward - 0.1, 1.4)
        return max(reward, 1.2)

    @staticmethod
    def _size_multiplier(conviction_score: float) -> float:
        if conviction_score >= 84:
            return 1.35
        if conviction_score >= 72:
            return 1.15
        if conviction_score >= 60:
            return 1.0
        return 0.85

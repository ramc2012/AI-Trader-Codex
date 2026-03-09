"""Generate trading signals from one or more ML direction predictors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from src.ml.features.feature_extractor import UnifiedFeatureExtractor
from src.ml.models.direction_predictor import DirectionPredictor
from src.strategies.base import Signal, SignalStrength, SignalType
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class EnsembleOutput:
    """Internal container for ensemble output."""

    probabilities: dict[str, float]
    direction: str
    confidence: float


class SignalGenerator:
    """Create BUY/SELL signals from weighted ML model predictions."""

    def __init__(
        self,
        models: list[DirectionPredictor],
        weights: list[float] | None = None,
        feature_extractor: UnifiedFeatureExtractor | None = None,
        confidence_threshold: float = 0.60,
        atr_multiplier: float = 1.25,
        risk_reward_ratio: float = 2.0,
    ) -> None:
        if not models:
            raise ValueError("SignalGenerator requires at least one model.")
        if not 0.0 < confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1.")

        self.models = models
        self.feature_extractor = feature_extractor or UnifiedFeatureExtractor()
        self.confidence_threshold = confidence_threshold
        self.atr_multiplier = atr_multiplier
        self.risk_reward_ratio = risk_reward_ratio
        self.weights = self._normalize_weights(weights, len(models))

    @staticmethod
    def _normalize_weights(weights: list[float] | None, count: int) -> list[float]:
        if weights is None:
            return [1.0 / count] * count
        if len(weights) != count:
            raise ValueError("weights length must match models length.")
        total = float(sum(max(w, 0.0) for w in weights))
        if total <= 0:
            return [1.0 / count] * count
        return [max(w, 0.0) / total for w in weights]

    def _prepare_features(self, data: pd.DataFrame) -> np.ndarray:
        if data.empty:
            raise ValueError("Input data is empty.")
        if not self.feature_extractor.pipeline.is_fitted:  # type: ignore[attr-defined]
            # Live-safe fallback: fit once on recent history when extractor
            # has not been loaded from training artifacts.
            self.feature_extractor.fit(data)
        transformed = self.feature_extractor.transform(data)
        transformed = transformed.replace([np.inf, -np.inf], np.nan).dropna()
        if transformed.empty:
            raise ValueError("No valid feature rows after transformation.")
        return transformed.values.astype(float)

    def _ensemble(self, features: np.ndarray) -> EnsembleOutput:
        latest = features[-1:].astype(float)
        probs_list: list[np.ndarray] = []

        for model in self.models:
            if not model.is_fitted:
                raise RuntimeError("All models must be fitted before generating signals.")
            probs = model.predict_proba(latest)[0]
            probs_list.append(probs)

        stacked = np.vstack(probs_list)
        combined = np.average(stacked, axis=0, weights=self.weights)

        labels = DirectionPredictor.DEFAULT_CLASSES
        direction_idx = int(np.argmax(combined))
        direction = labels[direction_idx]
        confidence = float(combined[direction_idx])
        probs_map = {labels[i]: float(combined[i]) for i in range(len(labels))}
        return EnsembleOutput(probabilities=probs_map, direction=direction, confidence=confidence)

    def _compute_stop_target(
        self,
        data: pd.DataFrame,
        side: SignalType,
    ) -> tuple[float | None, float | None]:
        if len(data) < 5:
            return None, None

        close = float(data["close"].iloc[-1])
        high = data["high"].astype(float)
        low = data["low"].astype(float)
        atr_proxy = float((high - low).tail(14).mean())
        if atr_proxy <= 0:
            return None, None

        risk = atr_proxy * self.atr_multiplier
        if side == SignalType.BUY:
            stop = close - risk
            target = close + (risk * self.risk_reward_ratio)
        else:
            stop = close + risk
            target = close - (risk * self.risk_reward_ratio)

        return float(stop), float(target)

    @staticmethod
    def _strength(confidence: float) -> SignalStrength:
        if confidence >= 0.80:
            return SignalStrength.STRONG
        if confidence >= 0.65:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK

    def generate_signal(
        self,
        data: pd.DataFrame,
        symbol: str,
        confidence_threshold: float | None = None,
    ) -> Signal | None:
        """Generate a single actionable signal from latest data point."""
        threshold = confidence_threshold or self.confidence_threshold
        features = self._prepare_features(data)
        output = self._ensemble(features)

        if output.confidence < threshold or output.direction == "neutral":
            return None

        side = SignalType.BUY if output.direction == "up" else SignalType.SELL
        close = float(data["close"].iloc[-1])
        stop, target = self._compute_stop_target(data, side)
        ts = data.index[-1]
        timestamp = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else datetime.utcnow()

        return Signal(
            timestamp=timestamp,
            symbol=symbol,
            signal_type=side,
            strength=self._strength(output.confidence),
            price=close,
            stop_loss=stop,
            target=target,
            strategy_name="ML_Ensemble",
            metadata={
                "confidence": round(output.confidence, 4),
                "probabilities": output.probabilities,
                "models": [m.model_type for m in self.models],
                "weights": self.weights,
            },
        )

    def generate_signals(
        self,
        data_by_symbol: dict[str, pd.DataFrame],
        confidence_threshold: float | None = None,
    ) -> list[Signal]:
        """Generate signals for multiple symbols."""
        out: list[Signal] = []
        for symbol, frame in data_by_symbol.items():
            try:
                signal = self.generate_signal(frame, symbol, confidence_threshold)
                if signal is not None:
                    out.append(signal)
            except Exception as exc:
                logger.warning("ml_signal_generation_failed", symbol=symbol, error=str(exc))
        return out


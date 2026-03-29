"""ML ensemble strategy wrapper for autonomous agent execution."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from src.ml.features.feature_extractor import UnifiedFeatureExtractor
from src.ml.models.direction_predictor import DirectionPredictor
from src.ml.signals.signal_generator import SignalGenerator
from src.strategies.base import BaseStrategy, Signal
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MLEnsembleStrategy(BaseStrategy):
    """Generate BUY/SELL signals from trained ML direction models.

    The strategy is intentionally fail-safe: when model artifacts are not
    available, it returns no signals instead of raising runtime errors.
    """

    name = "ML_Ensemble"

    def __init__(
        self,
        model_paths: list[str] | None = None,
        confidence_threshold: float = 0.62,
    ) -> None:
        self.model_paths = model_paths or self._default_model_paths()
        self.confidence_threshold = confidence_threshold
        self._models: list[DirectionPredictor] = []
        self._signal_generator: SignalGenerator | None = None
        self._load_attempted = False

    def _default_model_paths(self) -> list[str]:
        env_paths = os.environ.get("AI_MODEL_PATHS", "").strip()
        if env_paths:
            return [p.strip() for p in env_paths.split(",") if p.strip()]
        return [
            "models/direction_predictor.joblib",
            "models/direction_predictor_gbm.joblib",
            "models/direction_predictor_xgb.joblib",
        ]

    def _ensure_loaded(self) -> None:
        if self._load_attempted:
            return
        self._load_attempted = True

        from src.ml.inference.engine import MLInferenceEngine
        self._engine = MLInferenceEngine(self.model_paths)
        self._engine.load_models()
        
        if self._engine.is_loaded and self._engine.models:
            logger.info("ml_ensemble_loaded", models=len(self._engine.models))
        else:
            logger.warning("ml_ensemble_no_models_loaded", paths=self.model_paths)

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        self._ensure_loaded()
        if not hasattr(self, '_engine') or not self._engine.is_loaded or data.empty:
            return []

        symbol = ""
        if "symbol" in data.columns and len(data["symbol"]) > 0:
            symbol = str(data["symbol"].iloc[-1])

        try:
            # Get prediction dictionary from the inference engine
            pred_dict = self._engine.predict(data, symbol)
            direction = pred_dict.get("predicted_direction", "neutral")
            confidence = pred_dict.get("confidence", 0.0)
            latency = pred_dict.get("latency_ms", 0.0)
            
            if direction == "neutral" or confidence < self.confidence_threshold:
                return []
                
            signal_type = "BUY" if direction == "buy" else "SELL"
            
            # Formulate the signal
            close_price = float(data["close"].iloc[-1])
            is_buy = signal_type == "BUY"
            
            # Simple ML Target mapping based on ATR or fixed %
            atr = float(data["atr"].iloc[-1]) if "atr" in data.columns else close_price * 0.005
            target_distance = atr * 2.0
            stop_distance = atr * 1.5
            
            target = close_price + target_distance if is_buy else close_price - target_distance
            stop_loss = close_price - stop_distance if is_buy else close_price + stop_distance
            
            signal = Signal(
                symbol=symbol,
                signal_type=signal_type,
                price=close_price,
                target=target,
                stop_loss=stop_loss,
                conviction=min(100, int(confidence * 100)),
                metadata={
                    "model_latency_ms": round(latency, 2),
                    "confidence_score": round(confidence, 3),
                    "ml_features": pred_dict.get("features", {})
                }
            )
            return [signal]
        except Exception as exc:
            logger.warning("ml_ensemble_signal_failed", error=str(exc))
            return []


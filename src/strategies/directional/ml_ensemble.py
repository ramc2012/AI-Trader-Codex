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

        loaded: list[DirectionPredictor] = []
        for path in self.model_paths:
            try:
                if not Path(path).exists():
                    continue
                loaded.append(DirectionPredictor.load(path))
            except Exception as exc:
                logger.warning("ml_model_load_failed", path=path, error=str(exc))

        self._models = loaded
        if not self._models:
            logger.warning("ml_ensemble_no_models_loaded", paths=self.model_paths)
            return

        extractor = UnifiedFeatureExtractor(use_option_features=True)
        self._signal_generator = SignalGenerator(
            models=self._models,
            feature_extractor=extractor,
            confidence_threshold=self.confidence_threshold,
        )
        logger.info("ml_ensemble_loaded", models=len(self._models))

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        self._ensure_loaded()
        if self._signal_generator is None or data.empty:
            return []

        symbol = ""
        if "symbol" in data.columns and len(data["symbol"]) > 0:
            symbol = str(data["symbol"].iloc[-1])

        try:
            signal = self._signal_generator.generate_signal(
                data=data,
                symbol=symbol,
                confidence_threshold=self.confidence_threshold,
            )
            return [signal] if signal is not None else []
        except Exception as exc:
            logger.warning("ml_ensemble_signal_failed", error=str(exc))
            return []


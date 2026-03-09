"""Model training orchestration for ML direction models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.ml.features.feature_extractor import UnifiedFeatureExtractor
from src.ml.models.direction_predictor import DirectionPredictor
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TrainerConfig:
    """Configuration for dataset preparation and validation."""

    horizon: int = 1
    neutral_threshold: float = 0.001
    train_ratio: float = 0.70
    val_ratio: float = 0.15
    use_option_features: bool = True
    pca_components: float | int | None = None


class ModelTrainer:
    """Train/evaluate direction predictors using time-series-safe splits."""

    def __init__(self, config: dict[str, Any] | TrainerConfig | None = None) -> None:
        if config is None:
            self.config = TrainerConfig()
        elif isinstance(config, TrainerConfig):
            self.config = config
        else:
            self.config = TrainerConfig(**config)

    # ------------------------------------------------------------------
    # Dataset preparation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_input(data: pd.DataFrame) -> None:
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(data.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")
        if len(data) < 40:
            raise ValueError("Need at least 40 rows of data for ML training.")

    def _make_target(self, data: pd.DataFrame) -> pd.Series:
        future_return = data["close"].shift(-self.config.horizon) / data["close"] - 1.0
        labels = np.where(
            future_return > self.config.neutral_threshold,
            "up",
            np.where(future_return < -self.config.neutral_threshold, "down", "neutral"),
        )
        return pd.Series(labels, index=data.index, name="direction")

    def _new_extractor(self) -> UnifiedFeatureExtractor:
        return UnifiedFeatureExtractor(
            use_option_features=self.config.use_option_features,
            pca_components=self.config.pca_components,
        )

    def _prepare_xy(
        self,
        data: pd.DataFrame,
        extractor: UnifiedFeatureExtractor,
        fit_extractor: bool,
    ) -> tuple[np.ndarray, np.ndarray, pd.Index]:
        self._validate_input(data)
        if fit_extractor:
            features = extractor.fit_transform(data)
        else:
            features = extractor.transform(data)

        target = self._make_target(data)
        frame = features.copy()
        frame["target"] = target
        frame = frame.replace([np.inf, -np.inf], np.nan).dropna()

        X = frame.drop(columns=["target"]).values.astype(float)
        y = frame["target"].values
        idx = frame.index
        return X, y, idx

    # ------------------------------------------------------------------
    # Split helpers
    # ------------------------------------------------------------------

    def split_time_series(
        self,
        X: np.ndarray,
        y: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        n = len(X)
        if n < 30:
            raise ValueError("Insufficient rows after feature processing for train/val/test split.")

        train_end = int(n * self.config.train_ratio)
        val_end = train_end + int(n * self.config.val_ratio)

        train_end = max(train_end, 1)
        val_end = max(val_end, train_end + 1)
        val_end = min(val_end, n - 1)

        X_train, y_train = X[:train_end], y[:train_end]
        X_val, y_val = X[train_end:val_end], y[train_end:val_end]
        X_test, y_test = X[val_end:], y[val_end:]
        return X_train, y_train, X_val, y_val, X_test, y_test

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self,
        data: pd.DataFrame,
        model: DirectionPredictor | None = None,
    ) -> dict[str, Any]:
        """Train model on time-series split and return evaluation metrics."""
        predictor = model or DirectionPredictor()
        extractor = self._new_extractor()
        X, y, idx = self._prepare_xy(data, extractor, fit_extractor=True)
        X_train, y_train, X_val, y_val, X_test, y_test = self.split_time_series(X, y)

        val_metrics = predictor.train(X_train, y_train, X_val, y_val)
        test_metrics = predictor.evaluate(X_test, y_test) if len(X_test) > 0 else {}

        return {
            "model_type": predictor.model_type,
            "rows": len(X),
            "train_rows": len(X_train),
            "val_rows": len(X_val),
            "test_rows": len(X_test),
            "feature_count": X.shape[1] if X.ndim == 2 else 0,
            "val_metrics": val_metrics,
            "test_metrics": test_metrics,
            "feature_metadata": extractor.metadata(),
            "last_index": str(idx[-1]) if len(idx) else None,
            "predictor": predictor,
            "extractor": extractor,
        }

    def walk_forward_validation(
        self,
        data: pd.DataFrame,
        model: DirectionPredictor | None = None,
        train_window: int = 252,
        test_window: int = 21,
        step: int = 21,
    ) -> pd.DataFrame:
        """Perform rolling walk-forward evaluation on historical data."""
        self._validate_input(data)
        predictor = model or DirectionPredictor()
        rows: list[dict[str, Any]] = []

        max_start = len(data) - train_window - test_window
        if max_start < 0:
            raise ValueError("Not enough rows for walk-forward configuration.")

        for start in range(0, max_start + 1, max(step, 1)):
            train_df = data.iloc[start : start + train_window]
            test_df = data.iloc[start + train_window : start + train_window + test_window]
            if len(test_df) < 2:
                continue

            extractor = self._new_extractor()
            X_train, y_train, _ = self._prepare_xy(train_df, extractor, fit_extractor=True)
            X_test, y_test, idx_test = self._prepare_xy(test_df, extractor, fit_extractor=False)
            if len(X_train) < 20 or len(X_test) == 0:
                continue

            predictor_fold = DirectionPredictor(
                model_type=predictor.model_type,
                random_state=predictor.random_state,
            )
            predictor_fold.fit(X_train, y_train)
            metrics = predictor_fold.evaluate(X_test, y_test)
            predictions = predictor_fold.predict(X_test)

            rows.append(
                {
                    "train_start": str(train_df.index[0]),
                    "train_end": str(train_df.index[-1]),
                    "test_start": str(test_df.index[0]),
                    "test_end": str(test_df.index[-1]),
                    "test_rows": len(X_test),
                    "accuracy": metrics.get("accuracy", np.nan),
                    "f1_macro": metrics.get("f1_macro", np.nan),
                    "logloss": metrics.get("logloss", np.nan),
                    "predictions": predictions.tolist(),
                    "actual": np.asarray(y_test).tolist(),
                    "prediction_index": [str(i) for i in idx_test],
                }
            )

        result = pd.DataFrame(rows)
        logger.info("walk_forward_complete", windows=len(result))
        return result


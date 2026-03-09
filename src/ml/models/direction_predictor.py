"""Direction prediction model for market movement classification.

The implementation supports multiple model backends but defaults to a
tree-based classifier so it works in environments without deep-learning
dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, log_loss
from sklearn.preprocessing import LabelEncoder

from src.utils.logger import get_logger

logger = get_logger(__name__)


class DirectionPredictor:
    """Predict market direction probabilities (down/neutral/up)."""

    DEFAULT_CLASSES = ("down", "neutral", "up")

    def __init__(
        self,
        model_type: str = "gradient_boosting",
        random_state: int = 42,
    ) -> None:
        self.model_type = model_type.lower()
        self.random_state = random_state
        self.model: Any = self._build_model()
        self.label_encoder = LabelEncoder()
        self.label_encoder.fit(list(self.DEFAULT_CLASSES))
        self._is_fitted = False

    # ------------------------------------------------------------------
    # Model construction
    # ------------------------------------------------------------------

    def _build_model(self) -> Any:
        if self.model_type in {"gradient_boosting", "gbm", "lstm", "gru", "transformer"}:
            return GradientBoostingClassifier(random_state=self.random_state)
        if self.model_type in {"random_forest", "rf"}:
            return RandomForestClassifier(
                n_estimators=300,
                max_depth=8,
                random_state=self.random_state,
                class_weight="balanced_subsample",
                n_jobs=-1,
            )
        if self.model_type in {"logistic", "logreg"}:
            return LogisticRegression(
                max_iter=2000,
                multi_class="auto",
                class_weight="balanced",
                random_state=self.random_state,
            )
        if self.model_type in {"xgboost", "xgb"}:
            try:
                from xgboost import XGBClassifier

                return XGBClassifier(
                    n_estimators=400,
                    max_depth=6,
                    learning_rate=0.05,
                    subsample=0.9,
                    colsample_bytree=0.9,
                    objective="multi:softprob",
                    eval_metric="mlogloss",
                    random_state=self.random_state,
                )
            except Exception:
                logger.warning("xgboost_unavailable_falling_back", model="gradient_boosting")
                return GradientBoostingClassifier(random_state=self.random_state)
        if self.model_type in {"lightgbm", "lgbm"}:
            try:
                from lightgbm import LGBMClassifier

                return LGBMClassifier(
                    n_estimators=500,
                    learning_rate=0.03,
                    num_leaves=31,
                    subsample=0.9,
                    colsample_bytree=0.9,
                    random_state=self.random_state,
                )
            except Exception:
                logger.warning("lightgbm_unavailable_falling_back", model="gradient_boosting")
                return GradientBoostingClassifier(random_state=self.random_state)

        logger.warning("unknown_model_type_fallback", model_type=self.model_type)
        return GradientBoostingClassifier(random_state=self.random_state)

    # ------------------------------------------------------------------
    # Data handling
    # ------------------------------------------------------------------

    @staticmethod
    def _reshape_features(X: np.ndarray) -> np.ndarray:
        arr = np.asarray(X, dtype=float)
        if arr.ndim == 1:
            return arr.reshape(-1, 1)
        if arr.ndim == 3:
            # Flatten sequence models to tabular shape for sklearn models.
            return arr.reshape(arr.shape[0], arr.shape[1] * arr.shape[2])
        if arr.ndim != 2:
            raise ValueError(f"Expected 1D/2D/3D features, got shape={arr.shape}")
        return arr

    def _encode_labels(self, y: np.ndarray | list[Any]) -> np.ndarray:
        arr = np.asarray(y)
        if arr.dtype.kind in {"f"}:
            # Numeric returns -> map into direction classes.
            mapped = np.where(arr > 0.001, "up", np.where(arr < -0.001, "down", "neutral"))
            return self.label_encoder.transform(mapped)
        if arr.dtype.kind in {"i", "u"}:
            # If integers are already class indices (0,1,2), clip safely.
            if np.nanmin(arr) >= 0 and np.nanmax(arr) <= 2:
                return arr.astype(int)
            mapped = np.where(arr > 0, "up", np.where(arr < 0, "down", "neutral"))
            return self.label_encoder.transform(mapped)

        labels = np.asarray([str(v).lower() for v in arr])
        normalized = np.where(
            np.isin(labels, ("buy", "bull", "long", "up")),
            "up",
            np.where(np.isin(labels, ("sell", "bear", "short", "down")), "down", "neutral"),
        )
        return self.label_encoder.transform(normalized)

    # ------------------------------------------------------------------
    # Training / inference
    # ------------------------------------------------------------------

    def fit(self, X: np.ndarray, y: np.ndarray | list[Any]) -> DirectionPredictor:
        X_fit = self._reshape_features(X)
        y_fit = self._encode_labels(y)
        self.model.fit(X_fit, y_fit)
        self._is_fitted = True
        return self

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray | list[Any],
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | list[Any] | None = None,
        **_: Any,
    ) -> dict[str, float]:
        """Train model and return core validation metrics."""
        self.fit(X_train, y_train)
        metrics: dict[str, float] = {}

        if X_val is not None and y_val is not None and len(X_val) > 0:
            y_true = self._encode_labels(y_val)
            probs = self.predict_proba(X_val)
            pred_idx = probs.argmax(axis=1)

            metrics["val_accuracy"] = float(accuracy_score(y_true, pred_idx))
            metrics["val_f1_macro"] = float(f1_score(y_true, pred_idx, average="macro"))
            try:
                metrics["val_logloss"] = float(log_loss(y_true, probs, labels=[0, 1, 2]))
            except Exception:
                metrics["val_logloss"] = float("nan")

        logger.info("direction_predictor_trained", model=self.model_type, metrics=metrics)
        return metrics

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError("DirectionPredictor must be trained before predict_proba().")
        X_pred = self._reshape_features(X)
        probs = self.model.predict_proba(X_pred)

        # Some estimators may not emit all classes if training sample is imbalanced.
        if probs.shape[1] == len(self.DEFAULT_CLASSES):
            return probs

        out = np.zeros((probs.shape[0], len(self.DEFAULT_CLASSES)), dtype=float)
        for i, cls in enumerate(self.model.classes_):
            out[:, int(cls)] = probs[:, i]
        return out

    def predict(self, X: np.ndarray) -> np.ndarray:
        probs = self.predict_proba(X)
        pred_idx = probs.argmax(axis=1)
        return self.label_encoder.inverse_transform(pred_idx)

    def predict_direction(self, X: np.ndarray) -> str:
        """Predict latest direction label from feature matrix."""
        labels = self.predict(X)
        if len(labels) == 0:
            return "neutral"
        return str(labels[-1])

    def evaluate(
        self,
        X: np.ndarray,
        y: np.ndarray | list[Any],
    ) -> dict[str, float]:
        y_true = self._encode_labels(y)
        probs = self.predict_proba(X)
        pred_idx = probs.argmax(axis=1)
        return {
            "accuracy": float(accuracy_score(y_true, pred_idx)),
            "f1_macro": float(f1_score(y_true, pred_idx, average="macro")),
            "logloss": float(log_loss(y_true, probs, labels=[0, 1, 2])),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> str:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model_type": self.model_type,
            "random_state": self.random_state,
            "model": self.model,
            "label_encoder": self.label_encoder,
            "is_fitted": self._is_fitted,
        }
        joblib.dump(payload, out)
        logger.info("direction_predictor_saved", path=str(out))
        return str(out)

    @classmethod
    def load(cls, path: str | Path) -> DirectionPredictor:
        payload = joblib.load(path)
        predictor = cls(
            model_type=payload.get("model_type", "gradient_boosting"),
            random_state=payload.get("random_state", 42),
        )
        predictor.model = payload["model"]
        predictor.label_encoder = payload["label_encoder"]
        predictor._is_fitted = bool(payload.get("is_fitted", True))
        return predictor

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted


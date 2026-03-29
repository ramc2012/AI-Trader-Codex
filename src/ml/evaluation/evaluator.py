"""ML Model Evaluation Framework.

Provides walk-forward validation, direction accuracy metrics,
profit factor from model signals, and model drift detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class EvaluationMetrics:
    """Comprehensive model evaluation metrics."""

    model_name: str
    evaluation_date: str
    total_predictions: int = 0
    correct_direction: int = 0
    direction_accuracy: float = 0.0
    precision_bullish: float = 0.0
    recall_bullish: float = 0.0
    precision_bearish: float = 0.0
    recall_bearish: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_predicted_return: float = 0.0
    avg_actual_return: float = 0.0
    correlation: float = 0.0
    feature_importance: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "evaluation_date": self.evaluation_date,
            "total_predictions": self.total_predictions,
            "direction_accuracy": round(self.direction_accuracy, 3),
            "precision_bullish": round(self.precision_bullish, 3),
            "recall_bullish": round(self.recall_bullish, 3),
            "precision_bearish": round(self.precision_bearish, 3),
            "recall_bearish": round(self.recall_bearish, 3),
            "profit_factor": round(self.profit_factor, 3),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 3),
            "avg_predicted_return": round(self.avg_predicted_return, 5),
            "avg_actual_return": round(self.avg_actual_return, 5),
            "correlation": round(self.correlation, 3),
        }

    @property
    def is_profitable(self) -> bool:
        return self.profit_factor > 1.0

    @property
    def is_accurate(self) -> bool:
        return self.direction_accuracy > 0.55


@dataclass
class DriftReport:
    """Model drift detection report."""

    model_name: str
    drift_detected: bool
    drift_score: float  # 0-1, higher = more drift
    features_drifted: list[str] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "drift_detected": self.drift_detected,
            "drift_score": round(self.drift_score, 3),
            "features_drifted": self.features_drifted,
            "recommendation": self.recommendation,
        }


class ModelEvaluator:
    """Walk-forward model validation and evaluation.

    Evaluates trained models against held-out data using direction
    accuracy, profit factor, Sharpe ratio, and drift detection.

    Args:
        risk_free_rate: Annual risk-free rate for Sharpe calculation.
        trading_days: Number of trading days per year.
        drift_threshold: Maximum acceptable feature distribution shift.
    """

    def __init__(
        self,
        risk_free_rate: float = 0.05,
        trading_days: int = 252,
        drift_threshold: float = 0.15,
    ) -> None:
        self.risk_free_rate = risk_free_rate
        self.trading_days = trading_days
        self.drift_threshold = drift_threshold

    def evaluate(
        self,
        model: Any,
        model_name: str,
        test_features: pd.DataFrame,
        test_returns: pd.Series,
    ) -> EvaluationMetrics:
        """Run full evaluation of a model on test data.

        Args:
            model: Trained model with predict() method.
            model_name: Identifier for the model.
            test_features: Feature matrix for test period.
            test_returns: Actual forward returns for test period.

        Returns:
            EvaluationMetrics with all computed metrics.
        """
        metrics = EvaluationMetrics(
            model_name=model_name,
            evaluation_date=datetime.now().isoformat(),
        )

        try:
            predictions = model.predict(test_features)
        except Exception as exc:
            logger.error("model_evaluation_failed", model=model_name, error=str(exc))
            return metrics

        predictions = np.array(predictions).flatten()
        actuals = np.array(test_returns).flatten()

        if len(predictions) != len(actuals):
            logger.warning("prediction_length_mismatch", pred=len(predictions), actual=len(actuals))
            min_len = min(len(predictions), len(actuals))
            predictions = predictions[:min_len]
            actuals = actuals[:min_len]

        metrics.total_predictions = len(predictions)

        # Direction accuracy
        pred_direction = np.sign(predictions)
        actual_direction = np.sign(actuals)
        correct = np.sum(pred_direction == actual_direction)
        metrics.correct_direction = int(correct)
        metrics.direction_accuracy = float(correct / len(predictions)) if len(predictions) > 0 else 0.0

        # Precision/Recall for bullish
        bull_pred = pred_direction == 1
        bull_actual = actual_direction == 1
        tp_bull = np.sum(bull_pred & bull_actual)
        metrics.precision_bullish = float(tp_bull / np.sum(bull_pred)) if np.sum(bull_pred) > 0 else 0.0
        metrics.recall_bullish = float(tp_bull / np.sum(bull_actual)) if np.sum(bull_actual) > 0 else 0.0

        # Precision/Recall for bearish
        bear_pred = pred_direction == -1
        bear_actual = actual_direction == -1
        tp_bear = np.sum(bear_pred & bear_actual)
        metrics.precision_bearish = float(tp_bear / np.sum(bear_pred)) if np.sum(bear_pred) > 0 else 0.0
        metrics.recall_bearish = float(tp_bear / np.sum(bear_actual)) if np.sum(bear_actual) > 0 else 0.0

        # Strategy returns (trade in predicted direction)
        strategy_returns = np.sign(predictions) * actuals
        gross_profit = float(np.sum(strategy_returns[strategy_returns > 0]))
        gross_loss = float(abs(np.sum(strategy_returns[strategy_returns < 0])))
        metrics.profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

        # Sharpe ratio
        if len(strategy_returns) > 1 and np.std(strategy_returns) > 0:
            excess_return = np.mean(strategy_returns) - self.risk_free_rate / self.trading_days
            metrics.sharpe_ratio = float(excess_return / np.std(strategy_returns) * np.sqrt(self.trading_days))
        else:
            metrics.sharpe_ratio = 0.0

        # Max drawdown
        cumulative = np.cumsum(strategy_returns)
        peak = np.maximum.accumulate(cumulative)
        drawdowns = (peak - cumulative)
        metrics.max_drawdown_pct = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        # Average returns
        metrics.avg_predicted_return = float(np.mean(predictions))
        metrics.avg_actual_return = float(np.mean(actuals))

        # Correlation
        if len(predictions) > 2:
            metrics.correlation = float(np.corrcoef(predictions, actuals)[0, 1])
            if np.isnan(metrics.correlation):
                metrics.correlation = 0.0

        # Feature importance (if model supports it)
        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
            if hasattr(test_features, "columns"):
                for col, imp in zip(test_features.columns, importances):
                    metrics.feature_importance[str(col)] = float(imp)

        logger.info(
            "model_evaluated",
            model=model_name,
            accuracy=metrics.direction_accuracy,
            profit_factor=metrics.profit_factor,
            sharpe=metrics.sharpe_ratio,
        )

        return metrics

    def detect_drift(
        self,
        model_name: str,
        training_features: pd.DataFrame,
        current_features: pd.DataFrame,
    ) -> DriftReport:
        """Detect feature distribution drift between training and current data.

        Uses simple statistical tests (mean shift, variance ratio) per feature.

        Args:
            model_name: Model identifier.
            training_features: Features from training period.
            current_features: Features from current/recent period.

        Returns:
            DriftReport indicating whether drift was detected.
        """
        drifted_features: list[str] = []
        drift_scores: list[float] = []

        common_cols = set(training_features.columns) & set(current_features.columns)

        for col in common_cols:
            train_vals = training_features[col].dropna()
            curr_vals = current_features[col].dropna()

            if len(train_vals) < 10 or len(curr_vals) < 10:
                continue

            # Mean shift (normalized)
            train_mean = float(train_vals.mean())
            curr_mean = float(curr_vals.mean())
            train_std = float(train_vals.std())

            if train_std > 0:
                mean_shift = abs(curr_mean - train_mean) / train_std
            else:
                mean_shift = 0.0

            # Variance ratio
            curr_std = float(curr_vals.std())
            var_ratio = curr_std / train_std if train_std > 0 else 1.0
            var_deviation = abs(var_ratio - 1.0)

            # Combined drift score for this feature
            feature_drift = (mean_shift * 0.6 + var_deviation * 0.4)
            drift_scores.append(feature_drift)

            if feature_drift > self.drift_threshold:
                drifted_features.append(str(col))

        overall_drift = float(np.mean(drift_scores)) if drift_scores else 0.0
        drift_detected = len(drifted_features) > len(common_cols) * 0.2  # >20% features drifted

        recommendation = ""
        if drift_detected:
            if overall_drift > 0.5:
                recommendation = "CRITICAL: Major distribution shift detected. Retrain model immediately."
            else:
                recommendation = "WARNING: Moderate drift detected. Schedule retraining within 1 week."
        else:
            recommendation = "OK: Feature distributions are stable."

        return DriftReport(
            model_name=model_name,
            drift_detected=drift_detected,
            drift_score=overall_drift,
            features_drifted=drifted_features,
            recommendation=recommendation,
        )

    def walk_forward_evaluate(
        self,
        model_class: Any,
        data: pd.DataFrame,
        feature_columns: list[str],
        target_column: str,
        train_window: int = 252,
        test_window: int = 63,
        step: int = 21,
    ) -> list[EvaluationMetrics]:
        """Walk-forward validation across multiple time windows.

        Args:
            model_class: Callable that returns a new model instance.
            data: Full dataset with features and target.
            feature_columns: Column names for features.
            target_column: Column name for target returns.
            train_window: Training window size (bars).
            test_window: Testing window size (bars).
            step: Step size between windows (bars).

        Returns:
            List of EvaluationMetrics for each validation window.
        """
        results: list[EvaluationMetrics] = []
        n = len(data)

        for i in range(0, n - train_window - test_window, step):
            train_end = i + train_window
            test_end = train_end + test_window

            train_features = data[feature_columns].iloc[i:train_end]
            train_target = data[target_column].iloc[i:train_end]
            test_features = data[feature_columns].iloc[train_end:test_end]
            test_target = data[target_column].iloc[train_end:test_end]

            try:
                model = model_class()
                model.fit(train_features, train_target)
                metrics = self.evaluate(
                    model=model,
                    model_name=f"walkforward_{i}_{train_end}",
                    test_features=test_features,
                    test_returns=test_target,
                )
                results.append(metrics)
            except Exception as exc:
                logger.warning("walk_forward_window_failed", start=i, error=str(exc))

        logger.info("walk_forward_complete", windows=len(results))
        return results

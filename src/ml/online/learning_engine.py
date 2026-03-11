"""Online learning engine: feature capture, outcome labeling, windowed model retraining.

After each trade closes, this engine:
1. Retrieves the feature vector captured at signal time.
2. Labels it with the trade outcome (up / down / neutral).
3. When a retraining threshold is reached, retrains each DirectionPredictor model
   on the accumulated rolling buffer of labeled examples.
4. Applies a save gate (new model must not regress >2% on validation accuracy).
5. Updates ensemble weights (softmax of per-model validation accuracies).
6. Adapts the ML ensemble confidence threshold based on rolling signal precision.
7. Persists all state to disk so learning is never lost across restarts.

Thread safety: retraining runs in a threadpool executor so the asyncio event loop
is never blocked during heavy sklearn / XGBoost computation.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import tempfile
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from src.utils.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_BUFFER_SIZE = 500          # maximum labeled examples kept (rolling)
_RETRAIN_EVERY = 25         # retrain after accumulating this many new labels
_MIN_EXAMPLES = 100         # minimum buffer size before first retrain
_PENDING_TTL_HOURS = 24     # garbage-collect pending (unlabeled) signals after 24h
_GBM_MAX_ESTIMATORS = 600   # cap warm-start estimator growth for GBM
_GBM_ESTIMATOR_STEP = 50    # estimators added per incremental retrain cycle
_SAVE_GATE_TOLERANCE = 0.02  # allow up to 2% accuracy regression before rejecting new model
_THRESHOLD_MIN = 0.50
_THRESHOLD_MAX = 0.80
_PRECISION_WINDOW = 50      # examples used to evaluate rolling precision
_STATE_FILENAME = "online_learning_state.json"
_STATE_VERSION = 1


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class LabeledExample:
    """A single signal–outcome pair used for model retraining."""

    signal_id: str
    symbol: str
    strategy: str
    features: list[float]
    feature_names: list[str]
    signal_type: str            # "BUY" or "SELL"
    label: Optional[str]        # "up" / "down" / "neutral"; None = pending
    pnl_pct: float
    timestamp_entry: str        # ISO string
    timestamp_exit: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "features": self.features,
            "feature_names": self.feature_names,
            "signal_type": self.signal_type,
            "label": self.label,
            "pnl_pct": self.pnl_pct,
            "timestamp_entry": self.timestamp_entry,
            "timestamp_exit": self.timestamp_exit,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LabeledExample:
        return cls(
            signal_id=d["signal_id"],
            symbol=d.get("symbol", ""),
            strategy=d.get("strategy", ""),
            features=d.get("features", []),
            feature_names=d.get("feature_names", []),
            signal_type=d.get("signal_type", "BUY"),
            label=d.get("label"),
            pnl_pct=float(d.get("pnl_pct", 0.0)),
            timestamp_entry=d.get("timestamp_entry", ""),
            timestamp_exit=d.get("timestamp_exit"),
        )


def _outcome_label(pnl_pct: float, signal_type: str, threshold: float = 0.1) -> str:
    """Convert P&L % to a direction label aligned with the original signal type."""
    profitable = pnl_pct > threshold
    unprofitable = pnl_pct < -threshold
    if signal_type == "BUY":
        if profitable:
            return "up"
        if unprofitable:
            return "down"
        return "neutral"
    # SELL: a winning short means price went down
    if profitable:
        return "down"
    if unprofitable:
        return "up"
    return "neutral"


def _softmax(values: list[float]) -> list[float]:
    """Numerically stable softmax."""
    if not values:
        return []
    max_v = max(values)
    exps = [math.exp(v - max_v) for v in values]
    total = sum(exps)
    return [e / total for e in exps]


# ── Engine ────────────────────────────────────────────────────────────────────

class OnlineLearningEngine:
    """Captures signal features at entry, labels at exit, retrains models.

    Args:
        ml_ensemble_strategy: The live ``MLEnsembleStrategy`` instance used by
            the agent.  The engine calls ``update_confidence_threshold()``,
            ``update_model_weights()``, and ``reload_models()`` on it after each
            successful retrain cycle.
        data_dir: Directory where models and state JSON are persisted.
    """

    def __init__(self, ml_ensemble_strategy: Any, data_dir: Path) -> None:
        self._ensemble = ml_ensemble_strategy
        data_dir = Path(data_dir)
        self._model_save_dir = data_dir / "ml_models"
        self._state_path = data_dir / _STATE_FILENAME
        self._model_save_dir.mkdir(parents=True, exist_ok=True)

        # Pending examples awaiting outcome (signal_id → LabeledExample with label=None)
        self._pending: dict[str, LabeledExample] = {}
        # Labeled buffer (rolling, chronological)
        self._buffer: deque[LabeledExample] = deque(maxlen=_BUFFER_SIZE)
        # Per-model validation accuracies (updated after each retrain)
        self._model_val_accuracies: list[float] = []
        # Current confidence threshold
        self._confidence_threshold: float = 0.62
        # Counter of new labels since last retrain
        self._examples_since_last_retrain: int = 0
        # Lock to prevent concurrent retrains
        self._retrain_lock = asyncio.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def register_signal(
        self,
        signal_id: str,
        symbol: str,
        strategy: str,
        features: list[float],
        feature_names: list[str],
        signal_type: str,
    ) -> None:
        """Store a pending example at signal generation time.

        Called synchronously from ``_process_signal`` in the trading agent before
        order placement.  The example remains "pending" (label=None) until the
        position closes.
        """
        if not features:
            return  # no features extracted — skip silently
        self._pending[signal_id] = LabeledExample(
            signal_id=signal_id,
            symbol=symbol,
            strategy=strategy,
            features=features,
            feature_names=feature_names,
            signal_type=signal_type,
            label=None,
            pnl_pct=0.0,
            timestamp_entry=datetime.utcnow().isoformat(),
            timestamp_exit=None,
        )
        logger.debug("signal_registered_for_learning", signal_id=signal_id, symbol=symbol)

    async def label_outcome(
        self,
        signal_id: str,
        pnl_pct: float,
        exit_timestamp: str,
    ) -> None:
        """Label a pending example with its trade outcome and trigger retraining.

        Called asynchronously (via ``asyncio.ensure_future``) from
        ``_close_position`` in the trading agent immediately after
        ``_record_reinforcement``.
        """
        self._gc_pending()  # drop stale pending entries

        example = self._pending.pop(signal_id, None)
        if example is None:
            logger.debug("signal_not_found_for_labeling", signal_id=signal_id)
            return

        example.label = _outcome_label(pnl_pct, example.signal_type)
        example.pnl_pct = pnl_pct
        example.timestamp_exit = exit_timestamp

        self._buffer.append(example)
        self._examples_since_last_retrain += 1

        logger.debug(
            "signal_labeled",
            signal_id=signal_id,
            label=example.label,
            pnl_pct=round(pnl_pct, 3),
            buffer_size=len(self._buffer),
        )

        if (
            self._examples_since_last_retrain >= _RETRAIN_EVERY
            and len(self._buffer) >= _MIN_EXAMPLES
        ):
            await self._maybe_retrain()

        self._persist_state()

    @property
    def stats(self) -> dict[str, Any]:
        """Summary for API / monitoring endpoints."""
        return {
            "buffer_size": len(self._buffer),
            "pending_signals": len(self._pending),
            "examples_since_last_retrain": self._examples_since_last_retrain,
            "model_val_accuracies": self._model_val_accuracies,
            "confidence_threshold": self._confidence_threshold,
        }

    # ── Retraining ────────────────────────────────────────────────────────────

    async def _maybe_retrain(self) -> None:
        """Trigger a non-blocking retrain in the threadpool executor."""
        if self._retrain_lock.locked():
            logger.debug("online_retrain_skipped_already_running")
            return
        async with self._retrain_lock:
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(None, self._retrain_sync)
            except Exception as exc:
                logger.error("online_retrain_failed", error=str(exc), exc_info=True)

    def _retrain_sync(self) -> None:  # runs in threadpool — may call sklearn freely
        """Full retrain cycle on the rolling buffer (80/20 time-series split)."""
        from sklearn.base import clone
        from sklearn.metrics import accuracy_score

        # ── 1. Build dataset ──────────────────────────────────────────────────
        examples = [e for e in self._buffer if e.label is not None and e.features]
        if len(examples) < _MIN_EXAMPLES:
            logger.debug("online_retrain_insufficient_examples", n=len(examples))
            return

        # Determine common feature schema (handle schema drift gracefully)
        all_feat_names = [e.feature_names for e in examples if e.feature_names]
        if all_feat_names:
            common_names = set(all_feat_names[0])
            for fn in all_feat_names[1:]:
                common_names &= set(fn)
            if not common_names:
                logger.warning("online_retrain_no_common_features")
                return
            common_names_sorted = sorted(common_names)
        else:
            common_names_sorted = []

        rows_X, rows_y = [], []
        for ex in examples:
            if common_names_sorted and ex.feature_names:
                idx_map = {n: i for i, n in enumerate(ex.feature_names)}
                try:
                    row = [ex.features[idx_map[n]] for n in common_names_sorted]
                except (KeyError, IndexError):
                    continue
            else:
                row = ex.features
            rows_X.append(row)
            rows_y.append(ex.label)

        X = np.array(rows_X, dtype=float)
        y = np.array(rows_y, dtype=str)

        # Drop NaN / Inf rows
        valid_mask = np.all(np.isfinite(X), axis=1)
        X, y = X[valid_mask], y[valid_mask]

        if len(X) < 50:
            logger.warning("online_retrain_too_few_valid_rows", n=len(X))
            return

        # ── 2. Time-series split (no shuffle) ────────────────────────────────
        split = int(0.80 * len(X))
        X_train, y_train = X[:split], y[:split]
        X_val, y_val = X[split:], y[split:]

        # ── 3. Retrain each model ─────────────────────────────────────────────
        ensemble = self._ensemble
        if ensemble is None or not hasattr(ensemble, "_models"):
            logger.warning("online_retrain_no_ensemble")
            return

        models = getattr(ensemble, "_models", [])
        if not models:
            logger.debug("online_retrain_no_models_loaded")
            return

        # Initialise accuracy list on first retrain
        if not self._model_val_accuracies:
            self._model_val_accuracies = [0.50] * len(models)

        updated_models: list[Any] = []
        new_accuracies: list[float] = list(self._model_val_accuracies)

        for idx, predictor in enumerate(models):
            try:
                model = predictor.model
                model_type = getattr(predictor, "model_type", "")

                # ── Encode labels via the predictor's own label encoder ───────
                y_train_enc = predictor._encode_labels(y_train)
                y_val_enc = predictor._encode_labels(y_val)
                X_train_prep = predictor._reshape_features(X_train)
                X_val_prep = predictor._reshape_features(X_val)

                # ── Choose refit strategy ─────────────────────────────────────
                if model_type in {"gradient_boosting", "gbm"}:
                    # warm-start: add more trees without forgetting old ones
                    model.warm_start = True
                    model.n_estimators = min(
                        getattr(model, "n_estimators", 100) + _GBM_ESTIMATOR_STEP,
                        _GBM_MAX_ESTIMATORS,
                    )
                    model.fit(X_train_prep, y_train_enc)
                elif model_type in {"xgboost", "xgb"}:
                    # XGBoost continued training
                    try:
                        model.fit(X_train_prep, y_train_enc, xgb_model=model)
                    except Exception:
                        model.fit(X_train_prep, y_train_enc)
                else:
                    # RF, LogReg, LightGBM — cold refit (fast, tolerant to small N)
                    try:
                        model = clone(model)
                    except Exception:
                        pass
                    model.fit(X_train_prep, y_train_enc)

                # ── Evaluate on validation set ────────────────────────────────
                val_probs = model.predict_proba(X_val_prep)
                val_preds = val_probs.argmax(axis=1)
                new_acc = float(accuracy_score(y_val_enc, val_preds))

                # ── Save gate ─────────────────────────────────────────────────
                old_acc = self._model_val_accuracies[idx] if idx < len(self._model_val_accuracies) else 0.50
                if new_acc >= old_acc - _SAVE_GATE_TOLERANCE:
                    predictor.model = model
                    predictor._is_fitted = True
                    save_path = self._model_save_dir / f"model_{idx}_online.joblib"
                    predictor.save(str(save_path))
                    new_accuracies[idx] = new_acc
                    logger.info(
                        "online_model_saved",
                        model_idx=idx,
                        model_type=model_type,
                        old_acc=round(old_acc, 4),
                        new_acc=round(new_acc, 4),
                    )
                else:
                    logger.warning(
                        "online_model_not_saved_regression",
                        model_idx=idx,
                        model_type=model_type,
                        old_acc=round(old_acc, 4),
                        new_acc=round(new_acc, 4),
                    )
                updated_models.append(predictor)

            except Exception as exc:
                logger.error(
                    "online_model_retrain_error",
                    model_idx=idx,
                    error=str(exc),
                    exc_info=True,
                )
                updated_models.append(predictor)  # keep existing model

        # ── 4. Update ensemble weights ────────────────────────────────────────
        self._model_val_accuracies = new_accuracies
        weights = _softmax(new_accuracies)
        try:
            ensemble.update_model_weights(weights)
            ensemble.reload_models(updated_models)
        except Exception as exc:
            logger.error("online_ensemble_update_failed", error=str(exc))

        # ── 5. Adapt confidence threshold ─────────────────────────────────────
        self._update_confidence_threshold()

        # ── 6. Reset counter ──────────────────────────────────────────────────
        self._examples_since_last_retrain = 0
        logger.info(
            "online_retrain_complete",
            examples=len(examples),
            model_val_accuracies=[round(a, 4) for a in self._model_val_accuracies],
            confidence_threshold=round(self._confidence_threshold, 4),
            weights=[round(w, 4) for w in weights],
        )

    def _update_confidence_threshold(self) -> None:
        """Adapt confidence threshold based on rolling signal precision."""
        labeled = [e for e in self._buffer if e.label is not None]
        window = labeled[-_PRECISION_WINDOW:]
        if len(window) < 10:
            return

        correct = 0
        for ex in window:
            predicted_up = ex.signal_type == "BUY"
            actual_up = ex.label == "up"
            actual_down = ex.label == "down"
            if predicted_up and actual_up:
                correct += 1
            elif not predicted_up and actual_down:
                correct += 1

        precision = correct / len(window)
        old_threshold = self._confidence_threshold

        if precision < 0.45:
            self._confidence_threshold = min(self._confidence_threshold + 0.02, _THRESHOLD_MAX)
        elif precision > 0.60:
            self._confidence_threshold = max(self._confidence_threshold - 0.01, _THRESHOLD_MIN)

        if self._confidence_threshold != old_threshold:
            logger.info(
                "confidence_threshold_updated",
                old=round(old_threshold, 4),
                new=round(self._confidence_threshold, 4),
                precision=round(precision, 4),
            )
            try:
                self._ensemble.update_confidence_threshold(self._confidence_threshold)
            except Exception as exc:
                logger.warning("confidence_threshold_push_failed", error=str(exc))

    # ── Persistence ───────────────────────────────────────────────────────────

    def load_state(self) -> None:
        """Load persisted state and previously trained models (call once at startup)."""
        if not self._state_path.exists():
            logger.debug("online_learning_state_not_found", path=str(self._state_path))
            return
        try:
            data = json.loads(self._state_path.read_text())
            self._confidence_threshold = float(data.get("confidence_threshold", 0.62))
            self._model_val_accuracies = [float(v) for v in data.get("model_val_accuracies", [])]
            self._examples_since_last_retrain = int(data.get("examples_since_last_retrain", 0))

            for ex_dict in data.get("buffer", []):
                try:
                    ex = LabeledExample.from_dict(ex_dict)
                    if ex.label is not None:
                        self._buffer.append(ex)
                except Exception:
                    pass

            logger.info(
                "online_learning_state_loaded",
                buffer_size=len(self._buffer),
                confidence_threshold=round(self._confidence_threshold, 4),
                model_val_accuracies=self._model_val_accuracies,
            )

            # Push loaded threshold to ensemble immediately
            if self._ensemble is not None:
                try:
                    self._ensemble.update_confidence_threshold(self._confidence_threshold)
                except Exception:
                    pass

        except Exception as exc:
            logger.warning("online_learning_state_load_failed", error=str(exc))

    def _persist_state(self) -> None:
        """Atomically persist state to disk."""
        payload: dict[str, Any] = {
            "version": _STATE_VERSION,
            "confidence_threshold": self._confidence_threshold,
            "model_val_accuracies": self._model_val_accuracies,
            "examples_since_last_retrain": self._examples_since_last_retrain,
            "buffer": [e.to_dict() for e in self._buffer],
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
            logger.error("online_learning_state_save_failed", error=str(exc))
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _gc_pending(self) -> None:
        """Remove pending entries older than ``_PENDING_TTL_HOURS``."""
        cutoff = datetime.utcnow() - timedelta(hours=_PENDING_TTL_HOURS)
        stale = [
            sid
            for sid, ex in self._pending.items()
            if ex.timestamp_entry and datetime.fromisoformat(ex.timestamp_entry) < cutoff
        ]
        for sid in stale:
            del self._pending[sid]
        if stale:
            logger.debug("pending_signals_gc", removed=len(stale))

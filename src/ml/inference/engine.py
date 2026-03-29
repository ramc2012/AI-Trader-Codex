"""Machine Learning Inference Engine with Latency Tracking."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pandas as pd

from src.ml.features.feature_extractor import UnifiedFeatureExtractor
from src.ml.models.direction_predictor import DirectionPredictor
from src.utils.logger import get_logger

logger = get_logger(__name__)

class MLInferenceEngine:
    """Manages loaded ML models, extracts features, and runs batched predictions."""

    def __init__(self, model_paths: list[str]) -> None:
        self.model_paths = model_paths
        self.models: list[DirectionPredictor] = []
        self.feature_extractor = UnifiedFeatureExtractor(use_option_features=True)
        self.is_loaded = False

    def load_models(self) -> bool:
        """Load all models from disk."""
        if self.is_loaded:
            return bool(self.models)
        
        loaded = []
        for path in self.model_paths:
            try:
                if not Path(path).exists():
                    logger.debug("ml_model_not_found", path=path)
                    continue
                loaded.append(DirectionPredictor.load(path))
            except Exception as exc:
                logger.warning("ml_model_load_failed", path=path, error=str(exc))
        
        self.models = loaded
        self.is_loaded = True
        
        if self.models:
            logger.info("inference_engine_ready", num_models=len(self.models))
        else:
            logger.warning("inference_engine_no_models")
            
        return bool(self.models)

    def predict(self, df: pd.DataFrame, symbol: str) -> dict[str, Any]:
        """Run batched predictions across all ensemble models and track latency."""
        if not self.is_loaded:
            self.load_models()
        
        if not self.models or df.empty:
            return {"predicted_direction": "neutral", "confidence": 0.0, "latency_ms": 0.0, "features": None}
            
        start_time = time.perf_counter()
        
        try:
            # 1. Extract features
            features_df = self.feature_extractor.extract(df, symbol=symbol)
            if features_df.empty:
                return {"predicted_direction": "neutral", "confidence": 0.0, "latency_ms": 0.0, "features": None}
                
            # Use the latest row for inference
            latest_features = features_df.iloc[[-1]].copy()
            
            # Predict
            predictions = []
            for model in self.models:
                # model.predict_proba returns probability for [down, neutral, up]
                probs = model.predict_proba(latest_features.values)
                # Take highest probability index (0=down, 1=neutral, 2=up)
                pred_idx = probs[0].argmax()
                confidence = float(probs[0][pred_idx])
                direction = model.label_encoder.inverse_transform([pred_idx])[0]
                
                # normalize direction internally
                if direction in ["bull", "buy", "long", "up"]: dir_val = 1
                elif direction in ["bear", "sell", "short", "down"]: dir_val = -1
                else: dir_val = 0
                
                predictions.append({
                    "direction_val": dir_val,
                    "confidence": confidence,
                    "raw_probs": probs[0]
                })
                
            # Ensemble logic: strict consensus
            # If all models agree on direction, high confidence. Otherwise neutral.
            dir_vals = [p["direction_val"] for p in predictions]
            avg_conf = sum(p["confidence"] for p in predictions) / len(predictions)
            
            if all(v == 1 for v in dir_vals):
                final_dir = "buy"
            elif all(v == -1 for v in dir_vals):
                final_dir = "sell"
            else:
                final_dir = "neutral"
                avg_conf = 0.0
                
            latency = (time.perf_counter() - start_time) * 1000.0
            
            # Log metrics (could be picked up by Prometheus)
            logger.debug("ml_inference_completed", symbol=symbol, direction=final_dir, confidence=round(avg_conf, 3), latency_ms=round(latency, 2))
            
            return {
                "predicted_direction": final_dir,
                "confidence": avg_conf,
                "latency_ms": latency,
                "features": latest_features.to_dict(orient="records")[0]
            }
            
        except Exception as exc:
            logger.error("ml_inference_error", symbol=symbol, error=str(exc))
            return {"predicted_direction": "neutral", "confidence": 0.0, "latency_ms": 0.0, "features": None}

#!/usr/bin/env python3
"""Script to train and evaluate ML models for the AI-Trader ensemble."""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.connection import get_db
from src.integrations.fyers_client import FyersClient
from src.ml.features.feature_extractor import UnifiedFeatureExtractor
from src.ml.models.direction_predictor import DirectionPredictor
from src.utils.logger import get_logger

logger = get_logger(__name__)

def create_labels(df: pd.DataFrame, horizon: int = 5, threshold: float = 0.002) -> pd.DataFrame:
    """Create target labels looking forward 'horizon' bars."""
    df = df.copy()
    if len(df) <= horizon:
        df["target_direction"] = "neutral"
        return df

    # Forward return % 
    future_close = df["close"].shift(-horizon)
    returns = (future_close - df["close"]) / df["close"]

    # Assign labels based on threshold
    conditions = [
        (returns > threshold),
        (returns < -threshold)
    ]
    choices = ["up", "down"]
    df["target_direction"] = np.select(conditions, choices, default="neutral")
    return df

async def collect_training_data(symbols: list[str], days: int = 30) -> pd.DataFrame:
    """Collect recent high-res historical data across a subset of symbols to train on."""
    client = FyersClient()
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    logger.info("collecting_training_data", symbols=len(symbols), days=days)
    
    all_data = []
    
    for symbol in symbols:
        try:
            # 5-minute candles are good for day trading / scalping models
            df = await client.get_historical_data(
                symbol=symbol,
                resolution="5", 
                start_date=start_date,
                end_date=end_date
            )
            
            if df is None or df.empty:
                logger.warning("no_data_for_symbol", symbol=symbol)
                continue
                
            df["symbol"] = symbol
            
            # Create labels (predicting next 5 bars, e.g. 25 minutes out)
            df = create_labels(df, horizon=5, threshold=0.001)
            
            # Drop the forward-looking NaN rows at the end
            df = df.dropna(subset=["target_direction"])
            
            all_data.append(df)
            await asyncio.sleep(0.5)  # rate limit compliance
        except Exception as e:
            logger.error("error_fetching_data", symbol=symbol, error=str(e))
            
    if not all_data:
        return pd.DataFrame()
        
    return pd.concat(all_data, ignore_index=True)

async def train_workflow(args: argparse.Namespace) -> None:
    symbols = args.symbols.split(",")
    logger.info("starting_ml_training_workflow", symbols=symbols, model=args.model_type)
    
    # 1. Fetch data
    df = await collect_training_data(symbols, days=args.days)
    if df.empty:
        logger.error("training_aborted_no_data")
        return
        
    logger.info("data_collected", total_rows=len(df))
    
    # 2. Extract Features
    extractor = UnifiedFeatureExtractor(use_option_features=False) 
    
    all_features = []
    all_labels = []
    
    for symbol, group in df.groupby("symbol"):
        group = group.sort_values(by="timestamp").reset_index(drop=True)
        # Extract technicals/price features
        features_df = extractor.extract(group, symbol=symbol)
        
        # We must align the features with our target labels
        # Feature extractor drops the first N rows due to rolling windows (e.g. 20 for bollinger)
        aligned = pd.concat([features_df, group["target_direction"]], axis=1, join="inner")
        aligned = aligned.dropna()
        
        f_cols = [c for c in aligned.columns if c not in ["timestamp", "symbol", "target_direction"]]
        features = aligned[f_cols].values
        labels = aligned["target_direction"].values
        
        if len(features) > 0:
            all_features.append(features)
            all_labels.extend(labels)
            
    if not all_features:
        logger.error("training_aborted_no_valid_features")
        return
        
    X = np.vstack(all_features)
    y = np.array(all_labels)
    
    logger.info("features_extracted", shape=X.shape, labels=len(y))
    
    # Split into train/val (80/20 chronological split is better, but this is simple demo)
    split_idx = int(len(X) * 0.8)
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]
    
    logger.info("training_split", train=len(X_train), val=len(X_val))
    
    # 3. Train Model
    predictor = DirectionPredictor(model_type=args.model_type, random_state=42)
    metrics = predictor.train(X_train, y_train, X_val, y_val)
    
    logger.info("training_completed", metrics=metrics)
    
    # 4. Save Model
    models_dir = Path("models")
    models_dir.mkdir(exist_ok=True)
    
    # E.g. models/direction_predictor_gbm.joblib
    save_path = models_dir / f"direction_predictor_{args.model_type}.joblib"
    predictor.save(save_path)
    logger.info("model_saved", path=str(save_path))

if __name__ == "__main__":
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="Train AI Trading Ensemble Models")
    parser.add_argument("--symbols", type=str, default="NSE:NIFTY50-INDEX,NSE:NIFTYBANK-INDEX,NSE:RELIANCE-EQ,NSE:HDFCBANK-EQ,NSE:INFY-EQ", help="Comma separated symbols to train on")
    parser.add_argument("--days", type=int, default=30, help="Days of historical data to fetch")
    parser.add_argument("--model-type", type=str, default="gbm", choices=["gbm", "rf", "logistic", "xgb", "lgbm"], help="Model backend to use")
    
    args = parser.add_argument_group()
    args = parser.parse_args()
    
    asyncio.run(train_workflow(args))

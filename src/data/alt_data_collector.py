"""Alternative Data Collector.

Ingests, aggregates, and simulates (if necessary) advanced macro datasets
like FII/DII institutional flows, market breadth advance/decline ratios, 
and NLP-driven news sentiment score analysis.
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

class AltDataCollector:
    """Aggregates macro context and alternative data feeds."""

    def __init__(self) -> None:
        self.last_fetch_time: datetime | None = None
        self._cache: dict[str, Any] = {
            "fii_net_crores": 0.0,
            "dii_net_crores": 0.0,
            "market_breadth_ratio": 1.0,
            "news_sentiment": "neutral",
            "sentiment_score": 0.0,
        }

    async def fetch_macro_context(self) -> dict[str, Any]:
        """Fetch or simulate current macro context."""
        
        # In a real environment, this would hit NSE India APIs for FII/DII,
        # fetch News headlines from NewsCrypto/Reuters, and run an NLP model (VADER/FinBERT).
        
        # For demonstration of the architectural pipeline, we generate realistic
        # random walks for the macro variables.
        
        # Breadth is an advance/decline ratio (e.g., 1.5 = 1.5x more advancing than declining)
        breadth = max(0.2, min(5.0, random.gauss(1.0, 0.4)))
        
        # FII/DII Net Flow in Crores (positive = net buying)
        fii = random.gauss(0, 1500)
        dii = random.gauss(0, 1000)
        
        # News Sentiment bounded between -1.0 (extreme fear) and 1.0 (extreme greed)
        sent_score = max(-1.0, min(1.0, random.gauss(0.0, 0.3)))
        
        if sent_score > 0.4:
            sentiment_label = "bullish"
        elif sent_score < -0.4:
            sentiment_label = "bearish"
        else:
            sentiment_label = "neutral"
            
        self._cache = {
            "fii_net_crores": round(fii, 2),
            "dii_net_crores": round(dii, 2),
            "market_breadth_ratio": round(breadth, 2),
            "news_sentiment": sentiment_label,
            "sentiment_score": round(sent_score, 3),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self.last_fetch_time = datetime.now()
        
        logger.debug(
            "macro_context_updated", 
            breadth=self._cache["market_breadth_ratio"],
            fii_net=self._cache["fii_net_crores"],
            sentiment=self._cache["news_sentiment"]
        )
        
        return self._cache

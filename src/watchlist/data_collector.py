"""
Data collector for index historical and real-time data.
Fetches OHLC, market profile, and order flow data from Fyers.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from src.integrations.fyers_client import FyersClient
from src.utils.logger import get_logger
from src.watchlist.indices import (
    IndexWatchlist,
    MarketData,
    OrderFlowData,
)

logger = get_logger(__name__)


class IndexDataCollector:
    """
    Collects historical and real-time data for Indian indices.
    Supports spot and futures data collection.
    """

    def __init__(self, fyers_client: FyersClient):
        self.client = fyers_client
        self.watchlist = IndexWatchlist()
        logger.info("index_data_collector_initialized")

    def _build_market_data_from_quote(
        self,
        symbol: str,
        data: dict,
    ) -> Optional[MarketData]:
        """Convert a Fyers quote payload into MarketData."""
        if not data:
            return None
        if data.get("s") == "error" or data.get("code") == -300:
            logger.warning(
                "quote_symbol_invalid",
                symbol=symbol,
                error=data.get("errmsg", "invalid symbol"),
            )
            return None

        market_data = MarketData(
            symbol=symbol,
            timestamp=datetime.now(),
            ltp=data.get("lp", 0.0),
            open=data.get("open_price", 0.0),
            high=data.get("high_price", 0.0),
            low=data.get("low_price", 0.0),
            close=data.get("prev_close_price", 0.0),
            volume=data.get("volume", 0),
            oi=data.get("oi", None),
            bid=data.get("bid_price", None),
            ask=data.get("ask_price", None),
            bid_qty=data.get("bid_size", None),
            ask_qty=data.get("ask_size", None),
            change=data.get("ch", None),
            change_pct=data.get("chp", None),
        )
        return market_data

    async def fetch_historical_ohlc(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        resolution: str = "D",
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical OHLC data for an index.

        Args:
            symbol: Fyers symbol (e.g., NSE:NIFTY50-INDEX)
            from_date: Start date
            to_date: End date
            resolution: Timeframe (D=Daily, 60=1Hour, 15=15Min, etc.)

        Returns:
            DataFrame with OHLC data or None if failed
        """
        try:
            logger.info(
                "fetching_historical_data",
                symbol=symbol,
                from_date=from_date.date(),
                to_date=to_date.date(),
                resolution=resolution,
            )

            # Format dates for Fyers API
            from_str = from_date.strftime("%Y-%m-%d")
            to_str = to_date.strftime("%Y-%m-%d")

            data = self.client.get_history(
                symbol=symbol,
                resolution=resolution,
                range_from=from_str,
                range_to=to_str,
            )

            if not data or "candles" not in data or not data["candles"]:
                logger.warning("no_data_received", symbol=symbol)
                return None

            # Convert to DataFrame
            df = pd.DataFrame(
                data["candles"],
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )

            # Convert timestamp to datetime
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
            df.set_index("timestamp", inplace=True)

            logger.info(
                "historical_data_fetched",
                symbol=symbol,
                rows=len(df),
                from_date=df.index[0] if len(df) > 0 else None,
                to_date=df.index[-1] if len(df) > 0 else None,
            )

            return df

        except Exception as exc:
            logger.error("fetch_historical_data_failed", symbol=symbol, error=str(exc))
            return None

    async def fetch_current_quote(self, symbol: str) -> Optional[MarketData]:
        """
        Fetch current market quote for an index.

        Args:
            symbol: Fyers symbol

        Returns:
            MarketData object or None
        """
        try:
            quote = self.client.get_quotes([symbol])

            if not quote or "d" not in quote or len(quote["d"]) == 0:
                logger.warning("no_quote_data", symbol=symbol)
                return None

            data = quote["d"][0].get("v", {})
            market_data = self._build_market_data_from_quote(symbol, data)
            if not market_data:
                return None

            # Update watchlist
            self.watchlist.update_market_data(symbol, market_data)

            logger.debug("quote_fetched", symbol=symbol, ltp=market_data.ltp)
            return market_data

        except Exception as exc:
            logger.error("fetch_quote_failed", symbol=symbol, error=str(exc))
            return None

    async def fetch_all_quotes(self) -> Dict[str, MarketData]:
        """
        Fetch quotes for all indices in the watchlist.

        Returns:
            Dictionary mapping symbol to MarketData
        """
        results: Dict[str, MarketData] = {}
        symbols: list[str] = []
        for idx in self.watchlist.indices.values():
            symbols.append(idx.spot_symbol)
            if idx.futures_symbol:
                symbols.append(idx.futures_symbol)

        # Best path: one bulk call (dramatically faster than N sequential calls).
        try:
            quote = self.client.get_quotes(symbols)
            rows = quote.get("d", []) if isinstance(quote, dict) else []
            for item in rows:
                if item.get("s") != "ok":
                    continue
                symbol = item.get("n") or item.get("v", {}).get("symbol")
                if not symbol:
                    continue
                market_data = self._build_market_data_from_quote(symbol, item.get("v", {}))
                if not market_data:
                    continue
                self.watchlist.update_market_data(symbol, market_data)
                results[symbol] = market_data

            logger.info("all_quotes_fetched_bulk", requested=len(symbols), count=len(results))
            return results
        except Exception as exc:
            logger.warning("bulk_quotes_failed_fallback_single", error=str(exc), symbols=len(symbols))

        # Fallback path: per-symbol requests for robustness.
        for symbol in symbols:
            data = await self.fetch_current_quote(symbol)
            if data:
                results[symbol] = data

        logger.info("all_quotes_fetched_single", count=len(results))
        return results

    async def test_data_availability(self) -> Dict:
        """
        Test data availability for all indices.
        Checks historical data, quotes, and market depth.

        Returns:
            Test results dictionary
        """
        results = {
            "timestamp": datetime.now().isoformat(),
            "indices": {},
            "summary": {
                "total_indices": len(self.watchlist.indices),
                "spot_data_available": 0,
                "futures_data_available": 0,
                "historical_data_available": 0,
            },
        }

        # Test each index
        for name, idx in self.watchlist.indices.items():
            logger.info("testing_data_availability", index=name)

            index_result = {
                "name": name,
                "display_name": idx.display_name,
                "spot": {"symbol": idx.spot_symbol, "available": False, "error": None},
                "futures": {
                    "symbol": idx.futures_symbol,
                    "available": False,
                    "error": None,
                },
                "historical": {"available": False, "days": 0, "error": None},
            }

            # Test spot quote
            try:
                spot_data = await self.fetch_current_quote(idx.spot_symbol)
                if spot_data and spot_data.ltp > 0:
                    index_result["spot"]["available"] = True
                    index_result["spot"]["ltp"] = spot_data.ltp
                    results["summary"]["spot_data_available"] += 1
            except Exception as exc:
                index_result["spot"]["error"] = str(exc)

            # Test futures quote
            try:
                futures_data = await self.fetch_current_quote(idx.futures_symbol)
                if futures_data and futures_data.ltp > 0:
                    index_result["futures"]["available"] = True
                    index_result["futures"]["ltp"] = futures_data.ltp
                    index_result["futures"]["oi"] = futures_data.oi
                    results["summary"]["futures_data_available"] += 1
            except Exception as exc:
                index_result["futures"]["error"] = str(exc)

            # Test historical data (last 30 days)
            try:
                to_date = datetime.now()
                from_date = to_date - timedelta(days=30)

                hist_data = await self.fetch_historical_ohlc(
                    idx.spot_symbol, from_date, to_date, resolution="D"
                )

                if hist_data is not None and len(hist_data) > 0:
                    index_result["historical"]["available"] = True
                    index_result["historical"]["days"] = len(hist_data)
                    index_result["historical"]["from"] = hist_data.index[0].isoformat()
                    index_result["historical"]["to"] = hist_data.index[-1].isoformat()
                    results["summary"]["historical_data_available"] += 1
            except Exception as exc:
                index_result["historical"]["error"] = str(exc)

            results["indices"][name] = index_result

        logger.info("data_availability_test_complete", summary=results["summary"])
        return results

    def calculate_order_flow(self, symbol: str, market_data: MarketData) -> Optional[OrderFlowData]:
        """
        Calculate order flow metrics from market data.

        Args:
            symbol: Symbol
            market_data: Current market data

        Returns:
            OrderFlowData object or None
        """
        try:
            if not market_data.bid or not market_data.ask:
                return None

            spread = market_data.ask - market_data.bid
            mid_price = (market_data.bid + market_data.ask) / 2
            spread_pct = (spread / mid_price) * 100 if mid_price > 0 else 0

            # Calculate buy/sell metrics (simplified)
            total_bid = market_data.bid_qty or 0
            total_ask = market_data.ask_qty or 0
            buy_sell_ratio = total_bid / total_ask if total_ask > 0 else 0

            order_flow = OrderFlowData(
                symbol=symbol,
                timestamp=datetime.now(),
                bid_ask_spread=spread,
                bid_ask_spread_pct=spread_pct,
                mid_price=mid_price,
                bid_depth=[(market_data.bid, total_bid)],
                ask_depth=[(market_data.ask, total_ask)],
                total_bid_volume=total_bid,
                total_ask_volume=total_ask,
                buy_sell_ratio=buy_sell_ratio,
                aggressive_buys=0,  # Would need tick data
                aggressive_sells=0,
                trade_imbalance=0.0,
                volume_delta=0,
                cumulative_delta=0,
                max_volume_price=market_data.ltp,
                last_trades=[],
            )

            # Update watchlist
            self.watchlist.update_order_flow(symbol, order_flow)

            return order_flow

        except Exception as exc:
            logger.error("calculate_order_flow_failed", symbol=symbol, error=str(exc))
            return None

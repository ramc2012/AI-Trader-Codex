"""Tests for SQLAlchemy models and database operations.

These are unit tests that verify model structure and operation logic
without requiring a running database. Integration tests with TimescaleDB
are in tests/integration/.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.database.models import Base, IndexOHLC, OptionChain, TickData, TradeLog


class TestIndexOHLC:
    def test_model_tablename(self) -> None:
        assert IndexOHLC.__tablename__ == "index_ohlc"

    def test_model_repr(self) -> None:
        candle = IndexOHLC(
            symbol="NSE:NIFTY50-INDEX",
            timeframe="D",
            timestamp=datetime(2024, 2, 8),
            open=Decimal("22150.50"),
            high=Decimal("22200.75"),
            low=Decimal("22100.25"),
            close=Decimal("22180.00"),
            volume=150000,
        )
        r = repr(candle)
        assert "NSE:NIFTY50-INDEX" in r
        assert "22150" in r

    def test_model_columns(self) -> None:
        columns = {c.name for c in IndexOHLC.__table__.columns}
        expected = {"symbol", "timeframe", "timestamp", "open", "high", "low", "close", "volume"}
        assert columns == expected


class TestTickData:
    def test_model_tablename(self) -> None:
        assert TickData.__tablename__ == "tick_data"

    def test_model_repr(self) -> None:
        tick = TickData(
            symbol="NSE:NIFTY50-INDEX",
            timestamp=datetime(2024, 2, 8, 10, 0),
            ltp=Decimal("22150.50"),
            volume=1000,
        )
        assert "NSE:NIFTY50-INDEX" in repr(tick)
        assert "22150" in repr(tick)

    def test_nullable_fields(self) -> None:
        """Bid, ask, open, high, low, close are nullable."""
        tick = TickData(
            symbol="NSE:NIFTY50-INDEX",
            timestamp=datetime(2024, 2, 8),
            ltp=Decimal("22150.50"),
            volume=0,
        )
        assert tick.bid is None
        assert tick.ask is None


class TestOptionChain:
    def test_model_tablename(self) -> None:
        assert OptionChain.__tablename__ == "option_chain"

    def test_model_columns(self) -> None:
        columns = {c.name for c in OptionChain.__table__.columns}
        assert "iv" in columns
        assert "delta" in columns
        assert "gamma" in columns
        assert "theta" in columns
        assert "vega" in columns


class TestTradeLog:
    def test_model_tablename(self) -> None:
        assert TradeLog.__tablename__ == "trade_log"

    def test_model_repr(self) -> None:
        trade = TradeLog(
            id=1,
            timestamp=datetime(2024, 2, 8),
            symbol="NSE:NIFTY50-INDEX",
            side="BUY",
            quantity=50,
            price=Decimal("200.50"),
            order_type="MARKET",
            product_type="INTRADAY",
            status="COMPLETE",
        )
        r = repr(trade)
        assert "BUY" in r
        assert "50" in r
        assert "COMPLETE" in r

    def test_optional_fields(self) -> None:
        trade = TradeLog(
            id=1,
            timestamp=datetime(2024, 2, 8),
            symbol="NSE:NIFTY50-INDEX",
            side="BUY",
            quantity=50,
            price=Decimal("200.50"),
            order_type="MARKET",
            product_type="INTRADAY",
            status="PENDING",
        )
        assert trade.order_id is None
        assert trade.strategy is None
        assert trade.notes is None
        assert trade.pnl is None


class TestBaseModel:
    def test_all_models_share_base(self) -> None:
        """All models should inherit from the same Base."""
        assert issubclass(IndexOHLC, Base)
        assert issubclass(TickData, Base)
        assert issubclass(OptionChain, Base)
        assert issubclass(TradeLog, Base)

    def test_metadata_has_all_tables(self) -> None:
        table_names = set(Base.metadata.tables.keys())
        assert "index_ohlc" in table_names
        assert "tick_data" in table_names
        assert "option_chain" in table_names
        assert "trade_log" in table_names

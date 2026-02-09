"""SQLAlchemy ORM models for the Nifty AI Trader database.

Maps to the TimescaleDB schema defined in schema.sql.
Uses SQLAlchemy 2.0 declarative style with mapped_column.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class IndexOHLC(Base):
    """OHLCV candle data for index symbols (Nifty, Bank Nifty, Sensex)."""

    __tablename__ = "index_ohlc"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    timeframe: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="idx_ohlc_unique"),
        Index("idx_ohlc_symbol_tf_time", "symbol", "timeframe", timestamp.desc()),
    )

    def __repr__(self) -> str:
        return (
            f"<IndexOHLC {self.symbol} {self.timeframe} "
            f"{self.timestamp} O={self.open} H={self.high} "
            f"L={self.low} C={self.close} V={self.volume}>"
        )


class TickData(Base):
    """Real-time tick data captured from WebSocket stream."""

    __tablename__ = "tick_data"

    # Composite primary key: symbol + timestamp
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(primary_key=True)
    ltp: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    bid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ask: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    open: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    high: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    low: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    close: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    __table_args__ = (
        Index("idx_tick_symbol_time", "symbol", timestamp.desc()),
    )

    def __repr__(self) -> str:
        return f"<TickData {self.symbol} {self.timestamp} ltp={self.ltp}>"


class OptionChain(Base):
    """Option chain snapshot data."""

    __tablename__ = "option_chain"

    timestamp: Mapped[datetime] = mapped_column(primary_key=True)
    underlying: Mapped[str] = mapped_column(String, primary_key=True)
    expiry: Mapped[date] = mapped_column(Date, primary_key=True)
    strike: Mapped[Decimal] = mapped_column(Numeric(12, 2), primary_key=True)
    option_type: Mapped[str] = mapped_column(String, primary_key=True)  # CE or PE
    ltp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    oi: Mapped[int] = mapped_column(BigInteger, default=0)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
    iv: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    delta: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    gamma: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    theta: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    vega: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)

    __table_args__ = (
        Index("idx_optchain_underlying_expiry", "underlying", "expiry", timestamp.desc()),
        Index("idx_optchain_strike", "underlying", "strike", "option_type", timestamp.desc()),
    )

    def __repr__(self) -> str:
        return (
            f"<OptionChain {self.underlying} {self.expiry} "
            f"{self.strike}{self.option_type} ltp={self.ltp}>"
        )


class TradeLog(Base):
    """Audit log for every order placed by the trading system."""

    __tablename__ = "trade_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)  # BUY / SELL
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    order_type: Mapped[str] = mapped_column(String, nullable=False)
    product_type: Mapped[str] = mapped_column(String, nullable=False)
    order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    strategy: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    pnl: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    __table_args__ = (
        Index("idx_trade_log_time", timestamp.desc()),
        Index("idx_trade_log_symbol", "symbol", timestamp.desc()),
    )

    def __repr__(self) -> str:
        return (
            f"<TradeLog #{self.id} {self.side} {self.quantity}x "
            f"{self.symbol} @ {self.price} [{self.status}]>"
        )

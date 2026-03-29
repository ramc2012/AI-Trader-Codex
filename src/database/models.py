"""SQLAlchemy ORM models for the Nifty AI Trader database.

Maps to the TimescaleDB schema defined in schema.sql.
Uses SQLAlchemy 2.0 declarative style with mapped_column.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    BigInteger,
    Date,
    Float,
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
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    ltp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    oi: Mapped[int] = mapped_column(BigInteger, default=0)
    prev_oi: Mapped[int] = mapped_column(BigInteger, default=0)
    oich: Mapped[int] = mapped_column(BigInteger, default=0)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
    iv: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    delta: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    gamma: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    theta: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    vega: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    source_ts: Mapped[datetime | None] = mapped_column(nullable=True)
    source_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    integrity_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    is_partial: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("idx_optchain_underlying_expiry", "underlying", "expiry", timestamp.desc()),
        Index("idx_optchain_strike", "underlying", "strike", "option_type", timestamp.desc()),
    )

    def __repr__(self) -> str:
        return (
            f"<OptionChain {self.underlying} {self.expiry} "
            f"{self.strike}{self.option_type} ltp={self.ltp}>"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "underlying": self.underlying,
            "expiry": self.expiry.isoformat(),
            "strike": float(self.strike),
            "option_type": self.option_type,
            "symbol": self.symbol,
            "ltp": float(self.ltp or 0),
            "oi": int(self.oi or 0),
            "prev_oi": int(self.prev_oi or 0),
            "oich": int(self.oich or 0),
            "volume": int(self.volume or 0),
            "iv": float(self.iv or 0),
            "delta": float(self.delta) if self.delta is not None else None,
            "gamma": float(self.gamma) if self.gamma is not None else None,
            "theta": float(self.theta) if self.theta is not None else None,
            "vega": float(self.vega) if self.vega is not None else None,
            "source_ts": self.source_ts.isoformat() if self.source_ts else None,
            "source_latency_ms": int(self.source_latency_ms or 0),
            "integrity_score": float(self.integrity_score or 0),
            "is_stale": bool(self.is_stale),
            "is_partial": bool(self.is_partial),
        }


class OptionOHLC(Base):
    """OHLC candles for individual option symbols."""

    __tablename__ = "option_ohlc"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    timeframe: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    underlying: Mapped[str | None] = mapped_column(String, nullable=True)
    expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    strike: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    option_type: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="idx_option_ohlc_unique"),
        Index("idx_option_ohlc_symbol_tf_time", "symbol", "timeframe", timestamp.desc()),
    )

    def __repr__(self) -> str:
        return (
            f"<OptionOHLC {self.symbol} {self.timeframe} "
            f"{self.timestamp} O={self.open} H={self.high} "
            f"L={self.low} C={self.close} V={self.volume}>"
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


class MarketSnapshot(Base):
    """Latest market snapshot for quick lookups (live price, OI, volume)."""

    __tablename__ = "market_snapshot"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    ltp: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    prev_close: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    change: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    change_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    high: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    low: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
    oi: Mapped[int] = mapped_column(BigInteger, default=0)
    bid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ask: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        Index("idx_snapshot_updated", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<MarketSnapshot {self.symbol} ltp={self.ltp} chg={self.change_percent}%>"

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "ltp": float(self.ltp),
            "prev_close": float(self.prev_close) if self.prev_close else None,
            "change": float(self.change) if self.change else None,
            "change_percent": self.change_percent,
            "open": float(self.open) if self.open else None,
            "high": float(self.high) if self.high else None,
            "low": float(self.low) if self.low else None,
            "volume": self.volume,
            "oi": self.oi,
            "bid": float(self.bid) if self.bid else None,
            "ask": float(self.ask) if self.ask else None,
            "vwap": float(self.vwap) if self.vwap else None,
            "updated_at": self.updated_at.isoformat(),
        }


class Asset(Base):
    """FnO-eligible instrument registry."""

    __tablename__ = "asset"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    instrument_type: Mapped[str] = mapped_column(String, nullable=False)  # INDEX / EQUITY
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    tick_size: Mapped[float] = mapped_column(Float, default=0.05)
    strike_interval: Mapped[float] = mapped_column(Float, default=50.0)
    is_fno: Mapped[bool] = mapped_column(Boolean, default=False)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    exchange: Mapped[str] = mapped_column(String, default="NSE")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        Index("idx_asset_type", "instrument_type"),
        Index("idx_asset_sector", "sector"),
    )

    def __repr__(self) -> str:
        return f"<Asset {self.symbol} {self.instrument_type} lot={self.lot_size}>"

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "instrument_type": self.instrument_type,
            "lot_size": self.lot_size,
            "tick_size": self.tick_size,
            "strike_interval": self.strike_interval,
            "is_fno": self.is_fno,
            "sector": self.sector,
            "exchange": self.exchange,
            "is_active": self.is_active,
        }


class AlternativeData(Base):
    """Macro indicators, institutional flow, and NLP sentiment scores."""

    __tablename__ = "alternative_data"

    timestamp: Mapped[datetime] = mapped_column(primary_key=True)
    fii_net_crores: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0.0)
    dii_net_crores: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0.0)
    market_breadth_ratio: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=1.0)
    news_sentiment_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=0.0)
    news_sentiment_label: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("idx_altdata_timestamp", timestamp.desc()),
    )

    def __repr__(self) -> str:
        return (
            f"<AlternativeData {self.timestamp} FII={self.fii_net_crores} "
            f"Breadth={self.market_breadth_ratio} Sent={self.news_sentiment_score}>"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "fii_net_crores": float(self.fii_net_crores),
            "dii_net_crores": float(self.dii_net_crores),
            "market_breadth_ratio": float(self.market_breadth_ratio),
            "news_sentiment_score": float(self.news_sentiment_score),
            "news_sentiment_label": self.news_sentiment_label,
        }

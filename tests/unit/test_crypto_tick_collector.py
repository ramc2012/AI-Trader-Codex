"""Tests for the public crypto websocket collector."""

from __future__ import annotations

import json

from src.data.collectors.crypto_tick_collector import CryptoTickCollector


def test_crypto_tick_collector_emits_trade_and_closed_candle() -> None:
    ticks: list[dict[str, object]] = []
    candles: list[dict[str, object]] = []
    collector = CryptoTickCollector(
        symbols=["CRYPTO:BTCUSDT"],
        on_tick=ticks.append,
        on_candle=candles.append,
    )

    collector._handle_message(
        json.dumps(
            {
                "stream": "btcusdt@trade",
                "data": {
                    "e": "trade",
                    "s": "BTCUSDT",
                    "p": "43125.50",
                    "q": "0.0100",
                    "T": 1710000000000,
                },
            }
        )
    )
    collector._handle_message(
        json.dumps(
            {
                "stream": "btcusdt@kline_1m",
                "data": {
                    "e": "kline",
                    "s": "BTCUSDT",
                    "k": {
                        "t": 1710000000000,
                        "s": "BTCUSDT",
                        "o": "43000.00",
                        "h": "43200.00",
                        "l": "42950.00",
                        "c": "43125.50",
                        "v": "123.4500",
                        "x": True,
                    },
                },
            }
        )
    )

    assert ticks == [
        {
            "type": "tick",
            "symbol": "CRYPTO:BTCUSDT",
            "timestamp": "2024-03-09T21:30:00+05:30",
            "ltp": 43125.5,
            "bid": None,
            "ask": None,
            "volume": 0,
            "cumulative_volume": None,
            "source": "binance_ws",
        }
    ]
    assert candles == [
        {
            "type": "candle",
            "symbol": "CRYPTO:BTCUSDT",
            "timeframe": "1",
            "timestamp": "2024-03-09T21:30:00+05:30",
            "open": 43000.0,
            "high": 43200.0,
            "low": 42950.0,
            "close": 43125.5,
            "volume": 123,
            "source": "binance_ws",
        }
    ]

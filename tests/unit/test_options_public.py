"""Tests for public US and crypto options chart/straddle helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.api.routes import options as options_api


class _DummyResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}"

    def json(self) -> dict:
        return self._payload


def _client_factory(responses: list[_DummyResponse]):
    class _DummyAsyncClient:
        def __init__(self, *args, **kwargs):
            self._responses = list(responses)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            if not self._responses:
                raise AssertionError(f"Unexpected request for {url}")
            return self._responses.pop(0)

    return _DummyAsyncClient


@pytest.mark.anyio
async def test_fetch_us_option_chart_public_parses_yahoo_payload(monkeypatch) -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1709817600, 1709818500],
                    "indicators": {
                        "quote": [
                            {
                                "open": [1.1, 1.2],
                                "high": [1.3, 1.4],
                                "low": [1.0, 1.1],
                                "close": [1.25, 1.35],
                                "volume": [100, 150],
                            }
                        ]
                    },
                }
            ]
        }
    }
    monkeypatch.setattr(
        options_api.httpx,
        "AsyncClient",
        _client_factory([_DummyResponse(200, payload)]),
    )

    candles = await options_api._fetch_us_option_chart_public("US:AAPL260306C00232500", "15", 5)

    assert len(candles) == 2
    assert candles[0]["open"] == 1.1
    assert candles[1]["close"] == 1.35
    assert candles[0]["volume"] == 100
    assert candles[0]["timestamp"].endswith("+05:30")


@pytest.mark.anyio
async def test_fetch_crypto_option_chart_public_parses_deribit_payload(monkeypatch) -> None:
    payload = {
        "result": {
            "ticks": [1709817600000, 1709818500000],
            "open": [2100.0, 2110.0],
            "high": [2125.0, 2130.0],
            "low": [2090.0, 2105.0],
            "close": [2115.0, 2120.0],
            "volume": [12.5, 18.0],
        }
    }
    monkeypatch.setattr(
        options_api.httpx,
        "AsyncClient",
        _client_factory([_DummyResponse(200, payload)]),
    )

    candles = await options_api._fetch_crypto_option_chart_public("CRYPTO:ETH-7MAR26-2100-C", "15", 5)

    assert len(candles) == 2
    assert candles[0]["high"] == 2125.0
    assert candles[1]["close"] == 2120.0
    assert candles[1]["volume"] == 18


def test_merge_straddle_candles_sums_matching_timestamps() -> None:
    merged = options_api._merge_straddle_candles(
        [
            {"timestamp": "2026-03-07T10:00:00+05:30", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
            {"timestamp": "2026-03-07T10:15:00+05:30", "open": 11, "high": 13, "low": 10, "close": 12, "volume": 120},
        ],
        [
            {"timestamp": "2026-03-07T10:00:00+05:30", "open": 8, "high": 9, "low": 7, "close": 8.5, "volume": 90},
            {"timestamp": "2026-03-07T10:15:00+05:30", "open": 9, "high": 9.5, "low": 8, "close": 8.8, "volume": 95},
        ],
    )

    assert len(merged) == 2
    assert merged[0]["close"] == 19.5
    assert merged[1]["volume"] == 215


@pytest.mark.anyio
async def test_get_option_chart_data_uses_public_provider_for_us(monkeypatch) -> None:
    async def _fake_fetch(symbol: str, interval: str, days: int):
        assert symbol == "US:AAPL260306C00232500"
        assert interval == "15"
        assert days == 5
        return [{"timestamp": "2026-03-07T10:00:00+05:30", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10}]

    monkeypatch.setattr(options_api, "_fetch_public_option_chart", _fake_fetch)

    response = await options_api.get_option_chart_data(
        option_symbol="US:AAPL260306C00232500",
        interval="15",
        days=5,
        client=MagicMock(),
        db=MagicMock(),
    )

    assert response["count"] == 1
    assert response["candles"][0]["close"] == 2


@pytest.mark.anyio
async def test_get_atm_straddle_chart_uses_public_chain_for_us(monkeypatch) -> None:
    async def _fake_chain(underlying: str, strike_count: int, include_expiries: int):
        assert underlying == "US:AAPL"
        assert strike_count == 80
        assert include_expiries == 6
        return {
            "data": {
                "expiryData": [
                    {
                        "expiry": "2026-03-06",
                        "expiry_ts": 1772755200,
                        "spot": 232.2,
                        "strikes": [
                            {
                                "strike": 232.5,
                                "ce": {"symbol": "US:AAPL260306C00232500"},
                                "pe": {"symbol": "US:AAPL260306P00232500"},
                            }
                        ],
                    }
                ]
            }
        }

    async def _fake_chart(symbol: str, interval: str, days: int):
        if symbol.endswith("C00232500"):
            return [{"timestamp": "2026-03-07T10:00:00+05:30", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}]
        return [{"timestamp": "2026-03-07T10:00:00+05:30", "open": 8, "high": 9, "low": 7, "close": 8.5, "volume": 90}]

    monkeypatch.setattr(options_api, "_fetch_us_option_chain_public", _fake_chain)
    monkeypatch.setattr(options_api, "_fetch_public_option_chart", _fake_chart)

    response = await options_api.get_atm_straddle_chart(
        underlying="US:AAPL",
        expiry_ts=1772755200,
        strike=232.5,
        interval="15",
        days=5,
        client=MagicMock(),
        registry=MagicMock(),
        db=MagicMock(),
    )

    assert response["strike"] == 232.5
    assert response["ce_symbol"] == "US:AAPL260306C00232500"
    assert response["pe_symbol"] == "US:AAPL260306P00232500"
    assert response["count"] == 1
    assert response["candles"][0]["close"] == 19.0


@pytest.mark.anyio
async def test_fetch_public_straddle_candles_falls_back_to_nearby_strike(monkeypatch) -> None:
    async def _fake_chart(symbol: str, interval: str, days: int):
        if symbol.endswith("C00252500") or symbol.endswith("P00252500"):
            raise HTTPException(status_code=404, detail="No option chart data")
        if symbol.endswith("C00250000"):
            return [{"timestamp": "2026-03-07T10:00:00+05:30", "open": 7, "high": 8, "low": 6, "close": 7.5, "volume": 50}]
        return [{"timestamp": "2026-03-07T10:00:00+05:30", "open": 1, "high": 1.2, "low": 0.8, "close": 1.1, "volume": 60}]

    monkeypatch.setattr(options_api, "_fetch_public_option_chart", _fake_chart)

    strike, ce_symbol, pe_symbol, candles = await options_api._fetch_public_straddle_candles(
        [
            {"strike": 252.5, "ce": {"symbol": "US:AAPL260309C00252500"}, "pe": {"symbol": "US:AAPL260309P00252500"}},
            {"strike": 250.0, "ce": {"symbol": "US:AAPL260309C00250000"}, "pe": {"symbol": "US:AAPL260309P00250000"}},
        ],
        spot=252.4,
        strike=252.5,
        interval="15",
        days=5,
    )

    assert strike == 250.0
    assert ce_symbol == "US:AAPL260309C00250000"
    assert pe_symbol == "US:AAPL260309P00250000"
    assert candles[0]["close"] == 8.6

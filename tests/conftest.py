"""Shared test fixtures for the Nifty AI Trader test suite."""

import asyncio
import inspect

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run AnyIO tests on asyncio backend only."""
    return "asyncio"


def pytest_pyfunc_call(pyfuncitem):
    """Run ``@pytest.mark.asyncio`` tests without pytest-asyncio plugin."""
    if "asyncio" not in pyfuncitem.keywords:
        return None
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None
    signature = inspect.signature(pyfuncitem.obj)
    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in signature.parameters
        if name in pyfuncitem.funcargs
    }
    asyncio.run(pyfuncitem.obj(**kwargs))
    return True


@pytest.fixture
def sample_ohlc_data() -> list[dict]:
    """Return sample OHLC candle data for testing."""
    return [
        {
            "timestamp": 1707369000,
            "open": 22150.50,
            "high": 22200.75,
            "low": 22100.25,
            "close": 22180.00,
            "volume": 150000,
        },
        {
            "timestamp": 1707372600,
            "open": 22180.00,
            "high": 22250.00,
            "low": 22170.50,
            "close": 22230.25,
            "volume": 120000,
        },
    ]

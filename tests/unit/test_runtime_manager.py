"""Tests for runtime-manager collector boot behavior."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.data.runtime_manager import RuntimeManager


@pytest.mark.asyncio
async def test_runtime_manager_starts_public_crypto_collector_without_broker_auth() -> None:
    async def _noop_loop() -> None:
        await asyncio.sleep(0)

    client = MagicMock()
    client.is_authenticated = False
    client.try_auto_refresh_with_saved_pin.return_value = False
    registry = MagicMock()

    manager = RuntimeManager(client=client, registry=registry)
    manager._start_crypto_collector = AsyncMock()
    manager._start_tick_collector = AsyncMock()
    manager._start_order_collector = AsyncMock()
    manager._option_snapshot_loop = _noop_loop
    manager._instrument_refresh_loop = _noop_loop
    manager._preopen_refresh_loop = _noop_loop
    manager._tick_watchdog = _noop_loop

    await manager.start()

    manager._start_crypto_collector.assert_awaited_once()
    manager._start_tick_collector.assert_not_called()
    manager._start_order_collector.assert_not_called()
    registry.refresh.assert_not_called()

    await manager.stop()

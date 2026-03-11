from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.data import auto_collector


def test_collection_plan_includes_three_minute_bars() -> None:
    assert "3" in auto_collector.COLLECTION_PLAN
    assert auto_collector.COLLECTION_PLAN["3"]["days_back"] == 14


@pytest.mark.asyncio
async def test_intraday_refresh_collects_three_minute_bars(monkeypatch) -> None:
    collect_mock = AsyncMock(return_value=1)
    sleep_mock = AsyncMock(return_value=None)

    monkeypatch.setattr(auto_collector, "ALL_WATCHLIST_SYMBOLS", ["NSE:NIFTY50-INDEX"])
    monkeypatch.setattr(auto_collector, "collect_symbol_data", collect_mock)
    monkeypatch.setattr(auto_collector.asyncio, "sleep", sleep_mock)

    total = await auto_collector._intraday_refresh(client=object())  # type: ignore[arg-type]

    timeframes = [call.args[2] for call in collect_mock.await_args_list]
    assert timeframes == ["3", "5", "15", "60"]
    assert total == 4

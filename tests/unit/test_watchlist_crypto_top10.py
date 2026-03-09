from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import src.api.routes.watchlist as watchlist


def test_crypto_top10_maps_provider_quotes() -> None:
    fake_quote = AsyncMock(
        return_value={
            "ltp": 102_500.0,
            "change_pct": 2.4,
            "volume": 4_250_000.0,
            "source": "finnhub",
        }
    )

    with patch.object(watchlist, "_fetch_crypto_quote", fake_quote):
        rows = asyncio.run(watchlist._fetch_crypto_top10())

    assert rows
    assert rows[0]["price_usd"] == 102_500.0
    assert rows[0]["change_pct_24h"] == 2.4
    assert rows[0]["source"] == "finnhub"

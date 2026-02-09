"""Tests for the option chain data collector."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest
from fyers_apiv3.fyersModel import FyersModel

from src.config.market_hours import IST
from src.data.collectors.option_chain_collector import (
    ChainSnapshot,
    OptionChainCollector,
    OptionStrike,
)
from src.integrations.fyers_client import FyersClient
from src.utils.exceptions import DataFetchError


@pytest.fixture
def mock_client() -> FyersClient:
    with patch("src.integrations.fyers_client.get_settings") as ms:
        s = MagicMock()
        s.fyers_app_id = "T"
        s.fyers_secret_key = "T"
        s.fyers_redirect_uri = "http://localhost/cb"
        s.fyers_rate_limit_per_sec = 100
        ms.return_value = s
        c = FyersClient()
        c._access_token = "T:tok"
        c._fyers = MagicMock(spec=FyersModel)
        return c


@pytest.fixture
def sample_chain_response() -> dict:
    return {
        "s": "ok",
        "data": {
            "optionsChain": [
                {
                    "strike_price": 22000,
                    "expiry": "2024-02-15",
                    "ce": {"ltp": 250.0, "oi": 5000000, "volume": 100000, "iv": 15.5},
                    "pe": {"ltp": 180.0, "oi": 4000000, "volume": 80000, "iv": 16.2},
                },
                {
                    "strike_price": 22100,
                    "expiry": "2024-02-15",
                    "ce": {"ltp": 190.0, "oi": 4500000, "volume": 90000, "iv": 14.8},
                    "pe": {"ltp": 220.0, "oi": 3500000, "volume": 70000, "iv": 17.1},
                },
                {
                    "strike_price": 22200,
                    "expiry": "2024-02-15",
                    "ce": {"ltp": 140.0, "oi": 3000000, "volume": 60000, "iv": 14.0},
                    "pe": {"ltp": 270.0, "oi": 6000000, "volume": 120000, "iv": 18.0},
                },
            ]
        },
    }


class TestOptionStrike:
    def test_to_dict(self) -> None:
        s = OptionStrike(
            timestamp=datetime(2024, 2, 8, tzinfo=IST),
            underlying="NSE:NIFTY50-INDEX",
            expiry=date(2024, 2, 15),
            strike=22000.0,
            option_type="CE",
            ltp=250.0,
            oi=5000000,
        )
        d = s.to_dict()
        assert d["strike"] == 22000.0
        assert d["option_type"] == "CE"
        assert d["oi"] == 5000000


class TestChainSnapshot:
    def _make_snapshot(self) -> ChainSnapshot:
        now = datetime.now(tz=IST)
        return ChainSnapshot(
            underlying="NSE:NIFTY50-INDEX",
            timestamp=now,
            expiry=date(2024, 2, 15),
            strikes=[
                OptionStrike(now, "NSE:NIFTY50-INDEX", date(2024, 2, 15), 22000, "CE", oi=5000),
                OptionStrike(now, "NSE:NIFTY50-INDEX", date(2024, 2, 15), 22000, "PE", oi=4000),
                OptionStrike(now, "NSE:NIFTY50-INDEX", date(2024, 2, 15), 22100, "CE", oi=3000),
                OptionStrike(now, "NSE:NIFTY50-INDEX", date(2024, 2, 15), 22100, "PE", oi=6000),
            ],
        )

    def test_call_put_splits(self) -> None:
        snap = self._make_snapshot()
        assert len(snap.call_strikes) == 2
        assert len(snap.put_strikes) == 2

    def test_total_oi(self) -> None:
        snap = self._make_snapshot()
        assert snap.total_call_oi == 8000
        assert snap.total_put_oi == 10000

    def test_pcr(self) -> None:
        snap = self._make_snapshot()
        assert snap.pcr == pytest.approx(10000 / 8000)

    def test_pcr_zero_calls(self) -> None:
        snap = ChainSnapshot("S", datetime.now(tz=IST), date.today(), strikes=[])
        assert snap.pcr is None

    def test_max_pain(self) -> None:
        snap = self._make_snapshot()
        mp = snap.max_pain
        assert mp is not None
        assert mp in (22000.0, 22100.0)


class TestOptionChainCollector:
    def test_collect_snapshot(
        self, mock_client: FyersClient, sample_chain_response: dict
    ) -> None:
        mock_client._fyers.optionchain.return_value = sample_chain_response
        collector = OptionChainCollector(
            client=mock_client,
            symbols=["NSE:NIFTY50-INDEX"],
            strike_count=5,
        )
        snap = collector.collect_snapshot("NSE:NIFTY50-INDEX")
        assert len(snap.strikes) == 6  # 3 strikes × (CE + PE)
        assert snap.underlying == "NSE:NIFTY50-INDEX"

    def test_collect_all(
        self, mock_client: FyersClient, sample_chain_response: dict
    ) -> None:
        mock_client._fyers.optionchain.return_value = sample_chain_response
        collector = OptionChainCollector(
            client=mock_client,
            symbols=["NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX"],
        )
        snapshots = collector.collect_all()
        assert len(snapshots) == 2

    def test_collect_api_error(self, mock_client: FyersClient) -> None:
        mock_client._fyers.optionchain.return_value = {
            "s": "error",
            "code": -300,
            "message": "Invalid",
        }
        collector = OptionChainCollector(client=mock_client)
        with pytest.raises(DataFetchError):
            collector.collect_snapshot("NSE:NIFTY50-INDEX")

    def test_collect_all_handles_partial_failure(
        self, mock_client: FyersClient, sample_chain_response: dict
    ) -> None:
        # First call succeeds, second fails
        mock_client._fyers.optionchain.side_effect = [
            sample_chain_response,
            {"s": "error", "code": -300, "message": "Failed"},
        ]
        collector = OptionChainCollector(
            client=mock_client,
            symbols=["NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX"],
        )
        snapshots = collector.collect_all()
        assert len(snapshots) == 1  # only first succeeded

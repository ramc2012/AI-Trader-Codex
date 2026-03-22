"""Tests for FnO swing research helpers."""

from __future__ import annotations

import pandas as pd

from src.research.fno_swing_research import (
    ResearchConfig,
    _normalize_price_frame,
    add_swing_targets,
    choose_target_columns,
    classify_profile_shape_proxy,
    select_model_feature_columns,
)


def test_classify_profile_shape_proxy_handles_named_shapes() -> None:
    assert classify_profile_shape_proxy(skew_value=0.0, poc_position=0.50, range_to_atr=8.5) == "trend"
    assert classify_profile_shape_proxy(skew_value=-0.5, poc_position=0.70, range_to_atr=3.0) == "p_shape"
    assert classify_profile_shape_proxy(skew_value=0.6, poc_position=0.30, range_to_atr=3.0) == "b_shape"
    assert classify_profile_shape_proxy(skew_value=0.0, poc_position=0.50, range_to_atr=2.0) == "balanced"


def test_normalize_price_frame_flattens_single_ticker_multiindex() -> None:
    columns = pd.MultiIndex.from_tuples(
        [
            ("Adj Close", "^NSEI"),
            ("Close", "^NSEI"),
            ("High", "^NSEI"),
            ("Low", "^NSEI"),
            ("Open", "^NSEI"),
            ("Volume", "^NSEI"),
        ]
    )
    frame = pd.DataFrame(
        [[100.0, 100.0, 101.0, 99.0, 99.5, 1_000.0]],
        index=pd.to_datetime(["2024-01-01"]),
        columns=columns,
    )

    normalized = _normalize_price_frame(frame, "RELIANCE")

    assert not normalized.empty
    assert list(normalized.columns) == ["open", "high", "low", "close", "volume", "symbol", "sector", "ticker"]
    assert normalized.loc[pd.Timestamp("2024-01-01"), "close"] == 100.0
    assert normalized.loc[pd.Timestamp("2024-01-01"), "ticker"] == "RELIANCE.NS"


def test_normalize_price_frame_accepts_custom_metadata_for_non_equity_series() -> None:
    columns = pd.MultiIndex.from_tuples(
        [
            ("Adj Close", "^NSEI"),
            ("Close", "^NSEI"),
            ("High", "^NSEI"),
            ("Low", "^NSEI"),
            ("Open", "^NSEI"),
            ("Volume", "^NSEI"),
        ]
    )
    frame = pd.DataFrame(
        [[100.0, 100.0, 101.0, 99.0, 99.5, 1_000.0]],
        index=pd.to_datetime(["2024-01-01"]),
        columns=columns,
    )

    normalized = _normalize_price_frame(
        frame,
        "NIFTY_BENCH",
        ticker="^NSEI",
        sector="INDEX",
    )

    assert normalized.loc[pd.Timestamp("2024-01-01"), "symbol"] == "NIFTY_BENCH"
    assert normalized.loc[pd.Timestamp("2024-01-01"), "ticker"] == "^NSEI"
    assert normalized.loc[pd.Timestamp("2024-01-01"), "sector"] == "INDEX"


def test_add_swing_targets_labels_up_and_down_swings() -> None:
    frame = pd.DataFrame(
        {
            "close": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 112.0, 90.0, 89.0, 88.0, 87.0],
            "high": [101.0, 106.0, 101.0, 100.5, 100.5, 100.5, 100.5, 100.5, 100.5, 100.5, 111.0, 112.5, 95.0, 94.0, 93.0, 92.0],
            "low": [99.0, 99.0, 94.0, 99.5, 99.5, 99.5, 99.5, 99.5, 99.5, 99.5, 99.0, 99.0, 88.0, 87.5, 87.0, 86.5],
            "open": [100.0] * 16,
            "volume": [1_000.0] * 16,
            "atr_pct": [0.01] * 16,
        }
    )
    config = ResearchConfig(
        short_atr_multipliers=(1.0,),
        long_atr_multipliers=(1.0,),
        long_horizon_min_days=10,
        long_horizon_max_days=15,
    )

    labeled = add_swing_targets(frame, config)

    assert labeled.loc[0, "target_short_hit_atr_1_0"] == 1.0
    assert labeled.loc[0, "target_short_direction_atr_1_0"] == "up"
    assert labeled.loc[1, "target_short_direction_atr_1_0"] == "down"
    assert labeled.loc[0, "target_long_hit_atr_1_0"] == 1.0


def test_choose_target_columns_prefers_hit_rate_near_desired_level() -> None:
    dataset = pd.DataFrame(
        {
            "target_short_hit_atr_1_0": [1.0] * 40 + [0.0] * 60,
            "target_short_direction_atr_1_0": ["up"] * 40 + ["neutral"] * 60,
            "target_short_hit_atr_1_5": [1.0] * 10 + [0.0] * 90,
            "target_short_direction_atr_1_5": ["up"] * 10 + ["neutral"] * 90,
            "target_long_hit_atr_2_0": [1.0] * 6 + [0.0] * 94,
            "target_long_direction_atr_2_0": ["down"] * 6 + ["neutral"] * 94,
            "target_long_hit_atr_3_0": [1.0] * 2 + [0.0] * 98,
            "target_long_direction_atr_3_0": ["down"] * 2 + ["neutral"] * 98,
        }
    )
    config = ResearchConfig(
        short_atr_multipliers=(1.0, 1.5),
        long_atr_multipliers=(2.0, 3.0),
        desired_short_hit_rate=0.08,
        desired_long_hit_rate=0.05,
    )

    selected = choose_target_columns(dataset, config)

    assert selected["selected_short"]["multiplier"] == 1.5
    assert selected["selected_long"]["multiplier"] == 2.0


def test_select_model_feature_columns_excludes_future_and_target_leakage() -> None:
    dataset = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-01-01")],
            "symbol": ["RELIANCE"],
            "sector": ["Energy"],
            "ticker": ["RELIANCE.NS"],
            "profile_shape_code": ["trend"],
            "rsi_14": [62.0],
            "atr_pct": [0.02],
            "future_up_2d": [0.07],
            "target_short_hit_atr_1_0": [1.0],
            "target_short_direction_atr_1_0": ["up"],
            "target_long_direction_atr_2_0": ["neutral"],
        }
    )

    feature_columns = select_model_feature_columns(
        dataset,
        excluded_labels=["target_short_direction_atr_1_0", "target_long_direction_atr_2_0"],
    )

    assert feature_columns == ["rsi_14", "atr_pct"]

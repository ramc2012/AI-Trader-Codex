from pathlib import Path

from src.ml.online.strategy_performance_tracker import StrategyPerformanceTracker


def test_strategy_tracker_persists_market_specific_rewards(tmp_path: Path) -> None:
    tracker = StrategyPerformanceTracker(alpha=0.2, data_dir=tmp_path)

    global_ema, was_disabled, market_ema = tracker.record_trade("EMA_Crossover", 5.0, market="US")

    assert was_disabled is False
    assert global_ema > 0
    assert market_ema > 0

    reloaded = StrategyPerformanceTracker(alpha=0.2, data_dir=tmp_path)
    reloaded.load_state()

    assert reloaded.get_reward_ema("EMA_Crossover") == global_ema
    assert reloaded.get_reward_ema("EMA_Crossover", market="US", prefer_market=True) == market_ema
    assert reloaded.get_trade_count("EMA_Crossover", market="US", prefer_market=True) == 1


def test_strategy_tracker_market_rewards_do_not_overwrite_global_curve(tmp_path: Path) -> None:
    tracker = StrategyPerformanceTracker(alpha=0.2, data_dir=tmp_path)

    tracker.record_trade("Fractal_Profile_Breakout", 10.0, market="US")
    tracker.record_trade("Fractal_Profile_Breakout", -10.0, market="CRYPTO")

    global_reward = tracker.get_reward_ema("Fractal_Profile_Breakout")
    us_reward = tracker.get_reward_ema("Fractal_Profile_Breakout", market="US", prefer_market=True)
    crypto_reward = tracker.get_reward_ema("Fractal_Profile_Breakout", market="CRYPTO", prefer_market=True)

    assert us_reward > 0
    assert crypto_reward < 0
    assert abs(global_reward) < abs(us_reward)
    assert abs(global_reward) < abs(crypto_reward)


def test_strategy_tracker_can_seed_market_history_without_global_replay(tmp_path: Path) -> None:
    tracker = StrategyPerformanceTracker(alpha=0.2, data_dir=tmp_path)
    tracker.record_trade("Supertrend_Breakout", 10.0)

    tracker.seed_market_stats(
        [
            ("Supertrend_Breakout", "US", 4.0),
            ("Supertrend_Breakout", "US", -1.0),
            ("Supertrend_Breakout", "CRYPTO", -2.0),
        ]
    )

    assert tracker.has_market_stats() is True
    assert tracker.get_trade_count("Supertrend_Breakout") == 1
    assert tracker.get_trade_count("Supertrend_Breakout", market="US", prefer_market=True) == 2
    assert tracker.get_reward_ema("Supertrend_Breakout", market="CRYPTO", prefer_market=True) < 0

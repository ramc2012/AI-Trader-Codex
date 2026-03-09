"""Tests for agent event Telegram formatting."""

from src.agent.events import AgentEvent, AgentEventType


def test_fractal_candidate_telegram_text_includes_trade_levels() -> None:
    event = AgentEvent(
        event_type=AgentEventType.FRACTAL_CANDIDATE,
        title="Nifty candidate",
        message="Bullish structure confirmed",
        metadata={
            "symbol": "NSE:NIFTY50-INDEX",
            "direction": "bullish",
            "conviction": 82,
            "hourly_shape": "elongated_up",
            "consecutive_migration_hours": 3,
            "entry_trigger": 24220,
            "stop_reference": 24162,
            "target_reference": 24300,
            "suggested_contract": "NIFTY 24200 CE",
            "rationale": "3 hour migration with supportive options flow",
        },
    )

    text = event.to_telegram_text()

    assert "NSE:NIFTY50-INDEX" in text
    assert "82/100" in text
    assert "Entry: 24220" in text
    assert "Stop: 24162" in text
    assert "Contract: NIFTY 24200 CE" in text


def test_fractal_scan_summary_telegram_text_includes_leaders() -> None:
    event = AgentEvent(
        event_type=AgentEventType.FRACTAL_SCAN_SUMMARY,
        title="Fractal Watchlist Scan",
        message="2 candidate(s)",
        metadata={
            "scan_date": "2026-03-06",
            "symbols_scanned": 5,
            "candidates_found": 2,
            "top_symbols": "NSE:NIFTY50-INDEX, NSE:NIFTYBANK-INDEX",
        },
    )

    text = event.to_telegram_text()

    assert "2026-03-06" in text
    assert "Universe: 5" in text
    assert "Candidates: <b>2</b>" in text
    assert "NSE:NIFTY50-INDEX" in text

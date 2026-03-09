"""Tests for Telegram notifier event filtering."""

import asyncio

import pytest

from src.agent.events import AgentEvent, AgentEventBus, AgentEventType
from src.agent.telegram_notifier import TelegramNotifier


@pytest.mark.asyncio
async def test_notifier_forwards_trade_and_status_events_only(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = AgentEventBus()
    notifier = TelegramNotifier(bot_token="token", chat_id="chat", event_bus=bus)
    sent_messages: list[str] = []

    async def fake_send_message(text: str, parse_mode: str = "HTML") -> bool:
        sent_messages.append(f"{parse_mode}:{text}")
        return True

    monkeypatch.setattr(notifier, "send_message", fake_send_message)

    await notifier.start()
    try:
        await bus.emit(AgentEvent(
            event_type=AgentEventType.SIGNAL_GENERATED,
            title="Signal Generated",
            message="This should stay out of Telegram.",
        ))
        await bus.emit(AgentEvent(
            event_type=AgentEventType.AGENT_STARTED,
            title="AI Agent Started",
            message="Agent is now running.",
            severity="success",
        ))
        await bus.emit(AgentEvent(
            event_type=AgentEventType.ORDER_PLACED,
            title="Order Filled — NIFTY50",
            message="BUY 50 x NIFTY50 @ 22,000.00.",
            severity="success",
        ))
        await bus.emit(AgentEvent(
            event_type=AgentEventType.DAILY_SUMMARY,
            title="Agent Status Update",
            message="Positions:\n• NIFTY50 LONG x1 avg 22,000.00 P&L +120.00",
            severity="success",
        ))

        await asyncio.sleep(0.05)
    finally:
        await notifier.stop()

    assert len(sent_messages) == 3
    assert "AI Agent Started" in sent_messages[0]
    assert "Order Filled" in sent_messages[1]
    assert "Agent Status Update" in sent_messages[2]
    assert all("Signal Generated" not in message for message in sent_messages)

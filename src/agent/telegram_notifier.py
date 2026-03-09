"""Telegram notification service for the AI trading agent.

Subscribes to the AgentEventBus and forwards only high-signal lifecycle
and status-summary events to a Telegram chat via the Bot API. Detailed
trade, risk, and scan chatter stays in the web UI/event log so Telegram
remains a compact operational feed.
"""

from __future__ import annotations

import asyncio
from typing import Optional, Set

import httpx

from src.agent.events import AgentEvent, AgentEventBus, AgentEventType
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Keep Telegram focused on operational state, actual trade outcomes,
# and compact periodic position summaries.
TELEGRAM_EVENT_FILTER: Set[AgentEventType] = {
    AgentEventType.AGENT_STARTED,
    AgentEventType.AGENT_STOPPED,
    AgentEventType.AGENT_PAUSED,
    AgentEventType.AGENT_RESUMED,
    AgentEventType.AGENT_ERROR,
    AgentEventType.ORDER_PLACED,
    AgentEventType.ORDER_REJECTED,
    AgentEventType.POSITION_OPENED,
    AgentEventType.POSITION_CLOSED,
    AgentEventType.DAILY_SUMMARY,
}


class TelegramNotifier:
    """Send trading events to Telegram.

    Subscribes to an AgentEventBus, filters for trade-significant events,
    and sends formatted HTML messages to the configured Telegram chat.
    """

    TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        event_bus: AgentEventBus,
        enabled: bool = True,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._event_bus = event_bus
        self._client: Optional[httpx.AsyncClient] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._queue: Optional[asyncio.Queue[AgentEvent]] = None
        self._enabled = bool(enabled)
        self._credentials_configured = bool(bot_token and chat_id)
        self._last_error: str | None = None

    @property
    def is_configured(self) -> bool:
        """Whether Telegram credentials are set."""
        return self._credentials_configured

    @property
    def is_enabled(self) -> bool:
        """Whether Telegram delivery is enabled for this instance."""
        return self._enabled

    @property
    def can_send(self) -> bool:
        """Whether credentials are configured and delivery is enabled."""
        return self._enabled and self._credentials_configured

    @property
    def is_running(self) -> bool:
        """Whether the background consumer task is active."""
        return self._task is not None and not self._task.done()

    @property
    def last_error(self) -> str | None:
        """Most recent Telegram send error, if any."""
        return self._last_error

    async def start(self) -> None:
        """Subscribe to event bus and start consumer loop."""
        if not self._credentials_configured:
            logger.info("telegram_notifier_disabled", reason="missing credentials")
            return
        if not self._enabled:
            logger.info("telegram_notifier_disabled", reason="disabled by settings")
            return
        if self._task and not self._task.done():
            return

        self._client = httpx.AsyncClient(timeout=10.0)
        self._queue = self._event_bus.subscribe()
        self._task = asyncio.create_task(self._consumer_loop())
        logger.info("telegram_notifier_started")

    async def stop(self) -> None:
        """Unsubscribe and clean up."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._queue:
            self._event_bus.unsubscribe(self._queue)
            self._queue = None

        if self._client:
            await self._client.aclose()
            self._client = None

        logger.info("telegram_notifier_stopped")

    async def send_message(self, text: str, parse_mode: str = "HTML", force: bool = False) -> bool:
        """Send a message to the configured Telegram chat.

        Returns True if the message was sent successfully.
        """
        if not self._credentials_configured:
            return False
        if not self._enabled and not force:
            return False
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)

        url = self.TELEGRAM_API.format(token=self._bot_token)
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        try:
            response = await self._client.post(url, json=payload)
            if response.status_code == 200:
                self._last_error = None
                return True
            self._last_error = response.text[:200]
            logger.warning(
                "telegram_send_failed",
                status=response.status_code,
                body=response.text[:200],
            )
            return False
        except Exception as e:
            self._last_error = str(e)
            logger.warning("telegram_send_error", error=str(e))
            return False

    async def send_test_message(self) -> bool:
        """Send a test message to verify Telegram configuration."""
        if not self._credentials_configured:
            return False

        if not self._client:
            self._client = httpx.AsyncClient(timeout=10.0)

        text = (
            "<b>Nifty AI Trader — Test Message</b>\n\n"
            "Telegram integration is working correctly.\n"
            "You will receive agent status and position summaries here."
        )
        return await self.send_message(text, force=True)

    async def _consumer_loop(self) -> None:
        """Read events from queue, filter, format, and send to Telegram."""
        if not self._queue:
            return

        try:
            while True:
                event = await self._queue.get()

                # Only forward lifecycle and status-summary events.
                if event.event_type not in TELEGRAM_EVENT_FILTER:
                    continue

                text = self._format_event(event)
                await self.send_message(text)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("telegram_consumer_error", error=str(e))

    def _format_event(self, event: AgentEvent) -> str:
        """Format an AgentEvent as a Telegram HTML message."""
        # Use event's own formatting as base
        return event.to_telegram_text()

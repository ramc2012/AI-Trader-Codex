"""Tests for Telegram configuration persistence and status reporting."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.api.routes.auth import get_telegram_config, save_telegram_config
from src.api.schemas import TelegramConfigRequest
from src.config.settings import get_settings


class _DummyNotifier:
    def __init__(self, *, running: bool = False, last_error: str | None = None) -> None:
        self.is_running = running
        self.last_error = last_error
        self.stop_calls = 0

    async def stop(self) -> None:
        self.stop_calls += 1


def _write_env(
    path: Path,
    *,
    enabled: bool = True,
    bot: str = "",
    chat: str = "",
    interval: int = 30,
) -> None:
    path.write_text(
        "\n".join(
            [
                f"TELEGRAM_ENABLED={'true' if enabled else 'false'}",
                f'TELEGRAM_BOT_TOKEN="{bot}"',
                f'TELEGRAM_CHAT_ID="{chat}"',
                f"TELEGRAM_STATUS_INTERVAL_MINUTES={interval}",
                "",
            ]
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_save_telegram_config_preserves_omitted_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    _write_env(env_path, bot="existing-bot", chat="existing-chat", interval=45)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    monkeypatch.setenv("TELEGRAM_STATUS_INTERVAL_MINUTES", "45")
    get_settings.cache_clear()

    existing_notifier = _DummyNotifier()
    refreshed_notifier = _DummyNotifier()
    monkeypatch.setattr("src.api.routes.auth.get_telegram_notifier", lambda: existing_notifier)
    monkeypatch.setattr("src.api.routes.auth.reset_telegram_notifier", lambda: None)
    response = await save_telegram_config(TelegramConfigRequest(chat_id="updated-chat"))

    assert response.configured is True
    assert response.enabled is True
    assert response.bot_configured is True
    assert response.chat_configured is True
    assert response.status_interval_minutes == 45
    assert existing_notifier.stop_calls == 1
    contents = env_path.read_text(encoding="utf-8")
    assert "TELEGRAM_ENABLED=true" in contents
    assert "TELEGRAM_BOT_TOKEN=existing-bot" in contents
    assert 'TELEGRAM_CHAT_ID=updated-chat' in contents
    assert "TELEGRAM_STATUS_INTERVAL_MINUTES=45" in contents

    monkeypatch.setattr("src.api.routes.auth.get_telegram_notifier", lambda: refreshed_notifier)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_save_telegram_config_allows_explicit_clear(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    _write_env(env_path, bot="existing-bot", chat="existing-chat", interval=45)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    monkeypatch.setenv("TELEGRAM_STATUS_INTERVAL_MINUTES", "45")
    get_settings.cache_clear()

    notifier = _DummyNotifier()
    monkeypatch.setattr("src.api.routes.auth.get_telegram_notifier", lambda: notifier)
    monkeypatch.setattr("src.api.routes.auth.reset_telegram_notifier", lambda: None)
    response = await save_telegram_config(
        TelegramConfigRequest(
            enabled=False,
            bot_token="",
            chat_id="",
            status_interval_minutes=0,
        )
    )

    assert response.configured is False
    assert response.enabled is False
    assert response.bot_configured is False
    assert response.chat_configured is False
    assert response.active is False
    assert response.status_interval_minutes == 0
    contents = env_path.read_text(encoding="utf-8")
    assert "TELEGRAM_ENABLED=false" in contents
    assert 'TELEGRAM_BOT_TOKEN=""' in contents
    assert 'TELEGRAM_CHAT_ID=""' in contents
    assert "TELEGRAM_STATUS_INTERVAL_MINUTES=0" in contents


@pytest.mark.asyncio
async def test_get_telegram_config_reports_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_env(tmp_path / ".env", enabled=False, bot="bot-token", chat="123456", interval=15)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_ENABLED", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    monkeypatch.setenv("TELEGRAM_STATUS_INTERVAL_MINUTES", "15")
    get_settings.cache_clear()

    notifier = _DummyNotifier(running=True, last_error="chat not found")
    monkeypatch.setattr("src.api.routes.auth.get_telegram_notifier", lambda: notifier)

    response = await get_telegram_config()

    assert response.configured is True
    assert response.enabled is False
    assert response.active is False
    assert response.status_interval_minutes == 15
    assert response.last_error == "chat not found"

"""Tests for persistent FYERS PIN storage and crypto key migration."""

from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet

from src.config.settings import get_settings
from src.utils.pin_storage import load_pin, save_pin


def test_save_pin_uses_persistent_data_dir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()

    assert save_pin("1234") is True
    assert (data_dir / ".fyers_pin").exists()
    assert (data_dir / ".crypto_key").exists()
    assert not (tmp_path / ".fyers_pin").exists()
    assert not (tmp_path / ".crypto_key").exists()
    assert load_pin() == "1234"


def test_load_pin_migrates_legacy_pin_and_key(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()

    key = Fernet.generate_key()
    (tmp_path / ".crypto_key").write_bytes(key)
    (tmp_path / ".crypto_key").chmod(0o600)
    encrypted = Fernet(key).encrypt(b"5678").decode()
    (tmp_path / ".fyers_pin").write_text(encrypted, encoding="utf-8")
    (tmp_path / ".fyers_pin").chmod(0o600)

    assert load_pin() == "5678"
    assert (data_dir / ".fyers_pin").exists()
    assert (data_dir / ".crypto_key").exists()
    assert not (tmp_path / ".fyers_pin").exists()
    assert not (tmp_path / ".crypto_key").exists()

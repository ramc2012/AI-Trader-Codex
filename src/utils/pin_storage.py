"""Secure PIN storage utilities for Fyers authentication.

Provides encrypted storage and retrieval of user's trading PIN for
automatic token refresh functionality.
"""

from pathlib import Path
from typing import Optional

from src.config.settings import get_settings
from src.utils.crypto import encrypt_pin, decrypt_pin
from src.utils.logger import get_logger

logger = get_logger(__name__)

_LEGACY_PIN_FILE = Path(".fyers_pin")


def _pin_file_path() -> Path:
    path = get_settings().pin_file_path
    if path != _LEGACY_PIN_FILE and not path.exists() and _LEGACY_PIN_FILE.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_LEGACY_PIN_FILE.read_text(), encoding="utf-8")
        path.chmod(0o600)
        _LEGACY_PIN_FILE.unlink()
        logger.info(
            "pin_file_migrated",
            from_path=str(_LEGACY_PIN_FILE),
            to_path=str(path),
        )
    return path


def save_pin(pin: str) -> bool:
    """Save encrypted PIN to disk.
    
    Args:
        pin: User's FYERS PIN
        
    Returns:
        True if saved successfully
    """
    try:
        if not pin or not pin.isdigit() or not 4 <= len(pin) <= 6:
            logger.error("invalid_pin_format", length=len(pin) if pin else 0)
            return False
        
        encrypted = encrypt_pin(pin)
        pin_file = _pin_file_path()
        pin_file.parent.mkdir(parents=True, exist_ok=True)
        pin_file.write_text(encrypted, encoding="utf-8")
        pin_file.chmod(0o600)  # Owner read/write only
        
        logger.info("pin_saved_securely", path=str(pin_file))
        return True
        
    except Exception as exc:
        logger.error("pin_save_failed", error=str(exc))
        return False


def load_pin() -> Optional[str]:
    """Load and decrypt saved PIN.
    
    Returns:
        Decrypted PIN or None if not found or decryption fails
    """
    pin_file = _pin_file_path()
    if not pin_file.exists():
        logger.debug("pin_file_not_found", path=str(pin_file))
        return None
    
    try:
        encrypted = pin_file.read_text(encoding="utf-8")
        pin = decrypt_pin(encrypted)
        logger.debug("pin_loaded_successfully")
        return pin
        
    except Exception as exc:
        logger.error("pin_load_failed", error=str(exc))
        return None


def delete_pin() -> bool:
    """Delete saved PIN from disk.
    
    Returns:
        True if deleted successfully or file doesn't exist
    """
    try:
        pin_file = _pin_file_path()
        if pin_file.exists():
            pin_file.unlink()
            logger.info("pin_deleted", path=str(pin_file))
        if _LEGACY_PIN_FILE != pin_file and _LEGACY_PIN_FILE.exists():
            _LEGACY_PIN_FILE.unlink()
            logger.info("legacy_pin_deleted", path=str(_LEGACY_PIN_FILE))
        return True
        
    except Exception as exc:
        logger.error("pin_delete_failed", error=str(exc))
        return False


def has_saved_pin() -> bool:
    """Check if a PIN is currently saved.
    
    Returns:
        True if PIN file exists and is readable
    """
    pin_file = _pin_file_path()
    return pin_file.exists()

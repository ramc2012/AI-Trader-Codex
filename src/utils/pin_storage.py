"""Secure PIN storage utilities for Fyers authentication.

Provides encrypted storage and retrieval of user's trading PIN for
automatic token refresh functionality.
"""

from pathlib import Path
from typing import Optional

from src.utils.crypto import encrypt_pin, decrypt_pin
from src.utils.logger import get_logger

logger = get_logger(__name__)

# PIN file location (gitignored)
_PIN_FILE = Path(".fyers_pin")


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
        _PIN_FILE.write_text(encrypted)
        _PIN_FILE.chmod(0o600)  # Owner read/write only
        
        logger.info("pin_saved_securely", path=str(_PIN_FILE))
        return True
        
    except Exception as exc:
        logger.error("pin_save_failed", error=str(exc))
        return False


def load_pin() -> Optional[str]:
    """Load and decrypt saved PIN.
    
    Returns:
        Decrypted PIN or None if not found or decryption fails
    """
    if not _PIN_FILE.exists():
        logger.debug("pin_file_not_found", path=str(_PIN_FILE))
        return None
    
    try:
        encrypted = _PIN_FILE.read_text()
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
        if _PIN_FILE.exists():
            _PIN_FILE.unlink()
            logger.info("pin_deleted", path=str(_PIN_FILE))
        return True
        
    except Exception as exc:
        logger.error("pin_delete_failed", error=str(exc))
        return False


def has_saved_pin() -> bool:
    """Check if a PIN is currently saved.
    
    Returns:
        True if PIN file exists and is readable
    """
    return _PIN_FILE.exists()

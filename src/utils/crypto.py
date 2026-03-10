"""Cryptographic utilities for secure data storage.

Provides encryption/decryption for sensitive data like PINs using Fernet
symmetric encryption with a machine-specific key.
"""

import hashlib
from pathlib import Path

from cryptography.fernet import Fernet

from src.config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_LEGACY_KEY_FILE = Path(".crypto_key")


def _key_file_path() -> Path:
    path = get_settings().crypto_key_path
    if path != _LEGACY_KEY_FILE and not path.exists() and _LEGACY_KEY_FILE.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_LEGACY_KEY_FILE.read_bytes())
        path.chmod(0o600)
        _LEGACY_KEY_FILE.unlink()
        logger.info(
            "crypto_key_migrated",
            from_path=str(_LEGACY_KEY_FILE),
            to_path=str(path),
        )
    return path


def _get_or_create_key() -> bytes:
    """Get existing encryption key or create a new one.
    
    The key is stored in .crypto_key file and is unique per installation.
    This provides machine-specific encryption.
    
    Returns:
        Encryption key bytes
    """
    key_file = _key_file_path()
    if key_file.exists():
        try:
            key = key_file.read_bytes()
            # Validate it's a proper Fernet key
            Fernet(key)
            return key
        except Exception as exc:
            logger.warning("invalid_key_file_regenerating", error=str(exc))
    
    # Generate new key
    key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    key_file.chmod(0o600)  # Owner read/write only
    logger.info("new_encryption_key_generated", path=str(key_file))
    return key


def encrypt_pin(pin: str) -> str:
    """Encrypt a PIN for secure storage.
    
    Args:
        pin: Plain text FYERS PIN
        
    Returns:
        Encrypted PIN as base64 string
    """
    try:
        key = _get_or_create_key()
        f = Fernet(key)
        encrypted = f.encrypt(pin.encode())
        logger.debug("pin_encrypted", length=len(pin))
        return encrypted.decode()
    except Exception as exc:
        logger.error("pin_encryption_failed", error=str(exc))
        raise


def decrypt_pin(encrypted_pin: str) -> str:
    """Decrypt a stored PIN.
    
    Args:
        encrypted_pin: Encrypted PIN as base64 string
        
    Returns:
        Decrypted PIN as plain text
        
    Raises:
        Exception: If decryption fails (wrong key, corrupted data, etc.)
    """
    try:
        key = _get_or_create_key()
        f = Fernet(key)
        decrypted = f.decrypt(encrypted_pin.encode())
        logger.debug("pin_decrypted")
        return decrypted.decode()
    except Exception as exc:
        logger.error("pin_decryption_failed", error=str(exc))
        raise


def hash_pin(pin: str) -> str:
    """Create a SHA-256 hash of a PIN for validation.
    
    This is one-way - you can verify a PIN matches but can't recover it.
    
    Args:
        pin: Plain text PIN
        
    Returns:
        Hexadecimal SHA-256 hash
    """
    return hashlib.sha256(pin.encode()).hexdigest()


def verify_pin_hash(pin: str, pin_hash: str) -> bool:
    """Verify a PIN matches a stored hash.
    
    Args:
        pin: Plain text PIN to verify
        pin_hash: Stored PIN hash
        
    Returns:
        True if PIN matches hash
    """
    return hash_pin(pin) == pin_hash


def generate_app_id_hash(app_id: str, secret_key: str) -> str:
    """Generate SHA-256 hash of app_id + secret_key for Fyers API.
    
    This is required for Fyers refresh token API.
    
    Args:
        app_id: Fyers app ID
        secret_key: Fyers secret key
        
    Returns:
        Hexadecimal SHA-256 hash of concatenated app_id and secret_key
    """
    combined = f"{app_id}{secret_key}"
    return hashlib.sha256(combined.encode()).hexdigest()

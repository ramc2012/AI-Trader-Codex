# FyersClient Refresh Token Integration - Implementation Guide

## Changes Required to `src/integrations/fyers_client.py`

###  1. Add imports at top of file (after existing imports):

```python
from datetime import datetime, timedelta
import requests
from dateutil import parser
```

### 2. Update `__init__` method - add these instance variables after line 74:

```python
self._refresh_token: str | None = None
self._access_token_expires_at: str | None = None  
self._refresh_token_expires_at: str | None = None
```

### 3. Update `authenticate()` method - add after line 144 (after self._save_token()):

```python
# Store refresh token if provided by Fyers
if "refresh_token" in response:
    self._refresh_token = response["refresh_token"]
    logger.info("refresh_token_captured")
```

### 4. Replace existing `_save_token()` method (lines 172-181) with:

```python
def _save_token(self) -> None:
    """Save the current access token and refresh token to disk."""
    if not self._access_token:
        return
    
    data = {
        "access_token": self._access_token,
        "saved_at": datetime.now().isoformat(),
    }
    
    # Add refresh token if available
    if self._refresh_token:
        data["refresh_token"] = self._refresh_token
        # Access tokens expire in 24 hours
        data["access_token_expires_at"] = (
            datetime.now() + timedelta(hours=24)
        ).isoformat()
        # Refresh tokens expire in 15 days
        data["refresh_token_expires_at"] = (
            datetime.now() + timedelta(days=15)
        ).isoformat()
    
    self._token_path.write_text(json.dumps(data, indent=2))
    logger.debug("token_saved", path=str(self._token_path), has_refresh=bool(self._refresh_token))
```

### 5. Replace existing `_load_token()` method (lines 183-196) with:

```python
def _load_token(self) -> None:
    """Load a previously saved token from disk."""
    if not self._token_path.exists():
        return
    try:
        data = json.loads(self._token_path.read_text())
        token = data.get("access_token")
        if token:
            self._access_token = token
            self._refresh_token = data.get("refresh_token")
            self._access_token_expires_at = data.get("access_token_expires_at")
            self._refresh_token_expires_at = data.get("refresh_token_expires_at")
            self._init_fyers_model()
            logger.info("token_loaded_from_disk", 
                       path=str(self._token_path),
                       has_refresh=bool(self._refresh_token))
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("token_load_failed", error=str(exc))
```

### 6. Add new methods at the end of the class (before closing class definition):

[INSERT CONTENT FROM /tmp/fyers_refresh_additions.py HERE]

---

## Testing the Changes

After making these changes, test with:

```python
from src.integrations.fyers_client import FyersClient

# Initialize client
client = FyersClient()

# Check token status
status = client.get_token_status()
print(status)

# If access token expired but refresh token valid:
if status["access_token_expired"] and status["refresh_token_valid"]:
    client.refresh_access_token(pin="123456")  # Use actual PIN
```

---

## Sources

Implementation based on:
- [Fyers API v3 PyPI Documentation](https://pypi.org/project/fyers-apiv3/)
- [Fyers Refresh Token Issues Thread](https://fyers.in/community/questions-5gz5j8db/post/facing-issues-when-trying-to-refresh-token-to-get-new-token-piN3DMw3k3cwnXy)
- [GitHub - Automated Token Generation](https://github.com/tkanhe/fyers-api-access-token-v3)


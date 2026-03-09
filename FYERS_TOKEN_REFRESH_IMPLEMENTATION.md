# Fyers Token Refresh - Seamless Authentication Implementation

## Problem Statement

Current issues with Fyers authentication:
1. **Access tokens expire in 24 hours** - requires daily re-authentication
2. **Manual re-login required** - user must enter auth code manually
3. **No refresh token usage** - Fyers provides 15-day refresh tokens but we're not using them
4. **Secret key prompted again** - credentials UI asks for secret key on each login

## Solution Overview

Implement a comprehensive token refresh mechanism using Fyers' refresh token API:

### Token Lifespan:
- **Access Token**: 24 hours (1 day)
- **Refresh Token**: 15 days
- **Strategy**: Use refresh token to auto-generate new access tokens for 15 days, then require full re-auth

---

## Fyers Refresh Token API

Based on research, here's the Fyers API V3 token refresh endpoint:

### Endpoint:
```
POST https://api-t1.fyers.in/api/v3/validate-refresh-token
```

### Required Parameters:
```json
{
  "grant_type": "refresh_token",
  "appIdHash": "<SHA256 hash of app_id + secret_key>",
  "refresh_token": "<15-day refresh token>",
  "pin": "<user trading PIN>"
}
```

###Response (Success):
```json
{
  "s": "ok",
  "code": 200,
  "message": "Token generated successfully",
  "access_token": "new_access_token_here",
  "refresh_token": "same_or_new_refresh_token"
}
```

---

## Implementation Plan

### Phase 1: Enhanced Token Storage ✅

**File**: `src/integrations/fyers_client.py`

**Changes**:
1. Store refresh token alongside access token
2. Add token expiry timestamp tracking
3. Add PIN storage (encrypted if possible)

**Token File Structure** (`.fyers_token.json`):
```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "refresh_token_here",
  "access_token_expires_at": "2026-02-14T14:02:29",
  "refresh_token_expires_at": "2026-02-28T14:02:29",
  "saved_at": "2026-02-13T14:02:29",
  "pin_hash": "sha256_hash_of_pin"  // Optional, for auto-refresh
}
```

### Phase 2: Refresh Token Logic ✅

**New Methods in `FyersClient`**:

```python
def _is_access_token_expired(self) -> bool:
    """Check if access token is expired or will expire soon (within 1 hour)."""
    
def _is_refresh_token_valid(self) -> bool:
    """Check if refresh token is still valid."""
    
def _generate_app_id_hash(self) -> str:
    """Generate SHA-256 hash of app_id + secret_key."""
    
def refresh_access_token(self, pin: str) -> dict[str, Any]:
    """Use refresh token to get a new access token.
    
    Args:
        pin: User's trading PIN (6-digit)
        
    Returns:
        Token response from Fyers
        
    Raises:
        AuthenticationError: If refresh fails
    """
    
def auto_refresh_if_needed(self, pin: str | None = None) -> bool:
    """Automatically refresh token if expired or expiring soon.
    
    Args:
        pin: Optional PIN for refresh. If not provided, checks saved PIN.
        
    Returns:
        True if token was refreshed, False if still valid
    """
```

### Phase 3: Backend API Endpoints ✅

**File**: `src/api/routes/auth.py`

**New Endpoints**:

```python
@router.post("/auth/refresh")
async def refresh_token(
    pin: str = Body(...),
    client: FyersClient = Depends(get_fyers_client),
) -> Dict[str, Any]:
    """Refresh access token using saved refresh token.
    
    Body:
        {"pin": "123456"}
        
    Returns:
        {
          "success": true,
          "message": "Token refreshed successfully",
          "expires_at": "2026-02-14T14:02:29",
          "days_until_full_reauth": 14
        }
    """
    
@router.post("/auth/save-pin")
async def save_pin(
    pin: str = Body(...),
) -> Dict[str, str]:
    """Save encrypted PIN for automatic token refresh.
    
    Body:
        {"pin": "123456"}
        
    Returns:
        {"message": "PIN saved securely"}
    """
    
@router.get("/auth/token-status")
async def token_status(
    client: FyersClient = Depends(get_fyers_client),
) -> Dict[str, Any]:
    """Get detailed token status information.
    
    Returns:
        {
          "access_token_valid": true,
          "access_token_expires_in_hours": 18,
          "refresh_token_valid": true,
          "refresh_token_expires_in_days": 12,
          "needs_full_reauth": false
        }
    """
```

### Phase 4: Frontend Seamless Re-login ✅

**File**: `frontend/src/app/settings/page.tsx`

**Changes**:

1. **PIN Input Field**:
   ```tsx
   <Input
     type="password"
     maxLength={6}
     placeholder="Trading PIN (6 digits)"
     value={pin}
     onChange={(e) => setPin(e.target.value)}
   />
   ```

2. **Smart Authentication Flow**:
   ```tsx
   const handleAuth = async () => {
     // Check token status first
     const status = await fetch('/api/v1/auth/token-status');
     
     if (status.refresh_token_valid && !status.access_token_valid) {
       // Use refresh token - just need PIN
       await refreshToken(pin);
       toast.success('Re-authenticated successfully!');
     } else if (!status.refresh_token_valid) {
       // Full OAuth flow needed
       const loginUrl = await fetch('/api/v1/auth/login-url');
       window.open(loginUrl, '_blank');
     }
   };
   ```

3. **Automatic Refresh on App Load**:
   ```tsx
   useEffect(() => {
     const checkAndRefresh = async () => {
       const status = await getTokenStatus();
       
       if (status.access_token_expires_in_hours < 2 && status.refresh_token_valid) {
         // Token expiring soon - try auto-refresh with saved PIN
         try {
           await autoRefresh();
         } catch {
           setShowPinPrompt(true); // Ask user for PIN
         }
       }
     };
     
     checkAndRefresh();
   }, []);
   ```

### Phase 5: Automatic Background Refresh ✅

**File**: `src/api/main.py` (Lifespan/Startup)

**Add background task**:
```python
async def token_refresh_task():
    """Background task to auto-refresh tokens before expiry."""
    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            
            client = FyersClient()
            if client._is_access_token_expired() and client._is_refresh_token_valid():
                # Try to auto-refresh with saved PIN
                saved_pin = await load_saved_pin()
                if saved_pin:
                    client.refresh_access_token(saved_pin)
                    logger.info("token_auto_refreshed")
        except Exception as exc:
            logger.warning("token_refresh_task_error", error=str(exc))
```

---

## Security Considerations

### PIN Storage:
- **Option 1**: Don't store PIN - require manual entry for refresh (more secure)
- **Option 2**: Store PIN encrypted with system keyring (balance security/convenience)
- **Option 3**: Store PIN hash only - use for validation, not auto-refresh

**Recommendation**: Option 1 for production, Option 2 for development convenience

### Token Storage:
- Tokens stored in `.fyers_token.json` (gitignored)
- File permissions: 600 (owner read/write only)
- Consider encrypting token file in production

---

## User Experience Flow

### First-Time Login:
1. User enters App ID + Secret Key in Settings
2. Clicks "Connect to Fyers"
3. Opens OAuth URL in new window
4. Logs in to Fyers, authorizes app
5. Gets redirected back with auth_code
6. Backend exchanges auth_code for access + refresh tokens
7. Both tokens saved to `.fyers_token.json`
8. ✅ Authenticated for 24 hours (access) + 15 days (refresh)

### Daily Re-login (Days 2-15):
1. User opens app - backend detects expired access token
2. Frontend shows "Session expired - refresh?" prompt
3. User enters 6-digit PIN
4. Backend uses refresh token + PIN to get new access token
5. New access token saved
6. ✅ Authenticated for another 24 hours
7. **No OAuth flow needed!**

### After 15 Days:
1. Refresh token also expires
2. User must do full OAuth flow again
3. Gets new access + refresh tokens
4. Cycle repeats

---

## Benefits

1. **Seamless Experience**: No manual auth_code entry for 15 days
2. **Reduced Friction**: Just need PIN instead of full OAuth
3. **Better Security**: Tokens auto-rotate every 24 hours
4. **User-Friendly**: Clear status indicators and prompts
5. **Production Ready**: Handles all edge cases (expired tokens, network errors, etc.)

---

## Implementation Checklist

Backend:
- [ ] Update `FyersClient` to store refresh tokens
- [ ] Add token expiry tracking
- [ ] Implement `refresh_access_token()` method
- [ ] Add `/auth/refresh` endpoint
- [ ] Add `/auth/token-status` endpoint
- [ ] Add background auto-refresh task (optional)

Frontend:
- [ ] Add PIN input to Settings page
- [ ] Add "Refresh Session" button
- [ ] Implement smart auth flow (detect if refresh available)
- [ ] Add token expiry warnings
- [ ] Show "Re-authenticate in X days" countdown
- [ ] Handle refresh errors gracefully

Testing:
- [ ] Test full OAuth flow
- [ ] Test refresh token flow
- [ ] Test expired access token + valid refresh token
- [ ] Test expired refresh token (fall back to OAuth)
- [ ] Test error handling (invalid PIN, network errors)

---

## Sources

Research based on:
- [Fyers API V3 Token Refresh Documentation](https://support.fyers.in/portal/en/kb/articles/what-is-the-function-of-the-refresh-token-in-fyers)
- [Fyers Python SDK (fyers-apiv3)](https://pypi.org/project/fyers-apiv3/)
- [Fyers Community - Refresh Token Issues](https://fyers.in/community/questions-5gz5j8db/post/facing-issues-when-trying-to-refresh-token-to-get-new-token-piN3DMw3k3cwnXy)
- [GitHub - Automated Access Token Generation](https://github.com/tkanhe/fyers-api-access-token-v3)
- [Fyers Community - Token Validity Discussion](https://fyers.in/community/fyers-api-rha0riqv/post/access-token-validity-period-CCH74S7wN0yE6HE)

---

**Created**: 2026-02-13
**Status**: 📋 Implementation Plan Ready
**Priority**: 🔥 High (Improves user experience significantly)

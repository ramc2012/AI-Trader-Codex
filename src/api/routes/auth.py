"""Fyers authentication API endpoints.

Provides OAuth login flow, status checking, and logout for the Fyers
broker integration.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import (
    get_fyers_client,
    get_runtime_manager,
    get_telegram_notifier,
    reset_telegram_notifier,
    reset_fyers_client,
)
from src.api.schemas import (
    AuthLoginUrlResponse,
    AuthStatusResponse,
    FyersCredentialsRequest,
    FyersCredentialsResponse,
    MarketDataProvidersRequest,
    MarketDataProvidersResponse,
    TelegramConfigRequest,
    TelegramConfigResponse,
    ManualAuthCodeRequest,
    ManualAuthResponse,
    SavePinRequest,
    SavePinResponse,
    TokenRefreshRequest,
    TokenRefreshResponse,
    TokenStatusResponse,
    ValidateCredentialsResponse,
)
from src.config.settings import get_settings
from src.integrations.fyers_client import FyersClient
from src.utils.env_manager import EnvManager
from src.utils.exceptions import AuthenticationError
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Auth"])


def _get_env_manager() -> EnvManager:
    """Return an EnvManager pointing at the persistent credentials file.

    Called per-request (not once at module load) so it always uses the
    current DATA_DIR setting even after get_settings.cache_clear().
    """
    return EnvManager(env_path=get_settings().credentials_env_path)


def _build_telegram_config_response() -> TelegramConfigResponse:
    """Build Telegram config status with runtime notifier state."""
    settings = get_settings()
    notifier = get_telegram_notifier()
    bot = str(settings.telegram_bot_token or "").strip()
    chat = str(settings.telegram_chat_id or "").strip()
    interval = settings.telegram_status_interval_minutes
    return TelegramConfigResponse(
        configured=bool(bot and chat),
        enabled=bool(settings.telegram_enabled),
        bot_configured=bool(bot),
        chat_configured=bool(chat),
        active=bool(bot and chat and settings.telegram_enabled and notifier.is_running),
        status_interval_minutes=max(int(interval if interval is not None else 30), 0),
        last_error=notifier.last_error,
    )


@router.get("/auth/status", response_model=AuthStatusResponse)
async def auth_status(
    client: FyersClient = Depends(get_fyers_client),
) -> AuthStatusResponse:
    """Check current Fyers authentication status."""
    settings = get_settings()
    app_configured = bool(settings.fyers_app_id and settings.fyers_secret_key)

    if not app_configured:
        return AuthStatusResponse(
            authenticated=False,
            profile=None,
            app_configured=False,
        )

    try:
        refreshed = await asyncio.to_thread(client.try_auto_refresh_with_saved_pin, False)
        profile = None
        authenticated = False
        try:
            profile_resp = await asyncio.to_thread(client.get_profile)
            authenticated = profile_resp.get("s") == "ok"
            if authenticated:
                profile = profile_resp
        except Exception:
            authenticated = False

        if authenticated:
            if refreshed:
                asyncio.create_task(get_runtime_manager().restart_if_authenticated())
        return AuthStatusResponse(
            authenticated=authenticated,
            profile=profile,
            app_configured=True,
        )
    except Exception as exc:
        logger.warning("auth_status_check_failed", error=str(exc))
        return AuthStatusResponse(
            authenticated=False,
            profile=None,
            app_configured=True,
        )


@router.get("/auth/login-url", response_model=AuthLoginUrlResponse)
async def get_login_url(
    client: FyersClient = Depends(get_fyers_client),
) -> AuthLoginUrlResponse:
    """Generate Fyers OAuth authorization URL."""
    settings = get_settings()
    if not settings.fyers_app_id or not settings.fyers_secret_key:
        raise HTTPException(
            status_code=503,
            detail="Fyers API credentials not configured. Set FYERS_APP_ID and FYERS_SECRET_KEY in .env",
        )

    try:
        url = await asyncio.to_thread(client.generate_auth_url)
        return AuthLoginUrlResponse(url=url)
    except AuthenticationError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/auth/auto-refresh")
async def auto_refresh_token(
    client: FyersClient = Depends(get_fyers_client),
) -> Dict[str, Any]:
    """Attempt automatic token refresh using saved PIN.

    Called on app load when access token is expired but refresh token
    and saved PIN are available. Requires no user input.
    """
    try:
        from src.utils.pin_storage import has_saved_pin

        status_before = client.get_token_status()

        if status_before.get("access_token_valid"):
            asyncio.create_task(get_runtime_manager().restart_if_authenticated())
            return {"success": True, "message": "Token still valid", "refreshed": False}

        if not status_before.get("refresh_token_valid"):
            return {
                "success": False,
                "message": "Refresh token expired",
                "refreshed": False,
                "needs_full_reauth": True,
            }

        if not has_saved_pin():
            return {"success": False, "message": "No saved PIN", "refreshed": False}

        refreshed = await asyncio.to_thread(client.try_auto_refresh_with_saved_pin, True)
        if refreshed:
            asyncio.create_task(get_runtime_manager().restart_if_authenticated())
            logger.info("auto_refresh_successful")
            return {"success": True, "message": "Token refreshed automatically", "refreshed": True}

        status_after = client.get_token_status()
        if status_after.get("access_token_valid"):
            asyncio.create_task(get_runtime_manager().restart_if_authenticated())
            return {"success": True, "message": "Token is valid", "refreshed": False}

        return {"success": False, "message": "Automatic refresh failed", "refreshed": False}

    except AuthenticationError as exc:
        logger.error("auto_refresh_failed", error=str(exc))
        return {"success": False, "message": str(exc), "refreshed": False}
    except Exception as exc:
        logger.error("auto_refresh_error", error=str(exc))
        return {"success": False, "message": f"Unexpected error: {str(exc)}", "refreshed": False}


@router.post("/auth/logout")
async def logout(
    client: FyersClient = Depends(get_fyers_client),
) -> Dict[str, str]:
    """Logout from Fyers and clear stored token."""
    try:
        await get_runtime_manager().stop()
    except Exception:
        pass

    try:
        await asyncio.to_thread(client.close)
    except Exception:
        pass  # Best effort cleanup

    # Remove token file from persistent data directory
    token_path = get_settings().token_file_path
    if token_path.exists():
        token_path.unlink()
        logger.info("token_file_removed")

    return {"message": "Logged out successfully"}


@router.get("/auth/credentials", response_model=FyersCredentialsResponse)
async def get_credentials() -> FyersCredentialsResponse:
    """Get current Fyers API credentials (without exposing secret key)."""
    settings = get_settings()

    return FyersCredentialsResponse(
        app_id=settings.fyers_app_id if settings.fyers_app_id else "",
        redirect_uri=settings.fyers_redirect_uri,
        configured=bool(settings.fyers_app_id and settings.fyers_secret_key),
    )


@router.post("/auth/credentials", response_model=FyersCredentialsResponse)
async def save_credentials(
    credentials: FyersCredentialsRequest,
) -> FyersCredentialsResponse:
    """Save Fyers API credentials to .env file.

    This updates the .env file and reloads settings. A backup is created
    automatically before updating.
    """
    try:
        # Validate inputs
        if not credentials.app_id or not credentials.secret_key:
            raise HTTPException(
                status_code=400,
                detail="Both app_id and secret_key are required",
            )

        # Update .env file
        updates = {
            "FYERS_APP_ID": credentials.app_id,
            "FYERS_SECRET_KEY": credentials.secret_key,
            "FYERS_REDIRECT_URI": credentials.redirect_uri,
        }

        success = _get_env_manager().update_env(updates, create_backup=True)

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to update credentials. Check server logs.",
            )

        # Clear settings cache and reset FyersClient to pick up new credentials
        get_settings.cache_clear()
        reset_fyers_client()

        logger.info(
            "fyers_credentials_saved",
            app_id=credentials.app_id,
            redirect_uri=credentials.redirect_uri,
        )

        return FyersCredentialsResponse(
            app_id=credentials.app_id,
            redirect_uri=credentials.redirect_uri,
            configured=True,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("save_credentials_failed", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save credentials: {str(exc)}",
        )


@router.get("/auth/market-data-providers", response_model=MarketDataProvidersResponse)
async def get_market_data_providers() -> MarketDataProvidersResponse:
    """Return availability state for external US market-data providers."""
    settings = get_settings()
    return MarketDataProvidersResponse(
        finnhub_configured=bool(str(settings.finnhub_api_key or "").strip()),
        alphavantage_configured=bool(str(settings.alphavantage_api_key or "").strip()),
    )


@router.post("/auth/market-data-providers", response_model=MarketDataProvidersResponse)
async def save_market_data_providers(
    body: MarketDataProvidersRequest,
) -> MarketDataProvidersResponse:
    """Persist market-data provider keys to the credentials env file."""
    updates = {
        "FINNHUB_API_KEY": str(body.finnhub_api_key or "").strip(),
        "ALPHAVANTAGE_API_KEY": str(body.alphavantage_api_key or "").strip(),
    }
    success = _get_env_manager().update_env(updates, create_backup=True)
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to update market-data provider keys. Check server logs.",
        )
    get_settings.cache_clear()
    settings = get_settings()
    return MarketDataProvidersResponse(
        finnhub_configured=bool(str(settings.finnhub_api_key or "").strip()),
        alphavantage_configured=bool(str(settings.alphavantage_api_key or "").strip()),
    )


@router.get("/auth/telegram", response_model=TelegramConfigResponse)
async def get_telegram_config() -> TelegramConfigResponse:
    """Return Telegram integration configuration status."""
    return _build_telegram_config_response()


@router.post("/auth/telegram", response_model=TelegramConfigResponse)
async def save_telegram_config(body: TelegramConfigRequest) -> TelegramConfigResponse:
    """Persist Telegram credentials and hot-reload notifier state."""
    current_settings = get_settings()
    provided_fields = set(body.model_fields_set)
    existing_bot = str(current_settings.telegram_bot_token or "").strip()
    existing_chat = str(current_settings.telegram_chat_id or "").strip()
    existing_enabled = bool(current_settings.telegram_enabled)
    current_interval = current_settings.telegram_status_interval_minutes
    existing_interval = int(current_interval if current_interval is not None else 30)
    next_enabled = (
        existing_enabled
        if "enabled" not in provided_fields or body.enabled is None
        else bool(body.enabled)
    )
    next_bot = (
        existing_bot
        if "bot_token" not in provided_fields
        else str(body.bot_token or "").strip()
    )
    next_chat = (
        existing_chat
        if "chat_id" not in provided_fields
        else str(body.chat_id or "").strip()
    )
    next_interval = (
        existing_interval
        if "status_interval_minutes" not in provided_fields or body.status_interval_minutes is None
        else max(int(body.status_interval_minutes), 0)
    )

    updates = {
        "TELEGRAM_ENABLED": "true" if next_enabled else "false",
        "TELEGRAM_BOT_TOKEN": next_bot,
        "TELEGRAM_CHAT_ID": next_chat,
        "TELEGRAM_STATUS_INTERVAL_MINUTES": str(next_interval),
    }
    success = _get_env_manager().update_env(updates, create_backup=True)
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to update Telegram settings. Check server logs.",
        )

    # Hot-reload notifier so user doesn't need to restart backend manually.
    try:
        current_notifier = get_telegram_notifier()
        await current_notifier.stop()
    except Exception:
        pass

    get_settings.cache_clear()
    reset_telegram_notifier()

    # Start notifier immediately so lifecycle and future agent events are delivered
    # without requiring a backend restart or active agent loop at this moment.
    try:
        notifier = get_telegram_notifier()
        if notifier.can_send:
            await notifier.start()
    except Exception:
        pass

    return _build_telegram_config_response()


@router.post("/auth/validate", response_model=ValidateCredentialsResponse)
async def validate_credentials(
    credentials: FyersCredentialsRequest,
) -> ValidateCredentialsResponse:
    """Validate Fyers API credentials and generate login URL.

    This endpoint validates the credentials without saving them and returns
    a login URL if they are valid.
    """
    try:
        # Create temporary SessionModel with provided credentials
        from fyers_apiv3.fyersModel import SessionModel

        session = SessionModel(
            client_id=credentials.app_id,
            redirect_uri=credentials.redirect_uri,
            response_type="code",
            secret_key=credentials.secret_key,
            grant_type="authorization_code",
        )

        # Generate auth URL - this will fail if credentials are invalid
        response = session.generate_authcode()

        if not response or not isinstance(response, str):
            return ValidateCredentialsResponse(
                valid=False,
                message="Invalid credentials: Unable to generate authorization URL",
            )

        logger.info("credentials_validated", app_id=credentials.app_id)

        return ValidateCredentialsResponse(
            valid=True,
            message="Credentials are valid",
            login_url=response,
        )

    except Exception as exc:
        logger.warning("credential_validation_failed", error=str(exc))
        return ValidateCredentialsResponse(
            valid=False,
            message=f"Invalid credentials: {str(exc)}",
        )


@router.post("/auth/save-and-login")
async def save_and_login(
    credentials: FyersCredentialsRequest,
) -> Dict[str, Any]:
    """Save credentials and initiate automated login flow.

    This is a convenience endpoint that:
    1. Saves credentials to .env
    2. Validates them
    3. Returns login URL for OAuth flow
    """
    try:
        # Save credentials first
        await save_credentials(credentials)

        # Validate and get login URL
        validation = await validate_credentials(credentials)

        if not validation.valid:
            raise HTTPException(
                status_code=400,
                detail=validation.message,
            )

        logger.info("save_and_login_success", app_id=credentials.app_id)

        return {
            "success": True,
            "message": "Credentials saved successfully",
            "login_url": validation.login_url,
            "next_step": "Open the login_url in a browser to complete authentication",
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("save_and_login_failed", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save and login: {str(exc)}",
        )


@router.post("/auth/manual-code", response_model=ManualAuthResponse)
async def submit_manual_auth_code(
    request: ManualAuthCodeRequest,
    client: FyersClient = Depends(get_fyers_client),
) -> ManualAuthResponse:
    """Submit authorization code manually for authentication.

    Use this when the automatic redirect doesn't work. After opening the
    Fyers login URL, copy the authorization code from the redirect URL
    and submit it here.
    """
    try:
        # Clean the auth code - trim whitespace, newlines, etc.
        auth_code = request.auth_code.strip()

        # Basic validation
        if not auth_code:
            return ManualAuthResponse(
                success=False,
                message="Authorization code cannot be empty",
                authenticated=False,
            )

        # If user pasted a full URL instead of just the token, extract the token
        if "auth_code=" in auth_code or "https://" in auth_code or "http://" in auth_code:
            logger.info("extracting_token_from_url", original_length=len(auth_code))
            try:
                from urllib.parse import urlparse, parse_qs
                # Parse URL if it looks like a URL
                if "://" in auth_code:
                    parsed = urlparse(auth_code)
                    params = parse_qs(parsed.query)
                    if "auth_code" in params and params["auth_code"]:
                        auth_code = params["auth_code"][0]
                        logger.info("extracted_token_from_url", new_length=len(auth_code))
                # Or extract if it's just the query string
                elif "auth_code=" in auth_code:
                    params = parse_qs(auth_code)
                    if "auth_code" in params and params["auth_code"]:
                        auth_code = params["auth_code"][0]
                        logger.info("extracted_token_from_query", new_length=len(auth_code))
            except Exception as parse_exc:
                logger.warning("token_extraction_failed", error=str(parse_exc))
                # Continue with original auth_code if extraction fails

        # Final trim after potential extraction
        auth_code = auth_code.strip()

        # Log the code length for debugging (not the actual code for security)
        logger.info("manual_auth_attempt", code_length=len(auth_code), starts_with=auth_code[:3] if len(auth_code) > 3 else "")

        # Authenticate using the provided code
        await asyncio.to_thread(client.authenticate, auth_code)

        # Restart background services in a fire-and-forget task so the HTTP
        # response is returned immediately (registry refresh can take 10-30s).
        asyncio.create_task(get_runtime_manager().restart_if_authenticated())

        logger.info("manual_auth_success")

        return ManualAuthResponse(
            success=True,
            message="Authentication successful! You are now connected to Fyers.",
            authenticated=True,
        )

    except AuthenticationError as exc:
        logger.error("manual_auth_failed", error=str(exc), error_type=type(exc).__name__)
        return ManualAuthResponse(
            success=False,
            message=f"Authentication failed: {str(exc)}",
            authenticated=False,
        )
    except Exception as exc:
        logger.error("manual_auth_error", error=str(exc), error_type=type(exc).__name__)
        return ManualAuthResponse(
            success=False,
            message=f"Unexpected error: {str(exc)}",
            authenticated=False,
        )


@router.post("/auth/refresh", response_model=TokenRefreshResponse)
async def refresh_access_token(
    request: TokenRefreshRequest,
    client: FyersClient = Depends(get_fyers_client),
) -> TokenRefreshResponse:
    """Refresh access token using refresh token and PIN.
    
    This endpoint allows users to get a new access token without going through
    the full OAuth flow, using their FYERS PIN.
    
    Args:
        request: Contains the FYERS PIN
        client: FyersClient instance
        
    Returns:
        Token refresh status and expiry information
    """
    try:
        # Validate PIN format
        if not request.pin.isdigit() or not 4 <= len(request.pin) <= 6:
            return TokenRefreshResponse(
                success=False,
                message="PIN must be 4 to 6 digits",
                needs_full_reauth=False,
            )
        
        # Check if refresh token is available
        status = client.get_token_status()
        
        if not status["refresh_token_valid"]:
            return TokenRefreshResponse(
                success=False,
                message="Refresh token expired. Please re-authenticate via OAuth.",
                needs_full_reauth=True,
            )
        
        # Refresh the token
        await asyncio.to_thread(client.refresh_access_token, request.pin)
        asyncio.create_task(get_runtime_manager().restart_if_authenticated())
        
        # Get updated status
        new_status = client.get_token_status()
        
        logger.info("token_refresh_successful_via_api")
        
        return TokenRefreshResponse(
            success=True,
            message="Access token refreshed successfully",
            access_token_expires_at=None,  # Could calculate from status
            refresh_token_expires_in_days=new_status.get("refresh_token_expires_in_days"),
            needs_full_reauth=False,
        )
        
    except AuthenticationError as exc:
        logger.error("token_refresh_failed", error=str(exc))
        return TokenRefreshResponse(
            success=False,
            message=str(exc),
            needs_full_reauth="refresh token" in str(exc).lower(),
        )
    except Exception as exc:
        logger.error("token_refresh_error", error=str(exc))
        return TokenRefreshResponse(
            success=False,
            message=f"Unexpected error: {str(exc)}",
            needs_full_reauth=False,
        )


@router.post("/auth/save-pin", response_model=SavePinResponse)
async def save_user_pin(request: SavePinRequest) -> SavePinResponse:
    """Save encrypted PIN for automatic token refresh.
    
    The PIN is encrypted using Fernet symmetric encryption with a machine-specific
    key before being stored. This allows automatic token refresh without requiring
    manual PIN entry each time.
    
    Args:
        request: Contains PIN and save_pin flag
        
    Returns:
        Success status of PIN save operation
    """
    try:
        from src.utils.pin_storage import save_pin
        
        if not request.save_pin:
            return SavePinResponse(
                success=True,
                message="PIN not saved (user opted out)",
                pin_saved=False,
            )
        
        # Validate PIN
        if not request.pin.isdigit() or not 4 <= len(request.pin) <= 6:
            return SavePinResponse(
                success=False,
                message="Invalid PIN format. Must be 4 to 6 digits.",
                pin_saved=False,
            )
        
        # Save encrypted PIN
        success = save_pin(request.pin)
        
        if success:
            logger.info("user_pin_saved_successfully")
            return SavePinResponse(
                success=True,
                message="PIN saved securely for automatic refresh",
                pin_saved=True,
            )
        else:
            return SavePinResponse(
                success=False,
                message="Failed to save PIN",
                pin_saved=False,
            )
            
    except Exception as exc:
        logger.error("save_pin_error", error=str(exc))
        return SavePinResponse(
            success=False,
            message=f"Error saving PIN: {str(exc)}",
            pin_saved=False,
        )


@router.delete("/auth/pin")
async def delete_saved_pin() -> Dict[str, Any]:
    """Delete saved PIN from secure storage.
    
    This removes the encrypted PIN file, requiring manual PIN entry
    for future token refreshes.
    
    Returns:
        Success message
    """
    try:
        from src.utils.pin_storage import delete_pin
        
        success = delete_pin()
        
        if success:
            logger.info("user_pin_deleted")
            return {"success": True, "message": "PIN deleted successfully"}
        else:
            return {"success": False, "message": "Failed to delete PIN"}
            
    except Exception as exc:
        logger.error("delete_pin_error", error=str(exc))
        return {"success": False, "message": f"Error deleting PIN: {str(exc)}"}


@router.get("/auth/token-status", response_model=TokenStatusResponse)
async def get_token_status(
    client: FyersClient = Depends(get_fyers_client),
) -> TokenStatusResponse:
    """Get detailed token status information.
    
    Returns information about access token and refresh token expiry,
    helping the frontend determine whether to show refresh UI or
    full OAuth login.
    
    Returns:
        Detailed token status including expiry times
    """
    try:
        from src.utils.pin_storage import has_saved_pin
        has_pin = has_saved_pin()

        status = client.get_token_status()
        if (
            has_pin
            and not status.get("access_token_valid", False)
            and status.get("refresh_token_valid", False)
        ):
            refreshed = await asyncio.to_thread(client.try_auto_refresh_with_saved_pin, False)
            if refreshed:
                asyncio.create_task(get_runtime_manager().restart_if_authenticated())
                status = client.get_token_status()

        return TokenStatusResponse(
            access_token_valid=status.get("access_token_valid", False),
            access_token_expires_in_hours=status.get("access_token_expires_in_hours"),
            refresh_token_valid=status.get("refresh_token_valid", False),
            refresh_token_expires_in_days=status.get("refresh_token_expires_in_days"),
            needs_full_reauth=status.get("needs_full_reauth", True),
            has_saved_pin=has_pin,
        )
        
    except Exception as exc:
        logger.error("get_token_status_error", error=str(exc))
        # Return safe defaults on error
        return TokenStatusResponse(
            access_token_valid=False,
            refresh_token_valid=False,
            needs_full_reauth=True,
            has_saved_pin=False,
        )


# ── Broker Selection ──────────────────────────────────────────────────────────

@router.get("/auth/broker")
async def get_active_broker() -> Dict[str, Any]:
    """Return active broker name and status for all supported brokers."""
    settings = get_settings()
    active = str(settings.active_broker).lower().strip()

    brokers = []
    for broker_name in ("fyers", "upstox", "fivepaisa"):
        status: Dict[str, Any] = {
            "name": broker_name,
            "display_name": {"fyers": "Fyers", "upstox": "Upstox", "fivepaisa": "5paisa"}[broker_name],
            "active": broker_name == active,
            "configured": False,
            "authenticated": False,
        }
        try:
            if broker_name == "fyers":
                status["configured"] = bool(settings.fyers_app_id and settings.fyers_secret_key)
                if status["configured"]:
                    client = get_fyers_client()
                    status["authenticated"] = client.is_authenticated
            elif broker_name == "upstox":
                status["configured"] = bool(getattr(settings, "upstox_api_key", ""))
                if status["configured"]:
                    try:
                        from src.integrations.upstox_client import UpstoxClient
                        uc = UpstoxClient()
                        status["authenticated"] = uc.is_authenticated
                    except Exception:
                        pass
            elif broker_name == "fivepaisa":
                status["configured"] = bool(getattr(settings, "fivepaisa_user_key", ""))
                if status["configured"]:
                    try:
                        from src.integrations.fivepaisa_client import FivePaisaClient
                        fc = FivePaisaClient()
                        status["authenticated"] = fc.is_authenticated
                    except Exception:
                        pass
        except Exception:
            pass
        brokers.append(status)

    return {
        "active_broker": active,
        "brokers": brokers,
    }


@router.post("/auth/broker")
async def switch_broker(body: Dict[str, Any]) -> Dict[str, Any]:
    """Switch the active broker. Requires restart for full effect."""
    broker_name = str(body.get("broker", "")).lower().strip()

    if broker_name not in ("fyers", "upstox", "fivepaisa"):
        raise HTTPException(status_code=400, detail=f"Unknown broker: {broker_name}")

    updates = {"ACTIVE_BROKER": broker_name}
    success = _get_env_manager().update_env(updates, create_backup=True)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update broker setting.")

    get_settings.cache_clear()
    logger.info("broker_switched", broker=broker_name)

    return {
        "success": True,
        "active_broker": broker_name,
        "message": f"Active broker set to {broker_name}. Restart agent for full effect.",
    }


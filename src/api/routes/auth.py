"""Fyers authentication API endpoints.

Provides OAuth login flow, status checking, and logout for the Fyers
broker integration.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from src.api.dependencies import get_fyers_client
from src.api.schemas import (
    AuthLoginUrlResponse,
    AuthStatusResponse,
    FyersCredentialsRequest,
    FyersCredentialsResponse,
    ManualAuthCodeRequest,
    ManualAuthResponse,
    ValidateCredentialsResponse,
)
from src.config.settings import get_settings
from src.integrations.fyers_client import FyersClient
from src.utils.env_manager import EnvManager
from src.utils.exceptions import AuthenticationError
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Auth"])
env_manager = EnvManager()


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
        authenticated = await asyncio.to_thread(lambda: client.is_authenticated)
        profile = None
        if authenticated:
            profile = await asyncio.to_thread(client.get_profile)
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


@router.get("/auth/callback")
async def auth_callback(
    auth_code: str = Query(..., description="Authorization code from Fyers OAuth"),
    s: str = Query(default="", description="Status from Fyers redirect"),
    client: FyersClient = Depends(get_fyers_client),
) -> RedirectResponse:
    """Handle Fyers OAuth callback redirect.

    Exchanges the authorization code for an access token and redirects
    the user back to the frontend settings page.
    """
    settings = get_settings()
    frontend_url = settings.fyers_redirect_frontend_url

    try:
        await asyncio.to_thread(client.authenticate, auth_code)
        logger.info("auth_callback_success")
        return RedirectResponse(url=f"{frontend_url}?auth=success")
    except AuthenticationError as exc:
        logger.error("auth_callback_failed", error=str(exc))
        return RedirectResponse(url=f"{frontend_url}?auth=failed&error={str(exc)}")
    except Exception as exc:
        logger.error("auth_callback_error", error=str(exc))
        return RedirectResponse(url=f"{frontend_url}?auth=failed&error=Unexpected+error")


@router.post("/auth/logout")
async def logout(
    client: FyersClient = Depends(get_fyers_client),
) -> Dict[str, str]:
    """Logout from Fyers and clear stored token."""
    try:
        await asyncio.to_thread(client.close)
    except Exception:
        pass  # Best effort cleanup

    # Remove token file
    token_path = Path(".fyers_token.json")
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

        success = env_manager.update_env(updates, create_backup=True)

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to update credentials. Check server logs.",
            )

        # Clear settings cache to reload new values
        get_settings.cache_clear()

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
        # Authenticate using the provided code
        await asyncio.to_thread(client.authenticate, request.auth_code)

        logger.info("manual_auth_success")

        return ManualAuthResponse(
            success=True,
            message="Authentication successful! You are now connected to Fyers.",
            authenticated=True,
        )

    except AuthenticationError as exc:
        logger.error("manual_auth_failed", error=str(exc))
        return ManualAuthResponse(
            success=False,
            message=f"Authentication failed: {str(exc)}",
            authenticated=False,
        )
    except Exception as exc:
        logger.error("manual_auth_error", error=str(exc))
        return ManualAuthResponse(
            success=False,
            message=f"Unexpected error: {str(exc)}",
            authenticated=False,
        )

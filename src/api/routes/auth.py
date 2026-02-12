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
from src.api.schemas import AuthLoginUrlResponse, AuthStatusResponse
from src.config.settings import get_settings
from src.integrations.fyers_client import FyersClient
from src.utils.exceptions import AuthenticationError
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Auth"])


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

"""Login / logout endpoints.

These are the only routes (besides /api/health) mounted without the
require_auth dependency — see main.py.
"""
import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.config import settings
from app.core.auth import (
    auth_state,
    clear_session_cookie,
    require_auth,
    set_session_cookie,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class AuthStatusResponse(BaseModel):
    authenticated: bool
    auth_enabled: bool


@router.post("/login")
def login(payload: LoginRequest, response: Response):
    if not settings.AUTH_ENABLED:
        return {"authenticated": True, "auth_enabled": False}

    if not auth_state().verify_password(payload.password):
        # Deliberately vague: no distinction between "wrong password" and
        # anything else, and no timing signal beyond scrypt's own cost.
        logger.warning("Failed login attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    set_session_cookie(response, auth_state().issue_token())
    return {"authenticated": True, "auth_enabled": True}


@router.post("/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"authenticated": False, "auth_enabled": settings.AUTH_ENABLED}


@router.get("/status", response_model=AuthStatusResponse)
def auth_status(request: Request):
    """Unauthenticated probe so the SPA can decide whether to show /login."""
    if not settings.AUTH_ENABLED:
        return AuthStatusResponse(authenticated=True, auth_enabled=False)
    try:
        require_auth(request)
    except HTTPException:
        return AuthStatusResponse(authenticated=False, auth_enabled=True)
    return AuthStatusResponse(authenticated=True, auth_enabled=True)

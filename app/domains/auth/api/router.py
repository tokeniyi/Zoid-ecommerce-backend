"""Auth HTTP routes.

The router is intentionally thin: it validates transport shapes, delegates to
`AuthService`, and delivers/invalidates the session cookie via `SessionService`.
It never touches password or session internals.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.config import get_settings
from app.domains.auth.api.schemas import (
    LoginRequest,
    MessageResponse,
    SignUpRequest,
    UserResponse,
)
from app.domains.auth.application.service import (
    AuthenticatedSession,
    AuthService,
    SignUpCommand,
)
from app.domains.auth.domain.entities import User
from app.infrastructure.container import get_auth_service
from app.security.authentication.dependencies import (
    get_current_user_id,
    get_session_service,
)
from app.security.authentication.service import SessionService
from app.security.protection import rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])

# Credential guessing and account spam are throttled per client address.
_credential_rate_limit = Depends(
    rate_limit(limit=lambda: get_settings().login_rate_limit_per_minute)
)


@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_credential_rate_limit],
)
async def signup(
    body: SignUpRequest,
    service: AuthService = Depends(get_auth_service),
) -> User:
    """Register a new account."""
    return await service.sign_up(
        SignUpCommand(
            name=body.name,
            email=body.email,
            password=body.password,
            phone=body.phone,
        )
    )


@router.post("/login", response_model=UserResponse, dependencies=[_credential_rate_limit])
async def login(
    body: LoginRequest,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    session_service: SessionService = Depends(get_session_service),
) -> User:
    """Verify credentials and open a session (sets the auth cookie)."""
    result: AuthenticatedSession = await service.log_in(body.email, body.password)
    session_service.set_cookie(response, result.token)
    return result.user


@router.post("/logout", response_model=MessageResponse)
async def logout(
    response: Response,
    session_service: SessionService = Depends(get_session_service),
) -> MessageResponse:
    """Invalidate the session by clearing the auth cookie."""
    session_service.clear_cookie(response)
    return MessageResponse(detail="Logged out.")


@router.get("/me", response_model=UserResponse)
async def me(
    user_id: int = Depends(get_current_user_id),
    service: AuthService = Depends(get_auth_service),
) -> User:
    """Return the currently authenticated user."""
    return await service.get_user(user_id)

"""Cart request-scoped dependencies.

Resolves *whose* cart an incoming request refers to from either a valid session
cookie (authenticated) or a guest-cart cookie (anonymous). It never trusts a
caller-supplied cart id, so requests can only reach their own cart.
"""

from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings
from app.security.authentication.dependencies import (
    get_session_service,
    get_session_strategy,
)
from app.shared.exceptions import AuthenticationError

GUEST_CART_COOKIE = "guest_cart_id"
# Guest carts are handed a generous lifetime so a returning browser keeps its bag.
_GUEST_CART_MAX_AGE = 60 * 60 * 24 * 30


@dataclass(frozen=True)
class CartLocation:
    user_id: int | None
    guest_token: str | None
    authenticated: bool


def get_cart_location(request: Request) -> CartLocation:
    """Determine the cart owner from the session, else the guest cookie."""
    token = get_session_service().read_token(request)
    if token:
        try:
            claims = get_session_strategy().verify(token)
            return CartLocation(user_id=int(claims.subject), guest_token=None, authenticated=True)
        except (AuthenticationError, ValueError):
            # An invalid/expired session falls back to the guest cart, if any.
            pass
    return CartLocation(
        user_id=None,
        guest_token=request.cookies.get(GUEST_CART_COOKIE),
        authenticated=False,
    )


def attach_guest_cookie(
    response: Response, location: CartLocation, guest_token: str | None
) -> None:
    """Persist the guest-cart cookie for anonymous shoppers."""
    if location.authenticated or not guest_token:
        return
    settings = get_settings()
    response.set_cookie(
        key=GUEST_CART_COOKIE,
        value=guest_token,
        max_age=_GUEST_CART_MAX_AGE,
        path="/",
        domain=settings.cookie_domain or None,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_guest_cookie(response: Response) -> None:
    """Drop the guest-cart cookie after a merge folds it into the user's cart."""
    settings = get_settings()
    response.delete_cookie(
        key=GUEST_CART_COOKIE,
        path="/",
        domain=settings.cookie_domain or None,
    )

"""Aggregate v1 API router.

Each domain contributes its router here; the composition stays one line per
domain so `main.py` never needs to know about individual feature routers.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.domains.admin.api.router import router as admin_router
from app.domains.auth.api.router import router as auth_router
from app.domains.cart.api.router import router as cart_router
from app.domains.orders.api.router import router as orders_router
from app.domains.payments.api.router import router as payments_router
from app.domains.products.api.router import router as products_router
from app.domains.users.api.router import router as users_router
from app.domains.wishlist.api.router import router as wishlist_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(cart_router)
api_router.include_router(users_router)
api_router.include_router(products_router)
api_router.include_router(wishlist_router)
api_router.include_router(orders_router)
api_router.include_router(payments_router)
# Last: the admin surface is not a step in any customer flow, and its own
# guard covers every route under /admin regardless of where it is mounted.
api_router.include_router(admin_router)

__all__ = ["api_router"]

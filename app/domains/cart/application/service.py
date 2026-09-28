"""Cart application service.

Orchestrates guest and authenticated carts. Cart *location* is resolved from
either an authenticated ``user_id`` or a guest ``guest_token`` (never from a
caller-supplied cart id), so a shopper can only ever reach their own cart.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.domains.cart.application.merge import AbstractCartMergeStrategy, AdditiveMergeStrategy
from app.domains.cart.domain.entities import Cart, CartItem
from app.domains.cart.domain.repositories import AbstractCartRepository
from app.domains.products.domain.repositories import AbstractProductRepository
from app.shared.exceptions import NotFoundError, ValidationError


def new_guest_token() -> str:
    return uuid4().hex


class CartService:
    def __init__(
        self,
        *,
        carts: AbstractCartRepository,
        products: AbstractProductRepository,
        merge_strategy: AbstractCartMergeStrategy | None = None,
    ) -> None:
        self._carts = carts
        self._products = products
        self._merge_strategy = merge_strategy or AdditiveMergeStrategy()

    async def ensure_cart(self, *, user_id: int | None, guest_token: str | None) -> Cart:
        """Return the shopper's cart, creating it (or a fresh guest cart) as needed."""
        if user_id is not None:
            existing = await self._carts.get_by_user_id(user_id)
            if existing is not None:
                return existing
            return await self._carts.add(Cart(id=0, user_id=user_id))

        if guest_token is not None:
            existing = await self._carts.get_by_guest_token(guest_token)
            if existing is not None:
                return existing

        return await self._carts.add(Cart(id=0, guest_token=new_guest_token()))

    async def add_item(
        self, cart: Cart, *, product_slug: str, size: str, quantity: int
    ) -> Cart:
        product = await self._products.get_by_slug(product_slug)
        if product is None or not product.is_active:
            raise NotFoundError("Product not found")
        variant = next((v for v in product.variants if v.size == size), None)
        if variant is None:
            raise ValidationError(f"Size '{size}' is not available for this product")
        if quantity < 1:
            raise ValidationError("Quantity must be at least 1")

        image = product.primary_image or ""
        cart.add_item(
            CartItem(
                id=0,
                variant_id=variant.id,
                product_slug=product.slug,
                product_name=product.name,
                size=variant.size,
                quantity=quantity,
                unit_price=Decimal(product.price),
                image=image,
                currency=product.currency,
            )
        )
        return await self._carts.save(cart)

    async def update_item(self, cart: Cart, item_id: int, quantity: int) -> Cart:
        cart.set_quantity(item_id, quantity)
        return await self._carts.save(cart)

    async def remove_item(self, cart: Cart, item_id: int) -> Cart:
        cart.remove_item(item_id)
        return await self._carts.save(cart)

    async def merge_guest_into_user(self, *, user_id: int, guest_token: str) -> Cart:
        """Fold the guest cart identified by ``guest_token`` into the user's cart.

        The conflict policy is delegated to the injected merge strategy (see
        ``merge.py``); the guest cart is removed once folded in.
        """
        guest = await self._carts.get_by_guest_token(guest_token)
        if guest is None:
            raise NotFoundError("Guest cart not found")

        user_cart = await self.ensure_cart(user_id=user_id, guest_token=None)
        self._merge_strategy.merge(user_cart, guest)
        saved = await self._carts.save(user_cart)
        await self._carts.delete(guest)
        return saved

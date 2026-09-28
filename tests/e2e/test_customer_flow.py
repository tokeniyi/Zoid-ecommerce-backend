"""Phase 17 — the whole customer path, end to end, with no live provider.

One narrative, from an anonymous browser to a paid order the shop can read:
browse a product, fill a guest cart, get refused at checkout for having no
session, sign in, watch the guest bag fold into the account, check out a
``PENDING_PAYMENT`` order, pay it through the ``PaymentGateway`` contract,
confirm it, and have the store owner told by email and an admin able to see it.

Only the seams that reach outside the process are doubled. Persistence, the
session cookie, ownership, the guest-cart merge, RBAC and the payment ledger are
all the real thing; the payment provider is the genuine Paystack adapter driven
by a mock transport (so the request it signs and the response it parses are
exercised for real), and the newsdesk is a recording double for the email
contract. That is the whole point of the composition: the customer flow is
provable without a live Paystack, Stripe or Resend call.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from itertools import count
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.domains.cart.api.deps import GUEST_CART_COOKIE
from app.domains.payments.application.notifications import PaidOrderNotifier
from app.domains.payments.application.service import PaymentService
from app.domains.products.domain.entities import (
    Category,
    Inventory,
    Product,
    ProductImage,
    ProductVariant,
)
from app.infrastructure.container import get_payment_service, get_unit_of_work
from app.infrastructure.persistence.sqlalchemy.models import TransactionRow
from app.infrastructure.persistence.sqlalchemy.session import (
    build_sessionmaker,
    create_engine_from_url,
)
from app.infrastructure.persistence.sqlalchemy.unit_of_work import (
    AbstractUnitOfWork,
    SqlAlchemyUnitOfWork,
)
from app.integrations.payments import build_webhook_adapter
from app.integrations.payments.paystack import PaystackPaymentGateway
from app.security.authentication.session import session_strategy_from_settings
from tests.unit.payments.test_order_notification import RecordingSender

_settings = get_settings()
API = _settings.api_v1_prefix
COOKIE = _settings.cookie_name
GUEST = GUEST_CART_COOKIE
PASSWORD = "Sup3rSecret!"
PRICE = Decimal("42000.00")
PRICE_KOBO = 4_200_000
WEBHOOK_SECRET = "whsec_e2e_at_the_endpoint"
OWNER_EMAIL = "owner@zoid.example"

CHECKOUT: dict[str, Any] = {
    "contact_name": "Ada Zoid",
    "contact_email": "ada@example.com",
    "contact_phone": "+234 800 000 0000",
    "address_line": "12 Concrete Road",
    "city_state": "Lagos State",
}

#: A fresh starting id per process, so a redelivery test is never answered
#: "duplicate" by a previous run's committed receipt.
_event_numbers = count(uuid4().int % 1_000_000_000_000)


# --- fixtures and helpers -----------------------------------------------------


def _make_product() -> Product:
    tag = uuid4().hex[:8]
    return Product(
        id=0,
        slug=f"e2e-jersey-{tag}",
        name=f"E2E Jersey {tag}",
        category=Category(id=0, name="E2E Curated", slug="e2e-curated"),
        price=PRICE,
        images=[ProductImage(url="/front.jpg", view="front")],
        variants=[
            ProductVariant(
                id=0, sku=f"e2e-{tag}-M", size="M", inventory=Inventory(quantity=10)
            )
        ],
    )


async def _seed_product() -> str:
    """No public write endpoint exists, so the shelf is stocked via the repo."""
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            created = await uow.products.add(_make_product())
            await uow.commit()
            return created.slug
    finally:
        await engine.dispose()


def _register_and_login(client: TestClient) -> tuple[str, int]:
    email = f"zoid-e2e-{uuid4()}@example.com"
    signup = client.post(
        f"{API}/auth/signup",
        json={"name": "Buyer", "email": email, "password": PASSWORD},
    )
    assert signup.status_code == 201, signup.text
    login = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    session = str(login.cookies.get(COOKIE))
    me = client.get(f"{API}/auth/me", cookies={COOKIE: session})
    assert me.status_code == 200, me.text
    return session, int(me.json()["id"])


def _admin_token(user_id: int) -> str:
    """A real admin session, minted with the strategy the app uses."""
    return session_strategy_from_settings().issue(str(user_id), role="admin")[0]


def _paystack_gateway(calls: list[str]) -> PaystackPaymentGateway:
    """The genuine adapter, driven by a transport that answers from a script.

    Every request the gateway makes is recorded in ``calls`` so a test can prove
    the provider was reached through the ``PaymentGateway`` contract.
    """

    def answer(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.startswith("/transaction/verify"):
            reference = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "message": "Transaction verified successfully",
                    "data": {
                        "status": "success",
                        "reference": reference,
                        "gateway_reference": f"GW-{reference}",
                        "amount": PRICE_KOBO,
                        "currency": "NGN",
                    },
                },
            )
        reference = json.loads(request.content)["reference"]
        return httpx.Response(
            200,
            json={
                "status": True,
                "message": "Authorization URL created",
                "data": {
                    "authorization_url": f"https://checkout.paystack.com/{reference}",
                    "access_code": f"ac-{reference}",
                    "reference": reference,
                },
            },
        )

    return PaystackPaymentGateway(
        secret_key="sk_test_e2e_at_the_endpoint",
        callback_url="http://localhost:5173/checkout",
        webhook_secret=WEBHOOK_SECRET,
        transport=httpx.MockTransport(answer),
    )


@pytest.fixture
def store(client: TestClient) -> tuple[RecordingSender, list[str]]:
    """Point the payment endpoints at a scripted provider and a recording newsdesk.

    The override is installed the same way the container wires it, and removed
    afterwards so no other test inherits it.
    """
    calls: list[str] = []
    gateway = _paystack_gateway(calls)
    emails = RecordingSender()

    async def overridden(
        uow: AbstractUnitOfWork = Depends(get_unit_of_work),
    ) -> PaymentService:
        return PaymentService(
            transactions=uow.transactions,
            orders=uow.orders,
            refunds=uow.refunds,
            webhook_events=uow.webhook_events,
            gateway=gateway,
            webhook=build_webhook_adapter(gateway),
            notifier=PaidOrderNotifier(sender=emails, owner_email=OWNER_EMAIL),
        )

    client.app.dependency_overrides[get_payment_service] = overridden
    try:
        yield emails, calls
    finally:
        client.app.dependency_overrides.pop(get_payment_service, None)


def _add_to_cart(client: TestClient, slug: str, *, cookie: str | None = None):
    cookies = {GUEST: cookie} if cookie else None
    return client.post(
        f"{API}/cart/items",
        cookies=cookies,
        json={"product_slug": slug, "size": "M", "quantity": 1},
    )


def _checkout(client: TestClient, session: str) -> dict[str, Any]:
    response = client.post(f"{API}/orders", cookies={COOKIE: session}, json=CHECKOUT)
    assert response.status_code == 201, response.text
    return response.json()


def _initiate(client: TestClient, session: str, order_id: int):
    return client.post(
        f"{API}/payments/initiate", cookies={COOKIE: session}, json={"order_id": order_id}
    )


def _order_status(client: TestClient, session: str, order_id: int) -> str:
    response = client.get(f"{API}/orders/{order_id}", cookies={COOKIE: session})
    assert response.status_code == 200, response.text
    return str(response.json()["status"])


def _notification(*, reference: str) -> tuple[bytes, dict[str, str], str]:
    """A charge.success event, signed exactly as Paystack signs it."""
    number = next(_event_numbers)
    payload = json.dumps(
        {
            "event": "charge.success",
            "data": {
                "id": number,
                "status": "success",
                "reference": reference,
                "amount": PRICE_KOBO,
                "currency": "NGN",
                "gateway_reference": f"PS-API-{number}",
            },
        }
    ).encode()
    digest = hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha512).hexdigest()
    return payload, {"paystack-signature": digest}, f"charge.success:{number}"


def _deliver(client: TestClient, payload: bytes, headers: dict[str, str]):
    return client.post(f"{API}/payments/webhooks/paystack", content=payload, headers=headers)


async def _payment_statuses(reference: str) -> list[str]:
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            rows = (
                await uow.session.execute(
                    select(TransactionRow.status).where(TransactionRow.reference == reference)
                )
            ).scalars().all()
            return list(rows)
    finally:
        await engine.dispose()


# --- the guarded front door: a browser with no session ------------------------


async def test_anonymous_shopper_browses_and_bags_a_jersey_but_cannot_buy(
    client: TestClient,
) -> None:
    slug = await _seed_product()

    # Browsing is public: the product is legible by its own address.
    browsed = client.get(f"{API}/products/{slug}")
    assert browsed.status_code == 200, browsed.text
    assert browsed.json()["slug"] == slug
    assert browsed.json()["price"] == float(PRICE)

    # A guest can fill a cart, carried by the guest-cart cookie.
    added = _add_to_cart(client, slug)
    assert added.status_code == 200, added.text
    guest = added.cookies.get(GUEST)
    assert guest, "the guest cart cookie is issued"
    assert client.get(f"{API}/cart", cookies={GUEST: guest}).json()["count"] == 1

    # Every step that spends, moves or reveals an account is refused without one.
    assert client.post(f"{API}/orders", json=CHECKOUT).status_code == 401
    assert client.post(f"{API}/cart/merge").status_code == 401
    assert client.post(f"{API}/payments/initiate", json={"order_id": 1}).status_code == 401
    assert (
        client.post(f"{API}/payments/verify", json={"reference": "PAY-e2e-x"}).status_code
        == 401
    )
    assert client.get(f"{API}/admin/orders").status_code == 401


# --- the full path, confirmed by the customer's own verification --------------


async def test_the_whole_path_from_guest_cart_to_a_paid_order_the_shop_can_read(
    client: TestClient, store: tuple[RecordingSender, list[str]]
) -> None:
    emails, calls = store
    slug = await _seed_product()

    # A guest bags a jersey, then becomes a member; the bag follows them in.
    guest = _add_to_cart(client, slug).cookies.get(GUEST)
    session, user_id = _register_and_login(client)
    merged = client.post(f"{API}/cart/merge", cookies={COOKIE: session, GUEST: guest})
    assert merged.status_code == 200, merged.text
    assert merged.json()["count"] == 1

    # Checkout builds a pending order from the server-side cart.
    order = _checkout(client, session)
    assert order["status"] == "PENDING_PAYMENT"
    assert order["reference"].startswith("ZD-")
    order_id = order["id"]

    # Payment runs through the gateway contract; the client is only ever handed a
    # normalised redirect, never a provider name it should not care about.
    initiated = _initiate(client, session, order_id)
    assert initiated.status_code == 200, initiated.text
    payment = initiated.json()
    assert payment["status"] == "pending"
    assert payment["provider"] == "paystack"
    assert payment["next_action"]["url"].startswith("https://checkout.paystack.com/")
    assert any(path.startswith("/transaction/initialize") for path in calls)
    reference = payment["payment_id"]

    # Confirmation changes both ledger and order.
    verified = client.post(
        f"{API}/payments/verify", cookies={COOKIE: session}, json={"reference": reference}
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "paid"
    assert _order_status(client, session, order_id) == "PAID"
    assert await _payment_statuses(reference) == ["paid"]

    # The store owner is told once, with the order and payment in hand.
    assert [message.to for message in emails.calls] == [OWNER_EMAIL]
    body = emails.calls[0].text_body
    assert order["reference"] in body
    assert reference in body
    assert "42,000.00 NGN" in body

    # And an admin can read the paid order back out of the order book.
    book = client.get(
        f"{API}/admin/orders",
        cookies={COOKIE: _admin_token(user_id)},
        params={"page_size": 100},
    )
    assert book.status_code == 200, book.text
    row = next(item for item in book.json()["items"] if item["id"] == order_id)
    assert row["status"] == "PAID"
    assert row["reference"] == order["reference"]


# --- the provider's own announcement, and its redelivery ----------------------


async def test_a_webhook_settles_the_order_once_and_a_redelivery_repeats_nothing(
    client: TestClient, store: tuple[RecordingSender, list[str]]
) -> None:
    emails, _ = store
    slug = await _seed_product()
    session, user_id = _register_and_login(client)
    added = client.post(
        f"{API}/cart/items",
        cookies={COOKIE: session},
        json={"product_slug": slug, "size": "M", "quantity": 1},
    )
    assert added.status_code == 200, added.text
    order_id = _checkout(client, session)["id"]
    reference = _initiate(client, session, order_id).json()["payment_id"]
    payload, headers, _event_id = _notification(reference=reference)

    first = _deliver(client, payload, headers)
    assert first.status_code == 200, first.text
    assert first.json()["outcome"] == "applied"
    assert _order_status(client, session, order_id) == "PAID"
    assert len(emails.calls) == 1

    # The provider, unsure the first message landed, sends the very same event.
    second = _deliver(client, payload, headers)
    assert second.status_code == 200, second.text
    assert second.json()["outcome"] == "duplicate"

    # Nothing happened twice: one payment, one paid order, one email.
    assert await _payment_statuses(reference) == ["paid"]
    assert _order_status(client, session, order_id) == "PAID"
    assert len(emails.calls) == 1

    book = client.get(
        f"{API}/admin/orders",
        cookies={COOKIE: _admin_token(user_id)},
        params={"page_size": 100},
    )
    row = next(item for item in book.json()["items"] if item["id"] == order_id)
    assert row["status"] == "PAID"

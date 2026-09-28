"""Payments endpoints against the configured database, with a fake provider.

Persistence, ownership and permission are exercised for real; the provider is a
scripted double injected through the dependency container -- the same seam a
Paystack or Stripe adapter will slot into, which is the point of the contract.

The webhook half of this file uses the *real* Paystack adapter instead of a
double, because what is being proved is that a signed notification from a
provider with no session, no user and no permissions can settle an order -- and
that a second copy of the same notification cannot settle it again. Email at that
level is always a double: no test here needs a real message to leave the process.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterator
from decimal import Decimal
from itertools import count
from uuid import uuid4

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.domains.payments.application.notifications import PaidOrderNotifier
from app.domains.payments.application.service import PaymentService
from app.domains.payments.domain.enums import PaymentAction, PaymentStatus
from app.domains.payments.domain.gateway import (
    AbstractPaymentGateway,
    PaymentInitiation,
    PaymentRequest,
    PaymentVerification,
    RefundRequest,
    RefundResult,
)
from app.domains.products.domain.entities import (
    Category,
    Inventory,
    Product,
    ProductImage,
    ProductVariant,
)
from app.infrastructure.container import get_payment_service, get_unit_of_work
from app.infrastructure.persistence.sqlalchemy.models import TransactionRow, WebhookEventRow
from app.infrastructure.persistence.sqlalchemy.session import (
    build_sessionmaker,
    create_engine_from_url,
)
from app.infrastructure.persistence.sqlalchemy.unit_of_work import (
    AbstractUnitOfWork,
    SqlAlchemyUnitOfWork,
)
from app.integrations.email.sender import (
    AbstractEmailSender,
    EmailDelivery,
    EmailMessage,
)
from app.integrations.payments import build_payment_gateway, build_webhook_adapter
from app.integrations.payments.paystack import PaystackPaymentGateway
from app.security.authentication.session import session_strategy_from_settings
from app.shared.exceptions import ProviderNotConfiguredError
from tests.unit.payments.test_order_notification import RecordingSender

_settings = get_settings()
API = _settings.api_v1_prefix
COOKIE = _settings.cookie_name
PASSWORD = "Sup3rSecret!"
PRICE = Decimal("42000.00")
PRICE_KOBO = 4200000
WEBHOOK_SECRET = "whsec_test_at_the_endpoint"
#: Whichever e-mail the store has told us to notify. The provider behind it is
#: always a double in these tests.
OWNER_EMAIL = "owner@zoid.example"

CHECKOUT = {
    "contact_name": "Ada Zoid",
    "contact_email": "ada@example.com",
    "contact_phone": "+234 800 000 0000",
    "address_line": "12 Concrete Road",
    "city_state": "Lagos State",
}


class ScriptedGateway(AbstractPaymentGateway):
    """A provider double: it accepts anything and reports it as paid."""

    provider = "scripted"

    def __init__(self) -> None:
        self.requests: list[PaymentRequest] = []
        self.verified: list[str] = []
        self.refunds: list[RefundRequest] = []

    async def create_payment(self, request: PaymentRequest) -> PaymentInitiation:
        self.requests.append(request)
        return PaymentInitiation(
            success=True,
            status=PaymentStatus.PENDING,
            transaction_reference=request.reference,
            provider_reference=f"prov-{request.reference}",
            checkout_url=f"https://provider.example/checkout/{request.reference}",
            action=PaymentAction.REDIRECT,
        )

    async def verify_payment(self, reference: str) -> PaymentVerification:
        self.verified.append(reference)
        return PaymentVerification(
            success=True,
            status=PaymentStatus.PAID,
            transaction_reference=reference,
            provider_reference=f"prov-{reference}",
            amount=PRICE,
        )

    async def refund_payment(self, request: RefundRequest) -> RefundResult:
        self.refunds.append(request)
        return RefundResult(
            success=True,
            status=PaymentStatus.REFUNDED,
            transaction_reference=request.transaction_reference,
            provider_refund_reference=f"rf-{request.transaction_reference}",
            amount=request.amount,
        )


@pytest.fixture
def gateway(client: TestClient) -> Iterator[ScriptedGateway]:
    """Swap the wired gateway for the scripted double, for one test only."""
    scripted = ScriptedGateway()

    async def overridden(
        uow: AbstractUnitOfWork = Depends(get_unit_of_work),
    ) -> PaymentService:
        return PaymentService(
            transactions=uow.transactions,
            orders=uow.orders,
            refunds=uow.refunds,
            webhook_events=uow.webhook_events,
            gateway=scripted,
            provider=scripted.provider,
        )

    client.app.dependency_overrides[get_payment_service] = overridden
    yield scripted
    client.app.dependency_overrides.pop(get_payment_service, None)


def _make_product() -> Product:
    tag = uuid4().hex[:8]
    return Product(
        id=0,
        slug=f"pay-jersey-{tag}",
        name=f"Pay Jersey {tag}",
        category=Category(id=0, name="Pay Curated", slug="pay-curated"),
        price=PRICE,
        images=[ProductImage(url="/front.jpg", view="front")],
        variants=[
            ProductVariant(
                id=0, sku=f"pay-{tag}-M", size="M", inventory=Inventory(quantity=10)
            )
        ],
    )


async def _seed_product() -> str:
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            created = await uow.products.add(_make_product())
            await uow.commit()
            return created.slug
    finally:
        await engine.dispose()


def _register_and_login(client: TestClient) -> tuple[str, int]:
    email = f"zoid-pay-{uuid4()}@example.com"
    signup = client.post(
        f"{API}/auth/signup",
        json={"name": "Payer", "email": email, "password": PASSWORD},
    )
    assert signup.status_code == 201, signup.text
    login = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    session = login.cookies.get(COOKIE)
    me = client.get(f"{API}/auth/me", cookies={COOKIE: session})
    assert me.status_code == 200, me.text
    return session, me.json()["id"]


async def _placed_order(client: TestClient, session: str) -> int:
    """Cart -> order over HTTP, the way a customer reaches the pay step."""
    slug = await _seed_product()
    added = client.post(
        f"{API}/cart/items",
        cookies={COOKIE: session},
        json={"product_slug": slug, "size": "M", "quantity": 1},
    )
    assert added.status_code == 200, added.text
    order = client.post(f"{API}/orders", cookies={COOKIE: session}, json=CHECKOUT)
    assert order.status_code == 201, order.text
    return order.json()["id"]


def _initiate(client: TestClient, session: str, order_id: int):
    return client.post(
        f"{API}/payments/initiate", cookies={COOKIE: session}, json={"order_id": order_id}
    )


def _admin_token(user_id: int) -> str:
    """A session token carrying the admin role, minted with the real strategy."""
    return session_strategy_from_settings().issue(str(user_id), role="admin")[0]


async def test_payment_endpoints_reject_anonymous_callers(client: TestClient) -> None:
    assert client.post(f"{API}/payments/initiate", json={"order_id": 1}).status_code == 401
    assert (
        client.post(f"{API}/payments/verify", json={"reference": "PAY-x"})
    ).status_code == 401
    assert client.post(f"{API}/payments/refunds", json={"reference": "PAY-x"}).status_code == 401


async def test_customers_cannot_refund(
    client: TestClient, gateway: ScriptedGateway
) -> None:
    session, _ = _register_and_login(client)

    response = client.post(
        f"{API}/payments/refunds",
        cookies={COOKIE: session},
        json={"reference": "PAY-whatever"},
    )

    assert response.status_code == 403, response.text


async def test_a_provider_without_credentials_refuses_to_charge_anything(
    client: TestClient,
) -> None:
    """Selection is the factory's, persistence is the database's.

    Only the secret key is pinned -- so the endpoint proves that an
    under-configured provider fails loudly (501) instead of quietly doing
    something else, and that no payment attempt can leave the process.
    """
    session, _ = _register_and_login(client)
    order_id = await _placed_order(client, session)
    keyless = get_settings().model_copy(
        update={"payment_provider": "paystack", "paystack_secret_key": ""}
    )

    async def overridden(
        uow: AbstractUnitOfWork = Depends(get_unit_of_work),
    ) -> PaymentService:
        return PaymentService(
            transactions=uow.transactions,
            orders=uow.orders,
            refunds=uow.refunds,
            webhook_events=uow.webhook_events,
            gateway=build_payment_gateway(keyless),
        )

    client.app.dependency_overrides[get_payment_service] = overridden
    try:
        response = _initiate(client, session, order_id)
    finally:
        client.app.dependency_overrides.pop(get_payment_service, None)

    assert response.status_code == 501, response.text
    assert "not configured" in response.json()["detail"]


async def test_initiate_verify_and_refund_flow(
    client: TestClient, gateway: ScriptedGateway
) -> None:
    session, user_id = _register_and_login(client)
    order_id = await _placed_order(client, session)

    initiated = _initiate(client, session, order_id)

    assert initiated.status_code == 200, initiated.text
    body = initiated.json()
    # The standardized response: the client is told to redirect, never which
    # provider it is redirecting to.
    assert body["success"] is True
    assert body["status"] == "pending"
    assert body["payment_id"].startswith("PAY-")
    assert body["amount"] == float(PRICE)
    assert body["provider"] == "scripted"
    assert body["next_action"]["type"] == "redirect"
    assert body["next_action"]["url"].startswith("https://provider.example/checkout/")
    assert gateway.requests[0].order_reference.startswith("ZD-")

    verified = client.post(
        f"{API}/payments/verify",
        cookies={COOKIE: session},
        json={"reference": body["payment_id"]},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "paid"
    assert verified.json()["next_action"] is None

    refunded = client.post(
        f"{API}/payments/refunds",
        cookies={COOKIE: _admin_token(user_id)},
        json={"reference": body["payment_id"], "reason": "Returned jersey"},
    )
    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["status"] == "refunded"
    assert gateway.refunds[0].reason == "Returned jersey"

    # A settled payment cannot be re-initiated.
    assert _initiate(client, session, order_id).status_code == 409


async def test_a_payment_cannot_be_verified_by_another_user(
    client: TestClient, gateway: ScriptedGateway
) -> None:
    session, _ = _register_and_login(client)
    stranger, _ = _register_and_login(client)
    order_id = await _placed_order(client, session)
    payment_id = _initiate(client, session, order_id).json()["payment_id"]

    response = client.post(
        f"{API}/payments/verify",
        cookies={COOKIE: stranger},
        json={"reference": payment_id},
    )

    assert response.status_code == 404, response.text
    assert gateway.verified == []


async def test_payment_requests_are_validated(
    client: TestClient, gateway: ScriptedGateway
) -> None:
    session, _ = _register_and_login(client)

    # An authenticated call with a malformed body fails validation, not auth.
    assert (
        client.post(f"{API}/payments/initiate", cookies={COOKIE: session}, json={})
    ).status_code == 422
    assert (
        client.post(
            f"{API}/payments/verify", cookies={COOKIE: session}, json={"reference": "x"}
        )
    ).status_code == 422


# --- provider notifications at the endpoint -----------------------------------

#: A fresh starting id for each process. Receipts are committed to a database
#: that outlives the run, so event ids restarted from one would be answered
#: "duplicate" by the next run -- correctly, which is precisely the behaviour the
#: redelivery test exists to establish.
_event_numbers = count(uuid4().int % 1_000_000_000_000)


def _paystack_answer(request: httpx.Request) -> httpx.Response:
    """The two Paystack calls a checkout makes, answered from a script.

    The access code is derived from our reference because a payment attempt's
    provider reference has to be unique -- a script that reused one would be
    reporting a clash as though it were the application's bug.
    """
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


def _paystack_gateway() -> PaystackPaymentGateway:
    """The real adapter, transport and all, as the container would build it."""
    return PaystackPaymentGateway(
        secret_key="sk_test_at_the_endpoint",
        callback_url="http://localhost:5173/checkout",
        webhook_secret=WEBHOOK_SECRET,
        transport=httpx.MockTransport(_paystack_answer),
    )


def _wire(
    client: TestClient,
    *,
    gateway: PaystackPaymentGateway,
    notifier: PaidOrderNotifier | None = None,
) -> None:
    """Point the payment endpoints at this adapter, with this newsdesk."""

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
            notifier=notifier,
        )

    client.app.dependency_overrides[get_payment_service] = overridden


@pytest.fixture
def paystack(client: TestClient) -> Iterator[str]:
    """The real adapter, wired the way the container wires it, transport and all.

    Only the signing secret is chosen by the test: it is what lets these tests
    send a notification that Paystack itself would have signed.
    """
    _wire(client, gateway=_paystack_gateway())
    yield WEBHOOK_SECRET
    client.app.dependency_overrides.pop(get_payment_service, None)


def _notification(
    *,
    secret: str,
    reference: str | None,
    name: str = "charge.success",
    amount: int = PRICE_KOBO,
) -> tuple[bytes, dict[str, str], str]:
    """A Paystack event, signed as Paystack signs it, with its ledger identity.

    Every event gets a fresh id. An id reused between tests would be taken for a
    redelivery by the next one -- true of Paystack too, which is what the
    duplicate test below is here to establish.
    """
    number = next(_event_numbers)
    data: dict[str, object] = {
        "id": number,
        "status": "success" if name.endswith("success") else "failed",
        "amount": amount,
        "currency": "NGN",
        "gateway_reference": f"PS-API-{number}",
    }
    if reference is not None:
        data["reference"] = reference
    payload = json.dumps({"event": name, "data": data}).encode()
    digest = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
    return payload, {"paystack-signature": digest}, f"{name}:{number}"


def _deliver(
    client: TestClient,
    payload: bytes,
    headers: dict[str, str],
    *,
    provider: str = "paystack",
) -> httpx.Response:
    """Hand a notification to the endpoint. No cookies: a provider has none."""
    return client.post(
        f"{API}/payments/webhooks/{provider}", content=payload, headers=headers
    )


async def _receipts(event_id: str) -> list[tuple[str, bool]]:
    """What the ledger kept for one provider event.

    Read through a second unit of work, because the HTTP session is closed by
    then: only what was committed is real.
    """
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            rows = (
                await uow.session.execute(
                    select(WebhookEventRow.provider, WebhookEventRow.processed).where(
                        WebhookEventRow.event_id == event_id
                    )
                )
            ).all()
            return [(str(row[0]), bool(row[1])) for row in rows]
    finally:
        await engine.dispose()


async def _payment_statuses(reference: str) -> list[str]:
    """Every attempt recorded against one payment reference, in the database."""
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            found = (
                await uow.session.execute(
                    select(TransactionRow.status).where(
                        TransactionRow.reference == reference
                    )
                )
            ).scalars().all()
            return list(found)
    finally:
        await engine.dispose()


def _order_status(client: TestClient, session: str, order_id: int) -> str:
    response = client.get(f"{API}/orders/{order_id}", cookies={COOKIE: session})
    assert response.status_code == 200, response.text
    return str(response.json()["status"])


async def _paying_customer(client: TestClient) -> tuple[str, int, str]:
    """A customer with an order and an open payment attempt."""
    session, _ = _register_and_login(client)
    order_id = await _placed_order(client, session)
    payment_id = _initiate(client, session, order_id).json()["payment_id"]
    return session, order_id, payment_id


async def test_a_signed_notification_settles_the_order_it_names(
    client: TestClient, paystack: str
) -> None:
    session, order_id, payment_id = await _paying_customer(client)
    payload, headers, event_id = _notification(secret=paystack, reference=payment_id)

    response = _deliver(client, payload, headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"received": True, "outcome": "applied"}
    assert _order_status(client, session, order_id) == "PAID"
    assert await _payment_statuses(payment_id) == ["paid"]
    assert await _receipts(event_id) == [("paystack", True)]


@pytest.mark.parametrize(
    "spoofed", ["wrong_secret", "no_signature"], ids=("forged", "unsigned")
)
async def test_a_notification_that_is_not_authentically_paystacks_is_refused_before_it_is_read(
    client: TestClient, paystack: str, spoofed: str
) -> None:
    """400 rather than 401: nobody at a webhook endpoint holds a customer session,
    and the signature is what stands in for one."""
    session, order_id, payment_id = await _paying_customer(client)
    payload, headers, event_id = _notification(secret=paystack, reference=payment_id)
    if spoofed == "wrong_secret":
        payload, headers, event_id = _notification(
            secret="whsec_not_paystack", reference=payment_id
        )
    else:
        headers = {}

    response = _deliver(client, payload, headers)

    assert response.status_code == 400, response.text
    assert _order_status(client, session, order_id) == "PENDING_PAYMENT"
    # An unverifiable payload is not evidence: it is not even recorded as arrived.
    assert await _receipts(event_id) == []


async def test_a_redelivered_notification_is_answered_and_changes_nothing(
    client: TestClient, paystack: str
) -> None:
    session, order_id, payment_id = await _paying_customer(client)
    payload, headers, event_id = _notification(secret=paystack, reference=payment_id)

    first = _deliver(client, payload, headers)
    second = _deliver(client, payload, headers)
    third = _deliver(client, payload, headers)

    assert first.json()["outcome"] == "applied"
    assert second.status_code == 200, second.text
    assert second.json()["outcome"] == "duplicate"
    assert third.json()["outcome"] == "duplicate"
    # One receipt, one payment, one paid order -- nothing was done twice.
    assert await _receipts(event_id) == [("paystack", True)]
    assert await _payment_statuses(payment_id) == ["paid"]
    assert _order_status(client, session, order_id) == "PAID"


async def test_a_second_event_bringing_the_same_news_moves_nothing(
    client: TestClient, paystack: str
) -> None:
    """Two different events saying the payment is paid: the ledger already agrees."""
    session, order_id, payment_id = await _paying_customer(client)
    payload, headers, _ = _notification(secret=paystack, reference=payment_id)
    _deliver(client, payload, headers)

    again, headers, event_id = _notification(
        secret=paystack, reference=payment_id, name="payment.success"
    )
    response = _deliver(client, again, headers)

    assert response.json()["outcome"] == "applied"
    assert await _receipts(event_id) == [("paystack", True)]
    assert await _payment_statuses(payment_id) == ["paid"]
    assert _order_status(client, session, order_id) == "PAID"


async def test_a_notification_from_a_provider_that_is_not_configured_is_not_ours_to_read(
    client: TestClient, paystack: str
) -> None:
    """Paystack's own signature does not buy it Stripe's endpoint."""
    _, _, payment_id = await _paying_customer(client)
    payload, headers, event_id = _notification(secret=paystack, reference=payment_id)

    response = _deliver(client, payload, headers, provider="stripe")

    assert response.status_code == 404, response.text
    assert await _receipts(event_id) == []


async def test_a_notification_about_someone_elses_payment_is_recorded_and_harmless(
    client: TestClient, paystack: str
) -> None:
    session, order_id, _ = await _paying_customer(client)
    payload, headers, event_id = _notification(
        secret=paystack, reference="PAY-NOTMINE0000"
    )

    response = _deliver(client, payload, headers)

    assert response.json()["outcome"] == "unmatched"
    assert _order_status(client, session, order_id) == "PENDING_PAYMENT"
    # Kept, so the provider stops sending it again; unprocessed, because it is
    # not about anything this shop can act on.
    assert await _receipts(event_id) == [("paystack", False)]


async def test_a_notification_confirming_a_different_amount_is_not_believed(
    client: TestClient, paystack: str
) -> None:
    session, order_id, payment_id = await _paying_customer(client)
    payload, headers, event_id = _notification(
        secret=paystack, reference=payment_id, amount=100
    )

    response = _deliver(client, payload, headers)

    # Signed by Paystack and still refused: what the order was charged for is a
    # question this store answers from its own ledger.
    assert response.json()["outcome"] == "disputed"
    assert _order_status(client, session, order_id) == "PENDING_PAYMENT"
    assert await _payment_statuses(payment_id) == ["pending"]
    assert await _receipts(event_id) == [("paystack", False)]


async def test_a_failed_payment_notification_leaves_the_order_payable_again(
    client: TestClient, paystack: str
) -> None:
    session, order_id, payment_id = await _paying_customer(client)
    payload, headers, _ = _notification(
        secret=paystack, reference=payment_id, name="charge.failed"
    )

    response = _deliver(client, payload, headers)

    assert response.json()["outcome"] == "applied"
    assert await _payment_statuses(payment_id) == ["failed"]
    # The customer is not locked out of an order that was never charged.
    assert _order_status(client, session, order_id) == "PENDING_PAYMENT"
    reopened = _initiate(client, session, order_id)
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "pending"


async def test_a_webhook_and_a_verification_give_the_same_answer(
    client: TestClient, paystack: str
) -> None:
    """The customer's question and the provider's announcement settle one order
    once, whichever arrives first."""
    session, order_id, payment_id = await _paying_customer(client)
    payload, headers, _ = _notification(secret=paystack, reference=payment_id)

    delivered = _deliver(client, payload, headers)
    verified = client.post(
        f"{API}/payments/verify",
        cookies={COOKIE: session},
        json={"reference": payment_id},
    )

    assert delivered.json()["outcome"] == "applied"
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "paid"
    assert _order_status(client, session, order_id) == "PAID"
    assert await _payment_statuses(payment_id) == ["paid"]


# --- what a confirmed payment tells the store ---------------------------------


class UndeliverableSender(AbstractEmailSender):
    """An email provider that fails, however well the payment went."""

    provider = "undeliverable"

    def __init__(self) -> None:
        self.attempts = 0

    async def send(self, message: EmailMessage) -> EmailDelivery:
        self.attempts += 1
        raise ProviderNotConfiguredError("RESEND_API_KEY is not configured")


async def test_a_paid_order_is_announced_through_the_email_capability(
    client: TestClient,
) -> None:
    """The seam as built: a payment ending in a send, with no provider in sight.

    The sender is a double for the contract, so this passes with no Resend, no
    credentials and no network: what is proved is that confirming a payment
    reaches the email capability at all, and with the order in hand.
    """
    emails = RecordingSender()
    # Wired before the payment is started: from here on, this is the only
    # provider and the only newsdesk the endpoints have.
    _wire(
        client,
        gateway=_paystack_gateway(),
        notifier=PaidOrderNotifier(sender=emails, owner_email=OWNER_EMAIL),
    )
    try:
        session, order_id, payment_id = await _paying_customer(client)
        payload, headers, _ = _notification(secret=WEBHOOK_SECRET, reference=payment_id)
        delivered = _deliver(client, payload, headers)
    finally:
        client.app.dependency_overrides.pop(get_payment_service, None)

    assert delivered.json()["outcome"] == "applied"
    assert _order_status(client, session, order_id) == "PAID"
    assert [message.to for message in emails.calls] == [OWNER_EMAIL]
    body = emails.calls[0].text_body
    assert payment_id in body and "Ada Zoid" in body and "42,000.00 NGN" in body


async def test_an_email_that_cannot_be_sent_does_not_unpay_an_order(
    client: TestClient,
) -> None:
    """Notification is allowed to fail. A confirmed payment is not allowed to."""
    sender = UndeliverableSender()
    _wire(
        client,
        gateway=_paystack_gateway(),
        notifier=PaidOrderNotifier(sender=sender, owner_email=OWNER_EMAIL),
    )
    try:
        session, order_id, payment_id = await _paying_customer(client)
        payload, headers, event_id = _notification(
            secret=WEBHOOK_SECRET, reference=payment_id
        )
        response = _deliver(client, payload, headers)
    finally:
        client.app.dependency_overrides.pop(get_payment_service, None)

    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "applied"
    assert sender.attempts == 1
    assert _order_status(client, session, order_id) == "PAID"
    assert await _payment_statuses(payment_id) == ["paid"]
    assert await _receipts(event_id) == [("paystack", True)]

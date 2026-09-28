"""Paystack adapter.

Everything that is Paystack-specific lives here and nowhere else: the REST
endpoints, the kobo-denominated amounts, the ``{"status", "message", "data"}``
envelope, Paystack's error text, and the shape of a Paystack webhook signature.
The application sees only the payment contract, so a Paystack redirect is
indistinguishable from any other.

Three choices worth stating:

* One short-lived ``httpx.AsyncClient`` per call. Payment traffic is sparse, the
  overhead is negligible, and no connection state outlives the request.
* Unreachable is not the same as declined. A transport problem is reported as
  ``success=False`` with a ``PENDING`` status so the attempt stays open, while an
  explicit "no" from Paystack is reported as ``FAILED``.
* A notification whose signature does not match the body is refused here, before
  anyone downstream can read what it claims. An unverifiable payload is not
  evidence, and no amount of application logic can retrofit that.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

from app.domains.payments.domain.enums import (
    PaymentAction,
    PaymentStatus,
    WebhookKind,
)
from app.domains.payments.domain.gateway import (
    AbstractPaymentGateway,
    PaymentInitiation,
    PaymentRequest,
    PaymentVerification,
    RefundRequest,
    RefundResult,
)
from app.domains.payments.domain.webhooks import (
    AbstractWebhookAdapter,
    WebhookNotification,
)
from app.shared.exceptions import (
    ProviderNotConfiguredError,
    SignatureVerificationError,
    ValidationError,
)

DEFAULT_BASE_URL = "https://api.paystack.co"
#: Paystack answers "success" for a settled transaction.
_VERIFICATION_STATUSES = {
    "success": PaymentStatus.PAID,
    "failed": PaymentStatus.FAILED,
    "pending": PaymentStatus.PENDING,
}
#: The header Paystack signs its notifications into.
SIGNATURE_HEADER = "paystack-signature"
_TIMEOUT_SECONDS = 15.0

#: Paystack's event names, translated into what this shop does about them.
#: Anything not listed is still recorded; it simply asks for no action.
_EVENT_KINDS = {
    "charge.success": WebhookKind.PAYMENT_PAID,
    "payment.success": WebhookKind.PAYMENT_PAID,
    "charge.failed": WebhookKind.PAYMENT_FAILED,
    "payment.failed": WebhookKind.PAYMENT_FAILED,
    "charge.reversed": WebhookKind.PAYMENT_FAILED,
    "refund.successful": WebhookKind.REFUND_SETTLED,
    "refund.failed": WebhookKind.IGNORED,
}


def _to_smallest_unit(amount: Decimal) -> int:
    """Naira to kobo, which is the only unit Paystack accepts."""
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _from_smallest_unit(value: Any) -> Decimal | None:
    if not isinstance(value, int):
        return None
    return (Decimal(value) / 100).quantize(Decimal("0.01"))


class PaystackPaymentGateway(AbstractPaymentGateway, AbstractWebhookAdapter):
    """The payment contract, spoken to Paystack -- in both directions."""

    provider = "paystack"

    def __init__(
        self,
        *,
        secret_key: str,
        callback_url: str = "",
        webhook_secret: str = "",
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._callback_url = callback_url
        self._webhook_secret = webhook_secret
        self._base_url = base_url
        self._transport = transport

    async def create_payment(self, request: PaymentRequest) -> PaymentInitiation:
        payload: dict[str, Any] = {
            "email": request.email,
            "amount": _to_smallest_unit(request.amount),
            "currency": request.currency,
            "reference": request.reference,
            "callback_url": self._callback_url,
            "metadata": {
                "custom_fields": [
                    {
                        "display_name": "Order",
                        "variable": "order_reference",
                        "value": request.order_reference,
                    }
                ]
            },
        }
        try:
            status_code, body = await self._call("POST", "/transaction/initialize", payload)
        except httpx.HTTPError as exc:
            return PaymentInitiation(
                success=False,
                status=PaymentStatus.PENDING,
                transaction_reference=request.reference,
                message=f"Could not reach Paystack: {exc}",
            )

        if not _accepted(status_code, body):
            return PaymentInitiation(
                success=False,
                status=PaymentStatus.FAILED,
                transaction_reference=request.reference,
                message=_message(body) or "Paystack declined to start the payment.",
            )

        data = _data(body)
        authorization_url = data.get("authorization_url")
        if not isinstance(authorization_url, str) or not authorization_url:
            return PaymentInitiation(
                success=False,
                status=PaymentStatus.FAILED,
                transaction_reference=request.reference,
                message="Paystack returned no payment page.",
            )

        return PaymentInitiation(
            success=True,
            status=PaymentStatus.PENDING,
            # Paystack echoes our reference back; the access code is the handle
            # on the attempt until a gateway reference exists.
            transaction_reference=str(data.get("reference") or request.reference),
            provider_reference=_as_text(data.get("access_code")),
            checkout_url=authorization_url,
            action=PaymentAction.REDIRECT,
            message=_message(body),
        )

    async def verify_payment(self, reference: str) -> PaymentVerification:
        try:
            status_code, body = await self._call("GET", f"/transaction/verify/{reference}")
        except httpx.HTTPError as exc:
            return PaymentVerification(
                success=False,
                status=PaymentStatus.PENDING,
                transaction_reference=reference,
                message=f"Could not reach Paystack: {exc}",
            )

        if not _accepted(status_code, body):
            return PaymentVerification(
                success=False,
                status=PaymentStatus.PENDING,
                transaction_reference=reference,
                message=_message(body) or "Paystack did not answer the verification.",
            )

        data = _data(body)
        answer = str(data.get("status") or "").lower()
        return PaymentVerification(
            success=True,
            status=_VERIFICATION_STATUSES.get(answer, PaymentStatus.PENDING),
            transaction_reference=str(data.get("reference") or reference),
            provider_reference=_as_text(data.get("gateway_reference")),
            amount=_from_smallest_unit(data.get("amount")),
            message=_message(body),
        )

    async def refund_payment(self, request: RefundRequest) -> RefundResult:
        payload: dict[str, Any] = {}
        if request.amount is not None:
            payload["amount"] = _to_smallest_unit(request.amount)
        if request.reason:
            payload["merchant_note"] = request.reason

        try:
            status_code, body = await self._call(
                "POST", f"/transaction/{request.transaction_reference}/refund", payload
            )
        except httpx.HTTPError as exc:
            return RefundResult(
                success=False,
                status=PaymentStatus.PAID,
                transaction_reference=request.transaction_reference,
                message=f"Could not reach Paystack: {exc}",
            )

        data = _data(body)
        refused = str(data.get("status") or "").lower() == "failed"
        if refused or not _accepted(status_code, body):
            return RefundResult(
                success=False,
                status=PaymentStatus.PAID,
                transaction_reference=request.transaction_reference,
                message=_message(body) or "Paystack declined the refund.",
            )

        amount = _from_smallest_unit(data.get("amount"))
        return RefundResult(
            success=True,
            status=PaymentStatus.REFUNDED,
            transaction_reference=request.transaction_reference,
            provider_refund_reference=_as_text(data.get("id")),
            amount=amount if amount is not None else request.amount,
            message=_message(body),
        )

    # --- webhook intake ------------------------------------------------------

    def parse_notification(
        self, *, payload: bytes, headers: Mapping[str, str]
    ) -> WebhookNotification:
        """Verify Paystack's signature over the raw body, then read the event.

        The signature is the hex HMAC-SHA512 of the exact bytes Paystack sent,
        which is why the raw body is authenticated rather than a re-serialised
        copy of it: reordered keys or lost whitespace would break an otherwise
        honest notification.
        """
        if not self._webhook_secret:
            raise ProviderNotConfiguredError(
                "Paystack notifications cannot be verified without "
                "PAYSTACK_WEBHOOK_SECRET."
            )
        claimed = str(headers.get(SIGNATURE_HEADER) or "")
        digest = hmac.new(
            self._webhook_secret.encode(), payload, hashlib.sha512
        ).hexdigest()
        if not claimed or not hmac.compare_digest(claimed, digest):
            raise SignatureVerificationError("Paystack signature verification failed.")

        body = _read_json(payload)
        name, event_id = _event_fields(body)
        data = _data(body)
        return WebhookNotification(
            provider=self.provider,
            event_id=event_id,
            kind=_EVENT_KINDS.get(name, WebhookKind.IGNORED),
            reference=_reference_from(data),
            provider_reference=_text_or_none(data.get("gateway_reference")),
            amount=_from_smallest_unit(data.get("amount")),
            currency=_text_or_none(data.get("currency")),
            message=_text_or_none(data.get("failure_reason")) or _message(body),
        )

    async def _call(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> tuple[int, dict[str, Any]]:
        self._require_credentials()
        headers = {"Authorization": f"Bearer {self._secret_key}"}
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            transport=self._transport,
            timeout=_TIMEOUT_SECONDS,
        ) as client:
            response = await client.request(method, path, json=payload)

        body = response.json()
        if not isinstance(body, dict):
            body = {"message": str(body)}
        return response.status_code, body

    def _require_credentials(self) -> None:
        if not self._secret_key:
            raise ProviderNotConfiguredError(
                "Payment provider 'paystack' is selected but PAYSTACK_SECRET_KEY "
                "is not configured."
            )


def _accepted(status_code: int, body: Mapping[str, Any]) -> bool:
    """Paystack says ``status: true`` when it is happy, alongside a 2xx."""
    return 200 <= status_code < 300 and body.get("status") is True


def _data(body: Mapping[str, Any]) -> dict[str, Any]:
    data = body.get("data")
    return dict(data) if isinstance(data, Mapping) else {}


def _message(body: Mapping[str, Any]) -> str | None:
    message = body.get("message")
    return str(message) if isinstance(message, str) and message else None


def _as_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _read_json(payload: bytes) -> Mapping[str, Any]:
    """Parse an already-authenticated body. Unreadable is not unauthentic."""
    try:
        body = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "Paystack sent a notification this store cannot read"
        ) from exc
    if not isinstance(body, Mapping):
        raise ValidationError("Paystack sent a notification that is not an object")
    return body


def _event_fields(body: Mapping[str, Any]) -> tuple[str, str]:
    """Paystack's name and id for one notification.

    Newer integrations are sent ``{"event": "charge.success", "data": {...}}``;
    older ones nest the event as an object with its own ``id`` and
    ``description``. Both spellings are accepted. Without a name there is nothing
    to interpret, and where no event id is sent the id of the object being
    described stands in: an idempotency key only has to survive a redelivery
    unchanged, not mean anything to anybody else.
    """
    event = body.get("event")
    raw_data = body.get("data")
    data = raw_data if isinstance(raw_data, Mapping) else {}
    if isinstance(event, Mapping):
        name = str(event.get("description") or "").strip().lower()
        event_id = str(event.get("id") or "").strip()
    else:
        name = str(event or "").strip().lower()
        event_id = ""
    if not name:
        raise ValidationError("Paystack notification carries no event to interpret")
    if not event_id:
        described = data.get("id")
        if described is None:
            raise ValidationError("Paystack notification carries no event id to record")
        event_id = f"{name}:{described}"
    return name, event_id


def _reference_from(data: Mapping[str, Any]) -> str | None:
    """Our own reference, wherever Paystack chose to put it.

    Transaction events carry it on ``data``; a refund event nests the transaction
    one level down, so both are checked before concluding it is not about us.
    """
    nested = data.get("transaction")
    sources: list[Mapping[str, Any]] = [data]
    if isinstance(nested, Mapping):
        sources.append(nested)
    for source in sources:
        reference = source.get("reference")
        if isinstance(reference, str) and reference:
            return reference
    return None

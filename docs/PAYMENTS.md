# Zoid Backend — Payments

Payments live in the [`payments` domain](../app/domains/payments/) and depend on
a provider only through a **contract**. The application service speaks
"transaction" vocabulary end to end and never learns whether the money moved
through Paystack, Stripe or a test double — which is exactly what makes the
provider swappable and the flow testable without a live call.

## The contract

[`domain/gateway.py`](../app/domains/payments/domain/gateway.py) defines
`AbstractPaymentGateway`:

- `create_payment(PaymentRequest) -> PaymentInitiation`
- `verify_payment(reference) -> PaymentVerification`
- `refund_payment(RefundRequest) -> RefundResult`
- a `provider` label.

[`domain/webhooks.py`](../app/domains/payments/domain/webhooks.py) defines
`AbstractWebhookAdapter` — authenticate a raw provider payload into a
`WebhookNotification`. A real adapter (e.g. Paystack) implements **both**
contracts, so the composition hands the service one object for both directions.

Adapters are configuration-selected at the composition root
(`PAYMENT_PROVIDER`), never by business logic:
[`app/integrations/payments/`](../app/integrations/payments/) holds the Paystack
and Stripe adapters and the factory; the domain imports none of them.

## The purchase path

```
checkout (authenticated)            -> Order: PENDING_PAYMENT
POST /payments/initiate             -> Transaction opened, gateway.create_payment,
                                       customer gets a normalized redirect URL
   ... customer pays at the provider's hosted checkout ...
POST /payments/verify  (customer)   -> gateway.verify_payment confirms -> settle
      and/or                         ↕  (same settlement path)
POST /payments/webhooks/{provider}  -> signature-verified notification -> settle
                                       Order: PAID   +   owner email fired
```

Initiation is idempotent about a live payment: a pending transaction is reused,
a failed one is reopened, and an already-paid order **cannot** be paid again
(`ConflictError` / 409).

## Settlement — one path, two entrances

Both the customer's `verify` and the provider's webhook funnel through a single
private `_settle`: an order can only become paid by the same rules, whichever
announcement arrives first. A confirmation is refused if the provider reports a
**different amount** than the order asked for (`ConflictError`), and an
unreachable provider leaves the transaction `pending` — "unknown" is never
upgraded into success.

Confirmation cascades: on the one transition to `PAID` the order is marked paid
and the store owner is emailed. The email is a **notification, not part of
settlement** — it is allowed to fail (an unconfigured or unreachable provider)
without ever un-paying an order.

## Webhook idempotency

Handled in `PaymentService.handle_webhook`. The order of operations **is** the
guarantee:

1. **Authenticate** by signature. An inauthentic payload is refused (400) and is
   not even recorded — it is not evidence.
2. **Record** the event under its provider event-id *before* changing anything.
3. **Act once.** A second delivery of the same event-id is recognised as a
   `duplicate` and returns without touching a transaction, order, or stock level.

Outcomes a provider may receive: `applied`, `duplicate`, `ignored` (a kind the
app does not act on), `unmatched` (about a payment that isn't ours), or
`disputed` (contradicts the local ledger). A provider that is not the configured
one is answered `404` — Paystack's own signature does not buy it Stripe's
endpoint. A redelivery is always answered `200` so the provider stops retrying
news already acted on.

## Refunds

`POST /payments/refunds` (permission `manage:orders`). A local refund ledger
tracks what has already gone back, so a repeated refund can only ever reach the
outstanding balance; a full refund flips the payment to `REFUNDED`, a partial one
leaves it paid. Refunds already initiated are the only refunds acted on — one the
store did not start is not news to act on by guessing.

## Email notification

[`application/notifications.py`](../app/domains/payments/application/notifications.py)
builds the owner email from the order + transaction and sends it through the
`AbstractEmailSender` **contract** (selected by `EMAIL_PROVIDER`). The recipient
is `STORE_OWNER_EMAIL`; if it is not a valid address the notifier simply does not
send — a deployment choice, not a payment failure. See [SECURITY.md](SECURITY.md).

## Testing without a provider

Every payment test drives a real adapter with an `httpx.MockTransport` (so the
request it signs and the response it parses are exercised for real) or a scripted
`PaymentGateway` double, injected through the same dependency seam the container
uses — no live Paystack/Stripe/Resend call is ever made. See
`tests/api/payments/` and `tests/e2e/`.

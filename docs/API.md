# Zoid Backend — API Reference

The HTTP surface actually served by the application, as registered in
[`app/api/router.py`](../app/api/router.py). Every route is mounted under the
versioned prefix `API_V1_PREFIX` (default `/api/v1`) except the health probe.
The live, generated contract is available at `GET /openapi.json` when the app is
running and is the source of truth for request/response schemas; this document
describes intent, authentication and behaviour.

- Base URL (local): `http://localhost:8000/api/v1`
- Content type: `application/json`
- Auth: a JWT session in an `HttpOnly` cookie named `COOKIE_NAME`
  (default `app_session_id`). See [SECURITY.md](SECURITY.md).

## Error contract

Domain errors are raised as framework-free types in `app.shared.exceptions` and
translated to HTTP by a single handler in `app/main.py`. A client therefore sees
a consistent `{"detail": ...}` shape and never a stack trace.

| Exception | HTTP | Meaning |
| --- | --- | --- |
| `ValidationError` | 422 | Input failed a business rule |
| `AuthenticationError` | 401 | No valid session |
| `AuthorizationError` | 403 | Authenticated but not permitted |
| `NotFoundError` | 404 | Resource absent or not yours |
| `ConflictError` | 409 | Stateful clash (double-pay, duplicate) |
| `RateLimitError` | 429 | Too many requests |
| `SignatureVerificationError` | 400 | Bad webhook signature |
| `ProviderNotConfiguredError` | 501 | Selected provider lacks credentials |

## Health

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/health` | none | Liveness probe, outside the version prefix. |

## Auth

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/auth/signup` | none | Creates a customer and opens a session (201). |
| POST | `/auth/login` | none | Verifies credentials, sets the session cookie. Rate-limit friendly. |
| POST | `/auth/logout` | session | Clears the session cookie. |
| GET | `/auth/me` | session | The current principal's identity. |

## Users (profile)

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/users/me` | session | The caller's own profile. |
| PUT | `/users/me` | session | Update the caller's own profile. |

## Catalog (public, read-only)

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/products` | none | Paginated active products (`page`, `page_size`). Ordered oldest-first. |
| GET | `/products/{identifier}` | none | One product by slug or numeric id, with variants, stock and images. |
| GET | `/categories` | none | Product categories. |

There is no public write endpoint for the catalog; products are created/updated
only through the admin surface below.

## Cart

Public for guests (identified by the `guest_cart_id` cookie) and scoped to the
session for signed-in shoppers. Every operation resolves the cart from the
request — never a caller-supplied cart id — so cross-cart access is impossible.

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/cart` | none / session | The caller's cart; issues the guest cookie for anonymous carts. |
| POST | `/cart/items` | none / session | Add `{product_slug, size, quantity}`. |
| PATCH | `/cart/items/{item_id}` | none / session | Change a line's quantity. |
| DELETE | `/cart/items/{item_id}` | none / session | Remove a line. |
| POST | `/cart/merge` | session | Fold a guest cart into the now-authenticated user's cart and clear the guest cookie. |

## Wishlist

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/wishlist` | session | The caller's saved products. |
| POST | `/wishlist/items` | session | Save a product by slug. |
| DELETE | `/wishlist/items/{product_slug}` | session | Remove a saved product. |

## Orders

Checkout is authenticated and reads the caller's **server-side** cart; totals
are computed from authoritative server prices, never from the client.

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/orders` | session | Check out the cart into a new order (`201`). New orders start `PENDING_PAYMENT`. |
| GET | `/orders` | session | The caller's orders, newest first. |
| GET | `/orders/{order_id}` | session | One of the caller's orders (someone else's is 404). |

## Payments

Customers pay for their own orders; refunds are an order-management permission.
No endpoint here names a provider — the response is the normalized contract. See
[PAYMENTS.md](PAYMENTS.md).

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/payments/initiate` | session | Open a payment for a pending order through the gateway. |
| POST | `/payments/verify` | session | Ask the provider to confirm a payment; the client's word is not accepted. |
| POST | `/payments/refunds` | `manage:orders` | Refund a settled payment, in part or in full. |
| POST | `/payments/webhooks/{provider}` | signature | Provider notification, authenticated by signature rather than session. |

## Admin

The whole `/admin` surface is guarded at the **router level** by `require_admin`
so a route added later is protected by default. A non-admin calling these
directly — bypassing any frontend — gets 401 (no session) or 403 (wrong role).

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/admin/dashboard` | admin | Store-wide metrics. |
| POST | `/admin/products` | admin | Create a product. |
| PATCH | `/admin/products/{product_id}` | admin | Edit a product (including reversible `is_active`). |
| POST | `/admin/products/{product_id}/stock` | admin | Restock a variant. |
| GET | `/admin/orders` | admin | The order book. |
| GET | `/admin/users` | admin | The customer list. |

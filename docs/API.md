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
| GET | `/products` | none | Paginated active products (`page`, `page_size`). Oldest-first by default; see query parameters below. |
| GET | `/products/{identifier}` | none | One product by slug or numeric id, with variants, stock and images. |
| GET | `/categories` | none | Product categories. |

`GET /products` query parameters (all optional, combinable):

| Parameter | Meaning |
| --- | --- |
| `q` | Forgiving text search over name, category, colour, style and tone; typos are tolerated (`liverpol` finds Liverpool). Results are ranked by relevance. |
| `category` | Category slug. |
| `style`, `color`, `size` | Case-insensitive exact match (`size` = an offered size). |
| `min_price`, `max_price` | Inclusive price range. |
| `bestseller`, `special`, `new_arrival`, `on_sale` | Boolean flags. |
| `sort` | `relevance` (default when `q` is set), `oldest` (default otherwise), `newest`, `price_asc`, `price_desc`, `name`. |

Product responses carry `original_price`, `discount_percent` (computed from the two
prices, never stored) and `is_new_arrival`. `total`/`total_pages` count the filtered set.

There is no public write endpoint for the catalog; products are created/updated
only through the admin surface below.

## Cart

Public for guests (identified by the `guest_cart_id` cookie) and scoped to the
session for signed-in shoppers. Every operation resolves the cart from the
request — never a caller-supplied cart id — so cross-cart access is impossible.

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/cart` | none / session | The caller's cart; issues the guest cookie for anonymous carts. |
| POST | `/cart/items` | none / session | Add `{product_slug, size, quantity, customization?}`. `customization` is optional free text (max 100 chars, e.g. `"Name: EDDY, #10"`). Lines merge only when product, size **and** text (trimmed, case-insensitive) all match. |
| PATCH | `/cart/items/{item_id}` | none / session | Change a line's quantity. |
| DELETE | `/cart/items/{item_id}` | none / session | Remove a line. |
| POST | `/cart/merge` | session | Fold a guest cart into the now-authenticated user's cart and clear the guest cookie. |

## Wishlist

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/wishlist` | session | The caller's saved products. |
| POST | `/wishlist/items` | session | Save a product by slug. |
| DELETE | `/wishlist/items/{product_slug}` | session | Remove a saved product. |

## Delivery

Delivery is priced by the **server** from the shop's rate table; a request names
*where* the order should go, never an amount.

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/delivery/quote` | none | The fee for a destination. A place the shop does not serve is a normal answer (`support_required: true`, `fee: null`), not an error. |

Request (`option` decides which other fields are needed):

| `option` | Required fields | Notes |
| --- | --- | --- |
| `standard` | `address`, `city`, `state` — **or** `university` + `hostel_room` | Hand delivery. Lagos, Ogun and Port Harcourt only. A campus delivery is flagged `is_student`. |
| `express` | `address`, `city`, `state` | Prioritised hand delivery, same area. |
| `pickup` | `state`, `terminal` | Free, any state. A terminal the shop has not verified is accepted with `terminal_pending: true`. |
| `enquiry` | — | Never priced (`support_required: true`); cannot be checked out. |

The most specific matching rate wins: terminal, then university, then city, then
state. With no matching rate there is no price, never a guess. Rates are loaded with
`python -m app.cli.seed_delivery` (see the README); with an empty table every place
answers `support_required`.

## Orders

Checkout is authenticated and reads the caller's **server-side** cart; every amount
is computed by the server from authoritative prices, never from the client:
`total = subtotal (goods) + customization_total + delivery.fee`. Personalisation is
charged per unit (`CUSTOMIZATION_FEE`, default 2,000) on products whose style is
`Jersey`, and is snapshotted on each line as `customization_fee`.

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/orders` | session | Check out the cart into a new order (`201`). Body: `contact_name`, `contact_email`, `contact_phone`, `delivery` (see above), optional `notes`. A destination that is not priced (unserved place, `enquiry`) is refused with `422` before any stock is reserved. New orders start `PENDING_PAYMENT`. |
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

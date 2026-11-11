# Frontend integration guide

How to replace the storefront's local stores (`localStorage`, `catalog.ts`,
`ordersStore.ts`, the in-browser admin) with this API. The full endpoint reference is
[API.md](API.md); this page is the order to wire things in and the traps to avoid.
Everything below is exercised by the Postman suite in [`../postman`](../postman).

## 1. Connect

| Setting | Value |
| --- | --- |
| Base URL | `http://localhost:8000/api/v1` (add a `VITE_API_URL`; none exists today) |
| Every request | `credentials: "include"` (axios: `withCredentials: true`) — the session is an `HttpOnly` cookie, so there is no token to store |
| Backend CORS | `CORS_ORIGINS=http://localhost:3000` (Vite's port). Add the deployed origin, exactly, when you deploy |
| Production | Different sites for frontend and API need `COOKIE_SAMESITE=none` + `COOKIE_SECURE=true` (HTTPS); same site (e.g. `app.x.com` + `api.x.com`) works with `lax` and `COOKIE_DOMAIN=.x.com` |

Conventions: ids are integers; products are addressed by **slug**; money is a
**decimal string** (`"58500.00"`, never a number); lists are paged as
`{items, page, page_size, total, total_pages}`; errors are `{"detail": "..."}` (422s
add `errors: [...]` per field). Format money for display with `formatNaira(Number(x))`.

## 2. Accounts (`AuthContext`)

1. `POST /auth/signup` creates the account **but does not sign in** (the prototype's
   `signup()` did) — call `POST /auth/login` straight after.
2. `POST /auth/login` sets the cookie. `GET /auth/me` restores the session on page load
   (401 = signed out). `POST /auth/logout` clears it.
3. `GET/PUT /users/me` for the profile page. Orders and wishlist are no longer part of
   the user object: fetch them separately.
4. After login, if the visitor had a guest cart, call `POST /cart/merge` once.

## 3. Catalog (`catalog.ts`, Home, Collection, ProductDetail, search)

`GET /products` (paged, `q` search, filters, `sort`), `GET /products/{slug}`,
`GET /categories`. The forgiving search (typos) is now server-side via `q`.

| Prototype field | API field |
| --- | --- |
| `price: "₦58,500"` | `price: "58500.00"` (number-format it) |
| `originalPrice`, `discountBadge` | `original_price`, `discount_percent` (computed; render `${n}% OFF`) |
| `isBestseller`, `isSpecial`, `isNewArrival` | `is_bestseller`, `is_special`, `is_new_arrival` |
| `fitNote` | `fit_note` |
| `gallery[{label,image,treatment}]` | `gallery[{view,url}]`, views `front`/`back`/`detail` |
| `stock: {M: 8}` | `stock: {"M": 8}` (units **available**, i.e. not reserved) |
| `image` | `image` (the first picture) |

Image paths are the prototype's own (`/manus-storage/...`, `/jerseys/...`), so the
frontend must still serve them until you host images elsewhere and run
`seed_catalog --image-base-url`.

## 4. Cart and wishlist (`ShopContext`, `toggleWishlist`)

The cart now lives on the server and works for guests (a `guest_cart_id` cookie).
`GET /cart`, `POST /cart/items {product_slug, size, quantity, customization?}`,
`PATCH/DELETE /cart/items/{id}` (**line ids**, not slugs). The prototype's `customization`
string maps 1:1; lines with different text stay separate. Totals come back from the
server; do not recompute them. Wishlist: `GET /wishlist`, `POST /wishlist/items
{product_slug}`, `DELETE /wishlist/items/{slug}` (login required).

## 5. Checkout and payment (`Checkout.tsx`, `OrderReview.tsx`)

```
POST /delivery/quote      -> show the fee (or "ask us") as the customer fills the form
POST /orders              -> {contact_*, delivery{...}, notes}  => order, status PENDING_PAYMENT
POST /payments/initiate   -> {order_id}                         => next_action.url
   redirect the browser to next_action.url (the provider's page)
   the provider returns the customer to PAYMENT_RETURN_URL
POST /payments/verify     -> {reference}                        => status paid | pending | failed
GET  /orders/{id}         -> payment_status, payment_reference, fulfillment_status
```

* **Never send an amount.** Delivery, personalisation (₦2,000 per personalised
  *Jersey*) and goods are priced by the server; `total = subtotal + customization_total
  + delivery.fee`, and that exact total is what the provider charges.
* The `delivery` block maps to the form: `option` is `standard` | `express` | `pickup`
  (the prototype's "enquiry/WhatsApp" is **not** a checkout: a quote answers
  `support_required: true` — show the WhatsApp link). Home delivery needs
  `address, city, state`; campus delivery needs `university` + `hostel_room`
  (`is_student` comes back true); pickup needs `state` + `terminal`.
* A place the shop does not serve is `422` at `POST /orders` (nothing is reserved);
  offer terminal pickup instead.
* Remove the prototype's local "Paid" marking and its "simulate payment failure"
  button. Use `verify` on return, and the `/payment-failed` route when `status` is not
  `paid`. A `409` from verify means the provider confirmed a different amount: do not
  show success.
* Orders carry two independent statuses: `payment_status` (`pending|paid|cancelled`)
  and `fulfillment_status` (`processing|in_transit|delivered`). The prototype's
  "Processing / In Transit / Delivered" is the second; only show it for paid orders.
* `GET /orders` returns full orders with lines, so Profile needs one request.
* Order identifiers: show `reference` (`ZD-XXXXXXXX`), not `id`.

## 6. Admin (`Admin.tsx`)

Sign in through the normal login with an admin account (create the first one with
`python -m app.cli.create_admin`). Every `/admin` route is 401 without a session and
403 for customers; the frontend hiding is cosmetic.

| Admin screen | Endpoint |
| --- | --- |
| Inventory list (incl. hidden) | `GET /admin/products` (filters `q`, `active`, `stock`, …) |
| Add product / image upload | `POST /admin/products/images` (raw bytes, returns `url`) then `POST /admin/products` |
| Edit price / flags / sale | `PATCH /admin/products/{id}` (`original_price: null` ends a sale) |
| Remove a product | `PATCH ... {is_active: false}` — **archive, not delete** (hidden everywhere; reversible) |
| Stock +/- per size | `PATCH /admin/products/{id}/stock {size, delta | set_to}`; `POST .../stock` only adds |
| Orders, filters, search | `GET /admin/orders?payment_status&fulfillment_status&delivery_option&q&date_from&date_to` |
| Set In Transit / Delivered | `PATCH /admin/orders/{id}/fulfillment {status}` |
| Confirm a pickup terminal | `PATCH /admin/orders/{id}/fulfillment {terminal}` |
| Weekly/accounting/operations cards | `GET /admin/analytics?date_from&date_to` |
| Story moderation | `GET /admin/archives?status=pending`, `PATCH /admin/archives/{id}/moderation` |

Analytics differ from the prototype on purpose: **revenue counts only paid orders**
(the prototype counted any non-cancelled order); unpaid money shows as `outstanding`.
Refunds are not yet netted off.

## 7. Archives page

`GET /archives` (approved only), `POST /archives` (login required; starts `pending`),
`GET /archives/mine`, `PATCH/DELETE /archives/{id}` (own stories; an edit sends it back
for review). **Not provided:** likes and comments.

## 8. Decisions that are yours

1. **Signup does not sign in.** Easy to flip server-side if you want the prototype's
   behaviour; today the frontend calls login right after.
2. **Personalisation is stored for any product but charged only on `Jersey` style**
   (as the prototype did). Say if Heritage/Archive jerseys should be charged too.
3. **"Enquiry" delivery cannot be checked out** (no fee to charge); it is a WhatsApp
   hand-off. Say if you want to take such orders and set the fee afterwards.
4. **Discount badges are computed.** One prototype badge disagreed with the maths
   (Juventus: "18% OFF"; 63,500 vs 78,000 is 19%).
5. **Archived, not deleted.** There is no product delete.
6. **Seed data.** `seed_catalog` loads the prototype's 21 products; prices/stock are
   the shop's to change afterwards (a re-seed never overwrites stock).

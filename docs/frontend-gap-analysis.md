# Frontend ↔ Backend Gap Analysis

Compares what the storefront (`eddy-mfon/Zoid`, commit `ee9b5c5`) needs against what
the backend serves today (31 operations, verified from `/openapi.json`; 680 tests pass).

**Key fact:** the frontend never calls an API. Products, auth, cart, wishlist, orders and
the whole admin area live in `localStorage` / in-memory state. "Integration" means
replacing those local stores with API calls. `axios` is installed but unused.

Status key: ✅ matches · ⚠️ partial · ❌ missing. "Plan #" refers to `docs/backend_implement.md`.

## 1. Already aligned

| Area | Evidence |
| --- | --- |
| Money as decimal strings | Plan #1 done: `serialize_money` → `"58500.00"` |
| Auth endpoints | signup / login / logout / me exist; cookie session (`HttpOnly`) |
| Cart keyed by `product_slug + size` | Same identity the frontend's `addToBag` uses |
| Guest cart + merge on login | `guest_cart_id` cookie, `POST /cart/merge` |
| Wishlist by slug | Same as frontend `toggleWishlist(slug)` |
| Product detail fields | `tone, style, color, fit, fit_note, details, delivery, gallery, sizes, stock, is_bestseller, is_special` all present |
| CORS / ports | Default allowed origin `http://localhost:3000` = Vite dev port; API on `:8000` |

## 2. Gaps (backend work), in plan order

| Plan # | Gap | Frontend needs | Backend today |
| --- | --- | --- | --- |
| 2 | Catalog contract | `originalPrice`, `discountBadge` (should be *computed*), `isNewArrival`; search (typo-tolerant), filters (style/colour/size), sorting | ❌ no `original_price`, `is_new_arrival`; `GET /products` only has `page`/`page_size` |
| 3 | Product images | Admin uploads an image file / URL | ❌ no upload endpoint (storage adapters exist but no route) |
| 4 | Jersey customization | Name/number text on a bag line; lines merge only if text matches | ❌ `AddItemRequest` has no `customization` |
| 5 | Delivery & order shape | Delivery method (standard / express / pickup / unlisted), fee, student rate, GUO terminal pickup, customization cost, state/city eligibility | ❌ `CreateOrderRequest` is contact + `address_line` + `city_state` + `notes` only; no fee, no `POST /delivery/quote`; order total = item subtotal |
| 6 | Order lifecycle | Customer sees `Processing / In Transit / Delivered`; admin changes it | ⚠️ enum has `PROCESSING/SHIPPED/DELIVERED`, but ❌ no admin endpoint to change status; wording differs (`SHIPPED` vs "In Transit") |
| 7 | Admin operations | List all products incl. hidden, stock up *and down*, hide/unhide, dashboard with revenue, date filter, best sellers, trends | ⚠️ create/edit/restock-up only; dashboard has counts, no revenue or trends; ❌ no admin product list |
| 8 | Archives | "Tell your story" form, public approved list, admin moderation | ❌ nothing |
| 9 | Catalog seed | The 22 products in `catalog.ts` | ❌ DB is empty (`GET /products` → `total: 0`) |
| 10 | Local config | Frontend `:3000` ↔ backend `:8000` cookies | ✅ defaults already right; production cross-site cookies need `SameSite=None; Secure` + exact `CORS_ORIGINS` |

## 3. Gaps not in the plan (new findings)

1. **No way to create the first admin.** Roles are seeded (`customer`, `admin`), signup always
   makes a customer, and there is no script/CLI/endpoint to promote anyone. Every `/admin/*`
   route is therefore unreachable on a fresh deploy. Needs a small, safe bootstrap
   (e.g. a CLI command or env-driven first-admin seed).
2. **Payment is simulated in the frontend.** `OrderReview.tsx` marks orders `paymentStatus: "Paid"`
   locally and has a "DEV: Simulate payment failure" button. The real flow is
   `POST /orders` → `POST /payments/initiate` → redirect → `POST /payments/verify`. The frontend
   already has `/payment-failed` routes, and `PAYMENT_RETURN_URL` defaults to `/checkout`.
3. **Order identifiers differ.** Frontend uses `"ZD-A7K2M1"` strings; backend has integer `id` plus
   a `reference`. Frontend must display/use `reference`.
4. **`GET /orders` returns summaries without items.** The profile page lists items per order;
   plan #6 covers this ("without one request per order").

## 4. Frontend changes required (listed only — `Zoid` is not edited)

Replace local stores with API calls: `AuthContext` (login/signup/logout/me, currently fake),
`ShopContext` (server cart), wishlist, `catalog.ts` (fetch products), `ordersStore.ts` (orders),
`Checkout`/`OrderReview` (real order + payment redirect), `Admin.tsx` (admin API), `Archives.tsx`.
Requests must send `credentials: "include"`. Prices arrive as decimal strings, not `"₦58,500"`.
Add a `VITE_API_URL` setting; none exists today.

## 5. Testing constraints

- Payment initiate/verify needs a provider. With no keys the API returns `501`; tests use mocks.
  Real end-to-end payment testing needs Paystack **test** keys.
- Email (Resend) and image storage (Cloudinary/S3) likewise need credentials or mocks.
- Postman runs will use a throwaway local database; admin routes need the bootstrap in §3.1.

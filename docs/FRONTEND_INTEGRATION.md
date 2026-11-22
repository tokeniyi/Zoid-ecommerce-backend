# Zoid frontend API integration

This guide covers the storefront on [frontend main at `5fd2a105e12400e8a40193a46ba4768384fada50`](https://github.com/eddy-mfon/Zoid/tree/5fd2a105e12400e8a40193a46ba4768384fada50) and the API on [backend main at `b13fde9089c676169e8062e5f12faf8b15040ff8`](https://github.com/tokeniyi/Zoid-ecommerce-backend/tree/b13fde9089c676169e8062e5f12faf8b15040ff8). Both repositories were readable. At these revisions, no storefront screen calls the Zoid API. The mismatches below are between the prototype's local types and the API contracts. The frontend's Express entry point serves the SPA, and the Vite storage proxy and unused Maps/OAuth helpers are separate from the commerce API.

## Setup

| Setting | Verified in source | Integration and deployment |
| --- | --- | --- |
| API URL | README runs Uvicorn on `http://localhost:8000`. The default `API_V1_PREFIX` is `/api/v1`. `/health`, `/docs` and `/openapi.json` are at the API root. | Add `VITE_API_URL=http://localhost:8000/api/v1` in the frontend repo root (Vite `envDir`). Supply the deployed HTTPS API URL including its prefix at build time. The production URL and origins are unverified. |
| Browser | Vite starts on port 3000 and may choose another port. Backend defaults are `CORS_ORIGINS=http://localhost:3000` and `CORS_ALLOW_CREDENTIALS=true`. | Add each actual frontend origin, including scheme and port, to `CORS_ORIGINS`. Use `credentials: "include"` on reads, writes and sign-in (Axios `withCredentials: true`). Use `localhost` consistently in local URLs. |
| Cookies | `app_session_id` is HttpOnly by default, host-only unless `COOKIE_DOMAIN` is supplied, with `SameSite=Lax` and a seven-day default lifetime. `guest_cart_id` is HttpOnly, lasts 30 days and is always `SameSite=Lax`. | Deploy storefront and API on the same site over HTTPS, or proxy the API through the storefront origin, so both cookies work. Use `COOKIE_SECURE=true` in production. A truly cross-site session requires `COOKIE_SAMESITE=none` and HTTPS, and browser third-party-cookie rules still apply. That setting leaves the guest cart's Lax policy in place. |
| Data and providers | PostgreSQL stores users, products, inventory, carts, orders and stories. Checkout reads active delivery rates. Paystack, Cloudinary and Resend are default provider selections. | Run migrations, seed or load real catalog and delivery data, and provision an admin using the README commands. Set a production `JWT_SECRET`, payment credentials and webhook secret, `PAYMENT_RETURN_URL`, and public product media hosting. Configure storage credentials for uploads and email credentials if order notifications are needed. Keep all provider secrets server-side. |

[Backend setup](../README.md) · [Settings](../app/config/settings.py) · [CORS](../app/security/protection/cors.py) · [Session cookie](../app/security/authentication/service.py) · [Guest cookie](../app/domains/cart/api/deps.py) · [Vite configuration][vite]

Use a shared request wrapper. Join the base and route once, send JSON with `Content-Type: application/json` for JSON bodies, and handle `204` before parsing JSON. Upload uses raw bytes. The browser handles cookies. Set loading, empty and error states explicitly and keep the previous confirmed state when a write fails. App errors use `{"detail":"..."}`. Request validation returns `422` with `detail` and `errors: [{loc,msg,type}]`. Business-rule `422` can carry only `detail`. Session routes generally return `401` when signed out, admin routes `403` for non-admins, and scoped resources can return `404` for a different owner's ID.

Paths below are relative to the version prefix. Rows without an input take no body or query. IDs are integers unless a slug or reference is specified. Money responses are decimal strings in major units. Use `Number(amount)` for display formatting with `formatNaira` when the currency is NGN. The prototype's digit-stripping parser would turn `"58500.00"` into `5850000`. Paginated responses are `{items,page,page_size,total,total_pages}`, with `page=1`, `page_size=20` and a maximum size of 100. Reset the page when filters change and use `total` for the filtered count.

[Router registration](../app/api/router.py) · [Error handler](../app/main.py) · [Request validation](../app/security/protection/request_validation.py)

## Sign in, sign up and profile

[Auth][auth] and the dormant [AuthModal][authmodal] call synchronous methods in [AuthContext][authctx]. Login and signup ignore the password and generate a fake user in `zoid_user_session_v1`. Change the methods to promises, await them before routing or showing success, and remove quick demo login. The form currently accepts six characters on signup. Require at least eight.

| Request | Access and input | Success and errors |
| --- | --- | --- |
| `POST /auth/signup` | Public. `{name,email,phone?,password}`. Email must be valid, password 8–128 characters. Combine first/last name as the form does today. | `201` user, followed by a separate login. `409` duplicate email, `422` invalid input. |
| `POST /auth/login` | Public. `{email,password}`. | `200` user and session cookie. `401` invalid credentials. |
| `GET /auth/me` | Session. | `200` user. Treat `401` as signed out and handle other errors separately. |
| `POST /auth/logout` | Callable with or without a session. | `200 {"detail":"Logged out."}` and clears the session cookie. |
| `GET /users/me` | Session. | `200` user profile. |
| `PUT /users/me` | Session. `{name?,phone?}`. Omit fields to retain them. | `200` updated profile. `422` invalid input or blank name. |

User shape: `{"id":12,"name":"Ada Okafor","email":"ada@example.com","phone":"+2348012345678","role":"customer","created_at":"2026-11-10T10:00:00Z"}`. Map `created_at` to `createdAt` and allow a nullable phone. Keep role from the response for navigation and remove embedded `orders` and `wishlist` from the session model. Restore with `GET /auth/me` before evaluating route guards. On successful login, call `POST /cart/merge` before returning the shopper to checkout. After logout clear account-specific UI data and load the guest cart. Retain a merge failure state separately from login. `Profile` currently displays contact info only. Use `GET /users/me` there, and use `PUT` if adding an edit form. Email and password editing have no route here.

[Auth routes](../app/domains/auth/api/router.py) · [Auth schemas](../app/domains/auth/api/schemas.py) · [Auth service](../app/domains/auth/application/service.py) · [Profile service](../app/domains/users/application/service.py) · [Profile screen][profile]

## Home, Collection, product details and search

| Screen and current behavior | Wiring |
| --- | --- |
| [Home][home] builds bestseller/special shelves and inline search from [catalog.ts][catalog]. Some hero and editorial visuals are hardcoded. | Fetch `GET /products?bestseller=true&page_size=4` for the featured shelf and `GET /products?special=true` for specials. Keep editorial copy separate and resolve shoppable links by real slug. |
| [Collection][collection] filters the static array by style, color and offered size, shows local counts, ranks bestsellers then specials, and builds club/national/gym and sale/arrival rails. | Read categories for slug filters and use `style=Gym+Kit`, `bestseller=true` and `new_arrival=true` as appropriate. Use category slug for National Teams or Curated Jersey. The UI's Special filter means `isSpecial OR style=Heritage OR style=Special` and its special rail includes discounted items. API filters combine with AND. To preserve these rules, union matching queries by `id` and paginate/rank the combined set, or simplify the UI filters. Sorting each returned page would only rank within that page. |
| [CentralSearchModal][search] and Home use synchronous fuzzy `searchProducts`. | Use debounced `GET /products?q=liverpol&page_size=8`, cancel or ignore stale responses, use returned ordering and link by `slug`. |
| [ProductDetail][detail] reads `productBySlug`, local gallery/stock, and local related products; add-to-bag and save use context state. | Fetch `GET /products/{slug}` for the selected item, use a filtered products request for related items and exclude the current slug. Use the cart and wishlist endpoints below for mutations. Render load, unavailable (404) and request-failed states. |

| Request | Access and input | Success and errors |
| --- | --- | --- |
| `GET /products` | Public. Pagination plus `q` (max 100), `category` (slug), exact case-insensitive `style`, `color`, `size`, inclusive `min_price` and `max_price`, flags `bestseller`, `special`, `new_arrival`, `on_sale`. Sort `relevance`, `oldest`, `newest`, `price_asc`, `price_desc`, `name`. Defaults to relevance with a search and oldest otherwise. | `200` paginated product summaries. `422` invalid query. Zero results use an empty array. |
| `GET /products/{identifier}` | Public, slug or numeric ID. | `200` product detail; `404` absent or hidden. |
| `GET /categories` | Public. | `200` array of `{id,name,slug}`. The product's `category` is a display name. |

Example product summary (seed-like values):

```json
{"id":1,"slug":"ac-milan-2526","name":"AC Milan / 25—26","category":"CURATED JERSEY","price":"58500.00","original_price":"68000.00","discount_percent":14,"currency":"NGN","image":"/manus-storage/ac-milan-2526_b917ea29.jpg","sizes":["M","L","XL"],"stock":{"M":8,"L":5,"XL":2},"is_bestseller":true,"is_special":false,"is_new_arrival":false}
```

Use separate summary and detail types. Details add `gallery[{view,url}]`, `tone`, `style`, `color`, `fit`, `fit_note`, `details` and `delivery`. Map gallery `front/back/detail` to the UI's Front/Back/Close-up and image URL, map `fit_note` to `fitNote`, and map snake-case flags to camel case. Use `discount_percent` to build sale text and handle null originals and images. `stock[size]` is available quantity after reservations. A size filter means offered in that size, even if sold out. Root-relative media from seeding belongs on the storefront (`client/public`) or use `seed_catalog --image-base-url` with a real host. Render a placeholder for missing media.

[Catalog routes](../app/domains/products/api/router.py) · [Schemas](../app/domains/products/api/schemas.py) · [Product persistence](../app/infrastructure/persistence/sqlalchemy/repositories/product.py) · [Seed catalog](../app/cli/seed_catalog.py)

## Bag and wishlist

[ShopContext][shopctx] and [CartDrawer][cartdrawer] currently mutate a React array of full product objects, identify entries by slug/size/customization, and compute counts and prices locally. Hydrate with `GET /cart`, then replace cart state with each returned snapshot. Use `items[].id` as the React key and mutation ID. Map `product_slug → slug`, `product_name → name`, `unit_price → price display` and consume `line_total`, `count` and `total`. The cart total covers goods. Use the order response for final personalization and delivery charges.

| Request | Access and input | Success and errors |
| --- | --- | --- |
| `GET /cart` | Guest or session. | `200` cart, issues guest cookie for an anonymous cart. |
| `POST /cart/items` | Guest or session. `{product_slug,size,quantity?,customization?}`. Quantity defaults to 1 (1–99 in the body), text defaults to empty (max 100). | `200` cart. Same product, size and trimmed case-insensitive customization coalesce. `404` missing product, `422` bad size or body. |
| `PATCH /cart/items/{item_id}` | Guest or session. `{quantity}` from 1 to 99. | `200` cart. Unknown line is `422`. |
| `DELETE /cart/items/{item_id}` | Guest or session. | `200` cart. Removing an absent line returns the cart. |
| `POST /cart/merge` | Session, with the existing guest cookie when present. | `200` signed-in cart, merges quantities and clears the guest cookie. Without a cookie it returns the user's cart. A stale guest cookie can return `404`; load `GET /cart` and explain the draft could not be merged. |
| `GET /wishlist` | Session. | `200` `{items,count}`. |
| `POST /wishlist/items` | Session. `{product_slug}`. | `200` updated wishlist; `404` missing product. |
| `DELETE /wishlist/items/{product_slug}` | Session. | `200` updated wishlist; `404` missing saved item. |

Example add item request and response:

```http
POST /api/v1/cart/items
Content-Type: application/json

{"product_slug":"ac-milan-2526","size":"M","quantity":1,"customization":"Name: ADA, #10"}
```

```json
{"items":[{"id":31,"product_slug":"ac-milan-2526","product_name":"AC Milan / 25—26","size":"M","quantity":1,"unit_price":"58500.00","line_total":"58500.00","image":"/manus-storage/ac-milan-2526_b917ea29.jpg","currency":"NGN","customization":"Name: ADA, #10"}],"count":1,"total":"58500.00","currency":"NGN"}
```

[Home][home], [Navbar][navbar], [Collection][collection], [ProductDetail][detail] and [Profile][profile] currently save slugs through `AuthContext` and look cards up in the demo catalog. Use wishlist items directly (`id,product_slug,product_name,image,price,currency`), derive the saved-slug set from them and prompt for sign-in on guest writes. Keep a per-line pending state and refresh after ambiguous write failures. Stock is checked at order creation, so adding a bag item does not guarantee availability.

[Cart routes](../app/domains/cart/api/router.py) · [Cart service](../app/domains/cart/application/service.py) · [Wishlist schemas](../app/domains/wishlist/api/schemas.py) · [Wishlist service](../app/domains/wishlist/application/service.py)


## Checkout, review and payment return

[Checkout][checkout] uses `deliveryEligibility.ts`, local location dictionaries, and hardcoded fees. It saves `zoid_checkout_*` draft, bag and amount snapshots. [OrderReview][review] constructs two local order records, marks the admin record Paid and clears the bag. The failure pages reuse the review component and simulate retry. Replace them with one server order and a payment status driven by verification.

| Form choice | `delivery` request fields |
| --- | --- |
| Standard, given address | `option: "standard"`, `address`, `city` and `state` from the standard fields. |
| Standard, university | `option: "standard"`, `university` from `schoolName` and `hostel_room` from `hostelAndRoom`. Supply separate `city` or `state` only when known. The server can infer state from a matching campus rate. |
| Express | `option: "express"`, `address/city/state` from `expressAddress/expressCity/expressState`. |
| GUO | `option: "pickup"`, `state` and `terminal` from `pickupState/pickupTerminal`, with optional `city` and `note` from `pickupCity/pickupNote`. Collect a terminal name or use a meaningful requested terminal description. |
| Not listed / WhatsApp | Map `not_mentioned` to `option: "enquiry"` to show support guidance. This path ends at contact support. |

| Request | Access and input | Success and errors |
| --- | --- | --- |
| `POST /delivery/quote` | Public. Send the selected delivery object above, including optional `note`. | `200` `{option,fee,currency,is_student,state,city,university,terminal,terminal_pending,support_required,message}`. `422` incomplete destination. A valid destination with no rate returns `fee:null` and `support_required:true`. |
| `POST /orders` | Session. `{contact_name,contact_email,contact_phone,delivery,notes?}` from the form, with nonempty server cart. | `201` order, `status:"PENDING_PAYMENT"`. `422` invalid/unpriced delivery, empty cart or unavailable product/variant, `409` insufficient available inventory or a changed product price. |
| `GET /orders` | Session. | `200` unpaginated array of the caller's full orders, newest first. |
| `GET /orders/{order_id}` | Session, owner only. | `200` order, `404` missing or outside the session's orders. |
| `POST /payments/initiate` | Session and owner of a pending order. `{order_id}`. | `200` payment result, including failed initiation as `success:false`. `404` missing/other owner's order, `409` order no longer awaits payment, `501` provider unavailable due to configuration. |
| `POST /payments/verify` | Session and owner of the payment. `{reference}` (6–64 characters). | `200` payment result. `404` missing/other owner's reference, `409` confirmed amount mismatch, `501` provider missing configuration. A provider lookup failure can return `success:false` with the transaction's existing status. |

1. Load the cart and restore the session. When the signed-out shopper signs in from checkout, finish guest merge and consume the returned cart before allowing review.
2. Quote each complete delivery choice and quote again when the destination or option changes. Use `fee`, `terminal_pending` and `is_student` from the response. With `support_required` show the message and offer pickup or the existing WhatsApp handoff. Keep location dictionaries for suggestions only. Rates come from seeded/maintained rows. The most specific matching terminal, campus, city or state wins. A generic pickup rate can cover an unverified requested terminal and puts it into the confirmation queue.
3. On confirm, send one `POST /orders` and disable repeat submission while it is in flight. The server reprices from the cart and delivery rates, reserves stock, snapshots the order lines and consumes the cart. Use the returned `id` for requests and `reference` (e.g. `ZD-3F81D6AB`) on screen. If the result is ambiguous, refresh owned orders and the cart before letting the customer submit again. No order-creation idempotency key is defined. If a line price changed, reload the product, re-add the affected line at the current price, and let the shopper review the new amount.
4. Show the order's `subtotal`, `customization_total`, `delivery.fee` and `total` before redirect. The default personalization fee is ₦2,000 per customized unit of style `Jersey`. The order item `customization_fee` is the per-unit fee. Send only the order ID to initiation. Persist the returned pair `{order_id,payment_id}` across redirect, then follow `next_action.url` when `success` and a redirect action are present.
5. Implement a return handler at the deployed `PAYMENT_RETURN_URL` (default `/checkout` on dev). Run it before empty-bag/draft redirects, since the cart was consumed. Verify using the merchant `payment_id` as `reference`, with the returned merchant `reference` when provided. Stripe constructs the return query with `paid=1` or `cancelled=1` plus `reference`. Paystack receives the configured callback URL, so validate the actual return query in provider test mode. A callback flag is only a navigation hint. If stored state is absent, a verified result gives `order_id`, and Profile can also recover a pending order from `GET /orders`.
6. Reload `GET /orders/{id}` and render paid only when `payment_status=paid`. For pending or inconclusive verification, show a checking state and let the customer refresh, since the webhook can settle independently. For failed payment, allow another initiation on the same pending order. For `409` refresh the order and show support if still unresolved. On `401` preserve the return context through login. There is no customer cancellation or reservation-expiry route. Reload the cart after order creation and clear transient checkout/return data when resolved.

Example quote request `{"option":"standard","state":"Lagos","city":"Ikeja","address":"12 Allen Avenue"}`. Example support quote for `{"option":"enquiry","state":"Abuja"}`:

```json
{"option":"enquiry","fee":null,"currency":"NGN","is_student":false,"state":"FCT - Abuja","city":"","university":"","terminal":"","terminal_pending":false,"support_required":true,"message":"We will arrange this delivery with you directly."}
```

Example order creation, followed by selected response fields:

```json
{"contact_name":"Ada Okafor","contact_email":"ada@example.com","contact_phone":"+2348012345678","delivery":{"option":"pickup","state":"Abuja","city":"Abuja","terminal":"Requested Abuja terminal","note":"Please confirm the branch"}}
```

```json
{"id":42,"reference":"ZD-3F81D6AB","status":"PENDING_PAYMENT","payment_status":"pending","fulfillment_status":"processing","payment_reference":null,"paid_at":null,"currency":"NGN","subtotal":"58500.00","customization_total":"2000.00","total":"60500.00","count":1,"delivery":{"option":"pickup","fee":"0.00","state":"FCT - Abuja","city":"Abuja","university":"","hostel_room":"","terminal":"Requested Abuja terminal","terminal_pending":true,"note":"Please confirm the branch","is_student":false}}
```

This example assumes the seeded fallback pickup rate and the personalized cart item above. The full order also returns `contact_name/contact_email/contact_phone`, `address_line`, `city_state`, `notes`, `created_at` and `items` (cart line fields plus `customization_fee`). In [Profile][profile], replace `user.orders` with the returned array. Map date from `created_at`, label from `reference`, delivery address from `address_line` and `city_state`, and display item name/price/image from the snapshots. Use `payment_status` (pending/paid/cancelled) for the payment badge and `fulfillment_status` (processing/in_transit/delivered) for paid shipments.

Example initiation `{"order_id":42}` → `200`:

```json
{"success":true,"payment_id":"PAY-82CC14F9E3A1","status":"pending","amount":"60500.00","currency":"NGN","provider":"paystack","order_id":42,"next_action":{"type":"redirect","url":"https://checkout.paystack.com/example"},"message":null}
```

Verify with `{"reference":"PAY-82CC14F9E3A1"}`. The same shape returns with `next_action:null` and the transaction status (normally `pending`, `paid` or `failed` in the customer flow). Only the backend talks to the payment provider for verification. It receives signed webhook requests at `POST /payments/webhooks/{provider}` (configured provider, `200 {received,outcome}`; `400` invalid signature). The storefront makes no webhook request.

[Delivery schema](../app/domains/delivery/api/schemas.py) · [Delivery rules](../app/domains/delivery/domain/rules.py) · [Orders](../app/domains/orders/api/schemas.py) · [Order service](../app/domains/orders/application/service.py) · [Order storage](../app/infrastructure/persistence/sqlalchemy/models/order.py) · [Payment service](../app/domains/payments/application/service.py) · [Stripe return](../app/integrations/payments/stripe.py) · [Paystack callback](../app/integrations/payments/paystack.py) · [Payment setup](PAYMENTS.md)

## Archives

[Archives][archives] initializes demo stories, filters and opens them locally, and adds, edits, deletes, likes and comments using React state. Map `image_url` to `image` with a fallback and `created_at` to the display date. Use numeric IDs, derive edit/delete controls from the authenticated `mine` response, and keep author-facing status separate from the public feed.

| Request | Access and input | Success and errors |
| --- | --- | --- |
| `GET /archives` | Public. Pagination, optional `category`. | `200` page of approved stories, newest first. |
| `GET /archives/{story_id}` | Public. | `200` story; `404` absent or unapproved. |
| `GET /archives/mine` | Session. Pagination. | `200` page of own stories in all statuses. |
| `POST /archives` | Session. `{title,author,content,location?,year?,category?,image_url?}`. Content 10–5000 chars, year up to four characters, image URL HTTP(S) or a site path. | `201` own story with `status:"pending"`. `422` invalid input. |
| `PATCH /archives/{story_id}` | Session and owner. Send only changed fields from the creation schema. | `200` own story returned to pending, `404` missing/other owner, `422` invalid edit. |
| `DELETE /archives/{story_id}` | Session and owner. | `204` empty response; `404` missing/other owner. |

Example submission `{"title":"My first match","author":"Ada Okafor","content":"I watched my first match with my brother in Lagos.","location":"Lagos","year":"2006"}` → `201`:

```json
{"id":9,"title":"My first match","author":"Ada Okafor","content":"I watched my first match with my brother in Lagos.","location":"Lagos","year":"2006","category":"COMMUNITY STORY","image_url":"","created_at":"2026-11-10T12:00:00Z","status":"pending","updated_at":"2026-11-10T12:00:00Z"}
```

After submission or edit, show pending in My Stories and refresh the public list. Admin approval makes the story public. Public story responses omit `status` and `updated_at`. Hide existing like and comment controls until there is a backend contract for them. Existing editorial stories need an explicit content import or a separate static editorial section.

[Archives routes](../app/domains/archives/api/router.py) · [Schemas](../app/domains/archives/api/schemas.py) · [Moderation service](../app/domains/archives/application/service.py)


## Admin inventory, sales and fulfillment

[Admin][admin] starts with a copy of the demo catalog and calculates reports from the seeded `localStorage` [orders store][ordersstore] through [salesMetrics.ts][metrics]. Refresh reloads that store after a timer. Replace the store subscription with API queries and invalidate the affected inventory, order and report queries after successful writes. Gate navigation and page rendering on the restored admin role. All routes below require an admin session and use numeric product/order/story IDs. Every paginated response uses the shared envelope.

| Admin flow and request | Input | Success and errors |
| --- | --- | --- |
| KPI counts, `GET /admin/dashboard` | None. | `200 {catalog,orders,customers,needs_restocking}`. Use `catalog.units_available`, `inventory_value` and stock counts for the inventory cards. |
| Inventory and preview, `GET /admin/products` | Pagination, public catalog criteria plus `active=true/false` and `stock=in_stock/low_stock/out_of_stock`. | `200` page of product details plus `is_active`. Translate the existing hyphenated stock filter values to underscores. |
| Choose image, `POST /admin/products/images` | Raw browser `File` body (no multipart or data URL), JPEG, PNG, GIF or WebP, max `MAX_UPLOAD_BYTES` (default 5,000,000). | `201 {url,key,content_type,size}`. `422` unsupported file bytes or size; `501` storage configuration; `502` storage failure. |
| Add product, `POST /admin/products` | `{slug,name,category_slug,category_name,price,original_price?,currency?,sizes?,images?,tone?,style?,color?,fit?,fit_note?,details?,delivery?,is_bestseller?,is_special?,is_new_arrival?,is_active?}`. Each size is `{size,quantity?,sku?}`, each image `{url,view?}`. | `201` admin product; `409` duplicate slug, `422` invalid fields or duplicate sizes. |
| Edit price/flags/details or archive, `PATCH /admin/products/{product_id}` | Send changed `name,price,original_price,currency,tone,style,color,fit,fit_note,details,delivery,is_bestseller,is_special,is_new_arrival,is_active`. `original_price:null` clears a sale. | `200` updated admin product. `404` unknown ID, `422` invalid product changes. Use `is_active:false` for the existing Remove action and allow restore. |
| Set or correct stock, `PATCH /admin/products/{product_id}/stock` | `{size,delta}` or `{size,set_to}`. `set_to` is total physical stock including reserved units. | `200 {product_id,size,change,quantity,reserved,available}`. `404` missing size/product, `422` both/neither input or stock below reservations. |
| Restock, `POST /admin/products/{product_id}/stock` | `{size,quantity}`, quantity ≥ 1, existing size. | `200 {product_id,size,added,available}`. `404` missing size/product, `422` invalid quantity. |
| Sales, `GET /admin/orders` | Pagination, `payment_status`, `fulfillment_status`, `delivery_option=standard/express/pickup`, `q` (reference, name, email or phone), `date_from` and `date_to` (inclusive store dates). | `200` page of full order records. `422` invalid query. |
| Shipping status / pickup terminal, `PATCH /admin/orders/{order_id}/fulfillment` | `{status?,terminal?}` with at least one. Status `processing`, `in_transit` or `delivered`. Terminal requires a pickup order. | `200` updated order; `404` missing order, `409` unpaid order or terminal on a non-pickup order, `422` empty/invalid change. |
| Weekly, accounting, fulfillment, `GET /admin/analytics` | `date_from` and `date_to` as YYYY-MM-DD. Defaults to current Mon–Sun store week (UTC+1 by default). Supply both boundaries for custom ranges. | `200 {period,sales,accounting,operations,top_products,daily}`. `422` invalid or reversed dates or range over 366 days. |
| Story moderation, `GET /admin/archives` | Pagination, `status=pending/approved/rejected`. | `200` page of own-story-shaped records plus `user_id,moderation_note,reviewed_at`. |
| Approve or reject, `PATCH /admin/archives/{story_id}/moderation` | `{status:"approved"|"rejected",note?}`. | `200` admin story, `404` unknown ID, `422` invalid status. |
| Optional customer list, `GET /admin/users` | Pagination. | `200` page of customer profile objects. The audited Admin page has no customer list tab. |

For upload and create, keep the selected file for preview and send `fetch(url, {method:"POST", credentials:"include", body:file})` when saving. Use the returned public URL in `images`. Replace `FileReader` data URLs as persisted values. A successful upload followed by a failed product write can be retried with the same returned URL. S3-compatible storage needs `STORAGE_PUBLIC_BASE_URL`. For an image already hosted, send its URL directly.

Example product create after uploading an image:

```json
{"slug":"lagos-away-2026","name":"Lagos / Away 2026","category_slug":"curated-jersey","category_name":"CURATED JERSEY","price":"58500.00","currency":"NGN","style":"Jersey","sizes":[{"size":"M","quantity":8}],"images":[{"view":"front","url":"https://media.example.com/lagos-away.webp"}],"is_new_arrival":true}
```

Use decimal edits like `{"price":"56000.00","original_price":"58500.00"}`. For a stock correction, send `{"size":"M","delta":-2}` and replace the displayed count with `available`. If you expose an absolute stock edit, label it physical stock. The API's catalog count is available stock. Existing size-add/remove controls have no variant mutation endpoint.

Map `reference → orderId` for display and retain numeric `id` for updates. Map contact fields, `created_at` and order items from the order response, and `delivery.option=pickup` to `guo_pickup` (standard and express to `hand_delivery`). The latter filter needs two API queries to preserve its current meaning, or two explicit UI options. Map terminal details from `delivery.state/city/terminal/terminal_pending/note`. Send `{"status":"in_transit"}` for shipping or `{"terminal":"Confirmed Abuja branch"}` for a paid pickup order. Use the returned order for the updated row. The sales table's demo item category is absent from order snapshots.

For stats, use `sales.revenue`, `orders`, `units_sold`, `average_order_value`, `previous_revenue` and nullable `change_percent` for weekly cards. Bind the accounting cards to `accounting.gross_sales/customization_charges/delivery_charges/total_collected/outstanding`. Use `operations` for fulfillment counts, `daily[].date/revenue/orders/paid_orders/units_sold` for the trend, and `top_products[]` for rankings. Only paid orders contribute revenue, dates use store time and order creation, and refunds are not netted out of revenue. Add a separate admin moderation view for the Archives workflow. The payment refund endpoint exists for `manage:orders` and has no matching control on the audited page. Its contract is in the payment schemas.

[Admin routes](../app/domains/admin/api/router.py) · [Schemas](../app/domains/admin/api/schemas.py) · [Admin service](../app/domains/admin/application/service.py) · [Analytics](../app/domains/admin/application/analytics.py) · [Stock persistence](../app/infrastructure/persistence/sqlalchemy/models/inventory.py) · [Payment schemas](../app/domains/payments/api/schemas.py)

## Gaps and dependencies

| Affected flow | Owner and next change |
| --- | --- |
| Home newsletter | Backend or email marketing integration. The [Home][home] action only shows a local success message. The API has no subscription operation. Remove simulated success until connected. |
| Collection filters and curated sorting | Frontend. Preserve OR groupings across queries or redesign the filters. Server-side combined OR/group ordering would need a backend change. |
| Guest cart and account | Deployment. Verify credentialed CORS and cookies from the actual storefront origin. Use same-site hosting or proxying to retain guest persistence. Frontend must await login and merge before checkout. |
| Checkout and order return | Frontend and deployment. Use the server cart, seed delivery rates, configure hosted payment return and signed webhooks, and verify with test-mode credentials. Delivery has a quote endpoint and no live terminal/campus directory. Keep suggestions local or add a directory API. Delayed collection of an enquiry price and customer cancellation/reservation expiry would need backend workflows if required. |
| Archives likes, comments and editorial stories | Backend for likes/comments. Frontend or content migration for authored editorial entries. Existing story moderation is ready for a new admin view. |
| Admin inventory | Frontend and storage deployment for create, update, archive and upload. Backend needed to add/remove sizes on existing products, change existing gallery/category/slug, or hard-delete a product. Avoid sending these as extra patch fields. |
| Admin sales and reports | Frontend. Adapt both statuses and response fields. Hide item-category and demo-only custom-support totals where there is no contract. Refund-netted reporting needs backend accounting changes if required. |
| Demo browser state | Frontend. Retire fake sessions/orders/wishlist and admin seed data. If preserving a pre-integration in-memory bag is required, replay only shopper-selected lines with valid slugs and sizes, and surface rejected lines. Demo orders are not authoritative history. |

## Verification

Cross-checked route registration, request/response schemas, domain rules, repositories and tests at the pinned revisions. Ran the existing full backend suite with Python 3.14 against disposable local PostgreSQL 17. All 939 tests passed. A local ASGI smoke check also passed for health, OpenAPI, unauthenticated session handling and credentialed CORS preflight from the default Vite origin. The suite covers migrations and HTTP workflows including customer signup/login, guest merge, orders, payment settlement, catalog, wishlist, admin and Archives. The customer end-to-end test uses a mock transport with the Paystack adapter. Live payment, email, storage, hosted CORS and production data remain unverified.

[API tests](../tests/api) · [Customer end-to-end test](../tests/e2e/test_customer_flow.py) · [Testing setup](TESTING.md) · [OpenAPI and error reference](API.md)

[vite]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/vite.config.ts
[auth]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/pages/Auth.tsx
[authmodal]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/components/AuthModal.tsx
[authctx]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/contexts/AuthContext.tsx
[profile]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/pages/Profile.tsx
[home]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/pages/Home.tsx
[catalog]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/lib/catalog.ts
[collection]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/pages/Collection.tsx
[search]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/components/CentralSearchModal.tsx
[detail]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/pages/ProductDetail.tsx
[shopctx]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/contexts/ShopContext.tsx
[cartdrawer]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/components/CartDrawer.tsx
[navbar]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/components/Navbar.tsx
[checkout]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/pages/Checkout.tsx
[review]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/pages/OrderReview.tsx
[archives]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/pages/Archives.tsx
[admin]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/pages/Admin.tsx
[ordersstore]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/lib/ordersStore.ts
[metrics]: https://github.com/eddy-mfon/Zoid/blob/5fd2a105e12400e8a40193a46ba4768384fada50/client/src/lib/salesMetrics.ts

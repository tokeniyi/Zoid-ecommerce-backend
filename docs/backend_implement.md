# Backend Implementation Plan

Each branch is created in `Zoid-ecommerce-backend`, from the `backend` branch chosen as the integration base.

## Order

| Order | Branch | Changes | Verification |
|-------|--------|---------|--------------|
| 1 | `feat/commerce-money-contract` | Make all API money fields consistent and safe for payment use. Use decimal strings in API responses instead of floating-point numbers. Update product, cart, order, payment, refund, and admin serializers/tests. | `uv run pytest tests/unit tests/api` and `uv run ruff check .` |
| 2 | `feat/catalog-contract` | Add `original_price` and `is_new_arrival` to products; expose card fields required by the storefront; calculate `discount_percent` from the two prices; add server-side product search, filters, sorting, and pagination. Extend admin product create/update responses accordingly. | `uv run pytest tests/unit/products tests/api/products tests/api/admin` and `uv run ruff check .` |
| 3 | `feat/product-media` | Add protected admin image upload support using the configured storage provider. Product records will store stable public URLs only. Keep direct image-URL entry available for existing migrated assets. | `uv run pytest tests/unit/storage tests/api/admin` and manually create a product with an uploaded image, then load the returned URL in a browser. |
| 4 | `feat/cart-customization` | Add optional free-text customization to cart items. Ensure cart lines merge only when product, size, and customization all match. Validate length and preserve customization in cart responses. | `uv run pytest tests/unit/cart tests/api/cart` and manually add the same jersey/size twice with different text; confirm two lines remain. |
| 5 | `feat/delivery-orders` | Add delivery quote support and complete order storage: delivery option, subtype, structured delivery details, fulfillment details, delivery fee, customization total, subtotal, and total. Add a rate-rule table for state/city, university, and pickup-terminal pricing. The server calculates every amount. Save customization on each order item. | `uv run pytest tests/unit/orders tests/api/orders` and manually quote/create orders for standard, university, express, pickup, and unsupported locations. |
| 6 | `feat/payment-order-status` | Return payment information with orders. Keep payment status separate from fulfillment status. Add admin fulfillment updates for Processing, In Transit, and Delivered. Update customer order lists to return the data the profile screen needs without one request per order. | `uv run pytest tests/unit/payments tests/unit/orders tests/api/orders tests/api/payments tests/api/admin` and manually complete a test payment, verify it, then update fulfillment status as an admin. |
| 7 | `feat/admin-store-operations` | Add protected admin product listing, controlled stock adjustment up and down, product archive/unarchive through `is_active`, and all dashboard analytics shown by the frontend: revenue, date filtering, payment state, fulfillment state, best sellers, inventory figures, and trend data. | `uv run pytest tests/unit/admin tests/api/admin` and manually compare every value on the admin screen against known test orders. |
| 8 | `feat/archives-submissions` | Add archive-story database storage, customer submission endpoint, public approved-story list, and protected admin moderation. Stories will include title, author, location, content, status, and dates. | `uv run pytest tests/api tests/unit` and manually submit a story, approve it as an admin, then confirm it appears in the public list. |
| 9 | `feat/catalog-data-migration` | Add a repeatable import/seed process for the current frontend catalog: products, categories, stock, flags, prices, descriptions, and stable image URLs. It must be safe to run again without duplicating data. | Run the import against a disposable local database, then `uv run pytest`; manually compare product count, stock, prices, flags, and images to the current storefront. |
| 10 | `chore/local-session-config` | Document and set development defaults for the test frontend and backend URLs: frontend `http://localhost:3000`, backend `http://localhost:8000`. Keep production values environment-driven so you can replace them before deployment. | Start both applications locally and confirm login/logout cookies work across the two localhost ports. |

## Delivery Contract

The delivery branch (branch 5) will introduce:

- `POST /delivery/quote` — validates delivery details and returns server-calculated fees and totals.
- An order request that sends delivery choices and details, never client-calculated money.
- An order response that includes:
  - delivery and fulfillment details
  - item customization
  - subtotal
  - customization total
  - delivery fee
  - final total
  - payment status
  - fulfillment status
  - payment reference when available

The database will use a delivery-rate table rather than frontend-only calculations. The server will select the most specific valid rate:

1. Exact pickup terminal
2. Exact university
3. Exact state and city
4. State-level fallback
5. No matching rate → support-required, not an invented price

## Required Implementation Rules

- Product discounts are calculated, never stored as a separate editable badge.
- The browser never decides final prices, delivery fees, payment status, stock, or order status.
- No hardcoded production URLs or credentials.
- Existing database data is preserved through additive migrations.
- Every migration includes a downgrade path.
- Each branch is tested before you merge it into the backend integration branch.
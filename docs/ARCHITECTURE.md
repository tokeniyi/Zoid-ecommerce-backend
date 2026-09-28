# Zoid Jerseys Backend Architecture

## Security, Endpoint Protection, Payments, Integrations, and Full Project Structure

---

# 1. Core Architectural Rule

The backend follows this rule:

```text
API/UI concerns
        ↓
Application/use-case logic
        ↓
Domain/business rules
        ↓
Interfaces / contracts
        ↑
Infrastructure implementations
        ↑
External providers
```

The application must depend on **what a capability does**, not on how that capability is implemented.

For example:

```text
OrderService
    ↓
PaymentGateway
    ↓
PaystackPaymentGateway
    ↓
Paystack
```

The `OrderService` must not import:

```python
paystack
stripe
```

It only uses:

```python
payment_gateway.create_payment(...)
payment_gateway.verify_payment(...)
```

The same principle applies to:

```text
Database
Authentication
Password hashing
Email
File storage
Notifications
```

This directly supports the project's required modularity, replaceability, testability, and separation of concerns.

---

# 2. Complete Backend Project Structure

The backend should use the following structure.

```text
backend/
│
├── app/
│   │
│   ├── main.py
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── router.py
│   │
│   ├── domains/
│   │   │
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   │
│   │   │   ├── api/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── router.py
│   │   │   │   └── schemas.py
│   │   │   │
│   │   │   ├── application/
│   │   │   │   ├── __init__.py
│   │   │   │   └── service.py
│   │   │   │
│   │   │   └── domain/
│   │   │       ├── __init__.py
│   │   │       ├── entities.py
│   │   │       └── repositories.py
│   │   │
│   │   ├── users/
│   │   │   ├── __init__.py
│   │   │   ├── api/
│   │   │   │   ├── router.py
│   │   │   │   └── schemas.py
│   │   │   ├── application/
│   │   │   │   └── service.py
│   │   │   └── domain/
│   │   │       ├── entities.py
│   │   │       └── repositories.py
│   │   │
│   │   ├── products/
│   │   │   ├── __init__.py
│   │   │   ├── api/
│   │   │   │   ├── router.py
│   │   │   │   └── schemas.py
│   │   │   ├── application/
│   │   │   │   └── service.py
│   │   │   └── domain/
│   │   │       ├── entities.py
│   │   │       └── repositories.py
│   │   │
│   │   ├── cart/
│   │   │   ├── __init__.py
│   │   │   ├── api/
│   │   │   │   ├── router.py
│   │   │   │   └── schemas.py
│   │   │   ├── application/
│   │   │   │   └── service.py
│   │   │   └── domain/
│   │   │       ├── entities.py
│   │   │       └── repositories.py
│   │   │
│   │   ├── wishlist/
│   │   │   ├── __init__.py
│   │   │   ├── api/
│   │   │   │   ├── router.py
│   │   │   │   └── schemas.py
│   │   │   ├── application/
│   │   │   │   └── service.py
│   │   │   └── domain/
│   │   │       ├── entities.py
│   │   │       └── repositories.py
│   │   │
│   │   ├── orders/
│   │   │   ├── __init__.py
│   │   │   ├── api/
│   │   │   │   ├── router.py
│   │   │   │   └── schemas.py
│   │   │   ├── application/
│   │   │   │   └── service.py
│   │   │   └── domain/
│   │   │       ├── entities.py
│   │   │       ├── enums.py
│   │   │       └── repositories.py
│   │   │
│   │   ├── payments/
│   │   │   ├── __init__.py
│   │   │   ├── api/
│   │   │   │   ├── router.py
│   │   │   │   └── schemas.py
│   │   │   ├── application/
│   │   │   │   └── service.py
│   │   │   └── domain/
│   │   │       ├── entities.py
│   │   │       ├── enums.py
│   │   │       └── gateway.py
│   │   │
│   │   └── admin/
│   │       ├── __init__.py
│   │       ├── api/
│   │       │   ├── router.py
│   │       │   └── schemas.py
│   │       ├── application/
│   │       │   └── service.py
│   │       └── domain/
│   │           └── repositories.py
│   │
│   ├── infrastructure/
│   │   │
│   │   ├── persistence/
│   │   │   ├── __init__.py
│   │   │   │
│   │   │   └── sqlalchemy/
│   │   │       ├── __init__.py
│   │   │       ├── session.py
│   │   │       ├── unit_of_work.py
│   │   │       │
│   │   │       ├── models/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── user.py
│   │   │       │   ├── credential.py
│   │   │       │   ├── role.py
│   │   │       │   ├── address.py
│   │   │       │   ├── product.py
│   │   │       │   ├── category.py
│   │   │       │   ├── product_image.py
│   │   │       │   ├── product_variant.py
│   │   │       │   ├── inventory.py
│   │   │       │   ├── cart.py
│   │   │       │   ├── cart_item.py
│   │   │       │   ├── wishlist.py
│   │   │       │   ├── wishlist_item.py
│   │   │       │   ├── order.py
│   │   │       │   ├── order_item.py
│   │   │       │   ├── transaction.py
│   │   │       │   ├── refund.py
│   │   │       │   └── webhook_event.py
│   │   │       │
│   │   │       └── repositories/
│   │   │           ├── user.py
│   │   │           ├── credential.py
│   │   │           ├── product.py
│   │   │           ├── cart.py
│   │   │           ├── wishlist.py
│   │   │           ├── order.py
│   │   │           └── transaction.py
│   │   │
│   │   └── container.py
│   │
│   ├── integrations/
│   │   │
│   │   ├── payments/
│   │   │   ├── __init__.py
│   │   │   ├── paystack.py
│   │   │   ├── stripe.py
│   │   │   └── factory.py
│   │   │
│   │   ├── email/
│   │   │   ├── __init__.py
│   │   │   ├── sender.py
│   │   │   ├── resend.py
│   │   │   └── factory.py
│   │   │
│   │   └── storage/
│   │       ├── __init__.py
│   │       ├── cloudinary.py
│   │       ├── s3.py
│   │       └── factory.py
│   │
│   ├── security/
│   │   │
│   │   ├── authentication/
│   │   │   ├── __init__.py
│   │   │   ├── service.py
│   │   │   ├── session.py
│   │   │   ├── dependencies.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── password/
│   │   │   ├── __init__.py
│   │   │   ├── hasher.py
│   │   │   └── factory.py
│   │   │
│   │   ├── authorization/
│   │   │   ├── __init__.py
│   │   │   ├── roles.py
│   │   │   ├── permissions.py
│   │   │   └── dependencies.py
│   │   │
│   │   └── protection/
│   │       ├── __init__.py
│   │       ├── rate_limiter.py
│   │       ├── cors.py
│   │       ├── headers.py
│   │       └── request_validation.py
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   │
│   └── shared/
│       ├── __init__.py
│       ├── exceptions.py
│       ├── result.py
│       ├── pagination.py
│       └── types.py
│
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── tests/
│   ├── unit/
│   │   ├── auth/
│   │   ├── users/
│   │   ├── products/
│   │   ├── cart/
│   │   ├── orders/
│   │   ├── payments/
│   │   └── security/
│   │
│   ├── integration/
│   │   ├── database/
│   │   ├── payments/
│   │   └── email/
│   │
│   └── api/
│       ├── auth/
│       ├── products/
│       ├── cart/
│       ├── orders/
│       └── admin/
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── SECURITY.md
│   └── PAYMENTS.md
│
├── .env
├── .env.example
├── .gitignore
├── alembic.ini
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

# 3. Why the Structure Is Divided This Way

There are five major layers.

```text
domains/
    What the application does

security/
    Who is allowed to do it

infrastructure/
    How technical resources are implemented

integrations/
    How external providers are connected

api/
    How HTTP exposes the capabilities
```

These layers should not blur together.

For example:

```text
Product API
    ↓
Product Service
    ↓
Product Repository interface
    ↓
SQLAlchemy Product Repository
    ↓
PostgreSQL
```

The API doesn't know PostgreSQL exists.

Likewise:

```text
Order Service
    ↓
Payment Gateway interface
    ↓
Paystack Adapter
    ↓
Paystack
```

The Order Service doesn't know Paystack exists.

---

# 4. Security Architecture

Security is divided into:

```text
security/
├── authentication/
├── password/
├── authorization/
└── protection/
```

This matches the architecture requirement that authentication, password hashing, RBAC, and endpoint protection be replaceable and independently testable.

---

# 5. Authentication vs Authorization vs Protection

These three should not be treated as the same thing.

## Authentication

Answers:

> Who are you?

Example:

```text
User logs in
    ↓
credentials verified
    ↓
session created
    ↓
backend knows User #123 is authenticated
```

---

## Authorization

Answers:

> Are you allowed to do this?

Example:

```text
Authenticated user
    +
role = customer
    ↓
Can view own orders

Authenticated user
    +
role = admin
    ↓
Can manage products
```

---

## Protection

Answers:

> How do we protect the endpoint/system from abuse or invalid requests?

Examples:

```text
Rate limiting
CORS
security headers
request validation
CSRF protection where applicable
```

---

# 6. Authentication Workflow

The frontend contains:

```text
/login
/signup
```

The backend contains:

```text
/api/v1/auth/login
/api/v1/auth/signup
/api/v1/auth/logout
/api/v1/auth/me
```

The frontend should never implement password verification itself.

The flow is:

```text
LOGIN UI
    ↓
POST /api/v1/auth/login
    ↓
Auth Router
    ↓
Auth Service
    ↓
Credential Repository
    ↓
Password Hasher
    ↓
Credentials verified
    ↓
Session Service
    ↓
Session created
    ↓
HTTP response
```

The password hasher is replaceable.

For example:

```text
PasswordHasher
      ↑
      │
 ┌────┴─────┐
 │          │
Argon2    bcrypt
```

The authentication service only calls:

```python
password_hasher.verify(...)
```

It does not care which algorithm is underneath.

Your architecture specifically requires this abstraction so the password implementation can be changed without rewriting the application.

---

# 7. Session Architecture

The browser should receive a secure authentication mechanism after login.

Conceptually:

```text
Frontend
    ↓
login
    ↓
Backend
    ↓
session.create(user)
    ↓
secure HTTP-only cookie/session
```

Then later:

```text
Frontend
    ↓
GET /api/v1/auth/me
    ↓
Authentication dependency
    ↓
session.verify(...)
    ↓
Current user
```

The rest of the backend doesn't need to understand session internals.

It simply receives:

```python
current_user
```

from the authentication dependency.

The actual session strategy should stay behind the abstraction so it can be changed later, as required by the original architecture.

---

# 8. Protected Endpoints

Endpoints should belong to one of three access levels.

## Public

No authentication required.

```text
GET /api/v1/products
GET /api/v1/products/{id}
GET /api/v1/categories
POST /api/v1/auth/signup
POST /api/v1/auth/login
GET /api/v1/cart
POST /api/v1/cart/items
```

A guest can browse products and maintain a guest cart.

---

## Authenticated User

A valid authenticated session is required.

```text
POST /api/v1/orders
GET /api/v1/orders
GET /api/v1/orders/{id}
GET /api/v1/users/me
PUT /api/v1/users/me
POST /api/v1/payments/...
```

---

## Admin

Authenticated + role must be `admin`.

```text
GET /api/v1/admin/dashboard
POST /api/v1/admin/products
PATCH /api/v1/admin/products/{id}
POST /api/v1/admin/products/{id}/stock
GET /api/v1/admin/orders
GET /api/v1/admin/users
```

RBAC is explicitly required by the architecture.

---

# 9. How FastAPI Endpoint Protection Works

The route itself should remain simple.

Conceptually:

```python
@router.get("/orders")
async def get_orders(
    current_user = Depends(require_authenticated_user),
    service = Depends(get_order_service),
):
    return await service.get_user_orders(current_user.id)
```

For admin:

```python
@router.post("/products")
async def create_product(
    current_user = Depends(require_admin),
    service = Depends(get_product_service),
):
    ...
```

The route doesn't contain:

```text
password verification
session parsing
role checking
database query
```

It delegates those jobs.

---

# 10. Guest Checkout Workflow

This is your important example.

A user arrives for the first time.

```text
Visitor
   ↓
Product page
   ↓
Add Product A
   ↓
Add Product B
   ↓
Add Product C
   ↓
Guest Cart
```

The cart can be associated with a guest identifier.

Conceptually:

```text
Browser
   ↓
guest_cart_id
   ↓
Cart Service
   ↓
Cart Repository
   ↓
Database
```

The guest can therefore build a cart without creating an account.

This matches your architecture requirement for both guest and authenticated carts.

---

# 11. Guest Clicks "Proceed to Checkout"

The frontend tries to enter:

```text
/checkout
```

The frontend first checks whether the user is authenticated.

If not:

```text
/checkout
   ↓
authentication required
   ↓
/login?returnTo=/checkout
```

The important distinction is:

**the frontend controls navigation; the backend controls authorization.**

The backend must still reject unauthorized API requests.

The backend should return:

```http
401 Unauthorized
```

when an unauthenticated user attempts a protected operation.

Your frontend then interprets that response and sends the user to:

```text
/login
```

or:

```text
/signup
```

---

# 12. Login/Signup Does Not Know About Checkout

This is another important modularity boundary.

The login page should only know:

```text
"I need to authenticate a user."
```

It shouldn't contain:

```text
checkout logic
order creation
payment logic
cart logic
```

After successful authentication:

```text
Login Service
    ↓
authentication successful
    ↓
Frontend redirects to returnTo
    ↓
/checkout
```

The authentication module doesn't need to understand what `/checkout` does.

This is exactly the "one module calls another without knowing its internals" principle.

---

# 13. Guest Cart → Authenticated Cart

When login/signup succeeds:

```text
Guest Cart
    +
Authenticated User
    ↓
Cart Service
    ↓
merge_guest_cart()
    ↓
User Cart
```

For example:

```text
Guest Cart
├── Jersey A × 2
├── Jersey B × 1
└── Jersey C × 3

        ↓ Login

User Cart
├── Existing Item X
├── Jersey A × 2
├── Jersey B × 1
└── Jersey C × 3
```

The exact conflict/duplicate behavior must be defined by the application's requirements rather than silently assumed. Your architecture explicitly says guest-cart merge behavior should be resolved from the actual application requirements.

---

# 14. Checkout Workflow

After authentication:

```text
/login
   ↓
authentication succeeds
   ↓
cart merged
   ↓
redirect
   ↓
/checkout
```

The checkout UI collects:

```text
Customer details
Shipping/delivery details
Order information
```

The frontend sends:

```http
POST /api/v1/orders
```

The backend then performs:

```text
Order Router
     ↓
Order Schema validation
     ↓
Order Service
     ↓
Cart Service
     ↓
Inventory validation
     ↓
Pricing validation
     ↓
Order Repository
     ↓
Order created
```

The frontend does not directly create database orders.

---

# 15. Order Status Before Payment

The order should not immediately become:

```text
PAID
```

when the user clicks "Confirm Order".

Instead:

```text
PENDING_PAYMENT
```

is created.

Conceptually:

```text
Cart
 ↓
Order
 ↓
PENDING_PAYMENT
 ↓
Payment initiated
```

Your architecture already identifies payment status and order status as separate concepts.

---

# 16. Payment Architecture

This is the most important abstraction.

Do **not** make:

```text
OrderService → Paystack
```

or:

```text
OrderService → Stripe
```

Instead:

```text
OrderService
      ↓
PaymentService
      ↓
PaymentGateway
      ↓
selected provider
```

The contract lives here:

```text
domains/payments/domain/gateway.py
```

---

# 17. Payment Gateway Contract

The payment domain should expose a small provider-independent interface.

Conceptually:

```python
class PaymentGateway(Protocol):

    async def create_payment(
        self,
        request: PaymentRequest
    ) -> PaymentInitiation:
        ...

    async def verify_payment(
        self,
        reference: str
    ) -> PaymentVerification:
        ...

    async def refund_payment(
        self,
        request: RefundRequest
    ) -> RefundResult:
        ...
```

The exact methods can evolve with the real payment requirements.

The important part is that these methods describe **business capabilities**, not provider behavior.

---

# 18. Standard Payment Result

The payment provider should return a normalized result.

For example:

```python
PaymentInitiation(
    success=True,
    transaction_id="internal-id",
    provider_reference="provider-reference",
    checkout_url="https://...",
    status=PaymentStatus.PENDING,
)
```

The Payment Service should not care whether:

```text
checkout_url
```

came from:

```text
Paystack authorization_url
```

or:

```text
Stripe Checkout Session URL
```

It simply receives:

```text
payment initiated successfully
```

plus the information required to continue.

---

# 19. Paystack Implementation

The Paystack adapter lives here:

```text
app/
└── integrations/
    └── payments/
        └── paystack.py
```

It implements the generic interface.

```text
PaymentGateway
       ↑
       │ implements
       │
PaystackPaymentGateway
       ↓
    Paystack
```

Only this file should know details such as:

```text
Paystack API
Paystack request format
Paystack reference
Paystack verification endpoint
Paystack webhook signature
Paystack-specific errors
```

---

# 20. Stripe Implementation

Stripe gets another adapter:

```text
app/
└── integrations/
    └── payments/
        └── stripe.py
```

```text
PaymentGateway
       ↑
       │ implements
       │
StripePaymentGateway
       ↓
     Stripe
```

The rest of the application remains unchanged.

---

# 21. Selecting the Provider

Provider selection happens in configuration/bootstrap, not inside business logic.

For example:

```text
PAYMENT_PROVIDER=paystack
```

or:

```text
PAYMENT_PROVIDER=stripe
```

The factory:

```text
integrations/payments/factory.py
```

selects:

```text
PAYMENT_PROVIDER
       ↓
Payment Factory
       ↓
┌───────────────┐
│               │
▼               ▼
Paystack      Stripe
```

The application still receives:

```text
PaymentGateway
```

not:

```text
PaystackPaymentGateway
```

This matches your architecture's requirement that provider selection be configuration-driven.

---

# 22. The Order Service Never Changes

With Paystack:

```text
OrderService
     ↓
PaymentService
     ↓
PaymentGateway
     ↓
PaystackPaymentGateway
     ↓
Paystack
```

Change configuration.

Now:

```text
OrderService
     ↓
PaymentService
     ↓
PaymentGateway
     ↓
StripePaymentGateway
     ↓
Stripe
```

The following do not need provider-specific modifications:

```text
OrderService
CartService
Order Router
Order schemas
Database models
Admin dashboard
```

That is genuine provider swap-ability.

---

# 23. Payment Initiation Workflow

After "Confirm Order":

```text
Checkout UI
    ↓
POST /api/v1/orders
    ↓
Order Router
    ↓
Order Service
    ↓
Order created as PENDING_PAYMENT
    ↓
Payment Service
    ↓
PaymentGateway.create_payment()
    ↓
Selected provider adapter
    ↓
Paystack / Stripe
    ↓
PaymentInitiation result
    ↓
Backend
    ↓
Frontend
```

The frontend receives a standardized response.

For a hosted payment flow:

```json
{
  "success": true,
  "payment_id": "...",
  "status": "pending",
  "next_action": {
    "type": "redirect",
    "url": "https://provider-checkout-url"
  }
}
```

The frontend doesn't need to know:

```text
"This is Paystack."

or

"This is Stripe."
```

It only knows:

```text
"I have been told to redirect the user to the payment page."
```

This is the cleanest solution for your requirement.

---

# 24. Why Hosted Checkout Is Especially Useful Here

Suppose today:

```text
PAYMENT_PROVIDER=paystack
```

The frontend gets:

```text
next_action.type = redirect
```

Tomorrow:

```text
PAYMENT_PROVIDER=stripe
```

The frontend still gets:

```text
next_action.type = redirect
```

Therefore:

```text
Frontend
   ↓
Backend
   ↓
Payment interface
   ↓
Provider
   ↓
generic redirect URL
```

The frontend doesn't have to contain separate:

```text
PaystackPaymentComponent
StripePaymentComponent
```

unless a future requirement specifically calls for provider-specific embedded checkout.

---

# 25. Payment Confirmation Workflow

The browser returning from payment is **not sufficient evidence that payment succeeded**.

The backend must verify the payment.

The flow is:

```text
User completes provider payment
        ↓
Provider response/webhook
        ↓
Backend payment endpoint
        ↓
PaymentService
        ↓
PaymentGateway.verify_payment()
        ↓
Provider-specific verification
        ↓
Normalized PaymentVerification result
        ↓
Payment Service
        ↓
Transaction updated
        ↓
Order updated
```

Your architecture explicitly calls for transaction references, provider identifiers, payment status, and webhook-related information.

---

# 26. Payment Verification Result

The provider adapter converts its own response into something like:

```python
PaymentVerification(
    success=True,
    status=PaymentStatus.PAID,
    transaction_id=internal_transaction_id,
    provider_reference=reference,
)
```

For failure:

```python
PaymentVerification(
    success=False,
    status=PaymentStatus.FAILED,
    transaction_id=internal_transaction_id,
    provider_reference=reference,
)
```

The Payment Service only works with:

```text
success
status
transaction
```

not Paystack/Stripe-specific response structures.

---

# 27. Webhooks

The payment integration should support provider webhooks.

Conceptually:

```text
Paystack / Stripe
        ↓
POST /api/v1/payments/webhooks/{provider}
        ↓
Provider Adapter
        ↓
Verify signature
        ↓
Convert provider event
        ↓
Payment Service
        ↓
Update transaction/order
```

Provider-specific webhook verification belongs inside:

```text
integrations/payments/paystack.py
integrations/payments/stripe.py
```

The order service should never verify a Stripe signature or Paystack signature itself.

---

# 28. Idempotency

Payment systems must protect against the same event being processed twice.

For example:

```text
Webhook arrives
     ↓
Payment marked PAID

Same webhook arrives again
     ↓
Backend recognizes event/reference already processed
     ↓
No duplicate order update
No duplicate email
No duplicate inventory operation
```

This is why the database structure includes:

```text
transaction
webhook_event
refund
```

and why provider transaction identifiers should have appropriate uniqueness constraints. Your architecture explicitly identifies those payment records as part of the database design.

---

# 29. Successful Payment Workflow

The full successful path is:

```text
Customer
   ↓
Checkout
   ↓
Confirm Order
   ↓
Order Service
   ↓
PENDING_PAYMENT order
   ↓
Payment Service
   ↓
PaymentGateway
   ↓
Stripe / Paystack
   ↓
Customer pays
   ↓
Provider confirms payment
   ↓
Backend verifies
   ↓
Transaction = PAID
   ↓
Order = PAID
   ↓
Post-payment actions
   ├── Send store-owner email
   └── Make order visible to Admin
```

---

# 30. Email Architecture

Do not put email-provider logic inside `PaymentService`.

Bad:

```text
PaymentService
    ↓
Resend API
```

Instead:

```text
PaymentService
    ↓
Order/payment successfully confirmed
    ↓
Notification capability
    ↓
Email interface
    ↓
Selected email provider
```

For example:

```text
integrations/email/sender.py
```

defines the provider-independent contract.

Then:

```text
integrations/email/resend.py
```

implements it.

Later:

```text
integrations/email/sendgrid.py
```

could implement the same contract.

---

# 31. What Gets Emailed

After confirmed payment:

```text
Payment confirmed
      ↓
Order notification
      ↓
EmailSender.send()
      ↓
Store owner's configured email
```

The email should contain the required order information, for example:

```text
Order number
Customer information
Products
Quantities
Prices
Total
Delivery information
Payment reference
```

The actual email formatting belongs to the notification/application layer.

The provider adapter only knows:

```text
send email
```

not:

```text
this is an ecommerce order
```

---

# 32. Admin Dashboard Architecture

There are two separate things:

```text
/admin
```

is a **frontend route/UI**.

And:

```text
/api/v1/admin/...
```

are **backend APIs**.

Both must be protected.

Never rely only on hiding the frontend page.

---

# 33. Admin Access Workflow

User navigates to:

```text
/admin
```

Frontend checks:

```text
Is authenticated?
       ↓
Is role = admin?
```

If not:

```text
Not authenticated → /login
Authenticated but not admin → access denied
```

But the backend independently performs:

```text
GET /api/v1/admin/dashboard
       ↓
Authentication dependency
       ↓
Authorization dependency
       ↓
role == admin?
       ↓
allow / reject
```

Therefore a customer cannot bypass the UI by manually calling the API.

---

# 34. Admin Product Creation

Admin UI:

```text
/admin/products/new
```

submits:

```text
POST /api/v1/admin/products
```

Workflow:

```text
Admin Router
    ↓
require_admin
    ↓
Schema validation
    ↓
Admin/Product Service
    ↓
Product Repository interface
    ↓
SQLAlchemy repository
    ↓
PostgreSQL
```

The admin module should not directly manipulate SQLAlchemy.

---

# 35. Admin Stock Increase

```text
Admin Dashboard
    ↓
Increase Stock
    ↓
POST /api/v1/admin/products/{id}/stock
    ↓
Admin Service
    ↓
Inventory logic
    ↓
Inventory Repository
    ↓
Database
```

This keeps inventory rules in the application/domain rather than in the frontend.

---

# 36. How Admin Sees Paid Orders

There does not need to be a second copy of every order.

After payment succeeds:

```text
Order
   ↓
status = PAID
   ↓
stored in database
```

The admin dashboard requests:

```text
GET /api/v1/admin/orders
```

and the backend retrieves the relevant records.

So:

```text
Payment
   ↓
Order updated
   ↓
Database
   ↑
Admin Dashboard reads it
```

This is preferable to trying to manually "send the order" to the admin dashboard.

The dashboard is a consumer of the same authoritative backend data.

---

# 37. Complete End-to-End Guest Purchase

Here is the entire workflow in one sequence.

```text
┌──────────────────────────────────────────┐
│                CUSTOMER                  │
└────────────────────┬─────────────────────┘
                     │
                     ▼
              Browse Products
                     │
                     ▼
                Add to Cart
                     │
                     ▼
              Guest Cart Created
                     │
                     ▼
              Click Checkout
                     │
                     ▼
             Authentication Check
                     │
              ┌──────┴──────┐
              │             │
          logged in       guest
              │             │
              │             ▼
              │        /login or /signup
              │             │
              │             ▼
              │        Authentication
              │             │
              │             ▼
              │       Merge Guest Cart
              │             │
              └──────┬──────┘
                     ▼
                  /checkout
                     │
                     ▼
              Enter checkout data
                     │
                     ▼
              Confirm Order
                     │
                     ▼
               Order Service
                     │
                     ▼
             PENDING_PAYMENT
                     │
                     ▼
             Payment Service
                     │
                     ▼
              Payment Gateway
                     │
          ┌──────────┴──────────┐
          │                     │
       Paystack               Stripe
          │                     │
          └──────────┬──────────┘
                     ▼
              Payment Checkout
                     │
                     ▼
                 User Pays
                     │
                     ▼
          Provider Confirmation
                     │
                     ▼
             Backend Verification
                     │
                     ▼
             Payment = PAID
                     │
                     ▼
               Order = PAID
                     │
          ┌──────────┴───────────┐
          │                      │
          ▼                      ▼
   Store Owner Email       Admin Dashboard
```

---

# 38. What Each Module Is Allowed to Know

This is one of the most important rules in the project.

## Product Router knows

```text
HTTP
request
response
authentication requirements
```

It does not know:

```text
SQLAlchemy
PostgreSQL
Paystack
Stripe
```

---

## Product Service knows

```text
product business rules
```

It does not know:

```text
HTTP
PostgreSQL implementation
Stripe API
```

---

## Product Repository interface knows

```text
"What product data operations are required"
```

It does not know:

```text
how those operations are implemented
```

---

## SQLAlchemy Repository knows

```text
SQLAlchemy
database models
database queries
```

It does not contain:

```text
HTTP logic
frontend logic
Stripe logic
```

---

## Payment Service knows

```text
create payment
verify payment
refund payment
payment status
```

It does not know:

```text
Paystack API details
Stripe SDK details
```

---

## Paystack Adapter knows

```text
Paystack
```

Nothing outside that integration needs to know those details.

---

## Stripe Adapter knows

```text
Stripe
```

Nothing outside that integration needs to know those details.

---

# 39. Database Swap

Current:

```text
Domain
  ↓
Repository Interface
  ↓
SQLAlchemy Repository
  ↓
PostgreSQL
```

Potential future:

```text
Domain
  ↓
Repository Interface
  ↓
Another Repository
  ↓
Different Database
```

The domain and API remain isolated from the persistence implementation.

This is the stronger version of the database-modularity requirement in your architecture.

The swap is not intended to mean "change Postgres to MongoDB with one line." The goal is that database-specific code does not contaminate business logic and API code.

---

# 40. Payment Provider Swap

Current:

```text
PAYMENT_PROVIDER=paystack
```

gives:

```text
PaymentGateway
    ↓
PaystackPaymentGateway
```

Change configuration:

```text
PAYMENT_PROVIDER=stripe
```

gives:

```text
PaymentGateway
    ↓
StripePaymentGateway
```

No changes should be needed to:

```text
Checkout Service
Order Service
Cart Service
Admin Service
```

This directly follows your requirement that provider implementations be replaceable behind unified internal interfaces.

---

# 41. Adding a New Payment Provider

Suppose a new provider appears later:

```text
Flutterwave
```

The implementation process should be:

```text
1. Create:
   integrations/payments/flutterwave.py

2. Implement:
   PaymentGateway

3. Add provider selection:
   PAYMENT_PROVIDER=flutterwave

4. Add provider-specific tests

5. No rewrite of OrderService
```

That is what scalability should look like.

---

# 42. Adding Vendor Accounts

Later:

```text
domains/
    vendors/
```

could be introduced.

Then:

```text
users
auth
products
orders
```

continue to exist.

Vendor-specific logic lives in:

```text
domains/vendors/
```

and authorization gains:

```text
role = vendor
```

The existing customer/admin flows should not need to be rewritten simply because a new role exists.

---

# 43. Adding Coupons

Later:

```text
domains/
└── coupons/
    ├── api/
    │   ├── router.py
    │   └── schemas.py
    ├── application/
    │   └── service.py
    └── domain/
        ├── entities.py
        └── repositories.py
```

Then:

```text
Checkout
    ↓
Order Service
    ↓
Coupon Service
    ↓
final price
```

The coupon implementation remains isolated.

---

# 44. Adding Reviews

Similarly:

```text
domains/
└── reviews/
    ├── api/
    ├── application/
    └── domain/
```

Products do not need to be rewritten internally just because reviews exist.

The Product module can expose whatever stable capability the Review module requires.

---

# 45. Configuration

Everything that can safely be configuration-driven belongs in:

```text
app/config/settings.py
```

For example:

```text
DATABASE_URL=
PAYMENT_PROVIDER=
EMAIL_PROVIDER=
STORAGE_PROVIDER=

AUTH_SESSION_STRATEGY=

JWT_SECRET=
COOKIE_DOMAIN=

PAYSTACK_SECRET_KEY=
STRIPE_SECRET_KEY=

STORE_OWNER_EMAIL=
```

Secrets and provider credentials must never be hardcoded. This follows the configuration requirements in the original architecture.

---

# 46. `infrastructure/container.py`

This is the assembly/wiring point.

It decides:

```text
Which database implementation?
Which payment implementation?
Which email implementation?
Which storage implementation?
Which authentication implementation?
```

Conceptually:

```text
settings
   ↓
container
   ├── SQLAlchemy repositories
   ├── selected PaymentGateway
   ├── selected EmailSender
   └── selected StorageProvider
```

This keeps provider selection out of the actual business logic.

---

# 47. `main.py`

`main.py` should primarily bootstrap the application.

Conceptually:

```text
main.py
   ↓
load configuration
   ↓
initialize infrastructure
   ↓
initialize dependency container
   ↓
register API routers
   ↓
configure middleware/protection
   ↓
start FastAPI
```

It should not become the place where business logic is implemented.

---

# 48. API Registration

The route hierarchy can be:

```text
app/api/router.py
```

which includes:

```text
/auth
/users
/products
/cart
/wishlist
/orders
/payments
/admin
```

Then each domain owns its own router.

For example:

```text
api/router.py
    ↓
domains/auth/api/router.py
domains/products/api/router.py
domains/cart/api/router.py
domains/orders/api/router.py
domains/payments/api/router.py
domains/admin/api/router.py
```

This follows your requirement for routes to be grouped by domain/feature and kept separate from business logic.

---

# 49. Error Handling

Errors should also remain standardized.

For example:

```text
401
Unauthenticated

403
Authenticated but not permitted

404
Resource not found

409
Conflict

422
Validation failure
```

The API converts internal/application errors into HTTP responses.

The domain itself should not need to raise:

```python
HTTPException(...)
```

because HTTP is an API concern.

---

# 50. Testing Structure

Each boundary can be tested independently.

```text
tests/
├── unit/
│   ├── auth/
│   ├── products/
│   ├── orders/
│   ├── payments/
│   └── security/
│
├── integration/
│   ├── database/
│   ├── payments/
│   └── email/
│
└── api/
```

Examples:

```text
PaymentService
    ↓
mock PaymentGateway
```

Then you can test:

```text
successful payment
failed payment
verification failure
duplicate payment
refund
```

without contacting Paystack or Stripe.

The architecture explicitly calls for provider integrations to be mockable and for security/business logic to be independently testable.

---

# 51. The Dependency Rules

These should become explicit project rules.

### Rule 1

```text
Router → Service
```

Not:

```text
Router → Database
```

---

### Rule 2

```text
Service → Domain interfaces
```

Not:

```text
Service → Paystack SDK
```

---

### Rule 3

```text
Infrastructure → Domain interfaces
```

Infrastructure implements the contracts.

---

### Rule 4

```text
Domain does not import FastAPI
```

---

### Rule 5

```text
Domain does not import SQLAlchemy
```

---

### Rule 6

```text
Order domain does not import Stripe/Paystack
```

---

### Rule 7

```text
Frontend never bypasses backend authorization
```

---

### Rule 8

```text
Frontend navigation and backend authorization are separate concerns
```

---

# 52. Final Architecture

The whole backend can therefore be understood as:

```text
                         FRONTEND
                            │
                            │ HTTPS
                            ▼
                    ┌───────────────┐
                    │      API      │
                    │   FastAPI     │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ APPLICATION   │
                    │   SERVICES    │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    DOMAIN     │
                    │ Business Rules│
                    │  Interfaces   │
                    └───────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
        Persistence      Payments       Email
         Interface       Interface      Interface
              ▲             ▲             ▲
              │             │             │
              ▼             ▼             ▼
        SQLAlchemy       Paystack       Resend
              │          Stripe         etc.
              ▼
         PostgreSQL
```

Security surrounds the API:

```text
                         API
                          │
             ┌────────────┼────────────┐
             │            │            │
      Authentication  Authorization  Protection
             │            │            │
          "Who?"       "Allowed?"    "Safe?"
```

---

# 53. Complete Customer → Payment → Admin Flow

The complete business flow is:

```text
Customer
   │
   ▼
Next.js storefront
   │
   ▼
Cart API
   │
   ├── Guest → guest cart
   │
   └── Logged in → user cart
   │
   ▼
Checkout
   │
   ├── Unauthenticated
   │      ↓
   │   Login / Signup
   │      ↓
   │   Merge guest cart
   │      ↓
   │   Checkout
   │
   └── Authenticated
          ↓
       Confirm Order
          ↓
       Order Service
          ↓
       PENDING_PAYMENT
          ↓
       Payment Service
          ↓
       PaymentGateway
          ↓
    ┌─────┴──────┐
    │            │
 Paystack      Stripe
    │            │
    └─────┬──────┘
          ↓
       Customer Pays
          ↓
    Backend Verification
          ↓
    Transaction = PAID
          ↓
      Order = PAID
          │
    ┌─────┴────────────┐
    │                  │
    ▼                  ▼
Store Owner Email    Database
                         │
                         ▼
                  Admin Dashboard
                         │
                         ▼
              Admin Authentication
                         │
                         ▼
                  Admin Authorization
                         │
                         ▼
                Order/Product APIs
```

---

# 54. The Governing Question

For every new feature, the implementation process should ask:

> **How difficult will it be to add this feature without breaking existing features?**

Examples:

```text
Add Stripe
    ↓
new adapter + configuration
    ↓
existing order logic remains

Add Flutterwave
    ↓
new adapter + configuration
    ↓
existing order logic remains

Add Vendor
    ↓
new domain + permissions
    ↓
existing customer logic remains

Change PostgreSQL implementation
    ↓
new infrastructure implementation
    ↓
business logic remains

Change email provider
    ↓
new email adapter
    ↓
payment/order logic remains
```

That is the practical definition of **swap-ability + isolation + scalability** for this project.

---

# 55. Final Boundary Summary

| Component             | Knows                       | Must NOT know                   |
| --------------------- | --------------------------- | ------------------------------- |
| Frontend Router       | UI navigation               | DB internals                    |
| API Router            | HTTP                        | Payment/database implementation |
| Auth Service          | Authentication rules        | Checkout internals              |
| Security dependencies | Current user/role           | Business operations             |
| Domain Service        | Business rules              | HTTP/provider SDKs              |
| Repository Interface  | Required data capability    | DB implementation               |
| SQLAlchemy Repository | SQLAlchemy/PostgreSQL       | Frontend/payment logic          |
| Payment Service       | Payment business flow       | Paystack/Stripe internals       |
| PaymentGateway        | Payment capability contract | Provider implementation         |
| Paystack Adapter      | Paystack                    | Order business logic            |
| Stripe Adapter        | Stripe                      | Order business logic            |
| Email Interface       | Send-message capability     | Email provider details          |
| Email Adapter         | Email provider              | Order business rules            |
| Admin Service         | Admin capabilities          | Frontend UI details             |
| Config                | Runtime choices/secrets     | Business logic                  |

The result is that every major subsystem has a **stable contract** and a replaceable implementation. That is the structure I would use as the foundation for the FastAPI backend rather than the simpler `router/service/repository/model` layout alone. It also stays consistent with your original requirements for modularity, provider isolation, configuration-driven integrations, testing, and exact frontend/backend contracts.



Dependencies
Python                3.14.7

fastapi               0.141.1
starlette             1.6.0
uvicorn[standard]     0.53.0

pydantic              2.13.5
pydantic-settings     2.15.0
python-dotenv         1.2.3
email-validator       2.3.0

sqlalchemy             2.0.54
asyncpg                0.31.0
alembic                1.20.0

httpx                  0.28.1

pwdlib                 0.3.1
argon2-cffi            25.1.0
PyJWT                  2.14.0

stripe                 15.6.1
resend                 2.47.0
cloudinary             1.46.2
boto3                  1.43.24

redis                  8.1.0
fastapi-limiter        0.2.0
pyrate-limiter         4.5.0

pytest                 9.1.1
pytest-asyncio         1.4.0
pytest-cov             7.1.0
ruff                   0.16.8

use pyproject.toml and uv.lock

should be built inside the .venv
use .\.venv\Scripts\Activate.ps1 to activate it

---

# Appendix A — Implementation record (as-built)

This appendix documents the system **as it was actually built**, phase by phase
under a strict one-gated-phase-at-a-time workflow (implement → run that phase's
gate verbatim → PASS → report → commit `phase-NN` → stop). It complements the
prescriptive design above, which remains the authoritative specification.

## What was delivered

Every module in the target structure exists and is exercised by the suite
(637 tests, ~97% coverage as of the closing audit):

- **Domains** — `auth`, `users`, `products`, `categories`(read), `cart`,
  `wishlist`, `orders`, `payments`, `admin`, each split into `domain` /
  `application` / `api` /
  `infrastructure` layers.
- **Security** — JWT-cookie sessions, Argon2 password hashing (pwdlib),
  role/permission RBAC, and a `protection` layer (CORS, security headers,
  request-validation handling, a pluggable rate limiter).
- **Infrastructure** — a SQLAlchemy 2.0 async persistence layer behind
  repository interfaces, a unit of work, and a single **composition root**
  (`app/infrastructure/container.py`) that is the only place providers and
  repositories are selected and wired.
- **Integrations** — provider adapters behind contracts for payments
  (Paystack + Stripe), email (Resend), and storage (Cloudinary + S3), each
  chosen by configuration (`PAYMENT_PROVIDER`, `EMAIL_PROVIDER`,
  `STORAGE_PROVIDER`) so business logic never names a provider.

The Phase 18 compliance audit codified the dependency-direction rules as AST
guard tests in `tests/unit/test_architecture.py`: no domain/application/router
couple imports SQLAlchemy or FastAPI, provider SDKs stay inside
`app/integrations/*/`, and the domain layer reaches only the shared kernel and
sibling domain contracts.

## Errors and lessons encountered during implementation

Recorded so the same traps are not re-discovered:

- **One event loop for the whole test session.** The FastAPI test client is
  session-scoped and drives a lazily-created global async engine. Opening that
  engine on a second event loop (a per-test `TestClient` context) deadlocks or
  errors, so a single shared `client` fixture is used and API tests seed through
  repositories on short-lived engines they dispose themselves.
- **A startup/shutdown lifespan must not dispose the shared engine mid-suite.**
  Once `main.py` grew a lifespan that builds the session factory on boot and
  disposes it on shutdown, boot/health checks had to construct
  `TestClient(create_app())` *without* entering the context manager, or the
  session-scoped engine would be torn down under later tests.
- **The dev database accumulates rows across runs.** List endpoints that order
  oldest-first (products, customers) cannot be asserted by "it is on page one";
  membership tests page through the full result set. Newest-first lists (admin
  orders) are safe on the first page.
- **Webhook idempotency is an ordering property.** A provider event must be
  recorded under its provider event-id *before* any state changes, so a
  redelivery is recognised as seen and does nothing twice — one payment, one
  paid order, one email. Amounts that contradict the local order are recorded
  and *disputed*, not trusted.
- **Confirm-a-payment and notify-the-store are separate concerns.** Email is
  triggered on the single transition to PAID and is allowed to fail without
  un-paying an order.
- **f-strings that build literal OpenAPI paths** must escape the braces
  (`{{product_id}}`), or the template variable is evaluated as Python.
- **Case-insensitive filesystems** cannot hold both `architecture.md` and
  `ARCHITECTURE.md`; the spec file is renamed (via git) to the uppercase
  deliverable name the roadmap and this document's own tree call for.
- **Rate limiting is implemented but not yet attached to routes** — the
  `rate_limit` dependency factory exists and is exported; no endpoint consumes
  it yet (Not Specified which routes must be limited).
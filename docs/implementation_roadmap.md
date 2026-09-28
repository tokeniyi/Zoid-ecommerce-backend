# Zoid Jerseys Backend — Agent Implementation Roadmap

## Purpose

This document converts the backend architecture into a sequence of small, independently verifiable implementation phases.

The coding agent must work **strictly phase-by-phase**. It must not jump ahead, redesign the architecture, or add unspecified functionality.

The governing question for every phase is:

> **How difficult will it be to add this feature without breaking existing features?**

---

# 1. Non-Negotiable Agent Rules

## Rule 1 — Architecture is the source of truth

Implement only what is defined in the architecture and this roadmap.

If a required behavior is not specified:

```text
Do not guess.
Mark it: "Not Specified in Architecture."
Stop that decision at the current phase.
```

## Rule 2 — One phase at a time

The agent must:

```text
Implement phase
    ↓
Run the phase tests
    ↓
Run the required quality checks
    ↓
PASS → report completion
FAIL → fix only the current phase
```

The agent must not start the next phase until the current phase gate passes.

## Rule 3 — Small changes only

Each phase should introduce one coherent capability. Avoid large rewrites.

## Rule 4 — No provider leakage

Business/application code must never import provider SDKs directly.

Examples:

```text
Order/Payment service → PaymentGateway
not
Order/Payment service → stripe / paystack
```

```text
Application → EmailSender
not
Application → resend
```

```text
Application → repository interface
not
Application → SQLAlchemy/PostgreSQL implementation
```

## Rule 5 — Domain isolation

Domain code must not depend on:

```text
FastAPI
SQLAlchemy
PostgreSQL
provider SDKs
HTTP-specific exceptions
frontend code
```

## Rule 6 — Backend is the authority

Frontend navigation may improve UX, but backend authentication and authorization must always independently protect protected endpoints.

## Rule 7 — Secrets are configuration

Never hardcode credentials, API keys, passwords, JWT secrets, database URLs, or provider secrets.

Use `.env` locally and `.env.example` as the safe template.

## Rule 8 — Preserve the supplied dependency set

Use the exact versions supplied in the architecture unless a dependency-resolution failure proves that the stated set cannot be installed together. Do not silently upgrade or replace packages.

## Rule 9 — Use the virtual environment

All Python commands must run inside:

```text
.venv
```

Windows PowerShell activation:

```powershell
.\.venv\Scripts\Activate.ps1
```

Use `uv run ...` or the activated environment; do not install project dependencies globally.

## Rule 10 — Commit after every passed gate

After a phase passes:

```text
Review changes
↓
Run gate again
↓
Commit
↓
Proceed to next phase only after the commit exists
```

A recommended commit format is:

```text
phase-01: bootstrap project
phase-02: add configuration and shared primitives
phase-03: add persistence foundation
...
```

---

# 2. Required Dependency/Tooling Baseline

## Python

```text
Python 3.14.7
```

## Runtime/application dependencies

```text
fastapi==0.141.1
starlette==1.6.0
uvicorn[standard]==0.53.0
pydantic==2.13.5
pydantic-settings==2.15.0
python-dotenv==1.2.3
email-validator==2.3.0
sqlalchemy==2.0.54
asyncpg==0.31.0
alembic==1.20.0
httpx==0.28.1
pwdlib==0.3.1
argon2-cffi==25.1.0
PyJWT==2.14.0
stripe==15.6.1
resend==2.47.0
cloudinary==1.46.2
boto3==1.43.24
redis==8.1.0
fastapi-limiter==0.2.0
pyrate-limiter==4.5.0
```

## Development/test tooling

```text
pytest==9.1.1
pytest-asyncio==1.4.0
pytest-cov==7.1.0
ruff==0.16.8
```

## Project management files

Required:

```text
pyproject.toml
uv.lock
```

Do not create `requirements.txt` for this project.

---

# 3. Standard Verification Commands

Unless a phase specifies a narrower command, use these checks:

```powershell
uv run ruff check .
uv run pytest
```

For coverage verification when required:

```powershell
uv run pytest --cov=app --cov-report=term-missing
```

For dependency/environment verification:

```powershell
uv lock --check
uv sync
```

For a focused phase test:

```powershell
uv run pytest tests/unit/<area> -q
```

A phase is **PASS** only when:

```text
required tests = PASS
ruff = PASS
lock/environment check = PASS when applicable
no unrelated regressions = PASS
```

---

# 4. Phase Workflow Template

Every phase must follow this exact routine:

```text
1. Read the phase objective.
2. Inspect only the files relevant to the phase.
3. Implement only the listed work.
4. Create/update tests listed in the phase.
5. Run the phase verification commands.
6. If FAIL:
      fix the current phase only.
      rerun verification.
7. If PASS:
      provide a short completion report.
      stop.
8. Human reviews and commits the phase.
9. Agent is then allowed to start the next phase.
```

The agent should not continue after reporting a passed phase unless instructed to continue.

---

# Phase 00 — Repository and Environment Bootstrap

## Objective

Create a clean Python project that can be installed, locked, linted, and tested.

## Build

Create:

```text
backend/
├── app/
│   └── __init__.py
├── tests/
│   └── __init__.py
├── pyproject.toml
├── .env.example
├── .gitignore
├── README.md
└── uv.lock
```

Create the environment using `uv`:

```powershell
uv venv
.\.venv\Scripts\Activate.ps1
```

Configure `pyproject.toml` with the exact dependency versions in Section 2.

Generate/update the lock file:

```powershell
uv lock
uv sync
```

## Tests/Gate

Run:

```powershell
uv lock --check
uv sync
uv run python --version
uv run ruff check .
uv run pytest
```

### PASS condition

All commands succeed and `.venv` plus `uv.lock` exist.

### Stop condition

Do not create application features in this phase.

---

# Phase 01 — Application Bootstrap and Configuration

## Objective

Create the application entry point and centralized runtime configuration.

## Build

Create:

```text
app/
├── main.py
├── config/
│   ├── __init__.py
│   └── settings.py
└── shared/
    ├── __init__.py
    ├── exceptions.py
    ├── result.py
    ├── pagination.py
    └── types.py
```

Configuration must cover the architecture's required runtime choices/secrets, including:

```text
DATABASE_URL
PAYMENT_PROVIDER
EMAIL_PROVIDER
STORAGE_PROVIDER
AUTH_SESSION_STRATEGY
JWT_SECRET
COOKIE_DOMAIN
PAYSTACK_SECRET_KEY
STRIPE_SECRET_KEY
STORE_OWNER_EMAIL
```

Do not invent additional business configuration unless required by implementation.

Create a minimal FastAPI application and health endpoint if needed for bootstrap verification.

## Tests/Gate

Create a configuration test and application-startup test.

Run:

```powershell
uv run pytest tests/unit -q
uv run ruff check .
```

### PASS condition

The FastAPI application imports successfully and settings load from environment variables without hardcoded secrets.

---

# Phase 02 — Persistence Foundation

## Objective

Create database infrastructure without placing SQLAlchemy code in domain/application logic.

## Build

Create:

```text
app/infrastructure/
├── __init__.py
└── persistence/
    ├── __init__.py
    └── sqlalchemy/
        ├── __init__.py
        ├── session.py
        ├── unit_of_work.py
        ├── models/
        │   └── __init__.py
        └── repositories/
```

Implement:

```text
async SQLAlchemy engine/session
Unit of Work boundary
base model/metadata
Alembic integration
```

Use PostgreSQL through `asyncpg`.

Create:

```text
migrations/
├── env.py
├── script.py.mako
└── versions/
```

## Tests/Gate

Add a database integration test proving:

```text
session opens
transaction commits
transaction rolls back
```

Run:

```powershell
uv run pytest tests/integration/database -q
uv run ruff check .
```

### PASS condition

Database infrastructure works and no domain/application module imports SQLAlchemy implementation code.

---

# Phase 03 — Authentication Core

## Objective

Implement authentication as an isolated capability.

## Build

Create:

```text
app/domains/auth/
├── __init__.py
├── api/
│   ├── __init__.py
│   ├── router.py
│   └── schemas.py
├── application/
│   ├── __init__.py
│   └── service.py
└── domain/
    ├── __init__.py
    ├── entities.py
    └── repositories.py
```

Create credential persistence and user persistence contracts.

Create:

```text
app/security/authentication/
├── __init__.py
├── service.py
├── session.py
├── dependencies.py
└── schemas.py
```

Create password abstraction:

```text
app/security/password/
├── __init__.py
├── hasher.py
└── factory.py
```

Use the configured password implementation behind `PasswordHasher`.

Add endpoints:

```text
POST /api/v1/auth/signup
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me
```

The exact session strategy must remain behind the session abstraction. Do not invent an implementation policy beyond the architecture.

## Tests/Gate

Unit tests must cover at least:

```text
valid signup
invalid signup validation
valid password verification
invalid password verification
successful login
failed login
current-user retrieval
logout/session invalidation behavior
```

Run:

```powershell
uv run pytest tests/unit/auth tests/unit/security -q
uv run ruff check .
```

### PASS condition

Authentication works through abstractions and no domain/application code depends directly on password-library or session-library internals.

---

# Phase 04 — Authorization and Endpoint Protection

## Objective

Separate authorization from authentication and add reusable protection dependencies.

## Build

Create:

```text
app/security/authorization/
├── __init__.py
├── roles.py
├── permissions.py
└── dependencies.py
```

Create:

```text
app/security/protection/
├── __init__.py
├── rate_limiter.py
├── cors.py
├── headers.py
└── request_validation.py
```

Implement reusable concepts:

```text
require_authenticated_user
require_admin
role/permission checks
rate limiting
CORS configuration
security headers
request validation
```

Do not duplicate security logic inside individual routers.

## Tests/Gate

Prove:

```text
unauthenticated protected request → 401
authenticated non-admin admin request → 403
authorized admin request → allowed
public route → accessible without authentication
```

Also test rate-limit behavior at the defined boundary without making tests depend on timing randomness.

Run:

```powershell
uv run pytest tests/unit/security tests/api/auth -q
uv run ruff check .
```

### PASS condition

The backend, not the frontend, independently enforces authentication/authorization.

---

# Phase 05 — Users

## Objective

Implement user profile capability separately from authentication internals.

## Build

Create:

```text
app/domains/users/
├── __init__.py
├── api/
│   ├── router.py
│   └── schemas.py
├── application/
│   └── service.py
└── domain/
    ├── entities.py
    └── repositories.py
```

Create SQLAlchemy user/credential/role/address models as specified by the architecture.

Expose the defined self-service user operations.

## Tests/Gate

Test:

```text
get own profile
update own profile
cannot access another user's protected data through self-service endpoint
```

Run:

```powershell
uv run pytest tests/unit/users tests/api -q
uv run ruff check .
```

### PASS condition

User business logic is isolated from SQLAlchemy and HTTP.

---

# Phase 06 — Products, Categories, Variants, and Inventory

## Objective

Create the product catalog and inventory capability.

## Build

Create:

```text
app/domains/products/
├── __init__.py
├── api/
│   ├── router.py
│   └── schemas.py
├── application/
│   └── service.py
└── domain/
    ├── entities.py
    └── repositories.py
```

Create infrastructure models/repositories for:

```text
product
category
product_image
product_variant
inventory
```

Public catalog operations must be available through the product domain.

Do not place admin-only product mutation logic into public product endpoints.

## Tests/Gate

Test:

```text
list products
get product
list categories
product validation
variant validation
inventory validation
```

Run:

```powershell
uv run pytest tests/unit/products tests/api/products -q
uv run ruff check .
```

### PASS condition

Catalog reads and product business rules work without direct database access from the API layer.

---

# Phase 07 — Guest and Authenticated Cart

## Objective

Implement guest carts, authenticated carts, and the cart boundary needed by checkout.

## Build

Create:

```text
app/domains/cart/
├── __init__.py
├── api/
│   ├── router.py
│   └── schemas.py
├── application/
│   └── service.py
└── domain/
    ├── entities.py
    └── repositories.py
```

Create infrastructure models/repositories:

```text
cart
cart_item
```

Support:

```text
create/read guest cart
add item
update item
remove item
read authenticated cart
merge guest cart after authentication
```

The exact duplicate/conflict behavior during merge is **Not Specified in Architecture**. Do not invent it. Isolate the merge strategy so the requirement can be defined later.

## Tests/Gate

Test:

```text
guest creates cart
guest adds item
authenticated user reads own cart
guest cart cannot be read as another user's cart
merge operation is callable through the service boundary
```

Where conflict behavior is unspecified, test only the defined contract and mark the unresolved behavior clearly.

Run:

```powershell
uv run pytest tests/unit/cart tests/api/cart -q
uv run ruff check .
```

### PASS condition

Cart functionality works for both guest and authenticated flows and is ready for checkout.

---

# Phase 08 — Wishlist

## Objective

Add wishlist capability without modifying unrelated domains.

## Build

Create:

```text
app/domains/wishlist/
├── __init__.py
├── api/
│   ├── router.py
│   └── schemas.py
├── application/
│   └── service.py
└── domain/
    ├── entities.py
    └── repositories.py
```

Create:

```text
wishlist
wishlist_item
```

infrastructure models/repositories.

## Tests/Gate

Test add/remove/list behavior and ownership authorization.

Run:

```powershell
uv run pytest tests/unit -q
uv run ruff check .
```

### PASS condition

Wishlist functionality is isolated and all existing tests remain green.

---

# Phase 09 — Orders and Checkout Preparation

## Objective

Create orders independently of payment-provider implementation.

## Build

Create:

```text
app/domains/orders/
├── __init__.py
├── api/
│   ├── router.py
│   └── schemas.py
├── application/
│   └── service.py
└── domain/
    ├── entities.py
    ├── enums.py
    └── repositories.py
```

Create infrastructure models/repositories:

```text
order
order_item
```

Implement the defined order workflow:

```text
authenticated checkout
    ↓
validate cart
    ↓
validate inventory
    ↓
validate pricing
    ↓
create order
    ↓
PENDING_PAYMENT
```

Do not mark an order `PAID` merely because the order endpoint succeeded.

## Tests/Gate

Test:

```text
valid order creation
empty/invalid cart rejection
inventory validation failure
pricing validation failure
order starts in PENDING_PAYMENT
order ownership rules
```

Run:

```powershell
uv run pytest tests/unit/orders tests/api/orders -q
uv run ruff check .
```

### PASS condition

The system can create a valid pending-payment order without any provider SDK import in the order service.

---

# Phase 10 — Payment Domain Contract

## Objective

Create the provider-independent payment capability before writing Paystack or Stripe code.

## Build

Create/update:

```text
app/domains/payments/
├── __init__.py
├── api/
│   ├── router.py
│   └── schemas.py
├── application/
│   └── service.py
└── domain/
    ├── entities.py
    ├── enums.py
    └── gateway.py
```

Define normalized payment contracts for:

```text
create payment
verify payment
refund payment
payment initiation result
payment verification result
refund result
```

Use provider-independent fields such as:

```text
success
internal transaction id
provider reference
status
checkout URL / next action where required
```

Create transaction/refund/webhook-event persistence models only as required by the architecture.

## Tests/Gate

Mock the `PaymentGateway` and test `PaymentService` without any external provider.

At minimum test:

```text
initiation success
initiation failure
verification success
verification failure
refund success/failure handling
```

Run:

```powershell
uv run pytest tests/unit/payments -q
uv run ruff check .
```

### PASS condition

PaymentService imports no Paystack/Stripe SDK.

---

# Phase 11 — Payment Provider Adapters and Factory

## Objective

Implement provider-specific integrations behind the payment contract.

## Build

Create:

```text
app/integrations/payments/
├── __init__.py
├── paystack.py
├── stripe.py
└── factory.py
```

Each adapter must implement the existing `PaymentGateway` contract.

Provider-specific details belong only inside the relevant adapter:

```text
API request format
provider reference
verification endpoint
provider-specific errors
webhook signature verification
provider response parsing
```

Provider selection must be configuration-driven:

```text
PAYMENT_PROVIDER=paystack
```

or:

```text
PAYMENT_PROVIDER=stripe
```

The application receives `PaymentGateway`, not a concrete provider class.

## Tests/Gate

Unit-test each adapter with mocked HTTP/provider calls.

Test factory selection for:

```text
paystack
stripe
unsupported provider
```

Run:

```powershell
uv run pytest tests/unit/payments tests/integration/payments -q
uv run ruff check .
```

### PASS condition

Switching `PAYMENT_PROVIDER` changes the concrete adapter without changing OrderService or PaymentService.

---

# Phase 12 — Payment Verification, Webhooks, and Idempotency

## Objective

Make payment confirmation authoritative and safe against duplicate events.

## Build

Implement:

```text
provider webhook endpoint
provider signature verification through adapter
normalized webhook/event handling
transaction update
order update
idempotent webhook processing
```

Use:

```text
transaction
webhook_event
refund
```

persistence structures defined by the architecture.

The browser's return URL must never be treated as the sole proof of successful payment.

The backend must verify the payment/provider event through the payment abstraction.

## Tests/Gate

Test:

```text
valid webhook
invalid signature
payment verification success
payment verification failure
duplicate webhook event
already-paid transaction receives same event again
no duplicate state transition
```

Run:

```powershell
uv run pytest tests/unit/payments tests/integration/payments -q
uv run ruff check .
```

### PASS condition

Repeated identical provider events do not cause duplicate business effects.

---

# Phase 13 — Email Capability and Provider Adapter

## Objective

Send post-payment store-owner notifications without coupling payment logic to an email provider.

## Build

Create:

```text
app/integrations/email/
├── __init__.py
├── sender.py
├── resend.py
└── factory.py
```

Define a provider-independent email contract.

The notification/application logic determines the ecommerce message contents.

The provider adapter only knows how to send the message.

After confirmed payment, send the required store-owner email containing the order information defined by the architecture.

## Tests/Gate

Test:

```text
email message construction
successful send
send failure handling
provider factory selection
payment-success path calls EmailSender, not Resend directly
```

Run:

```powershell
uv run pytest tests/unit tests/integration/email -q
uv run ruff check .
```

### PASS condition

PaymentService/application logic depends on the email capability, not the Resend SDK.

---

# Phase 14 — Storage Capability and Adapters

## Objective

Isolate file/object storage behind a provider-independent interface.

## Build

Implement the storage capability required by the architecture using:

```text
Cloudinary
S3-compatible storage
```

Create:

```text
app/integrations/storage/
├── __init__.py
├── cloudinary.py
├── s3.py
└── factory.py
```

The exact storage operations required by product/image handling are **Not Specified in Architecture** beyond the provider-isolation requirement. Define only the minimum capability required by existing application code.

## Tests/Gate

Mock provider calls and verify:

```text
factory selection
upload behavior through interface
provider errors do not leak provider-specific implementation into application code
```

Run:

```powershell
uv run pytest tests/unit -q
uv run ruff check .
```

### PASS condition

Application code knows the storage contract, not Cloudinary/S3 implementation details.

---

# Phase 15 — Admin Domain and Dashboard APIs

## Objective

Implement admin capabilities with backend-enforced RBAC.

## Build

Create:

```text
app/domains/admin/
├── __init__.py
├── api/
│   ├── router.py
│   └── schemas.py
├── application/
│   └── service.py
└── domain/
    └── repositories.py
```

Implement the defined admin endpoints/capabilities, including:

```text
GET  /api/v1/admin/dashboard
POST /api/v1/admin/products
PATCH /api/v1/admin/products/{id}
POST /api/v1/admin/products/{id}/stock
GET  /api/v1/admin/orders
GET  /api/v1/admin/users
```

Protect every admin endpoint with reusable authentication + authorization dependencies.

Admin services must use application/repository boundaries rather than manipulating SQLAlchemy directly.

## Tests/Gate

Test:

```text
admin can access admin endpoints
customer receives 403
anonymous user receives 401
admin product creation/update
admin stock update
admin order retrieval
admin user retrieval
```

Run:

```powershell
uv run pytest tests/unit/admin tests/api/admin -q
uv run ruff check .
```

### PASS condition

A non-admin cannot bypass the frontend and gain admin access by calling the API directly.

---

# Phase 16 — API Composition and Dependency Wiring

## Objective

Connect all domain routers and infrastructure implementations through a single composition root.

## Build

Create/update:

```text
app/api/router.py
app/infrastructure/container.py
app/main.py
```

`container.py` is responsible for selecting/wiring:

```text
repositories
PaymentGateway
EmailSender
StorageProvider
auth/session implementation
```

`main.py` is responsible primarily for:

```text
load settings
initialize infrastructure
initialize dependency container
register routers
configure middleware/protection
create FastAPI app
```

The application business logic must not select providers itself.

## Tests/Gate

Run the complete API startup and route registration tests.

Run:

```powershell
uv run pytest tests -q
uv run ruff check .
uv lock --check
uv sync
```

### PASS condition

All routers register successfully and the application can boot with configured implementations.

---

# Phase 17 — End-to-End Customer Flow

## Objective

Verify the complete customer purchase path from cart to paid order.

## Required flow

```text
Browse products
    ↓
Guest cart
    ↓
Checkout attempt
    ↓
Login/signup when required
    ↓
Guest cart merge
    ↓
Checkout
    ↓
Create PENDING_PAYMENT order
    ↓
Payment initiation
    ↓
Provider checkout
    ↓
Backend verification/webhook
    ↓
Transaction = PAID
    ↓
Order = PAID
    ↓
Email notification
    ↓
Admin can read order
```

## Tests/Gate

Create an API/integration test that exercises the full flow using mocked external providers.

Verify:

```text
unauthenticated protected APIs return 401
authenticated checkout succeeds
order begins PENDING_PAYMENT
payment provider is called through PaymentGateway
successful verification changes transaction/order state
duplicate webhook does not repeat side effects
email is triggered after confirmed payment
admin API can read the paid order
```

Run:

```powershell
uv run pytest tests -q
```

### PASS condition

The complete business path works without requiring live Paystack/Stripe/Resend calls.

---

# Phase 18 — Final Architecture Compliance Audit

## Objective

Prove that the implementation still follows the intended architecture.

## Audit checklist

Search for forbidden coupling:

```text
Domain → FastAPI                  MUST NOT EXIST
Domain → SQLAlchemy               MUST NOT EXIST
Domain/Application → Stripe       MUST NOT EXIST
Domain/Application → Paystack     MUST NOT EXIST
Domain/Application → Resend       MUST NOT EXIST
Application → Cloudinary SDK      MUST NOT EXIST
Application → boto3                MUST NOT EXIST
Router → direct SQLAlchemy         MUST NOT EXIST
Frontend authorization only       MUST NOT be the sole security layer
```

Verify boundaries:

```text
Router → Service
Service → domain interfaces
Infrastructure → interfaces
Provider adapters → external providers
```

Verify configuration-driven selection:

```text
PAYMENT_PROVIDER
EMAIL_PROVIDER
STORAGE_PROVIDER
AUTH_SESSION_STRATEGY
```

## Tests/Gate

Run:

```powershell
uv run pytest --cov=app --cov-report=term-missing
uv run ruff check .
uv lock --check
uv sync
```

Then perform a manual architecture audit of imports and dependency direction.

### PASS condition

All automated checks pass and no forbidden dependency direction is present.

---

# Phase 19 — Documentation and Release Readiness

## Objective

Document the implemented system and make the repository reproducible.

## Required documents

```text
docs/
├── ARCHITECTURE.md
├── API.md
├── SECURITY.md
└── PAYMENTS.md
```

Update:

```text
README.md
.env.example
```

README must explain at minimum:

```text
prerequisites
virtual environment setup
PowerShell activation
uv sync
environment variables
how to run the API
how to run tests
how to run linting
how to run migrations
```

## Tests/Gate

Perform a clean-environment reproduction test:

```powershell
uv sync
uv run ruff check .
uv run pytest
```

### PASS condition

Another developer can clone the project, create/activate `.venv`, run `uv sync`, configure `.env`, and execute the test suite without undocumented setup steps.

---

# 5. Phase Completion Report Format

After each successful phase, the agent must report exactly this kind of information:

```text
PHASE: <number> — <name>
STATUS: PASS

Implemented:
- <small list of completed items>

Tests:
- <commands run>

Result:
- <pass/fail summary>

Architecture check:
- <boundary verified>

Next phase:
- <number and name>

STOP.
Wait for instruction to continue.
```

When a phase fails:

```text
PHASE: <number> — <name>
STATUS: FAIL

Failure:
- <exact failing test/check>

Current-phase scope only:
- <what must be fixed>

Do not continue to the next phase.
```

---

# 6. Definition of Done for Every Phase

A phase is not complete merely because the code exists.

It is complete only when:

```text
[ ] Required files exist
[ ] Required behavior is implemented
[ ] Required tests exist
[ ] Required tests pass
[ ] Existing tests still pass
[ ] Ruff passes
[ ] No forbidden dependency was introduced
[ ] No secrets were hardcoded
[ ] Architecture boundaries remain intact
[ ] Human review can be performed from a small diff
[ ] Phase commit can be created
```

---

# 7. Never Skip These Gates

The agent must **not** do this:

```text
Implement auth
    ↓
Implement products
    ↓
Implement payments
    ↓
Run tests at the end
```

It must do this:

```text
Phase 00
  ↓ PASS
Commit
  ↓
Phase 01
  ↓ PASS
Commit
  ↓
Phase 02
  ↓ PASS
Commit
  ↓
...
```

This keeps failures local and makes rollback/debugging easy.

---

# 8. Final Target Structure

After all phases, the backend should match the architecture's intended structure:

```text
backend/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── router.py
│   ├── domains/
│   │   ├── auth/
│   │   ├── users/
│   │   ├── products/
│   │   ├── cart/
│   │   ├── wishlist/
│   │   ├── orders/
│   │   ├── payments/
│   │   └── admin/
│   ├── infrastructure/
│   │   ├── persistence/
│   │   │   └── sqlalchemy/
│   │   └── container.py
│   ├── integrations/
│   │   ├── payments/
│   │   ├── email/
│   │   └── storage/
│   ├── security/
│   │   ├── authentication/
│   │   ├── password/
│   │   ├── authorization/
│   │   └── protection/
│   ├── config/
│   └── shared/
├── migrations/
├── tests/
├── docs/
├── .env
├── .env.example
├── .gitignore
├── alembic.ini
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
└── README.md
```

---

# 9. Agent Start Command

Before implementing Phase 00, the agent must first verify:

```powershell
python --version
uv --version
```

Then:

```powershell
uv venv
.\.venv\Scripts\Activate.ps1
```

Then begin **Phase 00 only**.

The agent must stop after the Phase 00 gate passes and wait for the instruction to continue.

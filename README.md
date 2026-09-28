# Zoid Jerseys Backend

FastAPI backend for the Zoid jersey storefront, built on a modular hexagonal
architecture (domains / security / infrastructure / integrations). Provider
integrations (payments, email, storage), the database, and the auth/session
strategy are all replaceable behind stable internal interfaces and selected by
configuration — never by business logic.

- [Architecture](docs/ARCHITECTURE.md) — design + as-built implementation record
- [API reference](docs/API.md) — every endpoint, auth and behaviour
- [Security](docs/SECURITY.md) — authN/authZ, RBAC, transport protection, secrets
- [Payments](docs/PAYMENTS.md) — gateway contract, settlement, webhook idempotency

## Prerequisites

- **Python 3.14+** (`python --version`)
- **[uv](https://docs.astral.sh/uv/)** (`uv --version`) — manages the virtual
  environment and locked dependencies
- **PostgreSQL** reachable at `DATABASE_URL` (the API and integration tests talk
  to a real database)
- Optional: **Redis** at `REDIS_URL` for the distributed rate limiter

## Virtual environment setup

All commands run from the `backend/` directory. On PowerShell:

```powershell
cd backend
uv venv                        # creates .venv
.\.venv\Scripts\Activate.ps1   # activate the virtual environment (PowerShell)
uv sync                        # install locked dependencies from uv.lock
```

> `uv run <cmd>` also works without activating — it runs the command inside the
> project environment. Activation is shown because the roadmap's setup steps use
> it. If you only ever use `uv run`, activation is optional.

## Environment variables

Copy the template and fill in real values:

```powershell
Copy-Item .env.example .env
```

Settings are read from the environment / `.env` by
[`app/config/settings.py`](app/config/settings.py) (case-insensitive). Every
secret is environment-only and never hardcoded; `.env` is git-ignored.

Key variables (see `.env.example` for the full, annotated list):

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL async DSN (`postgresql+asyncpg://…`) |
| `PAYMENT_PROVIDER` / `EMAIL_PROVIDER` / `STORAGE_PROVIDER` | Which adapter is selected (`paystack`/`stripe`, `resend`, `cloudinary`/`s3`) |
| `AUTH_SESSION_STRATEGY` | Session strategy (`jwt_cookie`) |
| `JWT_SECRET` | Session signing key |
| `PAYSTACK_SECRET_KEY` / `PAYSTACK_WEBHOOK_SECRET` | Paystack credentials + webhook signing |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | Stripe credentials + webhook signing |
| `RESEND_API_KEY`, `STORE_OWNER_EMAIL`, `EMAIL_FROM` | Email provider + owner notification |
| `CLOUDINARY_*` / `S3_*` | Storage provider credentials |
| `REDIS_URL`, `RATE_LIMIT_*` | Rate limiting |
| `CORS_ORIGINS` | Allowed browser origins |

A provider adapter that is selected but has no credentials fails loudly with
`501 ProviderNotConfiguredError` rather than silently falling back. Tests never
require live provider credentials — external providers are mocked.

## Run the API

```powershell
uv run uvicorn app.main:app --reload
```

- Interactive docs: `http://localhost:8000/docs`
- OpenAPI contract: `http://localhost:8000/openapi.json`
- Health probe: `GET http://localhost:8000/health`

## Run migrations

Database schema is managed with **Alembic** (config in `alembic.ini`,
migrations in `migrations/`).

```powershell
uv run alembic upgrade head                 # apply all migrations
uv run alembic downgrade -1                 # roll back one revision
uv run alembic revision --autogenerate -m "describe the change"   # new migration
uv run alembic heads                         # show current head revision
```

## Run the tests

The suite needs a reachable PostgreSQL database (API/integration tests run
against it); provider calls are always mocked.

```powershell
uv run pytest                 # whole suite
uv run pytest tests/unit      # a subset
uv run pytest --cov=app --cov-report=term-missing   # with coverage
```

## Run linting

```powershell
uv run ruff check .           # lint
uv run ruff check . --fix     # autofix where safe
```

## Reproduce from a clean clone

```powershell
git clone <repo> && cd backend
uv venv && .\.venv\Scripts\Activate.ps1
uv sync
Copy-Item .env.example .env    # then set DATABASE_URL etc.
uv run alembic upgrade head
uv run pytest
```

If any step above needs something not written here, that is a bug — please file
it.

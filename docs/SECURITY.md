# Zoid Backend — Security

Security is enforced **in the backend**, never delegated to the frontend. Hiding
an admin control in the UI is not a boundary: every protected operation is
guarded server-side, and the Phase 17 e2e and Phase 15 admin suites prove that a
caller who hits the API directly without the right session gets 401/403.

## Authentication — stateless JWT sessions

Implemented in [`app/security/authentication/`](../app/security/authentication/).

- Credentials are exchanged for a **JWT** signed with `JWT_SECRET`
  (algorithm `JWT_ALGORITHM`, default `HS256`) carrying the subject and role.
- The token is delivered in an **`HttpOnly` cookie** (`COOKIE_NAME`,
  `SameSite=Lax`, `Secure` when `COOKIE_SECURE=true`), so scripts on a
  malicious origin cannot read it. The selected strategy is
  `AUTH_SESSION_STRATEGY` (a single JWT-cookie strategy is implemented; the
  selector is the seam for another).
- A request's identity is derived **only** from a verified session; a caller can
  never assert a user id in a body or path to act as someone else. Ownership of
  carts, orders and payments is resolved from the session subject.
- `get_session_strategy()` / `get_session_service()` are cached at the
  composition layer; verification failures raise `AuthenticationError` (401).

## Password storage

[`app/security/password/`](../app/security/password/) hashes with **Argon2**
(via `pwdlib` / `argon2-cffi`). Plaintext passwords are never stored or logged;
the hasher compares rather than decrypts.

## Authorization — role & permission RBAC

[`app/security/authorization/`](../app/security/authorization/).

- Two roles: `customer`, `admin`. An unknown role string coerces to the
  **least-privileged** role (`customer`).
- Endpoints declare a required `Permission`; the guard resolves it against the
  caller's role. `admin` holds the full permission set (granted as
  `frozenset(Permission)`), so a newly added permission is covered without a
  manual edit; `customer` holds only the four self-service permissions.
- Reusable dependencies:
  - `require_authenticated_user` — any valid session, else **401**.
  - `require_permission(P)` / `require_admin` — permitted role, else **403**
    (authentication composes underneath, so no session is still 401).
- The admin surface is protected at the **router level**
  (`dependencies=[Depends(require_admin)]`), so a route added later is guarded
  by default rather than only if someone remembers to guard it.

## Transport protection

[`app/security/protection/`](../app/security/protection/) installs, via
`configure_protection(app)`:

- **CORS** restricted to `CORS_ORIGINS` with credentials allowed
  (`cors_allow_credentials`).
- **Security headers** on every response — `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, a locked-down
  `Permissions-Policy`, and `Cache-Control: no-store`. `Strict-Transport-Security`
  is added only when `COOKIE_SECURE=true` (i.e. an HTTPS deployment).
- **Request-validation handling** so malformed requests return the standard
  error shape rather than a stack trace.
- **Rate limiting**: a `rate_limit(...)` dependency factory backed by an
  in-memory limiter, swappable for a Redis-backed one (`REDIS_URL`) without
  touching callers. Tunables: `RATE_LIMIT_ENABLED`,
  `RATE_LIMIT_PER_MINUTE` (default 60), `LOGIN_RATE_LIMIT_PER_MINUTE`
  (default 5). **Status: implemented but not yet attached to specific routes** —
  which endpoints must be limited is Not Specified in the architecture, so no
  wiring was invented.

## Secrets handling

Every secret is read from the environment / `.env` (see
[`app/config/settings.py`](../app/config/settings.py)); none is hardcoded. Secret
fields are declared with `repr=False` so they are redacted from logs and tracebacks.
`.env` is git-ignored; `.env.example` carries only non-secret placeholders.
Provider adapters raise `ProviderNotConfiguredError` (501) rather than silently
falling back when a selected provider has no credentials.

## Payment webhooks

Provider notifications cannot hold a customer session, so they are authenticated
by **signature**: the raw body is verified (Paystack: HMAC-SHA512 over the exact
bytes with `PAYSTACK_WEBHOOK_SECRET`) *before* anything reads what it claims. A
forged or unsigned notification is refused (400) and never recorded as received.
See [PAYMENTS.md](PAYMENTS.md).

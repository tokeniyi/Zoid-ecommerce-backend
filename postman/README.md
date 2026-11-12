# End-to-end API suite (Postman)

A Postman collection that drives **every endpoint** of the real backend: 330
requests, ~600 assertions, covering all 45 API operations. It runs unchanged in the
Postman app, Newman or the **Postman CLI**.

## Run it

```bash
POSTMAN_BIN=/path/to/postman ./postman/run.sh     # `postman` if it is on your PATH
```

Needs PostgreSQL (`psql`) and Redis reachable locally, `uv`, `python3`, and the
Postman CLI. The script:

1. builds a throwaway database (`zoid_e2e`) and migrates it;
2. seeds it with the real commands (`seed_catalog`, `seed_delivery`, `create_admin`);
3. starts the stand-in Paystack/S3 server (`mock_services.py`) and the API, wired
   together through the documented environment variables;
4. regenerates the collection, **fails if any API operation has no request**, and runs it;
5. stops everything and exits non-zero if any assertion failed.

Database access uses the standard libpq variables: `export PGPASSWORD=...` first (and
`PGUSER`/`PGHOST` if it isn't `postgres@localhost`), or use `~/.pgpass`. No password is
built into the scripts. Other variables: `E2E_DB`, `API_PORT` (8000), `MOCK_PORT`
(9100), `ADMIN_EMAIL`. The admin password and JWT secret are random per run.
`./postman/run.sh --serve` starts the stack and leaves it running, for poking at by hand.

To use the collection in the Postman app instead, import
`zoid-backend.postman_collection.json` and `local.postman_environment.json`, start the
stack with `--serve`, and set the environment's `adminPassword` to the one it printed.

## What is (and isn't) real

* The API, database, migrations, seeds, sessions, cookies, CORS and validation are all
  real. Nothing in the backend is stubbed.
* **Payments** go through the real Paystack adapter to a local stand-in
  (`PAYSTACK_BASE_URL`). The stand-in remembers each payment's amount and reports
  "success" only after a test plays the customer (`/__mock/pay/{ref}`, optionally with
  the wrong amount). Webhooks are signed with the same HMAC-SHA512 over the raw body
  that Paystack uses. Real Paystack would add card entry on its hosted page, which no
  API test can drive; use Paystack **test keys** for that final check.
* **Image uploads** go through the real S3 adapter (boto3) to the same stand-in, which
  stores the bytes so a test can fetch the returned URL and compare them.
* **Email** is not exercised (no provider is configured); it is covered by unit tests.
* **Rate limiting** is switched off for the run (a 5/minute login limit would fight a
  test suite) and is covered by unit tests.

## How it is built

`build_collection.py` generates the collection, so ~330 requests with shared helpers
are reviewable as code, and expected catalog results are derived from the same seed
data the backend loads. The collection tells one story in dependency order: catalog,
delivery quotes, accounts, guest cart, merge and wishlist, checkout, payments, admin
operations, admin catalog, archives, an access-control sweep (every admin route is
refused to anonymous callers and customers), and transport hygiene (CORS, headers,
error shape).

**Identities.** The suite plays a guest, two shoppers and an admin, but the runner has
one cookie jar and cookies are per host. So each person gets their own loopback address
(`127.0.0.11`, `.12`, ...; all reach the same server) and their cookies can never mix.
That is why `run.sh` binds the API to `0.0.0.0` for the run, and why the credentials
are random.

**Keeping it honest.** `check_coverage.py` compares the collection with the live
OpenAPI document, so a new endpoint with no request fails the run. The suite was also
checked by mutation: re-introducing two real bugs (an archived product still served;
delivery missing from an order total) each made it fail on exactly the relevant
assertion.

## Regenerating

```bash
python3 postman/build_collection.py      # rewrites the two JSON files here (no secrets)
```

## Note on the Postman CLI in restricted networks

The CLI opens background connections to `gateway.postman.com`, `events.getpostman.com`
and `ra.gw.postman.com`. If a firewall blocks them, the CLI crashes mid-run with
`ECONNRESET` after a few seconds, regardless of your collection. Allow those hosts (or
run with Newman).

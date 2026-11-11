#!/usr/bin/env bash
# Run the whole API collection against a real, freshly built backend.
#
#   POSTMAN_BIN=/path/to/postman ./postman/run.sh          # build, run, report, clean up
#   ./postman/run.sh --serve                                # just start everything and wait
#
# What it does, in order:
#   1. creates a throwaway database ($E2E_DB, default zoid_e2e) and migrates it
#   2. seeds it with the real commands (catalog, delivery rates, one admin)
#   3. starts the stand-in Paystack/S3 server and the API, wired to each other
#   4. regenerates the collection and runs it with the Postman CLI
#   5. stops everything and exits non-zero if any assertion failed
#
# Needs: PostgreSQL (psql) and Redis reachable locally, `uv`, python3, and the Postman CLI.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
POSTMAN_BIN="${POSTMAN_BIN:-postman}"
export PGHOST="${PGHOST:-localhost}" PGUSER="${PGUSER:-postgres}" PGPASSWORD="${PGPASSWORD:-postgres}"
E2E_DB="${E2E_DB:-zoid_e2e}"
API_PORT="${API_PORT:-8000}"
MOCK_PORT="${MOCK_PORT:-9100}"
WORK="${WORK_DIR:-$(mktemp -d)}"
mkdir -p "$WORK"
ADMIN_EMAIL="${ADMIN_EMAIL:-owner@zoidjerseys.com}"
# Random per run: the API is bound to all loopback addresses (see below), so it must
# not be guessable. (Both only ever exist for the lifetime of this script.)
ADMIN_PASSWORD="${ADMIN_PASSWORD:-e2e-$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')}"
export JWT_SECRET="${JWT_SECRET:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')}"
WEBHOOK_SECRET="whsec_e2e_mock"
SERVE_ONLY=0
[ "${1:-}" = "--serve" ] && SERVE_ONLY=1

PIDS=()
cleanup() { for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

say "database $E2E_DB"
psql -q -d postgres -c "DROP DATABASE IF EXISTS $E2E_DB" -c "CREATE DATABASE $E2E_DB"

# The backend, configured entirely through its documented environment variables.
export APP_ENV=development
export DATABASE_URL="postgresql+asyncpg://$PGUSER:$PGPASSWORD@$PGHOST:5432/$E2E_DB"
export RATE_LIMIT_ENABLED=false
export CORS_ORIGINS="http://localhost:3000"
export PAYMENT_PROVIDER=paystack
export PAYSTACK_SECRET_KEY=sk_test_e2e_mock
export PAYSTACK_WEBHOOK_SECRET="$WEBHOOK_SECRET"
export PAYSTACK_BASE_URL="http://127.0.0.1:$MOCK_PORT"
export PAYMENT_RETURN_URL="http://localhost:3000/checkout"
export STORAGE_PROVIDER=s3
export S3_ENDPOINT_URL="http://127.0.0.1:$MOCK_PORT"
export S3_BUCKET=zoid-e2e S3_REGION=us-east-1
export S3_ACCESS_KEY_ID=e2e S3_SECRET_ACCESS_KEY=e2e-secret
export STORAGE_PUBLIC_BASE_URL="http://127.0.0.1:$MOCK_PORT/zoid-e2e"
export MAX_UPLOAD_BYTES=200000
export ZOID_ADMIN_PASSWORD="$ADMIN_PASSWORD"

cd "$ROOT"
say "migrate + seed"
uv run alembic upgrade head >/dev/null 2>"$WORK/alembic.log" || { cat "$WORK/alembic.log"; exit 1; }
uv run python -m app.cli.seed_catalog
uv run python -m app.cli.seed_delivery
uv run python -m app.cli.create_admin --email "$ADMIN_EMAIL" --name "E2E Owner"

say "start stand-in services (port $MOCK_PORT) and the API (port $API_PORT)"
python3 "$HERE/mock_services.py" "$MOCK_PORT" >"$WORK/mock.log" 2>&1 & PIDS+=($!)
# 0.0.0.0, not 127.0.0.1: the collection gives each person their own loopback address
# (127.0.0.11, .12, ...) so that their cookies cannot mix, and all of them must answer.
uv run uvicorn app.main:app --host 0.0.0.0 --port "$API_PORT" >"$WORK/api.log" 2>&1 & PIDS+=($!)
for _ in $(seq 1 40); do
  curl -fs "http://localhost:$API_PORT/health" >/dev/null 2>&1 \
    && curl -fs "http://127.0.0.1:$MOCK_PORT/__mock/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fs "http://localhost:$API_PORT/health" >/dev/null || { echo "API did not start"; cat "$WORK/api.log"; exit 1; }
echo "API: http://localhost:$API_PORT   stand-ins: http://127.0.0.1:$MOCK_PORT   logs: $WORK"

if [ "$SERVE_ONLY" = 1 ]; then
  echo "serving; press Ctrl-C to stop"
  wait
  exit 0
fi

say "build collection"
python3 "$HERE/build_collection.py" --out-dir "$WORK/postman" \
  --base-url "http://localhost:$API_PORT" --api-port "$API_PORT" --mock-url "http://127.0.0.1:$MOCK_PORT" \
  --admin-email "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" --webhook-secret "$WEBHOOK_SECRET"

say "coverage: every API operation must be exercised"
python3 "$HERE/check_coverage.py" "http://localhost:$API_PORT/openapi.json" "$WORK/postman"

say "run with the Postman CLI"
OUT="$WORK/postman.txt"
set +e
# --working-dir is where the upload fixture (fixtures/pixel.png) is found.
(cd "$WORK/postman" && "$POSTMAN_BIN" collection run zoid-backend.postman_collection.json \
  -e local.postman_environment.json --working-dir "$HERE" --no-report-events) >"$OUT" 2>&1
set -e
cat "$OUT"

# The CLI can crash *after* printing its results while trying to reach Postman's
# cloud, so its exit code says nothing about the tests. The results table does.
failed="$(awk -F'|' '/\| *(requests|test-scripts|prerequest-scripts|assertions) /{gsub(/ /,"",$4); s+=$4} END{print s+0}' "$OUT")"
executed="$(awk -F'|' '/\| *assertions /{gsub(/ /,"",$3); print $3}' "$OUT")"
say "result: ${executed:-0} assertions executed, $failed failed"
if [ -z "${executed:-}" ] || [ "$executed" = 0 ]; then echo "no results found"; exit 2; fi
[ "$failed" = 0 ] || exit 1

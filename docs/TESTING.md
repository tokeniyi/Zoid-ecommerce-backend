# Testing

## The test database

Tests that touch PostgreSQL are marked `database` (`pytestmark =
pytest.mark.database`) and run only against `TEST_DATABASE_URL`. They never fall
back to `DATABASE_URL`. The harness (`tests/conftest.py`,
`tests/support/database.py`) accepts a URL only when:

- the driver is `postgresql+asyncpg`;
- the database name contains `test` as a distinct token (`zoid_test`, not
  `latest`);
- the host is `localhost`, `127.0.0.1`, `::1` or the compose service `postgres`,
  unless `ALLOW_REMOTE_TEST_DATABASE=1` is set (for a CI database service).

Anything else stops the run before a single test executes.

For each run, the harness:

1. Drops and recreates the test database's `public` schema, then applies the
   real Alembic chain (`upgrade head`). This happens once, before the first
   database test.
2. Truncates every application table **before each database test**, except
   reference data seeded by migrations (`roles`). A crashed test cannot leak
   rows into the next one.
3. Truncates once more at the end of the run, leaving the database empty.

Two cases fail closed:

- **A database test is selected without `TEST_DATABASE_URL`.** Collection stops
  with an error naming the test.
- **No `TEST_DATABASE_URL` is set.** `DATABASE_URL` is replaced for the run by
  an address that refuses connections. An unmarked test that reaches for the
  database fails instead of writing to your development database.

Tests are not safe to run in parallel against one test database. Every worker
would truncate the same tables.

### One-time setup

```powershell
docker compose up -d postgres
docker compose exec postgres createdb -U postgres zoid_test
```

`TEST_DATABASE_URL` can live in your environment or in `.env` (see
`.env.example`). The environment wins.

## Commands

```powershell
uv run pytest -m "not database"     # fast: no PostgreSQL needed
uv run pytest                       # everything (needs TEST_DATABASE_URL)
uv run pytest tests/api/orders      # one area
uv run ruff check .
```

If an inherited `DEBUG` variable holds a non-boolean value (some toolchains set
`DEBUG=release`), the app fails to import. Set `DEBUG=false` for the run.

A test that runs for longer than 120 s dumps every thread's stack
(`faulthandler_timeout` in `pyproject.toml`). A hang is therefore reported with
its location, not as a silent stall. Importing the application takes several
seconds on Windows, so judge a run's speed by pytest's own reported time, not
wall-clock time.

## Recorded validation run

Use this procedure when a run's result must be evidence: before a PR, or when
investigating a failure. Credentials stay in the environment and never go into
logs or commits. The report goes to `artifacts/`, which git ignores.

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://postgres:<password>@localhost:5432/zoid_test"
$env:DEBUG = "false"
New-Item -ItemType Directory -Force artifacts | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$report = "artifacts/test-validation-$stamp.txt"

@(
  "started_at=$(Get-Date -Format o)",
  "git=$(git rev-parse --short HEAD) $(git branch --show-current)",
  "command=uv run pytest -ra --durations=25",
  "python=$(uv run python --version)",
  "packages=$(uv pip list | Select-String -Pattern '^(pytest|pytest-asyncio|sqlalchemy|alembic|fastapi|asyncpg) ' | ForEach-Object { $_.Line.Trim() })"
) | Set-Content $report

uv run pytest -ra --durations=25 *>&1 | Tee-Object -FilePath $report -Append
"exit_code=$LASTEXITCODE" | Add-Content $report
"finished_at=$(Get-Date -Format o)" | Add-Content $report
```

The pytest header records the redacted test database (`test database: ...`).
The summary line records passed, failed, skipped and errored tests. The
durations table names the slowest tests individually.

**If the run was stopped, timed out, or has no `exit_code`, record it as
incomplete.** An interrupted run is neither a pass nor a fail, and neither is
any subset of it. Note the last test shown and the time limit used. Then rerun
that test alone with `-vv --durations=0`.

## Migration checks

`tests/integration/database/test_migrations.py` runs against the schema built
by the migrations alone. It fails when:

- the models and migrations disagree (the same comparison `alembic revision
  --autogenerate` makes). Add the missing migration;
- the chain has more than one head. Add a merge revision;
- the seeded RBAC roles are missing;
- any `downgrade()` fails to undo its `upgrade()`. The test downgrades to base
  and re-applies the whole chain.

## Not covered yet

- **Rate limiting** is not attached to production routes yet. The routes and
  limits have been decided (login and register at 5/min, payment initiate and
  verify at 60/min). Until they are implemented, the only rate-limit tests
  exercise the limiter on a throwaway app.

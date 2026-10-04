# Spec: platform

Module id: `platform` · Depends on: — · Used by: every module

## Objective

Give every other module a working skeleton: one command to run everything, configuration that fails fast, JSON logs with a request id, and quality gates that run the same way locally and in CI. Nothing in this module knows about fees or refunds.

## Scope

**In scope**
- Repo skeleton matching the structure in `SPEC.md`.
- Docker compose stack, `.env.example`, settings loading.
- Logging, request ids, the injected clock.
- pre-commit hooks, CI workflow, `.gitattributes`, `.gitignore`.
- `git init` in the first task.
- A minimal `GET /health`. The `api` module extends it.

**Out of scope**
- Business tables. These belong to `data`.
- Endpoints other than `/health`. These belong to `api`.
- Deployment. This belongs to `delivery`.

## Docker compose

| Service | Image or build | Role | Ready when |
|---|---|---|---|
| `db` | `postgres:16` | Database. Named volume `pgdata`, so data survives restarts. | `pg_isready` passes |
| `migrate` | backend image | One-shot job: `python -m backend.bootstrap` (migrations, roles, seed, policy clauses). It is safe to run on every start. It is the only service that gets `OWNER_DATABASE_URL` (D-platform-1). | Exits 0 |
| `backend` | backend image | `python -m backend.api` (checks the configuration, then serves on `$PORT`) | `GET /health` returns 200 |
| `frontend` | multi-stage: build with Node, serve with nginx | Serves the built UI on port 8080. Proxies `/api/*` to `backend:8000/*` with the prefix stripped. | nginx is up |

Start order: `db` (healthy) → `migrate` (completed successfully) → `backend` (healthy) → `frontend`.

**Ports**
- `8080` is the app. Port 8000 is also exposed so the API and its OpenAPI docs can be reached directly.
- Through nginx, the backend's routes match the brief exactly (`/health`, `/cases`, …) under `/api`.

**Rules**
- The backend image runs as a non-root user.
- No secrets are baked into images.

**Deploy-ready from day one.** The deploy itself happens last (`SPEC-delivery.md`), but these keep it a config-only step:
- The nginx upstream is templated from `BACKEND_URL` (`envsubst`), with `http://backend:8000` as the local default. The same frontend image works locally and on the host, including SSE (`proxy_buffering off` on the events route).
- The backend binds to `${PORT:-8000}`.
- `uv run python -m backend.bootstrap` runs migrations, roles, the seed and the policy loader as one idempotent command. `--reset` restores the demo state. The `migrate` service uses it, and the host's pre-deploy step will too. It is owned by `api` (see `SPEC-data.md`).

## Configuration

Settings use `pydantic-settings` and load from the environment. Startup fails with one plain line naming the bad variable. It never prints the value.

| Variable | Example in `.env.example` | Notes |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `fees`, `change-me`, `fees` | For the `db` service |
| `APP_DATABASE_URL` | `postgresql+psycopg://app_writer:change-me@db:5432/fees` | Used by the API and the decision writer. Its user must be `app_writer`; bootstrap sets that role's password from this URL. |
| `AGENT_DATABASE_URL` | `postgresql+psycopg://agent_reader:change-me@db:5432/fees` | Read-only role, used by agent tools. Its user must be `agent_reader`; bootstrap sets that role's password from this URL. |
| `OWNER_DATABASE_URL` | commented out | Owner role, for `backend.bootstrap` only. Compose builds it from `POSTGRES_*` and passes it to `migrate` alone, so `.env` has no active line for it. Set it by hand only to run bootstrap outside compose. |
| `JEV_API_KEY` | empty | Empty puts Jev in replay mode |
| `OPENAI_API_KEY` | empty | Empty puts OpenAI in replay mode |
| `PROVIDER_MODE` | `auto` | `auto`, `live` or `replay`. `auto` means live when the key is present, replay when it isn't |
| `AUTO_APPROVE_ENABLED` | `false` | Shadow mode only (D5). Must stay `false` |
| `STAFF_ID` | `S07` | Seeded identity of the person using the UI (Luis) |
| `RATE_LIMIT` | `60/minute` | Per client, on the API |
| `LOG_LEVEL` | `INFO` | |
| `MASKING_SALT` | `change-me` | HMAC salt for hashing member ids in logs |
| `EVAL_DATABASE_NAME` | `fees_eval` | Separate database for evals, on the same server and with the same roles. The eval runner derives both role URLs by swapping the database name. |

Thresholds, timeouts and prices live in versioned config files under `backend/core/config/`, not in environment variables. Changing them is an "ask first" change.

## Logging and request ids

- Logs are structlog JSON lines with: `ts`, `level`, `event`, `request_id`, and `run_id` and `case_id` when known.
- **Request id:** the middleware accepts an `X-Request-ID` header if it is a valid UUID and generates one otherwise. It is returned in the response header and bound to every log line of that request.
- **Deny-list processor:** drops keys such as `body`, `message`, `text`, `name`, `first_name`, `last_name`, `account_number` and `email`. It replaces a raw `member_id` with an HMAC hash. This is a safety net; the code must not log these in the first place.
- **Clock:** `backend/core/clock.py` exposes a `Clock` protocol with `now()`. The system clock is used in production and a fixed clock in tests.

## Quality gates

**pre-commit** (`.pre-commit-config.yaml`):
- ruff check (with `--fix`) and ruff format
- mypy `--strict` on `backend` and `evals`
- ESLint and Prettier (check) on `frontend`
- `tsc --noEmit`
- gitleaks
- end-of-file and trailing-whitespace fixers

**CI** (`.github/workflows/ci.yml`) runs on push and pull request, with these jobs:

| Job | What it does |
|---|---|
| `lint` | pre-commit on all files |
| `backend` | `uv run python -m pytest` with a Postgres 16 service container, plus a coverage report |
| `frontend` | Vitest and `tsc` |
| `evals` | Replay evals; fail below 100% |
| `docker` | `docker compose build` |
| `e2e` | Compose stack in replay mode, then Playwright (`SPEC-delivery.md`); uploads traces on failure |

**Line endings:** `.gitattributes` forces LF for `*.sh`, `*.py`, `*.ts` and `*.tsx`, because development happens on Windows and runs in Linux containers.

## Acceptance criteria

1. On a clean clone, `cp .env.example .env && docker compose up --build` reaches a state where `http://localhost:8080` serves the UI shell, and `http://localhost:8080/api/health` returns 200 with `{"status": "ok", "database": "ok", "provider_mode": {"jev": "replay", "openai": "replay"}, "version": "<git sha>"}`.
2. If `db` is stopped, `/health` returns 503 with `"database": "unavailable"`, and the container logs show no stack trace.
3. `PROVIDER_MODE=banana` stops the backend at startup with one line naming `PROVIDER_MODE`.
4. Every backend log line is valid JSON with a `request_id`. A request sent with `X-Request-ID: <uuid>` gets the same id back and in its logs.
5. A unit test proves the deny-list processor removes `message` and hashes `member_id`.
6. `uv run python -m pre_commit run --all-files` passes on the skeleton, and the CI workflow is green on the first push.
7. `docker compose down && docker compose up` keeps the data (named volume), and `migrate` succeeds again without duplicating seed rows.

## Tests

| File | What it covers |
|---|---|
| `tests/unit/core/test_settings.py` | Mode resolution (`auto` with and without keys), invalid values |
| `tests/unit/core/test_logging.py` | Deny-list processor, request-id binding |
| `tests/api/test_health.py` | 200 when the database is up; 503 when it is down (database dependency overridden) |

## Boundaries specific to this module

- **Always:** keep `.env.example` complete. Every variable the code reads has an entry and a comment.
- **Ask first:** adding a service to compose, or changing ports.
- **Never:** commit `.env`, or log settings values.

## Decisions taken in this spec

- **D-platform-1 (2026-10-04, user decision).** The `app_writer` and `agent_reader` login roles are created from the first compose task (T3), not from T8, because `/health` checks the database as `app_writer`. Bootstrap connects as the owner through `OWNER_DATABASE_URL`, which compose builds from `POSTGRES_*` for `migrate` only. Each role's password comes from its own URL. T8 adds the grants, the read-only default and the statement timeout. Rejected: the owner in `APP_DATABASE_URL` until T8 (the API would hold owner rights, and every `.env` would need a manual edit later); accepting a 503 until T8 (breaks the start order and AC1).

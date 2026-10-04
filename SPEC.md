# Spec: Fee Refund Agent

Agentic flow that prepares overdraft-fee refund cases so Luis, a credit union employee, can approve, edit or reject them from one page in seconds. This file holds the capability map and the rules shared by every module. Each module has its own `SPEC-<module-id>.md` next to this file. The agent architecture (decisions D1–D10) is in [docs/agent-design.md](docs/agent-design.md) and is binding.

Status: draft, under review.

## Capability map

| Module id | Responsibility | Depends on | Spec |
|---|---|---|---|
| `platform` | Repo skeleton, docker compose, settings, JSON logs with request id, pre-commit, CI | — | [SPEC-platform.md](SPEC-platform.md) |
| `data` | Migrations (the PDF's tables, extensions, app tables), database roles, seed scenarios, read-only queries | platform | [SPEC-data.md](SPEC-data.md) |
| `policy` | Policy documents, clause search, deterministic rules, reason catalogue (EN/ES) | data | [SPEC-policy.md](SPEC-policy.md) |
| `providers` | Jev and OpenAI adapters, live/replay, timeouts, retries, cost, sanitising and masking | platform | [SPEC-providers.md](SPEC-providers.md) |
| `agent` | LangGraph flow, fallbacks, decision, draft, run persistence, stream events, shadow auto-approve | data, policy, providers | [SPEC-agent.md](SPEC-agent.md) |
| `api` | Endpoints, validation, rate limit, idempotent decision and refund, audit, SSE | agent | [SPEC-api.md](SPEC-api.md) |
| `ui` | Luis's page: queue, case detail, evidence, live steps, approve / edit / reject | api | [SPEC-ui.md](SPEC-ui.md) |
| `evals` | At least 10 cases, replay and live tracks, pass-rate script, Jev vs Luna comparison, with a Sol cost estimate | agent | [SPEC-evals.md](SPEC-evals.md) |
| `delivery` | README, diagrams, end-to-end tests, demo, deployment, MCP (if in scope) | ui, evals | [SPEC-delivery.md](SPEC-delivery.md) |

Build order: `platform → data → policy ∥ providers → agent → api → ui ∥ evals → delivery`

Arrows point one way only. The contract between two modules belongs in the spec of the module that provides it. For example, the API contract that the UI consumes is in `SPEC-api.md`.

## Objective

Today Luis needs a shared inbox, a transactions screen, the core banking system, the policy, his supervisor and a blank reply box to answer one fee refund request. This product puts all of that on one page, already prepared, so he decides with one click.

**User stories**

- As Luis, I open the queue and see each conversation's topic and status, so I know what needs me without opening anything.
- As Luis, I open Ana's case and see what she asked, the fee, the order the transactions posted in, her past refunds, the policy clause that applies, a recommendation and a reply. I approve with one click.
- As Luis, when the agent is unsure or something failed, I see why in plain words and what to do next.
- As Luis, I can edit the reply or reject the recommendation. Sending my decision twice never refunds twice.
- As a reviewer, I run `docker compose up` without API keys and still see the whole flow working on real recorded model answers. The page tells me it is in replay mode.

**Project-level success criteria** (each module spec adds its own):

1. `docker compose up` on a clean clone, with `.env` copied from `.env.example`, serves the app at `http://localhost:8080` with no other steps.
2. Ana's conversation (5012) runs end to end and shows "Ready to refund", with the fee, the posting order, the refund history, the quoted clause and a reply in English. One click refunds $35, and the refund appears in her transactions.
3. Every fallback in the design (Jev down, all classifiers down, Sol down, database timeout, ambiguous fee, manipulation) ends in a status with a plain-language reason. None of them shows a stack trace or an internal id.
4. No path lets customer text change the amount or the decision. This is proven by eval cases.
5. Replay evals run in CI and pass at 100%. A live pass rate is reported separately in the README, with its date and model versions.
6. `uv run python -m pre_commit run --all-files` and CI are green.

## Tech stack

Exact versions are pinned when the project is scaffolded, in `uv.lock` and `frontend/package-lock.json`. Major versions:

- **Backend:** Python 3.14, FastAPI, Pydantic 2, pydantic-settings, SQLAlchemy 2 (async, psycopg 3), Alembic, LangGraph 1.x, `openai` (Responses API), `typesafe-sdk` (Jev), tenacity (retries), structlog (logs), slowapi (rate limit), sse-starlette (SSE).
- **Frontend:** Node 24 LTS, npm, Vite, React 19, TypeScript 5 (strict), Tailwind CSS 4, TanStack Query 5, `openapi-typescript` to generate API types from the backend's OpenAPI schema, and `@fontsource-variable` Inter and Source Serif 4 (self-hosted fonts).
- **Database:** PostgreSQL 16.
- **Tests:** pytest, pytest-asyncio, pytest-cov (coverage report in CI; added 2026-10-04, user decision), Vitest, Testing Library, Playwright, `@axe-core/playwright`.
- **MCP:** the official `mcp` Python SDK (FastMCP).
- **Quality:** pre-commit (a dev dependency, run through `uv run`), ruff (lint and format), mypy `--strict`, ESLint, Prettier, gitleaks.
- **CI:** GitHub Actions.
- **Models:** GPT-6.1 Sol (`gpt-6.1-sol`, "Sol") drafts replies. GPT-6 Luna (`gpt-6-luna`, "Luna") is the classifier fallback. Jev runs every typed classification. Model ids live in config, so a vendor switch means a new adapter, not a new design.

Adding any dependency that is not on this list is an "ask first" change.

## Commands

All commands run from the repo root. Python tools always run as `uv run python -m <tool>`: the dev machine's Smart App Control blocks the per-venv `.exe` launchers that `uv run <tool>` would use, and the `python -m` form works the same on Linux and in CI.

| What | Command |
|---|---|
| Run everything | `docker compose up --build` |
| Install backend | `uv sync` |
| Install frontend | `npm --prefix frontend install` |
| Bootstrap (migrations, roles, seed, policy clauses) | `uv run python -m backend.bootstrap` |
| Reset the demo state (owner role) | `docker compose run --rm migrate python -m backend.bootstrap --reset` |
| Migrations only | `uv run python -m alembic -c backend/db/alembic.ini upgrade head` |
| Backend dev server | `uv run python -m uvicorn backend.api.main:create_app --factory --reload --port 8000` |
| Frontend dev server | `npm --prefix frontend run dev` |
| Regenerate API types | `npm --prefix frontend run gen:api` |
| Unit tests (no database) | `uv run python -m pytest tests/unit` |
| Integration and API tests (need Postgres) | `uv run python -m pytest tests/integration tests/api` |
| All backend tests | `uv run python -m pytest` |
| Frontend tests | `npm --prefix frontend test` |
| End-to-end tests | `npm --prefix frontend run e2e` |
| Lint, format, types | `uv run python -m pre_commit run --all-files` |
| Evals, replay (CI) | `uv run python -m evals.run --mode replay` |
| Evals, live (manual, spends tokens) | `uv run python -m evals.run --mode live` |
| Record new replays (manual, spends tokens) | `uv run python -m evals.run --mode live --record` |

## Project structure

```
backend/
  api/          FastAPI app, routers, request/response schemas, errors, rate limit, SSE
  agents/       LangGraph graph, state, nodes, decide, prompts/
  providers/    Jev and OpenAI adapters, replay store, retries/timeouts, pricing; recordings/
  policy/       policy documents (docs/*.md), clause store and search, rules, reason catalogue
  privacy/      sanitising and masking
  tools/        read-only data queries used by agents (and the MCP server, if in scope)
  db/           SQLAlchemy models, alembic/, seed/, roles
  core/         settings, logging, request id, clock
frontend/
  src/
    api/        generated types and TanStack Query hooks
    features/   queue/, case/
    components/ shared UI pieces
    copy/       every user-facing string (EN)
evals/          cases/, run.py, reports/
tests/
  unit/         pure logic, no database
  integration/  real Postgres: queries, roles, search, idempotency
  api/          HTTP-level tests
  e2e/          Playwright
docs/           agent-design.md, diagrams/
SPEC.md, SPEC-<module>.md, CLAUDE.md, README.md, docker-compose.yml, .env.example
```

One `pyproject.toml` at the root covers `backend` and `evals`. The frontend has its own `package.json`.

## Code style

Python: typed, small pure functions for anything that decides, `Decimal` for money, and plain-language reason codes from one catalogue.

```python
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from backend.policy.reasons import ReasonCode


class RuleResult(BaseModel, frozen=True):
    passed: bool
    reason: ReasonCode | None = None
    clause_id: str


def check_yearly_limit(
    past_refund_dates: list[date],
    fee_date: date,
    max_refunds: int,
    window_days: int,
    clause_id: str,
) -> RuleResult:
    """A member may have at most `max_refunds` fee refunds in the window ending on the fee date."""
    in_window = [d for d in past_refund_dates if 0 <= (fee_date - d).days < window_days]
    if len(in_window) >= max_refunds:
        return RuleResult(passed=False, reason=ReasonCode.YEARLY_LIMIT, clause_id=clause_id)
    return RuleResult(passed=True, clause_id=clause_id)
```

**Python conventions**

- `snake_case` for functions and variables, `PascalCase` for classes.
- Money is always `Decimal`, never `float`. Timestamps are timezone-aware UTC.
- Database access is async SQLAlchemy 2.0 style (`select()`), with no raw string SQL except migrations and roles.
- Nothing that decides reads the wall clock. Dates come from the data, or from an injected clock.
- No `print`. Use the structlog logger. Logs carry ids, never text, names, amounts or account numbers.
- Every external call (models, database tools) goes through a wrapper that applies its timeout and retries.

TypeScript: strict mode, data through TanStack Query hooks, and copy kept out of components.

```tsx
export function useCase(caseId: number) {
  return useQuery({
    queryKey: ["case", caseId],
    queryFn: () => api.getCase(caseId),
    staleTime: 5_000,
  });
}

export function StatusBanner({ status, reasons }: StatusBannerProps) {
  return (
    <section aria-live="polite" className={bannerTone[status]}>
      <h2 className="text-lg font-medium">{copy.status[status]}</h2>
      {reasons.map((r) => (
        <p key={r.code}>{r.message}</p>
      ))}
    </section>
  );
}
```

**TypeScript conventions**

- `camelCase` for variables, `PascalCase` for components, one component per file.
- API types are generated from the backend's OpenAPI schema, never written by hand.
- Every user-facing string lives in `frontend/src/copy/`. It is friendly, plain and direct, with no internal ids or technical terms.
- The UI uses Blossom's colours only, as Tailwind theme tokens: Navy `#001D3D`, Clay `#EFEEED`, Terracotta `#DC634B`, White `#FFFFFF`, plus neutral greys and success and error colours.

## Testing strategy

| Level | Where | What it proves | Tool |
|---|---|---|---|
| Unit | `tests/unit` | Rules, decision precedence, posting-order check, masking, sanitising, reason templates, replay keys, retry policy | pytest |
| Integration | `tests/integration` | Read-only queries against real Postgres; the agent role cannot write; clause search; refund idempotency; migrations upgrade and downgrade | pytest, Postgres |
| Agent | `tests/unit/agents` (decide, triage rules, draft post-check); `tests/integration/agents` (graph scenarios, fallbacks, runner; needs Postgres) | Graph routing and every fallback, using in-process fake providers (not replay files) | pytest |
| API | `tests/api` | Run case 5012 → read case → send decision twice → exactly one refund | pytest, httpx |
| Frontend | `frontend/src/**/*.test.tsx` | Status banner, evidence panel, decision panel states | Vitest, Testing Library |
| End to end | `tests/e2e` | Happy path, one fallback path and accessibility, in a browser, in replay mode | Playwright, axe |
| Evals | `evals/` | Behaviour on labelled cases. Replay in CI must be 100%; live is reported separately | `evals.run` |

**Rules**

- Tests that need a database use a real Postgres: the compose service locally, a service container in CI. No SQLite.
- Coverage: 90% or more lines for `backend/policy`, `backend/privacy` and `backend/agents/decide`; 80% or more for the rest of `backend`.
- Test-driven development is required for rules, decision precedence and masking. Write the failing test first.
- Evals are not tests. They live in `evals/`, and the replay and live pass rates are never combined.

## Boundaries

**Always**

- Follow [docs/agent-design.md](docs/agent-design.md). If a decision needs to change, update that document and this spec first.
- Run `uv run python -m pre_commit run --all-files` and the relevant tests before every commit. Commit one small slice at a time.
- Validate every input with Pydantic at the API edge.
- Put a timeout on every model and tool call, and retry model calls with backoff.
- Mask personal data before any model call or log line.
- Use reason codes from the catalogue. Luis sees templates, never codes.
- Check OpenAI's official docs (Responses API, structured outputs, prompt caching, reasoning effort) before writing code that calls OpenAI models.

**Ask first**

- Adding a dependency that is not in the tech stack above.
- Schema changes beyond what `SPEC-data.md` defines.
- Changing a threshold, policy parameter or timeout default.
- Changing the CI workflow's gates.
- Running live evals or recording replays (it spends tokens).
- Deleting or re-recording committed replays.

**Never**

- Let agents write to the database. The agent's database role is read-only.
- Move money anywhere except `POST /cases/{id}/decision`.
- Send customer text to the drafter (Sol), or let any model decide an amount or an outcome.
- Commit secrets. Keys live only in environment variables.
- Log message text, names, amounts or account numbers.
- Show stack traces, internal ids or technical terms in the UI.
- Skip, delete or weaken a failing test to get to green.
- Combine replay and live pass rates.
- Use `float` for money.
- Change the columns of the tables given in the brief. Extend with new tables instead.

## Open questions

Each one is resolved inside the module spec it belongs to. Numbers refer to [docs/agent-design.md §7](docs/agent-design.md#7-open-questions-for-the-spec).

| # | Question | Module | Status |
|---|---|---|---|
| 1 | Where "good standing" comes from | data | resolved: D-data-1 (derived; fraud not modelled) |
| 2 | Member names | data | resolved: D-data-3 (`member_profiles`) |
| 3 | Rolling 12 months or calendar year | policy | resolved: D-policy-1 (3 of any type, rolling 365 days) |
| 4 | Intent labels; fee questions without a refund ask | agent | resolved: D-agent-1, D-agent-3 |
| 5 | Supervisor flow | api | resolved: D-api-1 (route only; the API refuses refunds above the limit) |
| 6 | How the refund is written | data / api | resolved: D-data-2 (simulated core adapter) |
| 7 | Spec file name | — | resolved: `SPEC.md` plus `SPEC-<module>.md` at the root |
| 8 | Jev access | providers | resolved: we have a Jev API key |
| 9 | "Pick the fee" re-runs the graph | agent | resolved: D-agent-2 (new run with the fee pinned) |
| 10 | Which conversation statuses can run; one active run per case | api | resolved: D-api-2 (manual runs; `waiting_for_bank` and `read_by_bank`; one active run) |
| — | Bonus scope: deployment, MCP, demo format, end-to-end tests | delivery | resolved: D-delivery-1 to D-delivery-3 (all in scope; deploy last, on Render) |

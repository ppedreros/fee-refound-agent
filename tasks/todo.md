# Task list: Fee Refund Agent

The plan and its rationale are in [plan.md](plan.md). Specs: [SPEC.md](../SPEC.md) and `SPEC-<module>.md`.

**Definition of done (every task):**
- the acceptance criteria pass
- `uv run python -m pre_commit run --all-files` and the relevant tests pass, with the output shown
- the behaviour has been verified at runtime
- one commit per task

**Abbreviations:**
- AC = acceptance criterion
- "ask first" = needs the user's yes before running (spends tokens, or is outward-facing)

---

## Phase 1: Foundation (`platform`)

### - [x] T1: Backend skeleton and quality gates
**Description:** The repo already exists, on `main` with remote `origin` (github.com/ppedreros/fee-refound-agent). Add the root `pyproject.toml` (uv, ruff, mypy strict, pytest), pre-commit with the Python hooks and gitleaks, `.gitignore` and `.gitattributes` (LF), and settings with provider-mode resolution. Also a FastAPI app with a stub `/health`.
**Acceptance criteria:**
- [x] `uv sync` works. Settings resolve `auto` to live or replay depending on whether a key is present.
- [x] `PROVIDER_MODE=banana` fails at startup with one line naming the variable (SPEC-platform AC3).
- [x] `uv run python -m pre_commit run --all-files` passes.
**Verification:** `uv run python -m pytest tests/unit/core` · `uv run python -m pre_commit run --all-files`
**Dependencies:** None
**Files:** `pyproject.toml`, `.pre-commit-config.yaml`, `.gitignore` + `.gitattributes`, `backend/core/settings.py`, `backend/api/main.py`, `tests/unit/core/test_settings.py`
**Scope:** M. Config-heavy, so slightly over 5 files; all of them are scaffolding.

### - [x] T2: Frontend skeleton with Blossom tokens
**Description:** Vite, React and TypeScript (strict). Tailwind 4 with the colour tokens from SPEC-ui, the self-hosted fonts, ESLint, Prettier and Vitest. An app shell with a header and two empty panes, and `copy/en.ts`. The JavaScript pre-commit hooks are added too.
**Acceptance criteria:**
- [x] `npm --prefix frontend run build` and `npm --prefix frontend test` pass.
- [x] Tokens `navy`, `clay`, `terracotta`, `white`, the greys, `success` and `error` exist. Terracotta is not used for text anywhere.
- [x] Every string in the shell comes from `copy/en.ts`.
**Verification:** `npm --prefix frontend run build && npm --prefix frontend test` · `uv run python -m pre_commit run --all-files`
**Dependencies:** T1
**Files:** `frontend/package.json`, `frontend/vite.config.ts`, `frontend/src/index.css`, `frontend/src/App.tsx` + `App.test.tsx`, `frontend/src/copy/en.ts` (plus generated config)
**Scope:** M (scaffold)

### - [x] T3: Docker compose stack with a database health check
**Description:** Four services: `db`, `migrate` (runs `backend.bootstrap`, which for now only creates the `app_writer` and `agent_reader` login roles as the owner; D-platform-1), `backend` and `frontend`. The backend image runs as non-root and binds `$PORT`. The frontend nginx config is templated from `BACKEND_URL` and doesn't buffer SSE. There is a named volume, and `.env.example` lists every variable. `/health` checks the database as `app_writer`.
**Acceptance criteria:**
- [x] `cp .env.example .env && docker compose up --build` serves the shell at `:8080`, and `/api/health` returns 200 with `"database": "ok"` (SPEC-platform AC1, apart from the provider fields).
- [x] With `db` stopped, `/health` returns 503 with `"database": "unavailable"` and no trace (AC2).
- [x] `down` then `up` keeps the volume, and `migrate` exits 0 again (AC7). Both roles can log in with the passwords from their URLs.
- [x] A missing or malformed database URL, or a URL whose user isn't the expected role, stops startup with one line naming the variable.
**Verification:** `docker compose up --build`; `curl localhost:8080/api/health`; `docker compose stop db` and curl again · `uv run python -m pytest tests/api/test_health.py tests/unit/core tests/unit/db`
**Dependencies:** T1, T2
**Files:** `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile` + `frontend/nginx.conf.template`, `.dockerignore` files, `.env.example`, `backend/core/settings.py`, `backend/api/routes_health.py`, `backend/db/engine.py`, `backend/db/roles.py`, `backend/bootstrap.py`, `tests/api/test_health.py`, `tests/unit/db/test_login_roles.py`
**Scope:** M (L in files, but most are small config)

### - [x] T4: Logging, request ids, clock
**Description:** structlog JSON logging with a deny-list processor and HMAC-hashed member ids, request-id middleware, and the `Clock` protocol with a fixed clock for tests.
**Acceptance criteria:**
- [x] Every log line is JSON and has a `request_id`. A valid `X-Request-ID` is echoed back (SPEC-platform AC4).
- [x] The deny-list drops `message` and hashes `member_id` (AC5).
**Verification:** `uv run python -m pytest tests/unit/core`; `docker compose logs backend` shows JSON lines
**Dependencies:** T1
**Files:** `backend/core/logging.py`, `backend/api/middleware.py`, `backend/core/clock.py`, `backend/core/settings.py` (`LOG_LEVEL`, `MASKING_SALT`), `backend/api/main.py` + `__main__.py`, `docker-compose.yml`, `tests/unit/core/test_logging.py` + `test_clock.py`
**Scope:** S

### - [x] T5: CI workflow
**Description:** GitHub Actions jobs `lint`, `backend` (with a Postgres 16 service), `frontend` and `docker`. The `evals` and `e2e` jobs are added in T38 and T42.
**Acceptance criteria:**
- [x] The workflow runs on push and pull request, and every job is green on the skeleton.
**Verification:** push to `origin/main`; the Actions run is green
**Dependencies:** T1–T4
**Files:** `.github/workflows/ci.yml`
**Scope:** S

### - [x] T6: Jev spike: one real call, shape documented
**Description:** Read TypeSafe's docs (source-driven). Write the minimal `providers/types.py` and a `JevClassifier` that sends the D-agent triage questions (intent Choice, language, tone, manipulation Noul, multiple-requests Noul) for Ana's message, already masked by hand. Make **one live call**, record the real request and response shape, the latency and the error format in `docs/notes/jev.md`, and reproduce that response in a MockTransport test.
**Acceptance criteria:**
- [x] One live call succeeds with `JEV_API_KEY`. The response maps to `ChoiceAnswer` and `NoulAnswer` with no guessing.
- [x] `docs/notes/jev.md` documents the request, the response, the `confidence` semantics as observed, and the errors (401, 422, timeout). The invalid request came back as 400, not 422; both are documented.
- [x] The MockTransport test passes offline.
**Verification:** `uv run python -m pytest tests/unit/providers/test_jev.py` · the live call output, shown once
**Dependencies:** T1
**Files:** `backend/providers/types.py`, `backend/providers/jev.py`, `tests/unit/providers/test_jev.py` + `fixtures/jev_triage_ana.json`, `docs/notes/jev.md`
**Scope:** S. High risk, so it runs early.

### Checkpoint 1: Foundation
- [x] `docker compose up` serves the shell, and `/api/health` returns 200
- [x] `uv run python -m pre_commit run --all-files` is green, and CI is green (if the remote exists)
- [x] The Jev request and response shape is confirmed, and any difference from SPEC-providers has been noted in the spec

---

## Phase 2: Data (`data`)

### - [x] T7: Schema and migrations
**Description:** SQLAlchemy models and the initial Alembic migration, covering:
- the five tables from the brief, with their columns unchanged and the constraints from SPEC-data
- the extension tables `member_profiles` and `staff`
- `policy_clauses`, with a generated tsvector column and a GIN index
- the app tables, including the partial unique index on running runs and the append-only trigger on `audit_events`

A test fixture creates the `fees_test` database.
**Acceptance criteria:**
- [x] `alembic upgrade head` and `downgrade base` both work on an empty database (SPEC-data AC1).
- [x] The brief's tables match its column lists exactly, checked through `information_schema` (AC2).
- [x] `UPDATE` and `DELETE` on `audit_events` are rejected (AC7).
**Verification:** `uv run python -m pytest tests/integration/db/test_schema.py`
**Dependencies:** T3
**Files:** `backend/db/models.py`, `backend/db/alembic.ini` + `alembic/env.py` + `script.py.mako`, `backend/db/alembic/versions/0001_initial_schema.py`, `tests/integration/conftest.py` + `migrations.py`, `tests/integration/db/test_schema.py`, `docker-compose.yml` (db on 127.0.0.1, D-platform-2), `.github/workflows/ci.yml` (`TEST_DATABASE_URL`)
**Scope:** M

### - [x] T8: Database roles and bootstrap
**Description:** `backend/db/roles.py` already creates the `agent_reader` and `app_writer` login roles (T3, D-platform-1). T8 adds their grants from SPEC-data. `agent_reader` gets `default_transaction_read_only` and a 3-second `statement_timeout`. `backend/bootstrap.py` runs migrations and then roles. The seed and the policy loader are added in T9 and T11. The `migrate` service runs it.
**Acceptance criteria:**
- [x] Running bootstrap twice succeeds.
- [x] As `agent_reader`, `SELECT` works and `INSERT`, `UPDATE` and `DELETE` on every table fail (SPEC-data AC4).
**Verification:** `uv run python -m pytest tests/integration/db/test_roles.py`; `docker compose up` shows `migrate` exiting 0
**Dependencies:** T7
**Files:** `backend/db/roles.py`, `backend/db/migrations.py`, `backend/bootstrap.py`, `tests/integration/db/test_roles.py`, `tests/integration/migrations.py` (the exact grants are in SPEC-data)
**Scope:** S

### - [x] T9: Seed: the brief's rows, profiles, staff, reset
**Description:** A scenario registry (scenario 1 = the brief's data and Ana). It loads the brief's rows verbatim, plus member profiles and staff `S07`, `S14` and `SYSTEM`. Seeding is idempotent (`ON CONFLICT DO NOTHING`), and `--reset` truncates every table and re-seeds. Bootstrap calls the seed.
**Acceptance criteria:**
- [x] Seeding twice leaves the same counts. `--reset` restores the demo state (SPEC-data AC3; the refund part is re-checked in T21).
- [x] The brief's rows are byte-identical to the PDF tables.
**Verification:** `uv run python -m pytest tests/integration/db/test_seed.py`
**Dependencies:** T8
**Files:** `backend/db/seed/__init__.py`, `backend/db/seed/scenarios.py`, `backend/bootstrap.py` (`--reset`), `tests/integration/db/test_seed.py`. No separate seed `__main__`: the entry point is `python -m backend.bootstrap [--reset]`, as in SPEC.md.
**Scope:** M

### - [x] T10: Read-only tools and transaction kinds
**Description:** `classify_description`, with its patterns in `descriptions.yaml`. Also the tools `get_conversation`, `get_member_profile`, `list_member_accounts`, `list_transactions`, `list_fee_refunds`, `list_our_refunds` and `get_last_known_language`, with typed models, `ToolTimeout` and `ToolError`.
**Acceptance criteria:**
- [x] `list_transactions(301, 2026-09-14, 2026-09-14)` returns 88001, 88002 and 88003, with kinds `card_payment`, `fee` and `payroll_deposit` (SPEC-data AC5).
- [x] A slow query raises `ToolTimeout` (AC8). Every seeded description is classified correctly (AC9).
**Verification:** `uv run python -m pytest tests/unit/tools tests/integration/tools`
**Dependencies:** T9
**Files:** `backend/tools/queries.py` + `models.py`, `backend/tools/descriptions.py` + `backend/core/config/descriptions.yaml`, `backend/core/config/tools.yaml`, `backend/tools/errors.py`, `tests/unit/tools/test_classify_description.py`, `tests/integration/tools/test_queries.py`, `tests/conftest.py` (selector event loop for psycopg on Windows), shared role and seed fixtures in `tests/integration/`
**Scope:** M

### Checkpoint 2: Data
- [x] A fresh `docker compose up` migrates and seeds. `agent_reader` can't write.
- [x] All integration tests pass against compose Postgres.

---

## Phase 3: Ana end to end (thin vertical slice)

### - [x] T11: Policy documents and loader
**Description:** The six markdown documents with typed front-matter. `load_clauses(session)` splits them into clauses, upserts them and computes `policy_version`. Bootstrap calls it. `fee_schedule_clause(fee_type)` maps a fee type to its clause.
**Acceptance criteria:**
- [x] All documents load. A malformed front-matter fails the loader, naming the file and field (SPEC-policy AC1).
- [x] The params-vs-text test passes, and fails if `max_refunds_in_window` changes without the text (AC6).
**Verification:** `uv run python -m pytest tests/unit/policy/test_docs.py`
**Dependencies:** T10
**Files:** `backend/policy/docs/*.md` (6 content files), `backend/policy/loader.py`, `backend/bootstrap.py`, `tests/unit/policy/test_docs.py`, `tests/integration/policy/test_loader.py`
**Scope:** M (mostly content)

### - [x] T12: Rules (TDD)
**Description:** Write the failing tests first. Then implement `find_fee_candidates`, `verify_posting_order` (including the `data_mismatch` check and `balance_if_deposit_first`), `check_not_already_refunded`, `check_yearly_limit`, `check_good_standing` and `check_approval_limit`.
**Acceptance criteria:**
- [x] Ana's worked example passes on the seeded transactions (SPEC-policy AC2).
- [x] The boundary tests pass: 3 refunds, 364 vs 365 days, deposit before the fee, deposit that doesn't cover, chain off by $0.01 (AC3).
- [x] 90% or more coverage on `backend/policy`.
**Verification:** `uv run python -m pytest tests/unit/policy/test_rules.py --cov=backend/policy`
**Dependencies:** T10, T11
**Files:** `backend/policy/rules.py`, `backend/policy/models.py`, `backend/policy/reasons.py` (`ReasonCode` only), `tests/unit/policy/test_rules.py`
**Scope:** M

### - [x] T13: Reason catalogue and summaries
**Description:** The `ReasonCode` enum with its groups, EN and ES templates, and next steps, plus `render_reason` and `render_summary` (including the counterfactual sentence).
**Acceptance criteria:**
- [x] Every code renders in EN and ES with sample facts. The forbidden-words and gendered-pronoun tests pass (SPEC-policy AC5).
- [x] `render_summary` for Ana gives "The paycheck arrived the same day and the bill posted before it." and "…would have stayed at $1,360."
**Verification:** `uv run python -m pytest tests/unit/policy/test_reasons.py`
**Dependencies:** T12
**Files:** `backend/policy/reasons.py`, `tests/unit/policy/test_reasons.py`
**Scope:** S

### - [x] T14: Sanitising and masking (TDD)
**Description:** `sanitize` (NFKC, control and invisible characters, 2,000-character cap), plus `MaskingDictionary` (plain values) with `mask` and `unmask`.
**Acceptance criteria:**
- [x] The example mask from SPEC-providers AC6 produces the exact expected output. "$500", "Sep 14" and "CITY POWER & LIGHT" are untouched (AC7).
- [x] U+202E and U+200B are stripped, and the cap sets `truncated` (AC8). The mapping never prints its values.
**Verification:** `uv run python -m pytest tests/unit/privacy`
**Dependencies:** T1 (can run in parallel with T11–T13)
**Files:** `backend/privacy/sanitize.py`, `backend/privacy/mask.py`, `tests/unit/privacy/test_sanitize.py`, `tests/unit/privacy/test_mask.py`
**Scope:** S

### - [x] T15: Provider plumbing: retries, timeouts, deadline, cost, Jev classifier
**Description:** A retry policy (tenacity with jitter and `Retry-After`, no retry on 4xx or schema errors) with deadline support. Also `providers.yaml`, `pricing.yaml` and `compute_cost`. `JevClassifier` from T6 is hardened on top of these.
**Acceptance criteria:**
- [x] With MockTransport: a timeout is retried twice, a 400 is not retried, and a 429 with `Retry-After: 1` is honoured within the cap (SPEC-providers AC1 for Jev, AC2).
- [x] With a fake clock, no attempt starts after the deadline (AC3).
- [x] `compute_cost` matches the price table; an unknown model gives `None` (AC10).
**Verification:** `uv run python -m pytest tests/unit/providers`
**Dependencies:** T6
**Files:** `backend/providers/retry.py`, `backend/providers/cost.py`, `backend/providers/config.py`, `backend/core/config/providers.yaml` + `pricing.yaml`, `backend/providers/jev.py` + `types.py`, `tests/unit/providers/test_retry.py` + `test_cost.py` + `test_jev.py`
**Scope:** M

### - [x] T16: Triage thresholds and decision precedence (TDD)
**Description:** `triage_rules.py` applies the D3 thresholds to Jev answers and handles Luna labels (D-agent-5 and D-agent-7). `decide.py` covers status precedence, the recommendation (including `none` for `fee_question`), `clear` and `would_auto_approve`. The thresholds live in config.
**Acceptance criteria:**
- [x] Precedence is tested for every pair of competing codes. `drafter_down` and `classifier_down` lead to `needs_your_call`; `classified_with_backup` doesn't change the status.
- [x] The Noul bands follow D3 (`p_yes` ≤ 0.15 is a clear "no"). Luna `None` confidence is never treated as a number.
- [x] 90% or more coverage on `decide.py`.
**Verification:** `uv run python -m pytest tests/unit/agents --cov=backend/agents/decide.py`
**Dependencies:** T13
**Files:** `backend/agents/triage_rules.py`, `backend/agents/decide.py`, `backend/core/config/thresholds.yaml`, `tests/unit/agents/test_triage_rules.py`, `tests/unit/agents/test_decide.py`
**Scope:** M

### - [x] T17: Graph and nodes: Ana, with a template reply
**Description:** `GraphState` and the LangGraph `StateGraph` with every node from SPEC-agent. Check LangGraph's fan-in and stream APIs against the official docs first. At this stage two nodes are simpler than their final form:
- `find_policy` uses `rule_fallback` only (search comes in T30)
- `draft` uses the template only (Sol comes in T28)

The `triage-v1` prompt file and the EN/ES "refunded" templates are added. The test injects in-process fake providers.

**From T10:** tools don't retry by themselves. The node wrapper applies the one retry in `backend/core/config/tools.yaml` with the T15 retry policy and the run deadline, and a `ToolTimeout` after that becomes `data_timeout`.

**From the T6 spike:** the outline's manipulation wording gave Ana P(yes) 0.92, so `triage-v1` must reword it (and add Noul `criteria`) so that an ordinary refund request is a clear "no". Check it live on Ana and scenario 12 before the prompts freeze (`docs/notes/jev.md`, finding 1).
**Acceptance criteria:**
- [x] Ana (scenario 1) reaches `ready_to_refund` with $35 on 88002, `clear = true` and clause `fee-refund-policy#4`. The draft contains `{{first_name}}` and "$35".
- [x] No masked step input contains a seeded name or account number.
**Verification:** `uv run python -m pytest tests/integration/agents/test_graph_scenarios.py -k ana`
**Dependencies:** T12–T16
**Files:** `backend/agents/state.py`, `backend/agents/graph.py`, `backend/agents/nodes.py`, `backend/agents/prompts/` (`triage-v1.yaml`, `templates/`), `tests/integration/agents/test_graph_scenarios.py`
**Scope:** M

### - [x] T18: Runner and recorder: persistence and read-only sessions
**Description:** `run_case` creates the run, sets the case to `checking`, applies the 45-second timeout with deadline propagation, records one `agent_steps` row per node (meta, masked input, output) from outside node code, totals latency, tokens and cost, and resets interrupted runs at startup.
**Acceptance criteria:**
- [x] One `agent_runs` row and one step row per executed node, with latency. Totals add up (SPEC-agent AC7).
- [x] A node attempting an `INSERT` fails with a permission error, and the recorder still writes (AC6).
- [x] A run left `running` becomes `interrupted` at startup, and its case goes back to `not_checked`.
**Verification:** `uv run python -m pytest tests/integration/agents/test_runner.py`
**Dependencies:** T17
**Files:** `backend/agents/runner.py`, `backend/agents/recorder.py`, `backend/agents/deps.py`, `tests/integration/agents/test_runner.py`
**Scope:** M

### - [x] T19: API: queue and run
**Description:** `GET /cases` (views, ordering, cursor) and `POST /cases/{id}/run`, which starts the run as an asyncio task, returns 202, and returns 409 for `run_in_progress` (with the run id) or `case_not_running`. Startup calls the interrupted-run reset. Error bodies already use the envelope; full hardening is in T37.
**Acceptance criteria:**
- [x] `GET /cases` lists 5012 as `not_checked`. After a run it shows `ready_to_refund`, the topic and $35.
- [x] `POST /run` on 5009 (closed) gives 409. A second `POST /run` during a run gives 409 with the active `run_id` (SPEC-api AC4).
**Verification:** `uv run python -m pytest tests/api/test_runs.py`
**Dependencies:** T18
**Files:** `backend/api/routes_cases.py`, `backend/api/schemas.py`, `backend/api/queue.py`, `backend/api/resources.py` (in place of `deps.py`), `backend/api/errors.py`, `backend/api/main.py`, `backend/agents/runner.py`, `tests/api/test_runs.py` + `conftest.py`, `tests/unit/api/test_resources.py`; DB fixtures moved to `tests/conftest.py`
**Scope:** M

### - [x] T20: API: case view model
**Description:** `GET /cases/{id}`, with conversation, member, status, `summary`, rendered `reasons` and `notes`, recommendation, fee and candidates, all evidence sections (`fee_day` with its summary), clause, the draft with the first name filled in, the run with its steps, the decision, `actions`, `can_run` and `can_pick_fee`. Placeholders are filled in and masks are removed only here.
**Acceptance criteria:**
- [x] Ana's case returns everything that SPEC-ui's case pane reads. `actions` is `[approve, edit, reject]`, and `can_run` is true.
- [x] No field contains a reason code, `{{first_name}}` or `[ACCOUNT_…]` (SPEC-api AC9). An unknown id gives a friendly 404.
**Verification:** `uv run python -m pytest tests/api/test_case_view.py`
**Dependencies:** T19
**Files:** `backend/api/routes_cases.py`, `backend/api/view_model.py`, `backend/api/actions.py`, `backend/api/schemas.py`, `backend/agents/nodes.py` (each check stores its facts), `tests/api/test_case_view.py`, `tests/unit/api/test_actions.py`
**Scope:** M

### - [x] T21: Core-banking adapter
**Description:** `CoreBanking.post_fee_refund`, as one transaction: insert into `refunds` with `ON CONFLICT`, lock the sub-account, insert the refund transaction with the next `posting_ref`, and update the balance.
**Acceptance criteria:**
- [ ] Two calls on 88002, sequential or concurrent, produce one refund transaction and add $35 once. The second call reports `already_done` (SPEC-data AC6).
- [ ] After a refund, a restart keeps it, and `bootstrap --reset` restores the original state (AC3).
**Verification:** `uv run python -m pytest tests/integration/db/test_core_banking.py`
**Dependencies:** T9 (can run in parallel with T11–T20)
**Files:** `backend/db/core_banking.py`, `tests/integration/db/test_core_banking.py`
**Scope:** S

### - [x] T22: API: decision endpoint and the required API test
**Description:** `POST /cases/{id}/decision` with the `Idempotency-Key` header, the validation order from SPEC-api (limit before action), the effects in one transaction (decision, refund, reply message, closed conversation, case `done`, audit events, `eval_candidates`), and the `actions` rules per status.
**Acceptance criteria:**
- [x] **The required API test:** run 5012 → `GET` → approve → the same request again gives the same 200 → exactly one refund transaction, balance +$35 (SPEC-api AC1).
- [x] A new key on the decided case gives 409. The same key with a different body gives 422. A stale run gives 409. A disallowed action gives 422 (AC2, AC3).
**Verification:** `uv run python -m pytest tests/api/test_happy_path.py tests/api/test_decision_rules.py`
**Dependencies:** T20, T21
**Files:** `backend/api/routes_decision.py`, `backend/api/decision_service.py`, `backend/api/schemas.py`, `backend/api/actions.py` (`actions_for`, shared with the view), `backend/api/resources.py` (policy numbers, clock), `backend/core/settings.py` (`STAFF_ID`), `docker-compose.yml`, `tests/api/test_happy_path.py`, `tests/api/test_decision_rules.py`
**Scope:** M

### - [x] T23: UI: queue pane
**Description:** Generate the API types from OpenAPI (`gen:api`), add an API client and TanStack Query hooks, and build the queue pane: items, Open and Done tabs, selection with URL state, and the empty state.
**Acceptance criteria:**
- [x] The queue shows the seeded open conversations, with first name and last initial, subject, status and time. Selecting one sets `?case=`.
- [x] Refreshing restores the selection. "You're all caught up." shows when the list is empty.
**Verification:** `npm --prefix frontend test -- Queue` · manual check in compose
**Dependencies:** T2, T19
**Files:** `frontend/src/api/` (`openapi.json`, `schema.d.ts`, `client.ts`, `hooks.ts`), `frontend/src/features/queue/Queue.tsx` (+ test), `frontend/src/lib/` (`useUrlState.ts`, `format.ts`), `frontend/src/test/` (`fixtures.ts`, `render.tsx`), `frontend/src/copy/en.ts`, `frontend/src/App.tsx` (+ test), `frontend/src/main.tsx`, `frontend/vite.config.ts`, `frontend/package.json`, `backend/api/openapi.py`, `backend/api/schemas.py` (closed sets), `tests/unit/api/test_openapi.py`
**Scope:** M

### - [ ] T24: UI: case pane (decision card, reply, evidence), check with polling
**Description:** The case header, a decision card for every status in SPEC-ui (driven only by the API), the reply (read-only here; editing comes in T25), the evidence sections (posting-order table with marked rows and the summary, refunds, standing, policy quote, conversation, how it was prepared), and "Check this case". For now the check polls until it's done; SSE comes in T36.
**Acceptance criteria:**
- [ ] Table-driven test: each status fixture renders exactly the title, primary label and secondary actions from SPEC-ui (AC1). Buttons come only from `actions`, `can_run` and `can_pick_fee` (AC2).
- [ ] Ana's posting-order table marks the fee and deposit rows and shows the counterfactual sentence (AC7).
**Verification:** `npm --prefix frontend test -- DecisionCard EvidenceDay` · manual: check Ana in compose
**Dependencies:** T20, T23
**Files:** `frontend/src/features/case/CasePane.tsx`, `DecisionCard.tsx` (+ test), `Evidence.tsx`, `EvidenceDay.tsx` (+ test), `frontend/src/copy/en.ts`
**Scope:** M

### - [ ] T25: UI: decision actions
**Description:** Approve, Edit (textarea, counter, "Undo my changes"), reject with the required reason, `reply_only`, one idempotency key per attempt (reused on retry), the done state, and "Next case" with focus management.
**Acceptance criteria:**
- [ ] "Don't refund" and "Refund anyway" can't be submitted without a reason of 10 or more characters (SPEC-ui AC3).
- [ ] A retry after a network error reuses its `Idempotency-Key` (AC4).
- [ ] After approving, the card shows "Done" and "Refunded $35 and replied".
**Verification:** `npm --prefix frontend test -- useDecision DecisionCard`
**Dependencies:** T22, T24
**Files:** `frontend/src/features/case/DecisionActions.tsx`, `ReplyEditor.tsx`, `useDecision.ts` (+ test), `frontend/src/copy/en.ts`
**Scope:** M

### - [ ] T26: Ana in the browser, with a live Jev check
**Description:** An integration pass. Run compose with `PROVIDER_MODE=live` and only `JEV_API_KEY` set (drafts use the template), and fix whatever comes up between the layers. This is the first live triage through the whole product.
**Acceptance criteria:**
- [ ] In the browser: open Ana → "Check this case" → "Ready to refund" with the evidence → one click → "Done". Her transactions show the $35 refund, and the conversation is closed.
- [ ] The run's steps show the real Jev latency and cost. The logs hold no message text.
**Verification:** a manual walkthrough with screenshots; `uv run python -m pytest`; `npm --prefix frontend test`
**Dependencies:** T25
**Files:** fixes only (expected ≤ 5)
**Scope:** S–M

### Checkpoint 3: Ana end to end (review with the user)
- [ ] All tests pass, and pre-commit is clean
- [ ] Ana's full loop works in the browser with live Jev
- [ ] The user reviews the slice: UI, copy, evidence. Feedback is folded into the specs before Phase 4.

---

## Phase 4: Real models, fallbacks, replay

### - [ ] T27: Luna classifier and fallback chain
**Description:** Check OpenAI's docs first (Responses API, strict structured outputs, reasoning effort). `OpenAIClassifier` (`gpt-6-luna`, effort `none`) uses a strict JSON schema with enum and boolean fields, and returns `None` for confidence. `ClassifierChain` runs Jev, then Luna, then `ClassifierUnavailable`. The graph uses the chain, adds the `classified_with_backup` note, and handles `classifier_down` (the evidence is still loaded).
**Acceptance criteria:**
- [ ] Jev timeout → Luna answers, `meta.provider` is `openai` (model `gpt-6-luna`), `clear = false`, and the status is not changed by the note (SPEC-providers AC1 and AC5; SPEC-agent AC4).
- [ ] Both fail → `classifier_down` → `needs_your_call`, with the evidence and the recommendation present.
**Verification:** `uv run python -m pytest tests/unit/providers/test_openai_classifier.py tests/unit/providers/test_chain.py tests/integration/agents/test_fallbacks.py`
**Dependencies:** T26
**Files:** `backend/providers/openai_classifier.py`, `backend/providers/chain.py`, `backend/agents/nodes.py`, `tests/unit/providers/test_openai_classifier.py` + `test_chain.py`, `tests/integration/agents/test_fallbacks.py`
**Scope:** M

### - [ ] T28: Sol drafter, post-check and prompt caching
**Description:** `OpenAIDrafter` (`gpt-6.1-sol`, effort `low`), with structured `reply` output and the static system prompt first, so prefix caching applies. The `draft-v1.md` prompt. `DraftInput` has no field for the member's message. The post-check covers the placeholder, amounts, digits and length. Two failures fall back to the template with `drafter_down`, which leads to `needs_your_call`.
**Acceptance criteria:**
- [ ] Ana gets a Sol draft in English that passes the post-check. Cached tokens are recorded on the second run.
- [ ] Sol down, or two post-check failures → template + `drafter_down` → `needs_your_call`, with the recommendation kept (SPEC-agent AC4).
- [ ] A test proves that no message text reaches any `llm` step input.
**Verification:** `uv run python -m pytest tests/unit/providers/test_openai_drafter.py tests/unit/agents/test_draft_postcheck.py tests/integration/agents/test_fallbacks.py`; one live Ana run (needs `OPENAI_API_KEY`, open question 1)
**Dependencies:** T26 (can run in parallel with T27)
**Files:** `backend/providers/openai_drafter.py`, `backend/agents/prompts/draft-v1.md`, `backend/agents/draft_postcheck.py`, `tests/unit/providers/test_openai_drafter.py`, `tests/unit/agents/test_draft_postcheck.py`
**Scope:** M

### - [ ] T29: Replay store, modes, `/health` and header badge
**Description:** Replay keys and files, the hit, miss and record paths, the mode used by every adapter, `/health` `provider_mode` and `version`, the discreet "Replay mode" note in the UI header, and the recordings PII scan.
**Acceptance criteria:**
- [ ] With no keys, a recorded request returns the recorded answer with `mode = replay`. An unrecorded one raises `replay_miss`, and the fallback follows (SPEC-providers AC4).
- [ ] The recordings scan finds no personal data (AC9).
- [ ] `/health` shows both modes and the version. The header shows "Replay mode" (SPEC-ui AC8).
**Verification:** `uv run python -m pytest tests/unit/providers/test_replay.py tests/unit/providers/test_recordings_have_no_pii.py`; `npm --prefix frontend test -- Header`
**Dependencies:** T27, T28
**Files:** `backend/providers/replay.py`, `backend/providers/factory.py`, `backend/api/main.py`, `frontend/src/components/Header.tsx` (+ test), `tests/unit/providers/test_replay.py`
**Scope:** M

### - [ ] T30: Policy search: full-text, Jev clause choice, cross-check
**Description:** `build_policy_query`, `search_clauses` (`websearch_to_tsquery`, `ts_rank_cd`), the `clause-choice-v1` prompt, and the `find_policy` node: search, then Jev Choice, then cross-check against the decisive rule, with `rule_fallback` and a logged mismatch.
**Acceptance criteria:**
- [ ] For Ana, the top 5 include `fee-refund-policy#2` and `#4` (SPEC-policy AC4), and `found_by = search_confirmed`.
- [ ] A forced mismatch or low confidence leads to `rule_fallback`, the rule's clause, and a logged mismatch.
**Verification:** `uv run python -m pytest tests/integration/policy/test_search.py tests/integration/agents/test_graph_scenarios.py -k ana`
**Dependencies:** T29
**Files:** `backend/policy/search.py`, `backend/agents/nodes.py`, `backend/agents/prompts/clause-choice-v1.yaml`, `tests/integration/policy/test_search.py`
**Scope:** S–M

### Checkpoint 4: Real models and replay
- [ ] Compose with no keys starts in replay mode; with keys it runs live. `/health` agrees.
- [ ] Every fallback in SPEC-agent AC4 is proven by tests
- [ ] Recording is still deferred; the prompts may still change in Phase 5

---

## Phase 5: Every scenario and live steps

Each task below adds its seed scenarios, so that the graph scenario tests, the API rules and the UI fixtures cover them.

### - [ ] T31: Policy "no" scenarios (6, 7, 8, 11, 17) and the supervisor route
**Description:** Seed scenarios 6 (3 refunds already), 7 (deposit 2 days later), 8 (past-due LOAN), 11 (already refunded) and 17 (fee above $50). Add EN and ES decline templates, decline drafts that carry the clause, the `recommend_no_refund` and `needs_supervisor` paths, and the 403 `over_limit` in the API.
**Acceptance criteria:**
- [ ] Each scenario reaches its expected status and reason from SPEC-data.
- [ ] Scenario 17: approve gives 403 with the supervisor message, and the offered actions exclude refunds (SPEC-api AC3).
- [ ] The UI renders "We recommend not refunding" with the quote, "Refund anyway" with a reason, and "Needs supervisor approval".
**Verification:** `uv run python -m pytest tests/integration/agents/test_graph_scenarios.py tests/api/test_decision_rules.py`; `npm --prefix frontend test`
**Dependencies:** T30
**Files:** `backend/db/seed/scenarios.py`, `backend/agents/prompts/templates/`, `tests/integration/agents/test_graph_scenarios.py`, `tests/api/test_decision_rules.py`, `frontend/src/features/case/fixtures.ts`
**Scope:** M

### - [ ] T32: Fee identification scenarios (9, 10, 15) and "Pick the fee"
**Description:** Seed scenarios 9 (two fees, unclear message), 10 (two fees, the message names the bill) and 15 (no fee). Add the `fee-choice-v1` prompt and Jev fee choice, and the pinned-fee re-run (`POST /run {fee_txn_id}`, validated against the candidates, `fee_source = staff`) with the UI fee picker.
**Acceptance criteria:**
- [ ] Scenario 9 gives `fee_ambiguous` with candidates. Scenario 10 picks the right fee with Jev (`fee_source = jev`). Scenario 15 gives `fee_not_found`.
- [ ] Re-running 9 with a candidate gives `fee_source = staff`. A non-candidate gives 422 `invalid_fee` (SPEC-agent AC5).
- [ ] The UI shows the radio rows and "Check again with this fee" only when `can_pick_fee` is true.
**Verification:** `uv run python -m pytest tests/integration/agents -k "fee" tests/api/test_runs.py`; `npm --prefix frontend test -- FeePicker`
**Dependencies:** T30
**Files:** `backend/db/seed/scenarios.py`, `backend/agents/prompts/fee-choice-v1.yaml`, `backend/agents/nodes.py`, `backend/api/routes_cases.py`, `frontend/src/features/case/FeePicker.tsx`
**Scope:** M

### - [ ] T33: Routing scenarios (2, 3, 4) and the fee question (5)
**Description:** Seed the transactions scenario 5 needs. Add the early exit to `not_about_fee` with the topic label, and the `fee_question` path: recommendation `none`, the fee-schedule clause, no draft, and the `reply_only` and `reject` (refund anyway) actions.
**Acceptance criteria:**
- [ ] Scenarios 2, 3 and 4 give `not_about_fee` through the graph, with no balances loaded (no `load_accounts` step).
- [ ] Scenario 5 gives `needs_your_call` with `fee_question`, the `fee-schedule#4` clause and no draft. The actions are `reply_only` and `reject`.
**Verification:** `uv run python -m pytest tests/integration/agents -k "routing or fee_question" tests/api`
**Dependencies:** T30
**Files:** `backend/db/seed/scenarios.py`, `backend/agents/nodes.py`, `backend/api/view_model.py`, `tests/integration/agents/test_graph_scenarios.py`
**Scope:** S–M

### - [ ] T34: Injection, Spanish and multiple requests (12, 13, 14)
**Description:** Seed scenarios 12, 13 and 14. Wire the manipulation and multiple-requests Noul signals, the language fallback (`get_last_known_language`), the Spanish templates and Sol language handling, and the "Reply in Spanish" tag in the UI.
**Acceptance criteria:**
- [ ] Scenario 12 gives `needs_your_call` with `manipulation`, a recommendation of exactly $35, and no "$500" anywhere in the result or the draft (SPEC-agent AC3).
- [ ] Scenario 13 gives `ready_to_refund` with a Spanish draft. Scenario 14 gives `multiple_requests`.
**Verification:** `uv run python -m pytest tests/integration/agents -k "injection or spanish or multiple"`
**Dependencies:** T30
**Files:** `backend/db/seed/scenarios.py`, `backend/agents/nodes.py`, `backend/agents/prompts/templates/`, `tests/integration/agents/test_graph_scenarios.py`, `frontend/src/features/case/ReplyEditor.tsx`
**Scope:** M

### - [ ] T35: Robustness: data mismatch (16), missing recording (18), deadlines, interrupted runs
**Description:** Seed scenarios 16 and 18. Add the run-timeout reason mapping, end-to-end deadline propagation, and a tool timeout leading to `data_timeout`.
**Acceptance criteria:**
- [ ] Scenario 16 gives `data_mismatch`. Scenario 18 in replay gives `classifier_down`, with the evidence present.
- [ ] A hanging Sol (fake) falls back to the template before 45 s. A hanging tool gives `data_timeout`. The run timeout maps to the reason of the stalled node.
**Verification:** `uv run python -m pytest tests/integration/agents/test_fallbacks.py tests/integration/agents/test_runner.py`
**Dependencies:** T30
**Files:** `backend/db/seed/scenarios.py`, `backend/agents/runner.py`, `tests/integration/agents/test_fallbacks.py`, `tests/integration/agents/test_runner.py`
**Scope:** S–M

### - [ ] T36: Live steps over SSE (API, nginx, UI)
**Description:** Add `GET /cases/{id}/runs/{run_id}/events`: replay the recorded steps, then send live events with a keep-alive. The runner emits custom stream events. The UI `LiveSteps` (EventSource, attach on 409, collapse on done) replaces the polling from T24.
**Acceptance criteria:**
- [ ] Ana's stream has `started` and `finished` for each node, in order, then `done`. A late subscriber gets the full history (SPEC-agent AC8; SPEC-api AC8).
- [ ] It works **through nginx** in compose, with no buffering. The UI steps appear one by one (SPEC-ui AC5).
**Verification:** `uv run python -m pytest tests/api/test_runs.py -k events`; `npm --prefix frontend test -- LiveSteps`; manual check through `:8080`
**Dependencies:** T31–T35 (or any time after T30, if run in parallel)
**Files:** `backend/api/routes_events.py`, `backend/agents/runner.py`, `frontend/src/features/case/LiveSteps.tsx` (+ test), `frontend/src/features/case/useRunEvents.ts`
**Scope:** M

### Checkpoint 5: Every scenario
- [ ] All 18 scenarios pass in `test_graph_scenarios.py` with fakes
- [ ] Every status renders in the UI, and live steps work through nginx
- [ ] **Prompts frozen.** First full recording run of the 18 scenarios (ask first; needs both keys). Replay is verified with no keys.

---

## Phase 6: Hardening and evals

### - [ ] T37: API hardening: errors, validation, rate limits, reveal, auto-approve hook
**Description:**
- The global error envelope and the friendly 500.
- Strict validation of every input.
- Rate limits: slowapi, with 10/minute on `/run`.
- `GET …/accounts/{account_id}/number`, audited.
- The auto-approve completion hook, behind its flag and exercised only in tests.
**Acceptance criteria:**
- [ ] 404, 422 and 429 (with `Retry-After`) return friendly bodies, and no response contains a traceback (SPEC-api AC5, AC6).
- [ ] The reveal returns the full number and writes an audit event. Another member's account gives 404 (AC7).
- [ ] With the flag on, in a test only, a clear case is approved by `SYSTEM` through the decision service. With the flag off, nothing happens.
**Verification:** `uv run python -m pytest tests/api`
**Dependencies:** Checkpoint 5
**Files:** `backend/api/errors.py`, `backend/api/ratelimit.py`, `backend/api/routes_cases.py`, `tests/api/test_errors.py`, `tests/api/test_reveal.py`
**Scope:** M

### - [ ] T38: Eval runner, cases, scoring, replay track in CI
**Description:** The case schema (including `modes` and `record`) and scoring for every assertion type. About 30 YAML cases: 18 seed scenarios, 4 paraphrases, 2 Spanish, 6 injection, 2 extra routing, and fallback cases. The runner uses the `fees_eval` database, prints a labelled table and writes the reports. Record the message variants (ask first). Add the CI `evals` job, which fails below 100%.
**Acceptance criteria:**
- [ ] `--mode replay` with no keys runs the suite, prints the "MODE: REPLAY" table, writes JSON and Markdown, and exits 0 at 100% (SPEC-evals AC2).
- [ ] Changing the limit to 3 → 2 in a test copy makes a case fail, with exit 1 (AC3). Every injection case passes (AC4).
- [ ] The CI `evals` job is green.
**Verification:** `uv run python -m evals.run --mode replay`; `uv run python -m pytest tests/unit/evals`
**Dependencies:** T37 (and the Checkpoint 5 recordings)
**Files:** `evals/run.py`, `evals/scoring.py`, `evals/cases/` (YAML), `tests/unit/evals/test_case_schema.py` + `test_scoring.py`, `.github/workflows/ci.yml`
**Scope:** M

### - [ ] T39: Eval reports: cost, latency, classifier comparison, sweep, live run
**Description:**
- Per-step cost and latency, p50 and p95, and the manual-review rate.
- `--classifier jev|backup` (measured), with Sol as a priced estimate.
- `--sweep` over the recorded Jev probabilities.
- One `--mode live` run (ask first), which produces the "real" pass rate.
**Acceptance criteria:**
- [ ] The report includes cost per case and per step, p50 and p95, the manual-review rate, and the comparison table, with Sol marked as an estimate (SPEC-evals AC5).
- [ ] A live report exists, with its date and model versions, kept separate from replay.
**Verification:** `uv run python -m evals.run --mode replay --classifier backup`; `… --sweep intent=0.60:0.95:0.05`; the live report file
**Dependencies:** T38
**Files:** `evals/report.py`, `evals/run.py`, `evals/reports/` (generated)
**Scope:** S–M

### - [ ] T40: Feedback loop and shadow-mode agreement
**Description:** `evals.import_feedback` turns `eval_candidates` into YAML cases with `pending_review: true` and sets `exported_at`. A shadow-mode report gives the agreement between `would_auto_approve` and Luis's decisions (D5).
**Acceptance criteria:**
- [ ] An `edit` decision made through the API becomes a pending YAML case, and a second run exports nothing new (SPEC-evals AC6).
- [ ] The shadow report prints the agreement rate over the decided clear cases.
**Verification:** `uv run python -m pytest tests/integration/evals/test_import_feedback.py`; `uv run python -m evals.shadow_report`
**Dependencies:** T38
**Files:** `evals/import_feedback.py`, `evals/shadow_report.py`, `tests/integration/evals/test_import_feedback.py`
**Scope:** S

### - [ ] T41: UI polish: motion, accessibility, keyboard, responsive, states, copy lint
**Description:**
- Motion: 150–200 ms, honouring `prefers-reduced-motion`.
- Accessibility: landmarks, `aria-live`, focus rings.
- Keyboard: ↑, ↓, `j`, `k` and Enter.
- Responsive: one pane below 1,024 px.
- Skeletons, error banners and the network-down copy.
- The copy-lint test across every status fixture.
**Acceptance criteria:**
- [ ] No status fixture renders a `snake_case` token, `undefined`, `null`, `NaN` or `[ACCOUNT` (SPEC-ui AC6).
- [ ] Keyboard only: open Ana, approve, then "Next case" (AC9).
- [ ] With reduced motion, there are no transitions.
**Verification:** `npm --prefix frontend test`; manual keyboard and narrow-width check in compose
**Dependencies:** Checkpoint 5 (can run in parallel with T37–T40)
**Files:** `frontend/src/copy/copy.test.tsx`, `frontend/src/index.css`, `frontend/src/features/queue/Queue.tsx`, `frontend/src/components/ErrorBanner.tsx`, `frontend/src/components/Skeleton.tsx`
**Scope:** M

### Checkpoint 6: Hardened
- [ ] Every module's acceptance criteria pass (SPEC-platform through SPEC-evals)
- [ ] CI is green, with replay evals at 100%. A live pass rate exists.
- [ ] `would_auto_approve` is stored, and the flag is off in the shipped config

---

## Phase 7: Delivery A

### - [ ] T42: Playwright end-to-end tests in CI
**Description:** `happy-path.spec.ts`, `fallback.spec.ts` (scenario 18) and `a11y.spec.ts` (`@axe-core/playwright`). They run against the compose stack in replay. `globalSetup` resets with `bootstrap --reset`. Add the CI `e2e` job, which uploads traces on failure.
**Acceptance criteria:**
- [ ] All three specs pass locally and in CI (SPEC-delivery AC3).
- [ ] Lighthouse accessibility is 95 or more on the case page (SPEC-ui AC10).
**Verification:** `npm --prefix frontend run e2e`; the CI `e2e` job
**Dependencies:** Checkpoint 6
**Files:** `tests/e2e/happy-path.spec.ts`, `fallback.spec.ts`, `a11y.spec.ts`, `frontend/playwright.config.ts`, `.github/workflows/ci.yml`
**Scope:** M

### - [ ] T43: MCP server
**Description:** FastMCP over stdio, exposing the read-only tools on `agent_reader`, with masked outputs (`••4210`, first name only) and validated ids. Add a `.mcp.json` snippet.
**Acceptance criteria:**
- [ ] The in-process test lists the tools. `list_transactions(301, …)` returns three rows in order, with no full account number.
- [ ] Claude Code connects through the README snippet.
**Verification:** `uv run python -m pytest tests/integration/tools/test_mcp_server.py`; manual connection
**Dependencies:** Checkpoint 6
**Files:** `backend/tools/mcp_server.py`, `tests/integration/tools/test_mcp_server.py`, `.mcp.json.example`
**Scope:** S

### - [ ] T44: Diagrams: system (AWS target) and agent flow
**Description:** `docs/diagrams/system.md`: one Mermaid diagram of the AWS production target (CloudFront + S3, ALB, ECS Fargate, RDS with two roles, Secrets Manager, CloudWatch, NAT to Jev and OpenAI), with a note mapping it to compose. `docs/diagrams/agent-flow.md`: the structure, node kinds, prompts (one line each, linked), tool calls, fallback chains and handoffs, generated from the graph's node list.
**Acceptance criteria:**
- [ ] Both diagrams render on GitHub and cover everything the brief lists (SPEC-delivery AC2).
- [ ] The agent diagram matches the built graph. A test or script regenerates it and fails on drift.
**Verification:** a Mermaid render check (GitHub preview or `mmdc`); the drift check
**Dependencies:** Checkpoint 6
**Files:** `docs/diagrams/system.md`, `docs/diagrams/agent-flow.md`, `scripts/gen_agent_diagram.py`
**Scope:** S

### - [ ] T46: README and demo script
**Description:** The README sections from SPEC-delivery, in order: the replay statement up front, the four criteria, the evals with replay and live on separate lines, the known limitations, and the commands. Fill in the Commands section of `CLAUDE.md`. Write `docs/demo/script.md`, prepare the demo state, and hand it to the user to record the video.
**Acceptance criteria:**
- [ ] A clean clone with only Docker reaches Ana's approved refund by following the README alone (SPEC-delivery AC1). Tested in a fresh directory.
- [ ] The replay and live pass rates are on separate lines, and the live one has its date and model versions (AC6).
- [ ] The demo script is ready, and the video, or a link to it, is in the repo (AC5; the user records it).
**Verification:** fresh-clone walkthrough
**Dependencies:** T42–T44
**Files:** `README.md`, `CLAUDE.md`, `docs/demo/script.md`
**Scope:** S

### Checkpoint 7: Deliverable (gate for deploy)
- [ ] All Phase A acceptance criteria in SPEC-delivery pass
- [ ] **The user reviews the working deliverable.** Deploy starts only after this.

---

## Phase 8: Delivery B

### - [ ] T47: Render deploy, with a public health check
**Description:** Commit `render.yaml`:
- a backend web service, using the same image, with `/health` and a pre-deploy `python -m backend.bootstrap`
- a frontend web service, using the same nginx image and `BACKEND_URL`
- managed Postgres
- `PROVIDER_MODE=replay`, basic auth on the frontend, and a public `/api/health`

Creating the Render resources and pushing are **ask first**. If `CREATE ROLE` is refused, stop and ask (SPEC-delivery).
**Acceptance criteria:**
- [ ] The public URL serves the app behind basic auth. `/api/health` returns 200 with both provider modes set to `replay`.
- [ ] Ana's happy path works on the public URL. The README's "Deploy" section is filled in.
**Verification:** `curl https://<host>/api/health`; a manual walkthrough on the public URL
**Dependencies:** Checkpoint 7
**Files:** `render.yaml`, `README.md`
**Scope:** S

### Final checkpoint
- [ ] Every acceptance criterion in SPEC.md's project-level list passes
- [ ] The user signs off

# Implementation Plan: Fee Refund Agent

## Overview

Build the system described in [SPEC.md](../SPEC.md) and its nine module specs, following the binding architecture in [docs/agent-design.md](../docs/agent-design.md). The capability map gives the dependency direction:

`platform → data → policy ∥ providers → agent → api → ui ∥ evals → delivery`

The plan does **not** build those modules as horizontal layers. After the foundation, it builds one thin vertical path first: Ana's case, end to end, in the browser. It then widens that path, scenario by scenario, until all 18 seed scenarios, the evals and the delivery items work. Every task leaves the system runnable.

Detailed tasks, with acceptance criteria and verification, are in [tasks/todo.md](todo.md).

## Architecture decisions that shape the order

- **The riskiest unknown goes first.** Jev is a new API: its request and response shape, latency and error behaviour are unverified. A spike (T6) makes one real call before any code depends on it.
- **The walking skeleton uses real Jev and template replies.**
  - Phase 3 gets Ana's case working through every layer (rules → graph → API → UI → decision → refund) with live Jev triage and the deterministic template reply.
  - Sol, Luna, replay and search are added after that.
  - So when Phase 3 ends, the core product loop has been proven once, with a real model.
- **Tests always use in-process fake providers.** The running app uses live (keys present) or replay (keys absent). The two are never mixed (D10).
- **Recordings are made late.** Replay keys include the prompt version. Recording before the prompts settle (end of Phase 5) would force a re-recording. Each recording run is "ask first".
- **Deploy is last and gated** on the user's review of a working deliverable (D-delivery-1). Platform keeps it a config-only step from day one: nginx upstream from env, `$PORT`, `backend.bootstrap`.

## Dependency graph (tasks)

```
Foundation   T1 ─┬─ T2 ─────────────┐
                 ├─ T3 (needs T2) ──┼─ T5 CI (needs T1–T4)
                 ├─ T4 ─────────────┘
                 ├─ T6 Jev spike ── T15 provider plumbing
                 └─ T14 sanitise/mask
Data         T3 ── T7 ── T8 ── T9 ── T10
                               └──── T21 core-banking adapter
Policy       T10 ── T11 ── T12 ── T13 ── T16 decide
Ana slice    T12..T16 ── T17 graph ── T18 runner ── T19 API queue/run ── T20 API case view
             T20 + T21 ── T22 API decision
             T2 + T19 ── T23 UI queue ── T24 UI case (needs T20) ── T25 UI actions (needs T22)
             T25 ── T26 Ana live in browser ══ Checkpoint 3 (user review)
Models       T26 ─┬─ T27 Luna + chain ─┬─ T29 replay ── T30 search ══ Checkpoint 4
                  └─ T28 Sol ────────┘
Scenarios    T30 ─┬─ T31 policy "no" (6, 7, 8, 11, 17)
                  ├─ T32 fee choice (9, 10, 15)
                  ├─ T33 routing + fee question (2, 3, 4, 5)
                  ├─ T34 injection, Spanish, multiple (12, 13, 14)
                  ├─ T35 robustness (16, 18)
                  └─ T36 live steps (SSE) ══ Checkpoint 5 (prompts frozen, record)
Hardening    CP5 ─┬─ T37 API hardening ── T38 eval runner ─┬─ T39 reports
                  │                                         └─ T40 feedback + shadow
                  └─ T41 UI polish ══ Checkpoint 6
Delivery     CP6 ─┬─ T42 Playwright ─┐
                  ├─ T43 MCP         ├─ T46 README + demo ══ Checkpoint 7 (user review) ── T47 deploy
                  └─ T44 diagrams ───┘
```

T45 is intentionally unused, so the task numbers stay stable if a task has to be split during the build.

## Task list (index; details in [todo.md](todo.md))

### Phase 1: Foundation (`platform`)
- T1 Backend skeleton and quality gates
- T2 Frontend skeleton with Blossom tokens
- T3 Docker compose stack with a database health check
- T4 Logging, request ids, clock
- T5 CI workflow
- T6 Jev spike: one real call, shape documented
- **Checkpoint 1:** `docker compose up` serves the shell, `/api/health` is 200, and pre-commit and CI are green

### Phase 2: Data (`data`)
- T7 Schema and migrations
- T8 Database roles and bootstrap
- T9 Seed: the brief's rows, profiles, staff, reset
- T10 Read-only tools and transaction kinds
- **Checkpoint 2:** a migrated and seeded database; `agent_reader` can't write; Ana's day comes back in posting order

### Phase 3: Ana end to end (thin vertical slice)
- T11 Policy documents and loader
- T12 Rules (TDD)
- T13 Reason catalogue and summaries
- T14 Sanitising and masking (TDD)
- T15 Provider plumbing: retries, timeouts, deadline, cost, Jev classifier
- T16 Triage thresholds and decision precedence (TDD)
- T17 Graph and nodes: Ana, with a template reply
- T18 Runner and recorder: persistence and read-only sessions
- T19 API: queue and run
- T20 API: case view model
- T21 Core-banking adapter
- T22 API: decision endpoint and the required API test
- T23 UI: queue pane
- T24 UI: case pane (decision card, reply, evidence), check with polling
- T25 UI: decision actions
- T26 Ana in the browser, with a live Jev check
- **Checkpoint 3:** Ana works in the browser: check, then "Ready to refund", then one click, then "Done", with $35 in her transactions. Review with the user.

### Phase 4: Real models, fallbacks, replay (`providers`, `agent`)
- T27 Luna classifier and fallback chain
- T28 Sol drafter, post-check and prompt caching
- T29 Replay store, modes, `/health` and header badge
- T30 Policy search: full-text, Jev clause choice, cross-check
- **Checkpoint 4:** with no keys, compose runs in replay. With keys, it runs live. Every fallback is proven by tests.

### Phase 5: Every scenario and live steps
- T31 Policy "no" scenarios (6, 7, 8, 11, 17) and the supervisor route
- T32 Fee identification scenarios (9, 10, 15) and "Pick the fee"
- T33 Routing scenarios (2, 3, 4) and the fee question (5)
- T34 Injection, Spanish and multiple requests (12, 13, 14)
- T35 Robustness: data mismatch (16), missing recording (18), deadlines, interrupted runs
- T36 Live steps over SSE (API, nginx, UI)
- **Checkpoint 5:** all 18 scenarios pass, and every status renders in the UI. Prompts are frozen. First full recording run (ask first).

### Phase 6: Hardening and evals
- T37 API hardening: errors, validation, rate limits, reveal, auto-approve hook
- T38 Eval runner, cases, scoring, replay track in CI
- T39 Eval reports: cost, latency, classifier comparison, sweep, live run
- T40 Feedback loop and shadow-mode agreement
- T41 UI polish: motion, accessibility, keyboard, responsive, states, copy lint
- **Checkpoint 6:** every module's acceptance criteria pass; CI is green with replay evals at 100%; a live pass rate exists

### Phase 7: Delivery A
- T42 Playwright end-to-end tests (happy path, fallback, accessibility) in CI
- T43 MCP server
- T44 Diagrams: system (AWS target) and agent flow
- T46 README and demo script; the user records the video
- **Checkpoint 7:** the user reviews a working deliverable. This is the gate for deploy.

### Phase 8: Delivery B
- T47 Render deploy, with a public health check (ask first: outward-facing)
- **Final checkpoint**

## Parallelisation

| Can run in parallel | Why it's safe |
|---|---|
| T2 with T3–T6 | The frontend scaffold doesn't touch the backend |
| T11–T13 (policy), T14–T15 (providers), T16 (decide) | Separate modules, each depending only on finished foundations |
| T23–T25 (UI) with T21–T22 (decision backend) | After T19 and T20 fix the API contract (OpenAPI types) |
| T27 and T28 | Separate adapters |
| T31–T35 | Separate scenarios. Each adds its own seed data and tests; seed edits need care, because it is one registry file. |
| T38–T40 with T41 | Evals and UI polish don't share files |
| T42, T43, T44 | Independent deliverables |

These must stay sequential:
- **Migrations:** T7 before anything that touches the database.
- **The recording run:** only after the prompts freeze (Checkpoint 5).
- **T47:** only after Checkpoint 7.

## Cut line (if time runs short)

These go last and can be cut without breaking any required deliverable:

- the T39 threshold sweep
- the T40 shadow-mode agreement report
- T43 MCP
- T47 deploy

Everything above the cut line covers the brief's required deliverables and most bonuses.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Jev's real API differs from the docs (shape, `confidence` semantics, errors) | High | T6 spike before any dependent code; MockTransport tests use the observed shape; `docs/notes/jev.md` records it |
| LangGraph details (parallel fan-in, `astream` custom events) differ from what's assumed | Medium | Check against the official docs before T17 and T36 (source-driven); keep nodes plain async functions so the graph wiring is thin |
| SSE buffered by nginx or a proxy | Medium | `proxy_buffering off` on the events route (T3); verified through compose in T36, not only against uvicorn |
| Replay misses after prompt edits | Medium | The prompt version is in the replay key; record only after Checkpoint 5; CI evals fail loudly on a miss rather than silently degrading |
| OpenAI 6.x API details (strict structured outputs, reasoning effort, caching with cache-write pricing) differ from what's assumed | Medium | Check the official docs before T27 and T28 (source-driven). MockTransport tests use the observed shapes. The template path from T17 keeps drafts working meanwhile. |
| Database tests on Windows | Low | All database tests run against the compose Postgres (`fees_test` database); line endings forced by `.gitattributes` (T1) |
| Scope: 46 tasks | Medium | Small tasks with checkpoints; the cut line above; user review at Checkpoints 3 and 7 |
| Render managed Postgres refuses `CREATE ROLE` | Low (late) | Found in T47; the documented fallback is "ask first" (SPEC-delivery) |

## Resolved before the build

- **Models.** The project uses OpenAI, because there are OpenAI credits and no Anthropic credits. GPT-6.1 Sol drafts and GPT-6 Luna is the classifier fallback; Jev is unchanged. Recorded in `docs/agent-design.md` §8.
- **Repository.** It already exists: `main`, with remote `origin` (github.com/ppedreros/fee-refound-agent). Commits go in one per task, and they are pushed at each checkpoint so CI runs.

## Estimated timeline

These are estimates of working days with the user available for reviews. The biggest variables are review turnaround, surprises in the Jev or OpenAI APIs, and Docker on Windows.

| Phase | Tasks | Estimate | Running total |
|---|---|---|---|
| 1 Foundation | T1–T6 | 0.5–1 day | 1 |
| 2 Data | T7–T10 | 0.5–1 day | 2 |
| 3 Ana end to end | T11–T26 | 2–3 days | 4–5 (Checkpoint 3 review) |
| 4 Models and replay | T27–T30 | 1 day | 5–6 |
| 5 Every scenario | T31–T36 | 1–1.5 days | 6.5–7.5 |
| 6 Hardening and evals | T37–T41 | 1–1.5 days | 7.5–9 |
| 7 Delivery A | T42–T46 + video | 1 day | 8.5–10 (Checkpoint 7 review) |
| 8 Deploy | T47 | 0.5 day | 9–10.5 |

**Ways to finish sooner**
- **Running tasks in parallel** (separate worktrees for T31–T35, for T37–T41, and for T42–T44) brings the total to about **6–7 days**.
- **Cutting at the cut line** (no sweep, no shadow report, no MCP, no deploy) saves about 1.5 days.

## Scope and tooling (decided 2026-10-04)

- **Full scope.** Every task runs, including the cut-line items. The cut line stays above only as a fallback.
- **Tooling that needs no installs on the dev machine:**
  - npm instead of pnpm
  - pre-commit as a dev dependency, run with `uv run python -m pre_commit`
  - Python 3.14 (the installed, signed interpreter). The machine's application-control policy blocks venvs built on the uv-downloaded 3.12, and every planned dependency has 3.14 wheels for Windows and Linux.
  - Node 24 LTS
- **Docker Desktop must be running** from T3 onwards.

## Open questions

None.

## Definition of done (every task)

A task is checked off only when **all** of these hold:

- its acceptance criteria pass
- `uv run python -m pre_commit run --all-files` and the relevant tests pass, with the output shown
- the behaviour has been verified at runtime, not just type-checked
- it is committed as one small slice

Features also need their spec section to match what was built. Any deviation is updated in the spec first (SPEC.md "Always").

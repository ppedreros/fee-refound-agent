# Fee Refund Agent

[![CI](https://github.com/ppedreros/fee-refound-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/ppedreros/fee-refound-agent/actions/workflows/ci.yml)

Video Demo: https://drive.google.com/file/d/12Vq8Z1WNIxmRNGUqsuDQFpK2Qhdv4Rcy/view?usp=sharing

An agentic flow that prepares overdraft-fee refund requests for Luis, a credit union employee:
it reads the member's message and accounts, checks the refund policy, recommends what to do and
drafts the reply. Luis sees everything on one page and approves, edits or rejects in seconds;
the refund only ever happens on his click.

![Ana's case, ready to refund: the decision card with the recommendation and the drafted reply, and the evidence below it](docs/images/ana-case.png)

## Run it

You need Docker only.

```sh
cp .env.example .env && docker compose up --build
```

Then open <http://localhost:8080>, choose **Ana T.**, click **Check this case**, and approve
with **Refund $35 and send reply**. The first build takes a few minutes. To start over:
`docker compose run --rm migrate python -m backend.bootstrap --reset`.

## Replay mode

Without API keys, the system uses real model responses recorded earlier. `/health` and the page
header say which mode is on. Add `JEV_API_KEY` and `OPENAI_API_KEY` to `.env` to run live.

The recordings are in [`backend/providers/recordings/`](backend/providers/recordings/): each one
is a real answer to the exact masked question, looked up by its hash. One scenario (Liam N.,
scenario 18) is never recorded on purpose, so replay shows what happens when the models are
down.

## How it works

1. **Check this case** runs a LangGraph flow. It reads the conversation, Jev triages it, and three reads (accounts, transactions, refund history) run in parallel on a read-only database role.
2. Deterministic rules find the fee, check the policy (same-day deposit, 3 refunds a year, good standing, not already refunded) and decide the outcome and amount. Models never decide money.
3. Full-text search finds the policy clause and Jev confirms it. Sol drafts the reply from the facts only, never from the member's text, and a post-check rejects any other amount.
4. Any doubt or failure ends in **Needs your call**, with the reason in plain words and the evidence intact. The steps stream to the page as they happen, and every step is stored.
5. Luis decides. The refund is one idempotent `POST /cases/{id}/decision`, which the agent can't reach.

Diagrams: [the system on AWS](docs/diagrams/system.md) and [the agent flow](docs/diagrams/agent-flow.md), which is generated from the graph. The reasoning behind each choice is in [docs/agent-design.md](docs/agent-design.md).

## The four criteria

**Agentic logic.** The graph is in [`backend/agents/graph.py`](backend/agents/graph.py) and its
nodes in [`nodes.py`](backend/agents/nodes.py). Each step is the cheapest kind that can do it:
a database read, a rule, a typed classification (Jev) or, only for the reply, an LLM (Sol). Every
model call has a timeout, retries and a fallback ([agent design §5](docs/agent-design.md)), so a
failure changes the status, never the outcome. Customer text is data: it is sanitised, masked and
only ever classified, and the injection cases in the evals prove it can't change the amount.

**UI and plain language.** One page: the queue on the left, the decision first on the right, and
the evidence one click away ([`frontend/src/features/case/`](frontend/src/features/case/)). Every
string Luis reads is in [`frontend/src/copy/en.ts`](frontend/src/copy/en.ts), and every reason
comes from one catalogue with English and Spanish templates
([`backend/policy/reasons.py`](backend/policy/reasons.py)). A test renders every status and fails
on any internal code, placeholder or `undefined`. Keyboard only works, motion respects "reduce motion", axe finds no
serious problem, and Lighthouse scores accessibility 100.

**Learning speed: Jev.** Jev (TypeSafe's System One) answers typed questions with calibrated
numbers: a *Choice* with a probability per option, a *Noul* yes/no with P(yes). That is what a
"never guess" rule needs: act at 0.80, hand over below. It runs triage (five questions in one
call), the choice between two same-day fees and the clause confirmation. Measured live, it was
right on 33 of 33 triage verdicts at 228 ms and $0.000036, against 1.5 s and $0.000093 for the
LLM backup. What was learnt along the way, including two prompt fixes for how literally it reads,
is in [docs/notes/jev.md](docs/notes/jev.md).

**AI-native engineering.** Built with Claude Code, spec first: [`SPEC.md`](SPEC.md) and one spec
per module with acceptance criteria, the architecture decisions in
[docs/agent-design.md](docs/agent-design.md), and a task plan
([`tasks/plan.md`](tasks/plan.md), [`tasks/todo.md`](tasks/todo.md)) with human review at each
checkpoint. Each task was built test first and committed on its own, and what changed during the
build is recorded in the specs ("As built") before the code. The evals are part of the loop: the
first run found a false alarm on blunt refund requests and a gap in the text sanitiser, and both
were fixed before the task closed. Luis's corrections feed the same loop: every reply he edits and
every recommendation he rejects becomes a pending eval case (`evals.import_feedback`), masked,
which a person reviews before it joins the suite. A shadow report measures how often auto-approve
would have matched what he did. CI runs lint, strict types, secret scanning, 939 backend tests on
real Postgres, the frontend tests, the replay evals and the end-to-end tests.

## Evals

37 labelled cases ([`evals/cases/`](evals/cases/)): the 18 seed scenarios, paraphrases, Spanish,
six injection attacks, other topics and the fallbacks. Replay and live are separate tracks, never
mixed.

- **Replay** (recorded answers, CI on every push): **37 of 37 (100%)**.
- **Live**, 2026-10-04, `jev-1.13.0`, `gpt-6-luna`, `gpt-6.1-sol`: **33 of 33 (100%)**. The four fallback cases remove recordings on purpose, so they run in replay only.

Live, per case: latency p50 **3.5 s**, p95 **6.0 s**; cost **$0.00098** on average; 39% go to
Luis to decide. The reply is most of it: 3.1 s and $0.0013 per draft.

Triage, same cases, live ([report](evals/reports/2026-10-04-live.md)):

| Classifier | Right | p50 latency | Cost per case |
|---|---|---|---|
| Jev | 33 of 33 | 228 ms | $0.000036 |
| Luna (the backup) | 32 of 33 | 1.5 s | $0.000093 |
| Sol | not measured | — | $0.0019 (estimate: Luna's tokens at Sol's prices) |

Jev saves 61% of the cost and 84% of the latency against Luna, and about 98% of the cost against
Sol. Sol is never asked to classify: customer text never reaches the drafter. Threshold sweeps
are in [`evals/reports/`](evals/reports/).

## Commands

All commands run from the repo root. Python tools always run as `uv run python -m <tool>`. Those
that touch the database need it up: `docker compose up -d db`.

| What | Command |
|---|---|
| Run everything | `docker compose up --build` |
| Install backend | `uv sync` |
| Install frontend | `npm --prefix frontend install` |
| Reset the demo state (owner role) | `docker compose run --rm migrate python -m backend.bootstrap --reset` |
| Migrations only | `uv run python -m alembic -c backend/db/alembic.ini upgrade head` |
| Backend dev server | `uv run python -m uvicorn backend.api.main:create_app --factory --reload --port 8000` |
| Frontend dev server | `npm --prefix frontend run dev` |
| Regenerate API types | `npm --prefix frontend run gen:api` |
| Unit tests (no database) | `uv run python -m pytest tests/unit` |
| Integration and API tests (need Postgres) | `uv run python -m pytest tests/integration tests/api` |
| All backend tests | `uv run python -m pytest` |
| Frontend tests | `npm --prefix frontend test` |
| End-to-end tests (the stack in replay: `PROVIDER_MODE=replay docker compose up -d --build`) | `npm --prefix frontend run e2e` |
| Lint, format, types | `uv run python -m pre_commit run --all-files` |
| Evals, replay (CI) | `uv run python -m evals.run --mode replay` |
| Evals, live (manual, spends tokens) | `uv run python -m evals.run --mode live` |
| Record new replays (manual, spends tokens) | `uv run python -m evals.run --mode live --record` |
| Threshold sweep (replay, no calls) | `uv run python -m evals.run --mode replay --sweep intent=0.60:0.95:0.05` |
| Luis's edits as pending eval cases | `uv run python -m evals.import_feedback` |
| Shadow-mode agreement | `uv run python -m evals.shadow_report` |
| Regenerate the agent diagram | `uv run python -m scripts.gen_agent_diagram` |
| MCP server (read-only tools) | `uv run python -m backend.tools.mcp_server` |

**MCP.** To use the read-only tools from Claude Code, copy
[`.mcp.json.example`](.mcp.json.example) to `.mcp.json` and set the `agent_reader` password from
your `.env`. Outputs are masked (`••4210`, first names only), and the server can't write.

## Decisions and known limitations

- **Fraud history is not modelled.** "Good standing" means no unpaid balance on any sub-account (D-data-1).
- **Over-limit refunds are routed only.** Above Luis's $50 limit the case reads "Needs supervisor approval", with no draft; nothing in the app lets a supervisor approve yet.
- **Runs are manual.** A case is checked when Luis clicks "Check this case" (or "Check again"); nothing runs on arrival.
- **Extension tables are documented.** The brief's five tables are used as given. Member names, cases, runs, decisions, refunds, the audit log and the policy clauses live in extension tables, described in [SPEC-data.md](SPEC-data.md).
- **Third-party names in free text are not masked.** The member's own name, account numbers, emails, phones and long numbers are; "my husband Carlos" is not (an accepted risk, D9).
- **One staff user, no sign-in.** The demo acts as Luis (`STAFF_ID`); rate limits count per address, so behind nginx all browsers share one.
- **Auto-approve is shadow only.** It is built and tested, and off in every shipped configuration; the shadow report measures how often Luis would have agreed.

## Project structure

```
backend/
  api/          FastAPI app: routes, schemas, errors, rate limits, live steps (SSE), the decision
  agents/       the LangGraph flow, its nodes, the decision, prompts/
  providers/    Jev and OpenAI adapters, replay and recording, retries, cost; recordings/
  policy/       policy documents, clause search, rules, the reason catalogue
  privacy/      sanitising and masking
  tools/        read-only queries for the agent, and the MCP server
  db/           models, migrations, seed, roles
  core/         settings, logging, config/ (thresholds, prices, timeouts)
frontend/
  src/          the page: api/, features/queue/, features/case/, components/, copy/
  e2e/          Playwright end-to-end tests
evals/          cases/, the runner, scoring, reports/
scripts/        the agent diagram generator
tests/          unit/, integration/ and api/ (real Postgres)
docs/           agent-design.md, diagrams/, demo/, notes/
tasks/          the plan and the task list
SPEC.md, SPEC-<module>.md, CLAUDE.md, docker-compose.yml, .env.example
```

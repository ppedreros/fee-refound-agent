# Spec: delivery

Module id: `delivery` · Depends on: `ui`, `evals` (so, everything) · Used by: the reviewers

## Objective

Package the working system so a reviewer can understand it in minutes, run it with one command, see it work, and trust the numbers. The work comes in two phases:

| Phase | Contents | Gate |
|---|---|---|
| **A: deliverable** | README, system design diagram, agent flow diagram, Playwright end-to-end tests, MCP server, demo video | Every acceptance criterion in every other module passes |
| **B: deploy** (last) | Public URL on Render, with a health check | Phase A is done and the user has reviewed a working version (D-delivery-1) |

## Phase A

### README.md (written for reviewers)

**Sections, in order:**

1. **What this is.** Two sentences, plus a screenshot of Ana's case.
2. **Run it:** `cp .env.example .env && docker compose up --build`, then open `http://localhost:8080`.
3. **Replay mode, stated up front:** "Without API keys, the system uses real model responses recorded earlier. `/health` and the page header say which mode is on. Add `JEV_API_KEY` and `OPENAI_API_KEY` to run live."
4. **How it works.** Five lines, plus links to both diagrams and to `docs/agent-design.md`.
5. **The four criteria.** One short paragraph each, saying where to look for agentic logic, UI and plain language, learning speed (Jev: what it is and why it fits each step) and AI-native engineering (spec-first workflow, evals, how Claude Code was used).
6. **Evals.** The replay pass rate (CI badge), and the latest **live** pass rate with its date and model versions, kept as separate lines. Also the cost and latency per case, and the classifier comparison.
7. **Commands.** The table from `SPEC.md`.
8. **Decisions and known limitations:**
   - fraud history is not modelled
   - over-limit refunds are routed only
   - runs are manual
   - extension tables are documented
   - third-party names in free text are not masked
9. **Project structure.**
10. **Deploy.** Filled in during phase B.

### Diagrams (`docs/diagrams/`, Mermaid, rendered on GitHub)

**`system.md`.** One diagram, end to end, of the production target on AWS. Below it, a note on how the local compose stack maps to it.

| Layer | AWS component |
|---|---|
| Frontend | CloudFront + S3 (static build), with `/api/*` routed to the ALB |
| Backend | ALB → ECS Fargate service (FastAPI, runs in-process) in private subnets |
| Database | RDS PostgreSQL (Multi-AZ), with roles `agent_reader` and `app_writer` |
| Secrets | Secrets Manager → task environment |
| Observability | CloudWatch Logs (JSON lines), metrics and alarms on `/health`, error rate and run latency |
| Outbound | NAT → Jev API, OpenAI API |

**`agent-flow.md`.** This covers what the brief lists:
- the structure: sequential, with one parallel fan-out
- each node's kind (rule, Jev, LLM, tool)
- each system prompt, one line, linked to its file
- tool calls
- the fallback chain for each call (timeouts and retries)
- the handoff points to Luis

It is generated from the same node list as `SPEC-agent.md`, so the diagram and the code can't drift.

### End-to-end tests (`tests/e2e/`, Playwright)

**Setup.**
- They run against the compose stack in replay mode (`baseURL http://localhost:8080`).
- `globalSetup` runs `docker compose run --rm migrate python -m backend.bootstrap --reset`. This uses the owner role, and it resets the given tables too.

| Spec | Steps | Asserts |
|---|---|---|
| `happy-path.spec.ts` | Open the queue → select Ana → "Check this case" → wait for the steps → "Refund $35 and send reply" | Live step labels appear in order. Status reads "Ready to refund". After the click: "Done" and "Refunded $35 and replied". A second click is impossible because the button is gone. |
| `fallback.spec.ts` | Open scenario 18 → "Check this case" | Status reads "Needs your call", with "The automatic check isn't available right now." The evidence sections are still present. |
| `a11y.spec.ts` | Queue and Ana's case | `@axe-core/playwright` finds no serious or critical violations |

The `e2e` job is enabled in CI: it brings the stack up with compose, runs Playwright, and uploads traces when a test fails.

### MCP server (`backend/tools/mcp_server.py`)

**What it is.**
- Built with the official `mcp` Python SDK (FastMCP), over stdio.
- It exposes the read-only tools: `get_conversation`, `list_member_accounts`, `list_transactions`, `list_fee_refunds` and `search_clauses`.
- It always uses `agent_reader`, so it cannot write.

**Personal data.** Outputs are masked for any external client: account numbers become `••4210`, and only the first name is shown. Tools that take ids validate them.

**Running it.**
- Command: `uv run python -m backend.tools.mcp_server`.
- The README includes a `.mcp.json` snippet for Claude Code.

**Test.** `tests/integration/tools/test_mcp_server.py` starts the server in-process, lists the tools, and calls `list_transactions(301, 2026-09-14, 2026-09-14)`. It gets three rows in posting order, with no full account number in the output.

### Demo video

**Content.**
- A 2–3 minute walkthrough, stored at `docs/demo/demo.mp4` (or linked from the README if it is over 50 MB).
- `docs/demo/script.md` holds the storyboard:
  1. `docker compose up`
  2. the queue
  3. checking Ana's case live
  4. the posting-order evidence and the policy quote
  5. approve, then Done
  6. the injection case
  7. the fallback case
  8. `evals.run --mode replay` in the terminal
  9. Replay mode in the header

**Who records it.** The user records it. Claude prepares the script and the demo state (`docker compose run --rm migrate python -m backend.bootstrap --reset`).

## Phase B: deploy (only after phase A has been reviewed)

**Render blueprint (`render.yaml`, committed).**

| Resource | Details |
|---|---|
| `backend` | Docker web service, same image, health check path `/health`, pre-deploy `python -m backend.bootstrap` (needs `OWNER_DATABASE_URL`, see SPEC-platform D-platform-1) |
| `frontend` | Docker web service, same nginx image, with `BACKEND_URL` pointing to `backend`. SSE works the same as locally. |
| `db` | Managed PostgreSQL |

**Demo safety.**
- Fake data only.
- `PROVIDER_MODE=replay`. No model keys are set, so there is no token spend.
- API rate limits are on.
- A basic-auth password on the frontend, shared with the reviewers. `/api/health` stays public.
- "Reset demo" is documented as a one-off job: `python -m backend.bootstrap --reset`.

**Known risk.** Render's managed Postgres may not allow `CREATE ROLE`. If it doesn't, the fallback is one database user with agent sessions forced read-only (`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`). That weakens the "agents use a read-only role" boundary, so it is an **ask-first** change. If accepted, the README states it.

**Acceptance.** The public URL serves the app behind basic auth. `https://<host>/api/health` returns 200 with `provider_mode.jev` and `provider_mode.openai` equal to `replay`. Ana's happy path works on the public URL.

## Acceptance criteria (phase A)

1. A reviewer with only Docker installed can follow the README from a clean clone to Ana's approved refund without reading any other file.
2. Both diagrams render on GitHub. The system diagram covers cloud, backend, frontend and database. The agent diagram covers structure, prompts, tool calls, fallbacks and handoffs.
3. All three Playwright specs pass locally and in CI.
4. The MCP server test passes. The README snippet connects from Claude Code.
5. The demo video (or its link) and its script are in the repo.
6. The README shows the replay and live pass rates on separate lines, the live one with its date and model versions.

## Decisions taken in this spec

- **D-delivery-1.** Deploy happens last, on Render, only after the user has reviewed a working deliverable. Platform keeps it config-only: nginx upstream from env, `$PORT`, and one migrate-and-seed command.
- **D-delivery-2.** The system diagram shows the AWS production target. Render is presented as demo hosting.
- **D-delivery-3.** In scope: Playwright end-to-end tests with axe, the MCP server (masked outputs, read-only role), and the demo video recorded by the user.

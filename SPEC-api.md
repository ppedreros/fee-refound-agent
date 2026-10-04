# Spec: api

Module id: `api` · Depends on: `agent` (and `data`, `policy` through it) · Used by: `ui`, `delivery`

## Objective

Expose the five endpoints from the brief, plus a stream for live steps and an audited account-number reveal. The decision endpoint is the only place where money moves, and it is safe to send twice. Every input is validated. Every error is a friendly message with no stack trace.

## Conventions

- **Base path.** Backend routes are at the root (`/health`, `/cases`, …). nginx serves them under `/api`.
- **Identity.** The acting staff member is `STAFF_ID` from the environment (Luis, `S07`). Login is out of scope. Every audit event and decision records this id.
- **Error format.** Every error has the same shape. `code` is for UI logic only and is never shown; `message` is what Luis may see.

  ```json
  {"error": {"code": "case_not_running", "message": "This conversation is waiting for the member."}}
  ```

- **Unexpected errors.** A 500 is logged with the request id and returns "Something went wrong on our side. Please try again." The response has no trace, ever.
- **Rate limits** (slowapi, per client): `RATE_LIMIT` (default 60/minute) on every route, and 10/minute on `POST /cases/{id}/run`. A 429 carries `Retry-After` and "You're going a bit fast. Please wait a few seconds."
- **API types.** The OpenAPI schema is the source of the frontend's types (`npm --prefix frontend run gen:api`).

## Endpoints

### `GET /health`

200 or 503:

```json
{"status": "ok", "database": "ok", "provider_mode": {"jev": "replay", "openai": "replay"}, "version": "<git sha>"}
```

### `GET /cases`

The queue.

**Query parameters**
- `view`: `open` (default) or `done`.
  - `open` means the conversation status is `waiting_for_bank` or `read_by_bank`.
  - `done` means the case status is `done`, or the conversation is closed.
- `limit`: 1–100, default 50.
- `cursor`: opaque.

**Order.** Open cases are sorted by the oldest unanswered member message first.

**Each item:**

```json
{
  "id": 5012,
  "member_name": "Ana T.",
  "subject": "Overdraft fee",
  "received_at": "2026-09-15T08:12:44Z",
  "status": "ready_to_refund",
  "topic": "fee_refund_request",
  "amount": "35.00",
  "checked_at": "2026-10-03T14:02:10Z"
}
```

- Before a case has been checked, `status` is `not_checked` and `topic` is `null`.
- `amount` is `null` when there is no recommendation.

### `GET /cases/{id}`

One case, with its evidence. 404 means "We couldn't find that conversation."

| Field | Content |
|---|---|
| `conversation` | Subject, the conversation's status, messages (author `member` or `staff` with the staff member's display name, text, time) |
| `member` | Full name. Accounts as `••4210` with `account_id`. Sub-accounts: display name, type, balance, available. |
| `status`, `topic`, `language` | From the case and its latest run |
| `summary` | One plain sentence explaining the status, rendered by the backend from the facts (`render_summary` in `backend/policy/reasons.py`). For example: "The paycheck arrived the same day and the bill posted before it." `null` when the reasons already say it all. |
| `reasons`, `notes` | Rendered by `render_reason`: `{message, next_step}`. Codes are not included. |
| `recommendation` | `{action: refund \| no_refund \| none, amount}` |
| `fee`, `candidates` | Date, amount, fee type, how it was chosen (`rule`, `jev` or `staff`). Each candidate has a `fee_txn_id` for "Pick the fee". |
| `evidence.fee_day` | That day's transactions on the fee's sub-account, in posting order: position, description, amount, balance after, kind. Also `summary`, the counterfactual sentence from `render_summary` (for example "If the paycheck had posted first, the balance would have stayed at $1,360."), or `null`. |
| `evidence.refunds_in_window` | Date, fee type, amount, plus the window start and end and the max allowed |
| `evidence.checks` | One line per rule: plain label, passed or failed, and its facts |
| `clause` | Verbatim text, document title, section |
| `draft` | Reply text with the first name filled in, and `source` (`model` or `template`) |
| `run` | `run_id`, when it was checked, duration, cost (or `null`), provider mode, and steps (`node`, `state`, `latency_ms`) |
| `decision` | When decided: who, when, action, whether a refund was made, and the reply that was sent |
| `actions` | The decision actions allowed right now (see the decision rules below), so the UI never guesses |
| `can_run` | `true` when `POST /run` would be accepted: the conversation is runnable, no run is active, and the case is not `done` |
| `can_pick_fee` | `true` when the latest run ended with `fee_ambiguous` and `candidates` is not empty |

### `GET /cases/{id}/accounts/{account_id}/number`

Returns the full account number. It writes an `account_number_revealed` audit event. It returns 404 if the account doesn't belong to the case's member.

### `POST /cases/{id}/run`

Starts checking the case. Manual only (D-api-2).

**Body (optional):**

```json
{"fee_txn_id": 88002}
```

This is "Pick the fee": the id must be one of the latest run's candidates.

**Responses**

| Code | When | Body / message |
|---|---|---|
| 202 | Run started | `{"run_id": "…"}`. The case goes to `checking`. |
| 409 `run_in_progress` | A run is already active (enforced by a partial unique index on `agent_runs(case_id) WHERE status = 'running'`) | Includes the active `run_id`, so the UI attaches to it |
| 409 `case_not_running` | Conversation is `waiting_for_member` or `closed`, or the case is `done` | "This conversation is waiting for the member." / "This conversation is closed." / "This case is already done." |
| 422 `invalid_fee` | The pinned fee is not a candidate | "That fee isn't one of the options for this case." |

The run executes as an `asyncio` task inside the API process, with the run timeout from `SPEC-agent.md`.

### `GET /cases/{id}/runs/{run_id}/events`

Server-sent events (sse-starlette).

- Each event is `{"event": "step", "node", "state"}`. The last one is `{"event": "done", "status"}`.
- A client that connects late first receives the steps already recorded in `agent_steps`, then the live ones.
- A finished run returns its full history, then `done`.
- A keep-alive comment is sent every 15 seconds.

### `POST /cases/{id}/decision`

The only action that moves money.

**Header:** `Idempotency-Key: <uuid>` (required).

**Body:**

```json
{
  "run_id": "5b1c…",
  "action": "approve",
  "reply_text": "Hi Ana, …",
  "reason": null
}
```

**Actions**

| Action | Meaning | Refund? | `reason` |
|---|---|---|---|
| `approve` | Do what the recommendation says, with the draft unchanged | Yes, if the recommendation is `refund` | Not allowed |
| `edit` | Do what the recommendation says, with Luis's edited reply | Yes, if the recommendation is `refund` | Optional |
| `reject` | Act against the recommendation. On `refund` it doesn't refund. On `no_refund`, or on `none` with an identified fee (for example `fee_question`), it refunds: that is "Refund anyway". | Yes, unless the recommendation is `refund` | Required, 10–500 characters |
| `reply_only` | Send a reply and move no money. Used when there is no recommendation, for example `fee_not_found` or `fee_question`. | No | Optional |

**Validation, in order**

1. **Key.** `Idempotency-Key` must be a UUID, otherwise 422.
2. **Same key seen before.** With the same body, return the stored response with 200, and no side effects. With a different body, 422 `idempotency_mismatch`: "This decision was already sent with different details."
3. **Already decided.** The case is `done`: 409 `already_decided`, "Luis already decided this case at 10:42."
4. **Stale run.** `run_id` is not the case's latest run: 409 `stale_run`, "This case was checked again. Please look at the new result."
5. **Approval limit (D-api-1).** Checked before the action list, so the friendly message always wins. Any action that would refund above `staff_limit_usd` gives 403 `over_limit`: "A supervisor needs to approve this refund. That happens outside this tool for now."
6. **Action allowed.** The action must be in the case's `actions`, otherwise 422 `action_not_allowed`.
7. **Amount.** The refund amount is always the fee amount from the run. It is never in the request.
8. **Reply text.** 1–2,000 characters after trimming. Control characters are rejected. `{{first_name}}` is not allowed; the UI sends text with the name already filled in.

**Effects** (one database transaction, `app_writer`):

1. Insert the `decisions` row (`idempotency_key` UNIQUE).
2. If refunding, call `CoreBanking.post_fee_refund(fee_txn_id, decision_id, today)`. Money-level idempotency is `refunds.fee_txn_id` (see `SPEC-data.md`).
3. Insert the reply into `messages` with `author_id = STAFF_ID`.
4. Set `conversations.status = 'closed'`. As in the brief, Luis replies and closes the conversation.
5. Set the case to `done`.
6. Write audit events: `decision_made`, `refund_posted` when there was one, `reply_sent`.
7. For `edit`, `reject` and `reply_only`, insert an `eval_candidates` row (feedback loop).

**Response 200:**

```json
{"decision_id": "…", "refunded": true, "amount": "35.00", "case_status": "done"}
```

**Allowed `actions` per status**

| Status | Actions |
|---|---|
| `ready_to_refund` | `approve`, `edit`, `reject` |
| `recommend_no_refund` | `approve` (send the decline), `edit`, `reject` (refund anyway) |
| `needs_supervisor` | `reject` (don't refund), `reply_only`. `approve` and `edit` would hit the limit, so they are not offered. |
| `needs_your_call` with a recommendation | `approve`, `edit`, `reject` |
| `needs_your_call` without a recommendation | `reply_only`. Plus `reject` (refund anyway) when a fee is identified. Picking a fee is a re-run, signalled by `can_pick_fee`, not a decision action. |
| `not_checked`, `checking`, `not_about_fee`, `done` | none |

Rules that apply whatever the status:
- `approve` is offered only when there is a draft. `edit` is offered when there is a draft, or when Luis writes one himself.
- Actions that would refund are never offered when the amount is above the limit.

## Auto-approve (flag off; tests only)

When `AUTO_APPROVE_ENABLED=true` (never in the shipped config), the run endpoint's completion hook does the following for a run with `would_auto_approve`:

- it calls this module's own decision handler, in-process
- the actor is staff `SYSTEM`, the action is `approve`, and `Idempotency-Key` is the `run_id`
- money still moves only through the decision handler

The agent module never acts on this flag.

## Bootstrap

`backend/bootstrap.py` belongs to this module, because it is the composition root. It runs migrations, roles, the `data` seed and the `policy` clause loader. `--reset` restores the demo state.

## Startup

On startup, mark runs that are still `running` as `interrupted`, and set their cases back to `not_checked` (see `SPEC-agent.md`).

## Acceptance criteria

1. **API test (the brief's "one API test"):**
   - `POST /cases/5012/run` → wait for `done` on the events stream → `GET /cases/5012` shows `ready_to_refund` with the fee, the evidence and the draft.
   - `POST /decision` with `approve` → 200, refunded $35.
   - The same request again → the same 200.
   - Only one refund transaction exists, and the balance went up by $35 once.
2. A new idempotency key on the decided case → 409 `already_decided`. The same key with a different reply → 422 `idempotency_mismatch`.
3. A stale `run_id` → 409. An action that is not allowed → 422. An over-limit refund (scenario 17) → 403 with the supervisor message.
4. `POST /run` on a closed conversation → 409. A second `POST /run` during a run → 409 with the active `run_id`.
5. `GET /cases/999999` → 404 with the friendly body. Non-numeric ids → 422 with a friendly body. No response body contains a traceback.
6. The 61st request in a minute → 429 with `Retry-After`.
7. The account-number reveal returns the full number and writes an audit event. Another member's account → 404.
8. The events stream for a finished run returns all recorded steps, then `done`.
9. No response field contains a reason code, placeholder, or `[ACCOUNT_1]`-style token.

## Tests

| File | Covers |
|---|---|
| `tests/api/test_happy_path.py` | Criterion 1 (the required API test) |
| `tests/api/test_decision_rules.py` | Idempotency, stale run, allowed actions, limit, validation |
| `tests/api/test_runs.py` | Run conflicts, not-runnable statuses, pinned fee, events stream |
| `tests/api/test_errors.py` | 404, 422, 429, 500 envelope, no tracebacks |
| `tests/api/test_reveal.py` | Reveal and audit |

All API tests use fake providers and a real Postgres.

## Decisions taken in this spec

- **D-api-1.** Over-limit refunds are only routed. No approval happens inside this app, and the API refuses any refund above the limit. Rejected: role-based supervisor approval on the same page; an identity switcher in the UI.
- **D-api-2.** Runs are manual only: "Check this case" and "Check again". Only `waiting_for_bank` and `read_by_bank` conversations can run, and there is at most one active run per case. Rejected: a background auto-check worker; running when the case is opened. Consequence: the queue shows a topic and status only for cases already checked.
- **D-api-3.** The decision `action` is `approve`, `edit`, `reject` or `reply_only`. `reject` means "act against the recommendation", so on `none` with a fee it refunds. The amount never comes from the client.
- **D-api-4.** A decision closes the conversation and posts the reply as a staff message, as in the brief.

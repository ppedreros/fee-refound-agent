# Spec: agent

Module id: `agent` · Depends on: `data`, `policy`, `providers` · Used by: `api`, `evals`

## Objective

Turn one conversation into a prepared case. The output is a status, the reasons in plain words, the evidence, a quoted policy clause, a recommendation and, when there is something to send, a draft reply. It is built as a read-only LangGraph `StateGraph` that follows [docs/agent-design.md](docs/agent-design.md). It never moves money, and every step is recorded.

## Graph

```
load_conversation
  → triage ─────────────── confidently not about a fee ──→ finalize
  → { load_accounts ∥ load_transactions ∥ load_refund_history }
  → identify_fee ───────── fee_not_found · fee_ambiguous · data_timeout ──→ finalize
  → run_checks           (all rules, pure, microseconds)
  → decide               (status, recommendation, clear flag)
  → find_policy          (search → Jev Choice → cross-check against the decisive rule)
  → draft ─────────────── skipped when there is nothing to send ──→ finalize
  → finalize
```

This differs from the first version of D6, where `find_policy` ran in parallel with the checks. The clause to quote depends on which rule decided the case, and the rules are pure functions, so the parallelism bought nothing. `docs/agent-design.md` is updated to match.

## State

`GraphState` is a Pydantic model. Lists that several nodes add to use LangGraph reducers.

| Field | Set by | Notes |
|---|---|---|
| `case_id`, `run_id`, `pinned_fee_txn_id` | runner | `pinned_fee_txn_id` comes from Luis's "Pick the fee" (staff input, trusted) |
| `member_id`, `masked_message`, `masking` | `load_conversation` | `masking` is the dictionary. It is never serialised into steps. |
| `triage` | `triage` | topic, intent, language, tone, flags, `classifier_used` |
| `accounts`, `transactions`, `refunds` | `load_*` | Typed models from `backend/tools` |
| `fee`, `fee_source` | `identify_fee` | `fee_source` is `rule`, `jev` or `staff`. `candidates` is kept for the UI. |
| `checks` | `run_checks` | `list[RuleResult]` |
| `decision` | `decide` | status, recommendation, decisive rule, `clear`, `would_auto_approve` |
| `clause` | `find_policy` | The verbatim clause and how it was found (`search_confirmed` or `rule_fallback`) |
| `draft` | `draft` | Reply with the `{{first_name}}` placeholder, plus `source` (`model` or `template`) |
| `reasons` | any node | `list[ReasonCode]`, appended through a reducer |

## Nodes

| Node | Kind | Does | On failure |
|---|---|---|---|
| `load_conversation` | tool | Loads the conversation, the member messages since the last staff message (joined in order), the member profile and the account numbers. It loads no balances. It builds the masking dictionary, then sanitises and masks the message. | `data_timeout`, then finalize |
| `triage` | Jev (Luna fallback) | One request with these questions (prompt `triage-v1`): **intent** (Choice: `fee_refund_request`, `fee_question`, `card_issue`, `account_update`, `statement_question`, `other`), **language** (Choice: `en`, `es`, `other`), **tone** (Choice: `formal`, `casual`, `upset`), **manipulation** (Noul), **multiple_requests** (Noul). It then applies the D3 thresholds. | `ClassifierUnavailable`: adds `classifier_down`, treats the message as a possible fee request, and continues |
| `load_accounts` / `load_transactions` / `load_refund_history` | tool, in parallel | Sub-accounts and balances; transactions from 30 days before the message to the message date; fee refunds from 400 days before the message (`list_fee_refunds`), plus our own `refunds` rows for the member's fees (`list_our_refunds`) | `data_timeout`, then finalize |
| `identify_fee` | rule, plus Jev Choice | **Pinned fee:** it must be one of the case's candidates, otherwise `ToolError`. **No pin:** `find_fee_candidates`. 0 candidates gives `fee_not_found`. 1 candidate is chosen. More than 1 goes to Jev Choice (prompt `fee-choice-v1`, masked message plus candidates labelled "Sep 14 · −$35.00 · Courtesy Pay fee"). It is chosen if confidence ≥ 0.85, otherwise `fee_ambiguous`. | Classifier unavailable with more than 1 candidate gives `fee_ambiguous` |
| `run_checks` | rule | `verify_posting_order`, `check_not_already_refunded`, `check_yearly_limit`, `check_good_standing`, `check_approval_limit` (see `SPEC-policy.md`) | — |
| `decide` | rule | Status precedence, recommendation, `clear`, `would_auto_approve` (see below) | — |
| `find_policy` | tool, plus Jev Choice | Builds the query from the decisive rule's facts, gets the top 5 from `search_clauses`, then asks Jev Choice (prompt `clause-choice-v1`) to pick one. It uses that clause if it matches the decisive rule's `clause_id` and confidence ≥ 0.85 (`search_confirmed`). Otherwise it uses `get_clause(rule.clause_id)` (`rule_fallback`) and logs the mismatch. For `fee_question`, the decisive clause is the fee type's clause in the fee schedule (`fee_schedule_clause(fee_type)`, see `SPEC-policy.md`). | Any failure falls back to `rule_fallback` |
| `draft` | Sol | Runs when there is a recommendation (refund or no refund), the intent is `fee_refund_request` or unknown, and the language is `en` or `es`. Sends `DraftInput` (prompt `draft-v1`), then runs the post-check. | `DrafterUnavailable`, or the post-check failing twice: use the template and add `drafter_down` |
| `finalize` | rule | Builds `result`, sets the case's topic and status | — |

### Triage rules (from D3)

| Signal | Jev | Luna fallback |
|---|---|---|
| Not about a fee (early exit) | Intent is neither fee intent, with confidence ≥ 0.80 | Intent is neither fee intent. Luna is the trusted backup, so its label is used, plus the `classified_with_backup` note (D-agent-5). |
| `intent_unclear` | Confidence < 0.80 | Never. Luna gives a label only. |
| Language | `confidence ≥ 0.70`, else the last known language (`get_last_known_language`), else `en`. `other` with confidence ≥ 0.70 gives `language_unsupported`. | Same, using the label |
| Tone | `confidence ≥ 0.60`, else `neutral` | Label |
| `manipulation` | `p_yes > 0.15` | `label = true` |
| `multiple_requests` | `p_yes ≥ 0.50` | `label = true` |
| `fee_question` | Intent `fee_question` with confidence ≥ 0.80: adds `fee_question`. Evidence is still prepared, and no draft is written. | Same |

### Draft input (D2: facts only)

```json
{
  "language": "en",
  "tone": "casual",
  "outcome": "refund",
  "amount": "35.00",
  "fee_date": "2026-09-14",
  "fee_type": "Courtesy Pay",
  "sub_account_name": "Everyday Checking",
  "facts": ["deposit_same_day", "bill_posted_before_deposit"],
  "policy_clause": null,
  "first_name": "{{first_name}}"
}
```

`DraftInput` has no field that can hold the member's message. A test asserts that no message text reaches any `llm` step's `input_masked`.

**Post-check.** All of these must hold:

- `{{first_name}}` is present
- every amount is either the decided amount or one quoted in `policy_clause`
- no run of 6 or more digits
- 800 characters or fewer

**As built (T28).** The `draft` node sends Sol the facts as plain English sentences with no amount, built from the rules' facts: for a refund, the card sentence ("The paycheck arrived the same day and the bill posted before it."); for a decline, the decisive reason's sentence, with the member called "The member". A reply that fails the post-check is asked for once more; if Sol fails, or the second reply fails too, the node uses the template and adds `drafter_down`. Its step is then `failed`, with `error_code` set to the provider's reason or `postcheck_failed`, and `output.postcheck` lists the last problems. Both calls' tokens and cost are summed into the one step. Amounts are recognised in English and Spanish forms ("$35", "$35.00", "US$35", "35,00 $", "35 dólares"). Declines have no template until T31, so a failed decline draft leaves no draft, only `drafter_down`. When Luna answers triage, that step is an `llm` step too, and it carries the masked message, because classifying is its job; the test that no message text reaches an `llm` step's input covers Sol's step, the only one that writes free text.

**Templates.** The fallback templates are in `backend/agents/prompts/templates/`, in English and Spanish, one for "refunded" and one per decline reason (`yearly_limit`, `not_good_standing`, `deposit_not_same_day`, `already_refunded`).

**As built (T31).**
- **Decline templates.** `declined_<reason>.{en,es}.txt` for `yearly_limit`, `deposit_not_same_day`, `not_good_standing` and `already_refunded`. They explain the rule in plain words, with the limit or the refund date where it applies; a test renders every template and runs it through the post-check. The Spanish replies use "tú", as Sol's examples do; the existing "refunded" template is aligned with them.
- **Above the limit, no draft.** A refund above the staff limit gets no draft. This narrows the `draft` rule above: Luis can only "Don't refund" or "Send a reply only" (D-api-1), and a "we've refunded" reply would never be sent. For the clause choice, such a case is described as "Refund the $60 Extended overdraft fee, above the staff approval limit.", with the fact "The policy allows this $60 refund, but it is above your $50 limit." In a live check this made Jev confirm `staff-approval-limits#1`; before, it chose the same-day clause and the cross-check fell back.
- **Reason order.** `finalize` lists triage's reasons, then the decision's, then those that appear later (`drafter_down`), so Luis reads the policy reason before "Reply written from a standard template".
- **Live check (2026-10-04).** Scenarios 6, 7, 8, 11 and 17 reached their statuses with live Jev and Sol, and Sol's decline replies explained each rule in plain words. Jev confirmed the clause for 6, 7 and 17; for 8 and 11 it was unsure (confidence 0.4), and the cross-check quoted the rule's clause, as designed.

## Decision (`backend/agents/decide.py`)

**Codes added in this spec.** `fee_question` is in the uncertainty group. Luis sees "Ana is asking why a fee was charged, not for a refund.", and the next step is "Write a reply, or refund anyway".

**Recommendation.**
- `refund` when every check passes.
- `no_refund` when a policy rule fails. The decisive rule is the first failing rule, in this order: already refunded, posting order, yearly limit, good standing.
- `none` when there is no fee, no usable data, or the intent is `fee_question`. We don't recommend refunding what wasn't asked for, but the checks still run and show as evidence, so Luis can refund anyway.

**Status precedence** (exactly one per case):

| Order | Status | When |
|---|---|---|
| 1 | `needs_your_call` | Any uncertainty or failure code (`intent_unclear`, `fee_question`, `fee_ambiguous`, `fee_not_found`, `manipulation`, `multiple_requests`, `language_unsupported`, `classifier_down`, `drafter_down`, `data_timeout`, `data_mismatch`). It keeps the recommendation and draft when they exist. |
| 2 | `needs_supervisor` | Recommendation is `refund` and `over_limit` |
| 3 | `recommend_no_refund` | Recommendation is `no_refund` |
| 4 | `ready_to_refund` | Recommendation is `refund`, there are no codes above, and the amount is within the limit |
| — | `not_about_fee` | Early exit from triage |

The only note is `classified_with_backup`. It never changes the status, but it keeps the case from being "clear". Jev falling back to Luna is normal operation. Manual review happens only when Luna fails too (`classifier_down`), or when Sol fails (`drafter_down`), as the brief requires (D-agent-7).

**Clear case (D5).** `clear` is true when all of these hold:

- the status is `ready_to_refund`
- `classifier_used` is `jev`
- intent confidence is ≥ 0.80
- `fee_source` is `rule` (a single candidate)
- the posting-order check passed
- manipulation `p_yes` is ≤ 0.15
- the amount is ≤ $35

`would_auto_approve = clear`. It is always stored.

**How it is built (T16).** `backend/agents/triage_rules.py` and `decide.py`; the D3 thresholds and the $35 "clear" limit are in `backend/core/config/thresholds.yaml`. Details fixed while building:

- A missing manipulation `p_yes` from Jev counts as "yes" (the asymmetric band of D3).
- The early exit records `not_fee_request` (routing: no banner).
- A decline lists only its decisive reason; every check stays visible as evidence. `over_limit` is added only to a refund.
- `data_timeout` or `data_mismatch` mean no usable data, so the recommendation is `none`.
- `case_status(codes, action, about_fee)` is a pure function that `finalize` calls again, because `drafter_down` can appear after `decide`.

**`AUTO_APPROVE_ENABLED`.** This module never acts on it. The runner only stores `would_auto_approve`. The flag-on behaviour (only for tests, never in the shipped config) lives in `SPEC-api.md`, which owns the only path that moves money.

## How the graph is built (T17)

- `backend/agents/graph.py` wires the nodes in `nodes.py`. Each node returns its state update plus a `StepReport` (kind, masked input, output, `CallMeta`, prompt version, error code). A wrapper in `steps.py`, outside the node code, times it and emits the `started` and `finished`/`failed` stream events; the last one carries the `StepRecord` the runner stores (T18).
- The same wrapper module gives read tools their one retry (`tools.yaml`) on a fresh `agent_reader` session, never starting after the run deadline. Each node opens its own session, because the reads run in parallel.
- The member's messages since the last staff reply are joined, sanitised and masked; so is the subject. Jev's state is `{subject, message}` (D-providers-1).
- `result` also carries what Luis's page needs to show the evidence as the agent saw it: `candidates`, `facts` (all rule facts plus `fee_date`), `checks`, `decisive_rule`, `tone`, `classifier_used`, and `evidence` (`fee_day` rows of the fee's sub-account, core `refunds`, `sub_accounts` with balances). It never holds a name or an account number.
- At this stage `find_policy` always uses `rule_fallback` and `draft` the reply templates (`backend/agents/prompts/templates/refunded.{en,es}.txt`); decline templates come in T31. More than one fee candidate gives `fee_ambiguous` until the Jev fee choice lands in T32.

## Injection, Spanish and more than one request (T34)

The signals were already wired (T16, T17, T28); these scenarios prove them with real data. With fakes: the injection is flagged as `manipulation`, the recommendation stays exactly $35, and "500" appears nowhere in the result, the draft or Sol's input, while the triage step shows Jev judged the text as data. A Spanish message gets a Spanish draft input and, if Sol fails, the Spanish template; two requests give `multiple_requests` and keep the refund and its draft.

**Live check (2026-10-04).** Jev flagged Victor's message as manipulation and the case stayed at $35, with no "500" in the draft. Sol wrote Sofía's reply in Spanish ("Hola Sofía, gracias por escribirnos… tu nómina llegó ese mismo día…"). Jev flagged Mei's two requests.

## The fee question (T33)

- **No decline to explain.** A `fee_question` gets no recommendation and lists only `fee_question` as its reason, even when a rule would fail: nobody asked for a refund, so there is nothing to decline. Every check still shows as evidence, so Luis can still "Refund anyway". Before this, a failing rule also added its decline reason ("No deposit arrived on the day of the fee.") to a question about a savings fee.
- **The search looks for the fee.** For a question, the policy query is the fee type alone, with no "refund" and no rule topics, so the fee's schedule clause comes first (for Daniel, `fee-schedule#4`). The cross-check is against `fee_schedule_clause(fee_type)`, as before.
- **Live check (2026-10-04).** Daniel's question: `fee_question`, the "Savings below minimum balance" clause, no draft, and the actions "Send reply" and "Refund anyway". Jev chose the right clause with confidence 0.70, below the bar, so the rule's (same) clause was quoted. Marcus's card message exited early as `not_about_fee`.

## How `identify_fee` chooses between fees (T32)

- **Told apart by their cause.** Two same-day fees have the same date, amount and type, so the label of §6 can't tell them apart. Each candidate is described with the payment that caused it, the last debit before it that day: "Sep 14 · −$35.00 · Courtesy Pay fee · after CITY POWER & LIGHT −$60.00". Payees are not personal data, and masking keeps them for exactly this. The run's `candidates` carry the cause as `after: {payee, amount}`, and Luis's fee picker uses the same label.
- **Jev alone, and only when sure.** More than one candidate asks `AgentDeps.chooser` (`fee-choice-v1`: "Which of these fees is the member asking about in the `message`?", the masked `{subject, message}` as state, the transaction ids as option keys). The fee is chosen only with confidence ≥ 0.85, as `fee_source = jev`; otherwise, or if Jev is unavailable, it is `fee_ambiguous` and Luis picks. The backup is not asked: choosing which fee to refund needs a calibrated confidence, and Luna gives none (this narrows §5's "fee choice → Luna").
- **The reason** says the day the fees share ("Ben has 2 fees on Sep 14 and the message doesn't say which one."), or "2 recent fees" when they fell on different days.
- **Live check (2026-10-04).** Scenario 9: Jev was unsure (0.24), so Luis is asked to pick. Scenario 10: Jev chose the electric bill's fee with confidence 1.00.

## How `find_policy` is built (T30)

- **Jev alone.** The clause choice asks Jev directly (`AgentDeps.chooser`, the Jev link in whatever mode it runs), not the Jev → Luna chain: §5 sends a failed clause choice to the rule's clause, and Luna gives no confidence to compare with 0.85.
- **The question** (`clause-choice-v1`): "Which of these policy clauses is the rule behind the `decision`, given the `facts`?" The state is `{decision, facts}` in plain words ("Refund the $35 Courtesy Pay fee.", the same fact sentences Sol gets), with no member text. Each option's key is the clause id and its description the verbatim clause text; Jev accepts ids such as `fee-refund-policy#4` as keys (live check).
- **The cross-check.** The chosen clause is quoted (`search_confirmed`) only when it is the deciding rule's clause and Jev's confidence is at least 0.85. Otherwise the rule's clause is quoted (`rule_fallback`), and a `clause_mismatch` warning logs the expected clause, the chosen one and the confidence, as an eval signal. A failed search or an unavailable Jev also quote the rule's clause; the step still finishes, with `rerank_error` in its output. The step records the query, the clauses found, Jev's choice and confidence, and whether they disagreed.
- **Live check (2026-10-04).** For Ana, Jev chose `fee-refund-policy#4` with confidence 1.00 in 300 ms ($0.000025): `search_confirmed`.

## Case status values (contract used by `data` and `api`)

`not_checked` · `checking` · `ready_to_refund` · `recommend_no_refund` · `needs_supervisor` · `needs_your_call` · `not_about_fee` · `done`

The runner sets `checking` when a run starts and `not_checked` when it resets an interrupted run. The `api` decision handler sets `done`. The others come from runs.

## Runner and recording (`backend/agents/runner.py`)

- **Starting a run.** `run_case(case_id, pinned_fee_txn_id=None) -> RunResult` creates an `agent_runs` row (`running`) and sets the case to `checking`. It invokes the graph inside `asyncio.timeout(45)`, using `astream(stream_mode=["updates", "custom"])`.
- **Recording steps.** Every node is wrapped by a recorder that writes one `agent_steps` row with: kind, latency, `CallMeta` (model, mode, tokens, cost, attempts), `error_code`, the masked input and the output.
- **Stream events.** The recorder emits `{"event": "step", "node", "state": "started" | "finished" | "failed"}` and, at the end, `{"event": "done", "status"}`. The UI maps node names to copy.
- **Deadline propagation.** Every provider and tool call receives the run's remaining time. Retries stop rather than overrun it, so a hanging Sol (20 s per attempt) falls back to the template before the 45-second limit. Per-call defaults are unchanged.
- **Run timeout.** If the 45-second timeout still fires, the case becomes `needs_your_call`, with the reason that belongs to the node that was running: `classifier_down` for triage, `data_timeout` for loads. During `draft`, it falls back to the template exactly like a drafter failure.
- **Totals.** Latency, tokens and cost are summed into `agent_runs`, along with `policy_version`, `prompt_versions` and `provider_mode`.
- **Interrupted runs.** At startup, runs still marked `running` become `interrupted`, and their case goes back to `not_checked`, so "Check again" is offered.

**How it is built (T18).** `backend/agents/runner.py` and `recorder.py`. Details fixed while building:

- `run_case` creates the case row when it is missing and the run in one transaction; the partial unique index turns a second concurrent run into `RunInProgress(run_id)`.
- Each step row is written as soon as its node finishes (one short `app_writer` transaction), so a crash still leaves the trace up to that point. Stream events reach the UI without the step record.
- The run timeout (45 s) lives in `backend/core/config/runs.yaml`. When it fires, the result is `needs_your_call` with `classifier_down` for triage, `drafter_down` for draft and `data_timeout` otherwise; the full mapping, including the template fallback during `draft`, is finished in T35.
- An unexpected exception marks the run `failed` and puts the case back to `not_checked`, so "Check again" is offered.
- `total_latency_ms` is the run's wall time; tokens and cost are the sums of the steps' `CallMeta`; `prompt_versions` maps each node to the prompt it used.

**How it is built (T35).**
- **A reserve for the fallback.** `runs.yaml` keeps back `fallback_reserve_s: 3` from every model call: `AgentDeps.model_deadline` is the run's deadline minus the reserve, while reads keep the whole run. So when a model hangs, its fallback (the template, `classifier_down`) and the rest of the graph still finish inside the 45 seconds, with the evidence. Before, a model call could use the whole run, and the reads after it found the deadline already passed.
- **Every model call is bounded** by `bounded(deps, call)` (`steps.py`), even when the provider ignores the deadline it is given: past it, the call is `ProviderUnavailable("timeout")` and the node's fallback follows. The real adapters already stop retrying at the deadline; this also covers one that hangs.
- **The run timeout is the backstop.** It fires only when something ignores every bound, such as a read stuck in the driver, and `timeout_reason(node)` gives the stalled step's reason (`classifier_down` for triage, `drafter_down` for draft, `data_timeout` otherwise). That result has no evidence: the run never reached `finalize`.
- **Live check (2026-10-04).** Aisha's case (16) says "Balances for that day don't add up." with no recommendation. Liam's case (18) behaves like Ana's when live; in replay, with nothing recorded, it ends in `classifier_down` and `drafter_down` with its evidence and the template (tested with an empty replay store).

**Result shape** (`agent_runs.result`, served by the API with names and account numbers filled back in):

```json
{
  "status": "ready_to_refund",
  "reasons": [],
  "notes": [],
  "topic": "fee_refund_request",
  "language": "en",
  "recommendation": {"action": "refund", "amount": "35.00", "fee_txn_id": 88002},
  "fee": {"date": "2026-09-14", "amount": "-35.00", "type": "Courtesy Pay", "source": "rule"},
  "candidates": [],
  "facts": {"deposit_date": "2026-09-14", "deposit_amount": "1400.00", "deposit_posted_after_fee": true, "refunds_in_window": 2, "max_refunds": 3},
  "checks": [{"rule": "verify_posting_order", "passed": true}],
  "clause": {"id": "fee-refund-policy#4", "doc_title": "Fee Refund Policy", "section": "4", "text": "…", "found_by": "search_confirmed"},
  "draft": {"text": "Hi {{first_name}}, …", "source": "model"},
  "clear": true,
  "would_auto_approve": true
}
```

## Prompts (`backend/agents/prompts/`)

The prompts are versioned files (`triage-v1.yaml`, `fee-choice-v1.yaml`, `clause-choice-v1.yaml`, `draft-v1.md`), and their version is stored on every step. Their content follows the outlines in `docs/agent-design.md` §6. Changing a prompt means bumping its version and re-recording replays, which is an "ask first" change.

**Frozen at Checkpoint 5 (2026-10-04).** `triage-v1`, `fee-choice-v1`, `clause-choice-v1` and `draft-v1` are recorded, so they no longer change without a new version and a new recording.

## Acceptance criteria

1. Every seed scenario in `SPEC-data.md` reaches its expected status with in-process fake providers. Scenario 5 (5008) gives `needs_your_call` with `fee_question`, the fee, and the `fee-schedule#4` clause.
2. **Ana (5012):** `ready_to_refund`, recommendation $35 on fee 88002, `clear = true`, clause `fee-refund-policy#4`, an English draft that contains `{{first_name}}` and "$35".
3. **Scenario 12 (injection):** `needs_your_call` with `manipulation`, a recommendation of exactly $35, and no "$500" anywhere in the result or the draft.
4. **Fallbacks, with fakes:**
   - Jev down → Luna answers and `classified_with_backup` is added; `clear = false`.
   - Both classifiers down → `classifier_down`, but the evidence and recommendation are still present.
   - Sol down → `needs_your_call` with `drafter_down`, keeping the recommendation and the template draft, so Luis can still approve in one click.
   - A tool timeout → `data_timeout`.
   - The 45-second run timeout → a mapped reason.
5. **Pinned fee:** re-running scenario 9 with `pinned_fee_txn_id` set to one of its candidates gives `fee_source = staff` and no `fee_ambiguous`. A pin that is not a candidate is rejected.
6. **Read-only:**
   - Nodes and tools receive only an `agent_reader` session. The writer is not in the graph's dependency container.
   - The recorder writes steps from the runner's wrapper, outside node code.
   - A test makes a node attempt an `INSERT`, and it fails with a permission error.
7. **Recording:**
   - Each run writes one `agent_runs` row and one `agent_steps` row per executed node, with latency.
   - LLM and Jev steps also have tokens and cost.
   - No step's `input_masked` contains a seeded name or account number.
8. **Streaming:** the stream for Ana shows `started` and `finished` for each node, in graph order, followed by `done`.
9. 90% or more line coverage on `backend/agents/decide.py`. Status precedence is tested for every pair of competing codes.

## Tests

| File | Covers |
|---|---|
| `tests/unit/agents/test_decide.py` | Precedence, recommendation, clear flag (table-driven, TDD) |
| `tests/unit/agents/test_triage_rules.py` | D3 thresholds for Jev and Luna answers |
| `tests/unit/agents/test_draft_postcheck.py` | Placeholder, amounts, digits, length |
| `tests/integration/agents/test_graph_scenarios.py` | All 18 seed scenarios with fake providers (scenario 18 behaves like Ana with fakes; it only differs in replay) |
| `tests/integration/agents/test_fallbacks.py` | Every fallback in criterion 4 |
| `tests/integration/agents/test_runner.py` | Persistence, totals, stream order, interrupted runs, read-only sessions |

## Decisions taken in this spec

- **D-agent-1.** `fee_question` gets full evidence and the fee-schedule clause, with status `needs_your_call` and no draft. Rejected: a new "Ready to reply" status; treating it as a refund request.
- **D-agent-2.** "Pick the fee" starts a new, immutable run with the fee pinned. Rejected: resuming the existing run (the checkpointer pattern rejected in D6); no picking at all.
- **D-agent-3.** One intent Choice also serves as the inbox topic (six labels).
- **D-agent-4.** `find_policy` runs after `decide`, not in parallel with the checks, so the quoted clause is always the decisive rule's.
- **D-agent-5.** Luna is a trusted backup for Jev. Its labels route the case, including the early exit for non-fee messages. Its cases are never "clear" and carry the `classified_with_backup` note.
- **D-agent-7.** Fallbacks and manual review: Jev → Luna is normal operation. `classifier_down` (both failed) and `drafter_down` (Sol failed, template used) go to `needs_your_call`, matching the brief's "LLM down → manual review, with the reason shown".
- **D-agent-6.** Deadline propagation: every call is bounded by the run's remaining time, so fallbacks happen inside the run timeout.

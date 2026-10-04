# Spec: policy

Module id: `policy` · Depends on: `data` · Used by: `agent`, `evals`

## Objective

Hold the credit union's rules in one place and make them checkable:

- short policy documents, which are the single source of every number the rules use
- clause search, so the agent can find and quote the rule it applies
- deterministic rule functions, one per check, each declaring the clause it implements
- the reason catalogue: every code Luis might see, its plain-language template, and its next step

Nothing in this module calls a model.

## Policy documents (`backend/policy/docs/*.md`)

Each document is markdown with a YAML front-matter. Each `## N. Title` section is one clause, with id `<slug>#<N>`.

| Slug | Title | Clauses (summary) | Params |
|---|---|---|---|
| `fee-refund-policy` | Fee Refund Policy | 1 scope (service fees can be refunded as a courtesy) · 2 limit: "Members in good standing can receive up to 3 fee refunds in any 12-month period." · 3 good standing: "no unpaid balance on any account" · 4 same-day deposit: "We refund a Courtesy Pay fee when a deposit that posted the same day would have covered the payment if it had posted first." · 5 one refund per fee | `max_refunds_in_window: 3`, `window_days: 365` |
| `courtesy-pay-rules` | Courtesy Pay and Overdraft Rules | 1 what Courtesy Pay is · 2 the nightly posting order · 3 one fee per item paid into overdraft | — |
| `fee-schedule` | Fee Schedule | 1 Courtesy Pay $35 per item · 2 Extended overdraft $60 after 7 days overdrawn · 3 Out-of-network ATM $5 · 4 Savings below minimum balance $5 · 5 Paper statement $3 | `fees` (map of fee type to amount) |
| `staff-approval-limits` | Staff Approval Limits | 1 "Staff can approve a fee refund of up to $50. Larger refunds need a supervisor." | `staff_limit_usd: 50` |
| `member-communication` | Talking to Members | 1 plain language · 2 reply in the member's language · 3 never share internal notes | — |
| `account-standing` | Account Standing | 1 what counts as an unpaid balance (any account below zero, including a past-due loan payment) | — |

**Front-matter shape**

```yaml
slug: fee-refund-policy
title: Fee Refund Policy
version: 2026-09-01
params:
  max_refunds_in_window: 3
  window_days: 365
```

**Rules for the documents**

- **Typed parameters.** A Pydantic model per document validates the front-matter. Invalid params make the loader (and so the bootstrap) fail with the file and field named.
- **Policy version.** `policy_version` is a hash of all document contents. Every run stores it.
- **Text and params agree.** A consistency test asserts that each clause that states a number shows the same value as its param. For example, `fee-refund-policy#2` must say "3" and "12-month".

## Clause store and search

- **Loading.** `load_clauses(session)` in this module parses the documents and upserts them into `policy_clauses`. `backend.bootstrap` calls it. The table's schema is owned by `SPEC-data.md`.
- **Fee-schedule lookup.** `fee_schedule_clause(fee_type) -> clause_id` maps a fee type to its clause in `fee-schedule`, for example "Savings below minimum" to `fee-schedule#4`. It is used as the decisive clause for `fee_question` cases.
- **Search.** `search_clauses(query: str, k: int = 5) -> list[Clause]` uses `websearch_to_tsquery('english', query)`, ranked by `ts_rank_cd`, over an `agent_reader` session.
- **Query building.** `build_policy_query(facts: CaseFacts) -> str` builds the query from case facts only, never from customer text. For example: "courtesy pay fee refund same day deposit limit 12 month good standing".
- **Lookup by id.** `get_clause(clause_id) -> Clause` is the fallback when the Jev rerank misses or disagrees (D7b).

## Rules (`backend/policy/rules.py`)

All rules are pure functions over typed inputs and return a `RuleResult(passed, reason, clause_id, facts)`. None of them reads the database or the clock.

| Rule | Passes when | Fails with | Clause |
|---|---|---|---|
| `find_fee_candidates(txns, message_at, lookback_days=30)` | Returns fee transactions (kind `fee`, amount < 0) posted in the 30 days before the message. This is not a pass/fail rule. | — | — |
| `verify_posting_order(fee, same_day_txns)` | A deposit (kind `payroll_deposit` or `deposit`, not a refund) posted on the fee's date, and opening balance + same-day deposits − the non-fee debits up to the one that caused the fee ≥ 0 | `deposit_not_same_day` | `fee-refund-policy#4` |
| (same function, data check) | Each `balance_after` equals the previous one plus `amount`, exactly, across that day | `data_mismatch` | — |
| `check_not_already_refunded(fee, our_refunds, refund_txns)` | No `refunds` row for this fee, and no `fee_refund` transaction of the same fee type and amount dated within 30 days after the fee | `already_refunded` | `fee-refund-policy#5` |
| `check_yearly_limit(refund_dates, fee_date, max_refunds, window_days)` | Fewer than `max_refunds` fee refunds (any type) in the `window_days` ending on the fee date | `yearly_limit` | `fee-refund-policy#2` |
| `check_good_standing(sub_accounts)` | No sub-account has `available < 0` | `not_good_standing` | `fee-refund-policy#3` |
| `check_approval_limit(amount, staff_limit)` | `amount ≤ staff_limit` | `over_limit` | `staff-approval-limits#1` |

**Facts.** Each result carries facts the UI and the draft can use, as typed values, not sentences. For example:

```json
{"deposit_date": "2026-09-14", "deposit_amount": "1400.00", "deposit_posted_after_fee": true, "balance_if_deposit_first": "1360.00"}
```

`balance_if_deposit_first` feeds the counterfactual sentence in `render_summary`.

**Worked example: Ana, fee 88002, with these docs**

| Check | Inputs | Result |
|---|---|---|
| Posting order | Opening balance 20.00; 88001 −60.00 → −40.00; 88002 −35.00 → −75.00; 88003 +1400.00 → 1325.00. 20 + 1400 − 60 = 1360 ≥ 0 | Passes; chain is consistent |
| Yearly limit | Refunds in 2025-09-15 → 2026-09-14: Mar 3 ($35), Jan 20 ($5). 2 < 3 | Passes |
| Good standing | 1301 210.40 · 1302 1325.00 · 1303 48.00, none below zero | Passes |
| Already refunded | No refund matches 88002 | Passes |
| Approval limit | 35.00 ≤ 50 | Passes |

## Reason catalogue (`backend/policy/reasons.py`)

`ReasonCode` is an enum with exactly the codes in D4a of [docs/agent-design.md](docs/agent-design.md), plus their group (uncertainty, failure, policy, note, routing).

Each code has an English and a Spanish template, and one next step. Luis's UI uses English.

`render_reason(code, facts, lang) -> RenderedReason(message, next_step)` renders one.

`render_summary(status, recommendation, facts, lang) -> str | None` renders the one-sentence "why" shown on the decision card. For example, for `ready_to_refund`: "The paycheck arrived the same day and the bill posted before it." For the posting-order section it adds the counterfactual: "If the paycheck had posted first, the balance would have stayed at $1,360." The same template rules apply.

**Template rules**

- **Plain language.** No internal terms. A test fails if any template contains words such as "id", "Jev", "LLM", "model", "confidence", "null", "error", "code" or "transaction id".
- **No assumed gender.** Templates use the first name or "the message", never "her" or "his".
- **Every placeholder is filled.** Each code is rendered in tests with sample facts, so a missing fact fails in CI, not in front of Luis.

## Acceptance criteria

1. All six documents load. Every clause has an id, document title, section and text. A malformed front-matter fails the loader, naming the file and field. `fee_schedule_clause` covers every fee type in `fee-schedule`.
2. The worked example above passes as a unit test, using the seeded transactions.
3. Every rule has table-driven tests covering a pass, a fail, and the boundary. The boundaries include: exactly 3 refunds (fails), a refund 364 days before the fee (counts) and one 365 days before (doesn't), a deposit posted before the fee, a deposit that wouldn't have covered the payment, and a balance chain off by $0.01.
4. `search_clauses(build_policy_query(ana_facts))` returns `fee-refund-policy#2` and `fee-refund-policy#4` in the top 5.
5. Every `ReasonCode` renders in EN and ES with sample facts. The forbidden-words test and the no-gendered-pronouns test pass.
6. The params-vs-text consistency test passes. Changing `max_refunds_in_window` to 2 without editing the text makes it fail.
7. 90% or more line coverage on `backend/policy`.

## Tests

| File | Covers |
|---|---|
| `tests/unit/policy/test_rules.py` | Every rule, table-driven, including the worked example |
| `tests/unit/policy/test_docs.py` | Front-matter validation, clause splitting, params vs text |
| `tests/unit/policy/test_reasons.py` | Rendering, forbidden words, pronouns, next steps |
| `tests/integration/policy/test_search.py` | Full-text search against seeded clauses |

## Decisions taken in this spec

- **D-policy-1.** Limit: up to **3 fee refunds of any type in a rolling 365-day window ending on the fee date**. Rejected: 2 of the same type in rolling 12 months; 2 of the same type per calendar year.
- **D-policy-2.** The window is anchored on the fee date, not the wall clock, so results are reproducible and evals are stable.
- **D-policy-3.** "Already refunded" counts a refund in our `refunds` table, or a core refund of the same type and amount within 30 days after the fee. This is because the brief's core refunds don't reference the fee they refund.
- **D-policy-4.** Same-day rule: a non-refund deposit posted the same day, which would have covered the payment if it had posted first.

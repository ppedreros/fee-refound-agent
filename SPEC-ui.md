# Spec: ui

Module id: `ui` · Depends on: `api` · Used by: `delivery`

## Objective

One page where Luis sees, for each conversation, what needs him and why, and makes the final call in seconds. The decision is always at the top, and the evidence is one click away. The design does as little as it can: nothing that doesn't earn its place, subtle motion, Blossom's colours, and copy in Luis's words.

## Layout (two panes, decision first)

```
┌─ Queue (320 px) ─┬─ Case ───────────────────────────────────────────┐
│ Open · Done      │ Ana Torres · Overdraft fee          Check again  │
│                  │ "My paycheck came the same day. Can you…"  Sep 15│
│▌Ana T.     $35   │                                                  │
│ Overdraft fee    │ ● Ready to refund                         $35.00 │
│ Ready to refund  │   The paycheck arrived the same day and the bill │
│                  │   posted before it.                              │
│ Sam R.           │   [ Refund $35 and send reply ]   Don't refund   │
│ Card not working │                                                  │
│ Not checked yet  │ Reply ─────────────────────────────────── Edit   │
│                  │   Hi Ana, you're right: your paycheck arrived…   │
│                  │                                                  │
│                  │ ▸ What happened on Sep 14                        │
│                  │ ▸ Refunds in the last 12 months · 2 of 3         │
│                  │ ▸ Account standing · No unpaid balances          │
│                  │ ▸ Policy · Fee Refund Policy, section 4          │
│                  │ ▸ Conversation · 1 message                       │
│                  │ ▸ How this was prepared · 2.8 s · $0.004         │
└──────────────────┴──────────────────────────────────────────────────┘
                                             Replay mode (header, right)
```

**Breakpoints**
- **1024 px and wider:** two panes.
- **Narrower:** one pane, with the queue first and a "Back to queue" link.

**URL state.** `?view=open&case=5012`. Refreshing or sharing the link restores the view.

## Visual system

**Colour tokens** (Tailwind theme):

| Token | Value | Used for |
|---|---|---|
| `navy` | `#001D3D` | Text, the primary button (white text, about 16:1 contrast), headings |
| `clay` | `#EFEEED` | Page background, quiet surfaces |
| `white` | `#FFFFFF` | Cards, the case pane, the selected queue item |
| `terracotta` | `#DC634B` | Accent only, never text: selected-item bar, "Needs your call" dot, focus ring, live-step progress line, Replay mode dot |
| `grey-*` | Neutral scale (for example 50 to 700) | Secondary text (≥ 4.5:1 on white), borders, dividers |
| `success` | Accessible green, for example `#1F7A4D` | "Ready to refund" dot, "Done" check |
| `error` | Accessible red, for example `#B42318` | Error banners only |

**Why Terracotta is never used for text.** White on Terracotta, or Terracotta on white, is about 3.5:1. That passes for non-text elements (3:1) but fails WCAG AA for normal text (4.5:1).

**Typography**
- **Headings** (case title, status title): Source Serif 4, echoing Blossom's serif headings.
- **Everything else:** Inter.
- Both are self-hosted through `@fontsource-variable`, so the page makes no external font calls.
- Amounts use `tabular-nums`. Body text is 15 px; the queue is 14 px.

**Motion.**
- Durations are 150–200 ms, ease-out. Content appears with opacity plus a 4 px rise. Sections expand using CSS grid rows.
- Live steps appear one by one.
- With `prefers-reduced-motion`, there is no motion at all.

**Restraint**
- No icon library: a few inline SVGs (chevron, check, dot).
- No shadows heavier than one subtle elevation on the case card.
- No emoji. No gradients.

## Queue

Each item shows:

- a status dot
- the member's first name and last initial
- the subject, or the topic once the case has been checked
- the status label
- the amount, when there is a recommendation
- when it was received ("Sep 15", or "2 h ago" if it was today)

**Selection.** The selected item has a white background and a Terracotta bar on its left edge.

**Tabs.** "Open" and "Done".

**Empty state.** "You're all caught up."

**Keyboard.**
- `↑`/`↓` or `j`/`k` move through the queue. `Enter` opens a case.
- Focus is always visible.

## Case: the decision card

The card follows the API's `status`, `summary`, `reasons`, `notes`, `recommendation`, `actions`, `can_run` and `can_pick_fee`. The UI never computes which actions are allowed. "Check this case" and "Check again" appear only when `can_run` is true. The fee picker appears only when `can_pick_fee` is true.

| Status | Title | Body | Primary action | Secondary |
|---|---|---|---|---|
| `not_checked` | Not checked yet | "We'll read the message, find the fee and check the rules." | Check this case | — |
| `checking` | Checking… | Live steps (below) | — | — |
| `ready_to_refund` | Ready to refund | `summary` | Refund $35 and send reply | Don't refund |
| `recommend_no_refund` | We recommend not refunding | The reason and the quoted clause | Send reply | Refund anyway |
| `needs_supervisor` | Needs supervisor approval | "A supervisor needs to approve this refund. That happens outside this tool for now." | — | Don't refund · Send a reply only |
| `needs_your_call` | Needs your call | One line per reason, each with its next step. The recommendation (if any) appears as "We'd refund $35" or "We'd not refund". | Follows the recommendation, if any | Depends on the reason (below) |
| `not_about_fee` | This message isn't about a fee | Topic label | — | Check again |
| `done` | Done | "Refunded $35 and replied · Luis · Oct 3, 10:42", or "Replied without a refund · …" | — | — |

**As built (T24).**
- **Buttons** come from one pure function (`features/case/cardButtons.ts`) over `status`, `actions`, `recommendation` and `can_run`. `approve` (or `edit` when there is no draft) is the primary action and is labelled by the recommendation: "Refund $35 and send reply", or "Send reply" for a decline. `reject` reads "Don't refund" against a refund and "Refund anyway" otherwise. `reply_only` reads "Send a reply only" for `needs_supervisor` and "Send reply" elsewhere, where it is the primary action. `edit` is never a button of its own. "Check this case" is the card's primary action for `not_checked`, and "Check again" is the card's only action for `not_about_fee`; for the other checked statuses "Check again" sits in the case header, top right, as in the layout.
- **Fee picker.** With `can_pick_fee`, the radio rows and "Check again with this fee" come first (it is the reason's next step), and "Send reply" takes the secondary style. The button stays disabled until a fee is picked.
- **Bodies.** `needs_supervisor` shows the summary ("The policy allows this $60 refund, but it is above your $50 limit.") before the fixed sentence. `checking` shows a thin Terracotta line and "We're reading the message and checking the rules. This takes a few seconds." Notes are quiet grey lines under the body.
- **Checking, until the live steps (T36).** After `POST /run`, the case query asks again every second while the status is `checking`; a 409 `run_in_progress` is followed the same way, without an error. When the status leaves `checking`, the queue is refreshed too. The page keeps the previous result while a check runs, because the API serves the latest completed run.
- **Header.** "Ana Torres · Overdraft fee", the latest member message quoted on one line with its date, and the accounts as "Primary Savings, Everyday Checking ••4210 · Vacation Savings ••4211". The "Show" reveal waits for its endpoint, and "Replay mode" for `/health` to report modes (T29).
- **Evidence.** Sections open with CSS grid rows and are `inert` while closed. "How this was prepared" puts the three parallel reads on one line ("Looking at accounts and transactions") with the slowest time, shows costs with two significant digits ("$0.000032"), and adds the replay note only when Jev answered from recordings. Rule facts are not shown: the sections already present them in words.
- Tests run with `TZ=UTC`, so dates read the same on every machine. Phone widths are checked at 520 px with headless Chrome for now; Chrome on Windows won't open a narrower window, and Playwright's device emulation comes in T42.

**As built (T32).** The fee picker is its own component (`FeePicker.tsx`). Its rows use the API's labels, which name the payment that caused each fee ("Sep 14 · −$35.00 · Courtesy Pay fee · after CITY POWER & LIGHT −$60.00"), so two same-day fees can be told apart.

**As built (T37).** The header lists each account as its own item, "Everyday Checking ••4210 · Show". "Show" swaps the masked digits for the full number for as long as the case stays open (it is fetched again after a reload), and a failed reveal shows the API's message after the accounts.

**`needs_your_call` specifics**

- **`fee_ambiguous`.** Shows the candidates as radio rows ("Sep 14 · −$35.00 · Courtesy Pay fee"). The action is "Check again with this fee", which runs `POST /run` with that `fee_txn_id`.
- **No recommendation.** The reply box opens empty, and the action is "Send reply" (`reply_only`).

**Overriding the recommendation.** "Don't refund" and "Refund anyway" open an inline, required field: "Why? This helps us improve." It takes 10 to 500 characters. The button stays disabled until the reason is valid.

**Note.** `classified_with_backup` ("Checked with our backup system.") is a single quiet grey line under the body, never a banner. `drafter_down` is a reason, so it shows in the `needs_your_call` reasons list.

**One click, clear label.** The primary button always states what will happen, including the amount: "Refund $35 and send reply". There is no confirmation dialog. The label is the confirmation, and the API is idempotent.

**After a decision**
- The card switches to `done`, with a 150 ms crossfade.
- A "Next case" button moves to the next open case.
- Focus moves to the card title.

## Reply

- Shows the draft with the first name filled in. A small "Reply in Spanish" tag appears when the language is `es`.
- **Edit** turns the text into a textarea (1–2,000 characters, with a counter). The action sent becomes `edit`, the primary label doesn't change, and "Undo my changes" restores the draft.
- When there is no draft, the textarea starts empty.

**As built (T25).**
- **Following the recommendation.** The primary button sends `approve` with the draft unchanged; once Luis edits the text it sends `edit`. "Undo my changes" restores the draft. The counter counts characters after trimming ("1,234 / 2,000"), and a decision button stays disabled while the reply is empty.
- **Acting against it, or replying only.** "Don't refund", "Refund anyway" and "Send a reply only" open an inline step that takes the place of the card's buttons: Luis's reply (it starts empty, because our draft says the opposite outcome), the reason field for "Don't refund" and "Refund anyway" (10 to 500 characters), a button with the same label, and "Cancel", which brings the draft back. "Needs supervisor approval" shows no reply until Luis picks one of its actions.
- **Idempotency.** One key per attempt, a version 4 UUID made with `crypto.getRandomValues` (`randomUUID` needs a secure context). A retry after a network error or a 5xx reuses it; once the server has answered with a 4xx or a result, or the details change, the next attempt gets a new key.
- **After the decision.** The case and the queue are fetched again, the card fades in as "Done" (150 ms), focus moves to the card title, and "Next case" opens the first other open conversation in the queue. An error from the API (for example 409 `already_decided`) shows its message in the card, and the case is fetched again.

## Evidence sections (collapsed by default; the header line carries the summary)

| Section | Content |
|---|---|
| What happened on {fee date} | Posting-order table: order, description, amount, balance after. The fee row has a Terracotta left marker and the deposit row is marked in green. Then `evidence.fee_day.summary` from the API, for example "If the paycheck had posted first, the balance would have stayed at $1,360." |
| Refunds in the last 12 months · N of 3 | Date, fee type and amount for each refund, plus the window ("Sep 15, 2025 to Sep 14, 2026") |
| Account standing | "No unpaid balances", or the sub-accounts below zero with their amounts |
| Policy · {doc}, section {n} | The clause as a block quote, verbatim |
| Conversation · N messages | The full thread, with the member on the left and staff on the right |
| How this was prepared · {duration} · {cost} | Each step with a plain label and its time. "Checked with our backup system" when Luna answered. "Model answers are recorded (Replay mode)" when in replay. The time it was checked. |

**As built (T29).** The header reads `/health` once (`["health"]`, never stale, not retried). When either provider is in replay mode, it shows "Replay mode" on the right, after a small Terracotta dot, with the tooltip "Model answers are recorded, not live." (also given to screen readers as its description). Nothing shows when both are live or when the health check fails.

**As built (T26).** Each step shows its own time in milliseconds below a second ("261 ms"), so the real Jev latency is visible next to the fast rule steps; the section header keeps the run's total ("0.5 s").

**Member header.**
- Full name, with each account shown as "Everyday Checking ••4210 · Show".
- "Show" calls the reveal endpoint, which is audited.
- The full number is shown for that session only.

## Live steps (while a case is being checked)

**Mechanics.**
- "Check this case" and "Check again" call `POST /run`, then open an `EventSource` on the events endpoint.
- On a 409 `run_in_progress`, the UI attaches to the returned run.

**Step labels:**

| Node | Label |
|---|---|
| `load_conversation` | Reading the conversation |
| `triage` | Understanding the message |
| `load_*` | Looking at accounts and transactions |
| `identify_fee` | Finding the fee |
| `run_checks` | Checking the rules |
| `decide` | Making a recommendation |
| `find_policy` | Finding the policy that applies |
| `draft` | Writing a reply |
| `finalize` | Done |

**As built (T36).** "Check this case" (or a 409) refetches the case, whose `checking_run_id` mounts `LiveSteps`: an `EventSource` on that run, one row per label in the order the steps started (the three reads share one row, done when all three are), a pulsing dot while a row runs, a green check when it is done, and "Didn't finish" in grey when it failed. On `done` the stream closes and the case and the queue are fetched again, so the card shows the new status without a reload. This replaces the one-second polling of T24.

**Display.**
- Each step fades in when it starts and gets a check when it finishes.
- A thin Terracotta line shows progress. It is not a percentage.
- On `done`, the step list collapses into "How this was prepared", the case is re-fetched, and the decision card fades in.
- A step that fails shows its plain label with "didn't finish". The final status explains the rest.

## Data and state

- **Queries** (TanStack Query): `["cases", view]` and `["case", id]`.
  - The case query has a `staleTime` of 5 s.
  - After a run finishes or a decision is made, both keys are invalidated.
- **Mutations.** `runCase` and `decide`.
  - `decide` creates one `Idempotency-Key` per decision attempt and reuses it on retry until it gets a response.
- **API types.** Generated from OpenAPI (`frontend/src/api/schema.d.ts`), never edited by hand.
- **Health.** `GET /health` is read once, to show "Replay mode" in the header with the tooltip "Model answers are recorded, not live."

**As built (T23).**
- **API types.** `npm --prefix frontend run gen:api` writes the backend's schema to `frontend/src/api/openapi.json` (`python -m backend.api.openapi`, no server needed) and turns it into `schema.d.ts` with openapi-typescript. openapi-typescript 7 declares TypeScript 5 as a peer and the app is on TypeScript 6, so the script runs a pinned `npx --yes openapi-typescript@7.13.0` (it brings its own TypeScript) instead of adding it to `devDependencies`. Both files are committed and skipped by Prettier; a backend unit test fails when the committed schema no longer matches the API. Statuses, topics, actions, authors and sources are closed sets (`Literal`) in the schema, so the copy maps are checked for completeness (`satisfies Record<CaseStatus, string>`).
- **Client.** `src/api/client.ts` is a thin `fetch` wrapper typed by the schema (no extra library), with one function per endpoint under `/api`. Every failure is an `ApiError` carrying the API's `message` (or the calm network and generic messages from the copy file), its `code`, and the active `run_id` on a 409. Queries are not retried on a 4xx, and at most twice on a network error or a 5xx. In development, Vite proxies `/api` to the local backend, as nginx does in the container.
- **URL state** has no router: `useSyncExternalStore` over `location.search`, and `pushState` on change (`?view=open&case=5012`). Switching tabs clears the selected case.
- **Queue.** The status dot is decorative (the status label is text): success for "Ready to refund" and "Done", Terracotta for "Needs your call" and "Needs supervisor approval", navy for "We recommend not refunding", grey for the rest (hollow when not checked, pulsing while checking, still with reduced motion). The second line is the topic once the case is checked, otherwise the subject. Only the first page (50 conversations) is shown; paging further is left for later, since the demo has five.

## Errors, loading, empty

| Situation | What Luis sees |
|---|---|
| Loading | Skeleton blocks shaped like the final content, with no spinners in the case pane |
| API error with a body | The API's `message`, in a calm banner with "Try again" |
| Network down | "We can't reach the server. Check your connection and try again." |
| Decision conflict (409) | The API's message, plus the case is re-fetched |
| Anything unexpected | "Something went wrong on our side. Please try again." Never a code, a trace or `undefined`. |

## Copy rules

- Every string lives in `frontend/src/copy/en.ts`. Components contain no literal copy.
- Luis is addressed as "you", and the agent speaks as "we".
- Members are named by first name.
- Status names are fixed: Ready to refund · We recommend not refunding · Needs supervisor approval · Needs your call · This message isn't about a fee · Not checked yet · Checking… · Done.
- No internal terms: no "run", "agent", "model", "confidence", "Jev", "LLM", "status code", or ids.

## Accessibility

- WCAG 2.2 AA.
- Landmarks: `nav` for the queue and `main` for the case.
- The decision card title and the live steps are in an `aria-live="polite"` region.
- Every control is reachable by keyboard and has a visible focus ring (Terracotta, 2 px, offset).
- Collapsible sections are buttons with `aria-expanded`.

## Acceptance criteria

1. For each status, the decision card shows exactly the title, primary label and secondary actions in the table above, driven only by the API fixture (table-driven Vitest).
2. The actions rendered are exactly the API's `actions`, plus the run buttons when `can_run` is true and the fee picker when `can_pick_fee` is true. A fixture with `actions: []`, `can_run: false` and `can_pick_fee: false` renders no buttons.
3. "Don't refund" and "Refund anyway" can't be submitted without a 10-character reason.
4. A decision retried after a network error reuses its `Idempotency-Key`.
5. During a check, the steps appear in event order with their plain labels. On `done`, the card shows the new status without a page reload.
6. Rendering every status fixture produces no text that matches `/\b[a-z]+_[a-z_]+\b/`, `undefined`, `null`, `NaN` or `[ACCOUNT`.
7. The posting-order table marks the fee row and the deposit row, and shows the counterfactual sentence for Ana.
8. "Replay mode" shows in the header when `/health` reports replay.
9. Keyboard only: open Ana's case, approve, and reach "Next case" without a mouse.
10. Lighthouse accessibility score of 95 or more on the case page (checked in `delivery`).

## Tests

| File | Covers |
|---|---|
| `frontend/src/features/case/DecisionCard.test.tsx` | Criteria 1–3 |
| `frontend/src/features/case/useDecision.test.ts` | Idempotency key reuse |
| `frontend/src/features/case/LiveSteps.test.tsx` | Event order, labels, collapse on done (mocked `EventSource`) |
| `frontend/src/features/case/EvidenceDay.test.tsx` | Row marking, counterfactual sentence |
| `frontend/src/copy/copy.test.tsx` | Criterion 6 across all fixtures |
| `frontend/src/features/queue/Queue.test.tsx` | Selection, keyboard navigation, empty state |

The API is mocked by stubbing the generated client module (`vi.mock`). There is no MSW dependency.

## Decisions taken in this spec

- **D-ui-1.** Two panes, decision first, evidence collapsed. Rejected: three columns; a full-width table with a side panel.
- **D-ui-2.** Terracotta is used only as a non-text accent. Navy carries the primary action. This is for accessible contrast.
- **D-ui-3.** No confirmation dialog: the primary label states the amount and the effect, and the API is idempotent.
- **D-ui-4.** Fonts: Source Serif 4 for headings and Inter for body, self-hosted.

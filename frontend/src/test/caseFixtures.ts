// One case view per status, typed by the generated schema. Ana's is the API's real response.
import type { CaseView } from "../api/client";

export const anaReady: CaseView = {
  id: 5012,
  conversation: {
    subject: "Overdraft fee",
    status: "waiting_for_bank",
    messages: [
      {
        author: "member",
        author_name: "Ana Torres",
        body: "My paycheck came the same day. Can you refund this?",
        created_at: "2026-09-15T08:12:44Z",
      },
    ],
  },
  member: {
    name: "Ana Torres",
    accounts: [
      {
        account_id: 710,
        masked_number: "••4210",
        sub_accounts: [
          { name: "Primary Savings", type: "SAVINGS", balance: "215.40", available: "210.40" },
          { name: "Everyday Checking", type: "CHECKING", balance: "1325.00", available: "1325.00" },
        ],
      },
      {
        account_id: 711,
        masked_number: "••4211",
        sub_accounts: [
          { name: "Vacation Savings", type: "SAVINGS", balance: "48.00", available: "48.00" },
        ],
      },
    ],
  },
  status: "ready_to_refund",
  topic: "fee_refund_request",
  language: "en",
  summary: "The paycheck arrived the same day and the bill posted before it.",
  reasons: [],
  notes: [],
  recommendation: { action: "refund", amount: "35.00" },
  fee: {
    fee_txn_id: 88002,
    date: "2026-09-14",
    amount: "-35.00",
    fee_type: "Courtesy Pay",
    description: "Fee Withdrawal ; Courtesy Pay fee",
    sub_account_name: "Everyday Checking",
    source: "rule",
  },
  candidates: [{ fee_txn_id: 88002, label: "Sep 14 · −$35.00 · Courtesy Pay fee" }],
  evidence: {
    fee_day: {
      date: "2026-09-14",
      rows: [
        {
          position: 1,
          description: "Withdrawal Debit Card CITY POWER & LIGHT",
          amount: "-60.00",
          balance_after: "-40.00",
          kind: "card_payment",
          is_fee: false,
          is_deposit: false,
        },
        {
          position: 2,
          description: "Fee Withdrawal ; Courtesy Pay fee",
          amount: "-35.00",
          balance_after: "-75.00",
          kind: "fee",
          is_fee: true,
          is_deposit: false,
        },
        {
          position: 3,
          description: "Deposit ACH ACME LOGISTICS*PAYROLL",
          amount: "1400.00",
          balance_after: "1325.00",
          kind: "payroll_deposit",
          is_fee: false,
          is_deposit: true,
        },
      ],
      summary: "If the paycheck had posted first, the balance would have stayed at $1,360.",
    },
    refunds_in_window: {
      start: "2025-09-15",
      end: "2026-09-14",
      count: 2,
      max_allowed: 3,
      items: [
        { date: "2026-01-20", fee_type: "Out of Network", amount: "5.00" },
        { date: "2026-03-03", fee_type: "Courtesy Pay", amount: "35.00" },
      ],
    },
    standing: { ok: true, below_zero: [] },
    checks: [
      {
        label: "A same-day deposit would have covered the payment",
        passed: true,
        facts: { deposit_kind: "payroll_deposit", balance_if_deposit_first: "1360.00" },
      },
      { label: "This fee hasn't been refunded yet", passed: true, facts: {} },
      {
        label: "Fewer than 3 refunds in the last 12 months",
        passed: true,
        facts: { max_refunds: 3, refunds_in_window: 2 },
      },
      { label: "No unpaid balances", passed: true, facts: {} },
      {
        label: "Within your $50 approval limit",
        passed: true,
        facts: { amount: "35.00", staff_limit: "50" },
      },
    ],
  },
  clause: {
    doc_title: "Fee Refund Policy",
    section: "4. Same-day deposits",
    text: "We refund a Courtesy Pay fee when a deposit that posted the same day would have covered the payment if it had posted first. Refunds and transfers between the member's own accounts don't count as deposits.",
  },
  draft: {
    text: "Hi Ana, thanks for reaching out. We checked your account: your paycheck arrived on Sep 14, the same day as the $35 Courtesy Pay fee, so we've refunded the fee to your Everyday Checking account. You'll see it there shortly. If there's anything else, just reply to this message.",
    source: "template",
  },
  run: {
    run_id: "bf5975f1-b419-4d2b-bc60-5328e5909ced",
    checked_at: "2026-10-04T10:54:57Z",
    duration_ms: 510,
    cost_usd: "0.000032",
    provider_mode: { jev: "live", openai: "replay" },
    steps: [
      { node: "load_conversation", state: "finished", latency_ms: 35 },
      { node: "triage", state: "finished", latency_ms: 317 },
      { node: "load_accounts", state: "finished", latency_ms: 15 },
      { node: "load_refund_history", state: "finished", latency_ms: 27 },
      { node: "load_transactions", state: "finished", latency_ms: 25 },
      { node: "identify_fee", state: "finished", latency_ms: 0 },
      { node: "run_checks", state: "finished", latency_ms: 0 },
      { node: "decide", state: "finished", latency_ms: 0 },
      { node: "find_policy", state: "finished", latency_ms: 5 },
      { node: "draft", state: "finished", latency_ms: 1 },
      { node: "finalize", state: "finished", latency_ms: 0 },
    ],
  },
  decision: null,
  actions: ["approve", "edit", "reject"],
  can_run: true,
  can_pick_fee: false,
  checking_run_id: null,
};

const unchecked = {
  topic: null,
  language: null,
  summary: null,
  reasons: [],
  notes: [],
  recommendation: { action: "none", amount: null },
  fee: null,
  candidates: [],
  evidence: { fee_day: null, refunds_in_window: null, standing: null, checks: [] },
  clause: null,
  draft: null,
  run: null,
  actions: [],
} satisfies Partial<CaseView>;

export const notChecked: CaseView = {
  ...anaReady,
  ...unchecked,
  id: 5011,
  status: "not_checked",
  member: { name: "Marcus Reed", accounts: [] },
  conversation: {
    subject: "Card not working",
    status: "read_by_bank",
    messages: [
      {
        author: "member",
        author_name: "Marcus Reed",
        body: "My card gets declined at the gas station.",
        created_at: "2026-09-14T17:03:10Z",
      },
      {
        author: "staff",
        author_name: "Sam",
        body: "Thanks, we are checking your card now.",
        created_at: "2026-09-14T17:40:12Z",
      },
    ],
  },
};

export const checking: CaseView = {
  ...anaReady,
  status: "checking",
  actions: [],
  can_run: false,
  checking_run_id: "7a1c2e9d-3b4f-4c5a-8d6e-0f1a2b3c4d5e",
};

export const recommendNoRefund: CaseView = {
  ...anaReady,
  status: "recommend_no_refund",
  summary: "The paycheck arrived on Sep 16, two days after the fee.",
  reasons: [
    {
      message: "The paycheck arrived on Sep 16, two days after the fee.",
      next_step: "Send the reply, or refund anyway",
    },
  ],
  recommendation: { action: "no_refund", amount: "35.00" },
  draft: {
    text: "Hi Ana, thanks for reaching out. We looked at your account and can't refund this fee.",
    source: "template",
  },
};

export const needsSupervisor: CaseView = {
  ...anaReady,
  status: "needs_supervisor",
  summary: "The policy allows this $60 refund, but it is above your $50 limit.",
  reasons: [
    {
      message: "This refund is above your approval limit.",
      next_step: "A supervisor needs to approve it",
    },
  ],
  recommendation: { action: "refund", amount: "60.00" },
  draft: null, // nothing in the app can send a refund above the limit, so none is written
  actions: ["reject", "reply_only"],
};

export const needsYourCall: CaseView = {
  ...anaReady,
  status: "needs_your_call",
  summary: null,
  reasons: [
    {
      message:
        "The message includes instructions aimed at us. I ignored them; the numbers below come from Ana's account only.",
      next_step: "Review before approving",
    },
  ],
  notes: [{ message: "Checked with our backup system.", next_step: null }],
};

export const feeQuestion: CaseView = {
  ...anaReady,
  status: "needs_your_call",
  topic: "fee_question",
  summary: null,
  reasons: [
    {
      message: "Daniel is asking why a fee was charged, not for a refund.",
      next_step: "Explain the fee",
    },
  ],
  recommendation: { action: "none", amount: null },
  draft: null,
  actions: ["reply_only", "reject"],
};

export const feeAmbiguous: CaseView = {
  ...anaReady,
  status: "needs_your_call",
  summary: null,
  reasons: [
    {
      message: "Ana has 2 fees on Sep 14 and the message doesn't say which one.",
      next_step: "Pick the fee",
    },
  ],
  recommendation: { action: "none", amount: null },
  fee: null,
  candidates: [
    {
      fee_txn_id: 90902,
      label: "Sep 14 · −$35.00 · Courtesy Pay fee · after CITY POWER & LIGHT −$60.00",
    },
    {
      fee_txn_id: 90904,
      label: "Sep 14 · −$35.00 · Courtesy Pay fee · after STREAMFLIX −$15.99",
    },
  ],
  evidence: { ...anaReady.evidence, fee_day: null, refunds_in_window: null },
  clause: null,
  draft: null,
  actions: ["reply_only"],
  can_pick_fee: true,
};

export const notAboutFee: CaseView = {
  ...anaReady,
  ...unchecked,
  status: "not_about_fee",
  topic: "card_issue",
  run: anaReady.run,
  can_run: true,
};

export const done: CaseView = {
  ...anaReady,
  status: "done",
  conversation: { ...anaReady.conversation, status: "closed" },
  decision: {
    by: "Luis",
    at: "2026-10-03T10:42:00Z",
    action: "approve",
    refunded: true,
    amount: "35.00",
    reply: anaReady.draft?.text ?? "",
  },
  actions: [],
  can_run: false,
};

export const doneWithoutRefund: CaseView = {
  ...done,
  decision: {
    by: "Luis",
    at: "2026-10-03T10:42:00Z",
    action: "reject",
    refunded: false,
    amount: null,
    reply: "Hi Ana, we can't refund this fee.",
  },
};

export const spanish: CaseView = {
  ...anaReady,
  language: "es",
  draft: { text: "Hola Ana, gracias por escribirnos.", source: "template" },
};

export const ALL_STATUSES: [string, CaseView][] = [
  ["not checked", notChecked],
  ["checking", checking],
  ["ready to refund", anaReady],
  ["recommend no refund", recommendNoRefund],
  ["needs supervisor", needsSupervisor],
  ["needs your call", needsYourCall],
  ["fee question", feeQuestion],
  ["fee ambiguous", feeAmbiguous],
  ["not about a fee", notAboutFee],
  ["done", done],
  ["done without a refund", doneWithoutRefund],
  ["spanish", spanish],
];

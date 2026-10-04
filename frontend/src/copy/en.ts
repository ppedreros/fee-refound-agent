// Every user-facing string lives here. Write for Luis: friendly, plain, direct, no internal terms.
import type { CaseStatus, Topic } from "../api/client";

const plural = (count: number, one: string, many: string) =>
  `${String(count)} ${count === 1 ? one : many}`;

export const copy = {
  loading: "Loading…",
  app: {
    title: "Fee refunds",
    replay: "Replay mode",
    replayTooltip: "Model answers are recorded, not live.",
  },
  queue: {
    label: "Conversations",
    tabs: { open: "Open", done: "Done" },
    tabsLabel: "Which conversations",
    empty: "You're all caught up.",
  },
  case: {
    label: "Conversation",
    empty: "Choose a conversation to see what it needs.",
    back: "Back to queue",
    title: (name: string, subject: string) => `${name} · ${subject}`,
    account: (names: string, masked: string) => `${names} ${masked}`,
    show: "Show",
    separator: " · ",
  },
  status: {
    not_checked: "Not checked yet",
    checking: "Checking…",
    ready_to_refund: "Ready to refund",
    recommend_no_refund: "We recommend not refunding",
    needs_supervisor: "Needs supervisor approval",
    needs_your_call: "Needs your call",
    not_about_fee: "This message isn't about a fee",
    done: "Done",
  } satisfies Record<CaseStatus, string>,
  topic: {
    fee_refund_request: "Fee refund request",
    fee_question: "Question about a fee",
    card_issue: "Card issue",
    account_update: "Account update",
    statement_question: "Statement question",
    other: "Something else",
  } satisfies Record<Topic, string>,
  card: {
    notChecked: "We'll read the message, find the fee and check the rules.",
    checking: "We're reading the message and checking the rules. This takes a few seconds.",
    supervisor:
      "A supervisor needs to approve this refund. That happens outside this tool for now.",
    wouldRefund: (amount: string) => `We'd refund ${amount}`,
    wouldNotRefund: "We'd not refund",
    refundedAndReplied: (amount: string) => `Refunded ${amount} and replied`,
    repliedWithoutRefund: "Replied without a refund",
    decidedBy: (summary: string, name: string, when: string) => `${summary} · ${name} · ${when}`,
    pickFee: "Which fee is it?",
    next: "Next case",
  },
  actions: {
    checkCase: "Check this case",
    checkAgain: "Check again",
    checkWithFee: "Check again with this fee",
    refundAndReply: (amount: string) => `Refund ${amount} and send reply`,
    sendReply: "Send reply",
    dontRefund: "Don't refund",
    refundAnyway: "Refund anyway",
    replyOnly: "Send a reply only",
  },
  reply: {
    title: "Reply",
    spanish: "Reply in Spanish",
    edit: "Edit",
    undo: "Undo my changes",
    counter: (count: number) => `${count.toLocaleString("en-US")} / 2,000`,
  },
  reason: {
    label: "Why? This helps us improve.",
    cancel: "Cancel",
  },
  evidence: {
    // A section header carries its summary after a middle dot: "Account standing · No unpaid balances".
    titled: (...parts: string[]) => parts.join(" · "),
    feeDay: (date: string) => `What happened on ${date}`,
    columns: {
      order: "Order",
      description: "Description",
      amount: "Amount",
      balance: "Balance after",
    },
    feeRow: "The fee",
    depositRow: "The deposit",
    refunds: (count: number, max: number) =>
      `Refunds in the last 12 months · ${String(count)} of ${String(max)}`,
    refundsWindow: (start: string, end: string) => `${start} to ${end}`,
    refundsNone: "No refunds in this period.",
    standing: "Account standing",
    standingOk: "No unpaid balances",
    standingBelow: (count: number) => plural(count, "balance below zero", "balances below zero"),
    policy: (doc: string, section: string) => `Policy · ${doc}, section ${section}`,
    conversation: (count: number) => `Conversation · ${plural(count, "message", "messages")}`,
    prepared: "How this was prepared",
    checkedAt: (when: string) => `Checked ${when}`,
    replay: "Model answers are recorded (Replay mode)",
    stepFailed: "didn't finish",
  },
  steps: {
    load_conversation: "Reading the conversation",
    triage: "Understanding the message",
    load: "Looking at accounts and transactions",
    identify_fee: "Finding the fee",
    run_checks: "Checking the rules",
    decide: "Making a recommendation",
    find_policy: "Finding the policy that applies",
    draft: "Writing a reply",
    finalize: "Done",
    other: "Another step",
  },
  // Live steps: the state of each step, read out after its label.
  live: {
    running: "In progress",
    finished: "Done",
    failed: "Didn't finish",
  },
  time: {
    justNow: "Just now",
    minutesAgo: (minutes: number) => `${String(minutes)} min ago`,
    hoursAgo: (hours: number) => `${String(hours)} h ago`,
  },
  errors: {
    network: "We can't reach the server. Check your connection and try again.",
    unexpected: "Something went wrong on our side. Please try again.",
    tryAgain: "Try again",
  },
} as const;

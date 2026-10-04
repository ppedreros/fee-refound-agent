// Every user-facing string lives here. Write for Luis: friendly, plain, direct, no internal terms.
import type { CaseStatus, Topic } from "../api/client";

export const copy = {
  app: {
    title: "Fee refunds",
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

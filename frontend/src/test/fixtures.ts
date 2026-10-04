// API responses for tests, typed by the generated schema so they can't drift from the API.
import type { QueueItem } from "../api/client";

export const NOW = new Date("2026-09-15T10:12:44Z");

export const ana: QueueItem = {
  id: 5012,
  member_name: "Ana T.",
  subject: "Overdraft fee",
  received_at: "2026-09-15T08:12:44Z",
  status: "ready_to_refund",
  topic: "fee_refund_request",
  amount: "35.00",
  checked_at: "2026-09-15T10:02:10Z",
};

export const marcus: QueueItem = {
  id: 5011,
  member_name: "Marcus R.",
  subject: "Card not working",
  received_at: "2026-09-14T17:03:10Z",
  status: "not_checked",
  topic: null,
  amount: null,
  checked_at: null,
};

export const daniel: QueueItem = {
  id: 5008,
  member_name: "Daniel O.",
  subject: "Fee on my savings",
  received_at: "2026-09-13T19:22:51Z",
  status: "needs_your_call",
  topic: "fee_question",
  amount: null,
  checked_at: "2026-09-15T09:00:00Z",
};

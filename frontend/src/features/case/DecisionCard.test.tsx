import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { CaseView } from "../../api/client";
import { copy } from "../../copy/en";
import {
  anaReady,
  checking,
  done,
  doneWithoutRefund,
  feeAmbiguous,
  feeQuestion,
  needsSupervisor,
  needsYourCall,
  notAboutFee,
  notChecked,
  recommendNoRefund,
} from "../../test/caseFixtures";
import { DecisionCard } from "./DecisionCard";

function renderCard(view: CaseView) {
  const onRun = vi.fn();
  const onDecide = vi.fn();
  render(<DecisionCard view={view} running={false} onRun={onRun} onDecide={onDecide} />);
  return { onRun, onDecide };
}

function buttonNames(): string[] {
  return screen.queryAllByRole("button").map((button) => button.textContent);
}

// SPEC-ui, "Case: the decision card": title, then the primary action, then the secondary ones.
describe.each<[string, CaseView, string, string[]]>([
  ["not checked", notChecked, copy.status.not_checked, [copy.actions.checkCase]],
  ["checking", checking, copy.status.checking, []],
  [
    "ready to refund",
    anaReady,
    copy.status.ready_to_refund,
    [copy.actions.refundAndReply("$35"), copy.actions.dontRefund],
  ],
  [
    "recommend no refund",
    recommendNoRefund,
    copy.status.recommend_no_refund,
    [copy.actions.sendReply, copy.actions.refundAnyway],
  ],
  [
    "needs supervisor",
    needsSupervisor,
    copy.status.needs_supervisor,
    [copy.actions.dontRefund, copy.actions.replyOnly],
  ],
  [
    "needs your call, with a recommendation",
    needsYourCall,
    copy.status.needs_your_call,
    [copy.actions.refundAndReply("$35"), copy.actions.dontRefund],
  ],
  [
    "needs your call, a question about a fee",
    feeQuestion,
    copy.status.needs_your_call,
    [copy.actions.sendReply, copy.actions.refundAnyway],
  ],
  [
    "needs your call, two possible fees",
    feeAmbiguous,
    copy.status.needs_your_call,
    [copy.actions.checkWithFee, copy.actions.sendReply], // picking the fee comes first
  ],
  ["not about a fee", notAboutFee, copy.status.not_about_fee, [copy.actions.checkAgain]],
  ["done", done, copy.status.done, []],
])("Decision card: %s", (_name, view, title, buttons) => {
  it("shows its title and exactly its actions", () => {
    renderCard(view);

    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(title);
    expect(buttonNames()).toEqual(buttons);
  });
});

describe("Decision card", () => {
  it("explains a refund with the summary", () => {
    renderCard(anaReady);

    expect(screen.getByText(anaReady.summary ?? "")).toBeInTheDocument();
  });

  it("explains a decline with the reason and quotes the clause", () => {
    renderCard(recommendNoRefund);

    expect(screen.getByText(recommendNoRefund.summary ?? "")).toBeInTheDocument();
    expect(screen.getByText(anaReady.clause?.text ?? "")).toBeInTheDocument();
  });

  it("lists each reason with its next step, the recommendation and a quiet note", () => {
    renderCard(needsYourCall);

    const reason = needsYourCall.reasons[0];
    expect(screen.getByText(reason?.message ?? "")).toBeInTheDocument();
    expect(screen.getByText(reason?.next_step ?? "")).toBeInTheDocument();
    expect(screen.getByText(copy.card.wouldRefund("$35"))).toBeInTheDocument();
    expect(screen.getByText("Checked with our backup system.")).toBeInTheDocument();
  });

  it("tells Luis a supervisor is needed", () => {
    renderCard(needsSupervisor);

    expect(screen.getByText(copy.card.supervisor)).toBeInTheDocument();
  });

  it("says who decided, what happened and when", () => {
    renderCard(done);

    expect(
      screen.getByText(
        copy.card.decidedBy(copy.card.refundedAndReplied("$35"), "Luis", "Oct 3, 10:42"),
      ),
    ).toBeInTheDocument();
  });

  it("says when a case closed without a refund", () => {
    renderCard(doneWithoutRefund);

    expect(screen.getByText(/^Replied without a refund · Luis/)).toBeInTheDocument();
  });

  it("starts a check", async () => {
    const user = userEvent.setup();
    const { onRun } = renderCard(notChecked);

    await user.click(screen.getByRole("button", { name: copy.actions.checkCase }));

    expect(onRun).toHaveBeenCalledWith(undefined);
  });

  it("renders no buttons when the case offers nothing", () => {
    renderCard({ ...done, actions: [], can_run: false, can_pick_fee: false });

    expect(screen.queryAllByRole("button")).toEqual([]);
  });
});

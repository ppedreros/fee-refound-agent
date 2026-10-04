import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, type CaseView } from "../../api/client";
import { copy } from "../../copy/en";
import { anaReady, done, feeQuestion, recommendNoRefund } from "../../test/caseFixtures";
import { ana, daniel, marcus } from "../../test/fixtures";
import { renderWithClient } from "../../test/render";
import { CasePane } from "./CasePane";

vi.mock("../../api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("../../api/client")>();
  return {
    ...original,
    api: { listCases: vi.fn(), getCase: vi.fn(), runCase: vi.fn(), decide: vi.fn() },
  };
});

const getCase = vi.mocked(api.getCase);
const decide = vi.mocked(api.decide);
const RESULT = {
  decision_id: "118de9ba-cb7d-419a-8c3f-8fed9a385dd3",
  refunded: true,
  amount: "35.00",
  case_status: "done" as const,
};
const RUN_ID = anaReady.run?.run_id;

beforeEach(() => {
  vi.mocked(api.listCases).mockResolvedValue({ items: [ana, marcus, daniel], next_cursor: null });
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderPane(view: CaseView) {
  getCase.mockResolvedValue(view);
  const onNext = vi.fn();
  renderWithClient(<CasePane caseId={view.id} onBack={vi.fn()} onNext={onNext} />);
  return { onNext };
}

describe("Deciding a case", () => {
  it("approves with one click, then shows what happened and offers the next case", async () => {
    const user = userEvent.setup();
    const { onNext } = renderPane(anaReady);
    decide.mockImplementation(() => {
      getCase.mockResolvedValue(done);
      return Promise.resolve(RESULT);
    });

    await user.click(await screen.findByRole("button", { name: "Refund $35 and send reply" }));

    expect(decide).toHaveBeenCalledWith(5012, expect.any(String), {
      run_id: RUN_ID,
      action: "approve",
      reply_text: anaReady.draft?.text,
      reason: null,
    });
    const title = await screen.findByRole("heading", { name: copy.status.done });
    expect(screen.getByText(/^Refunded \$35 and replied · Luis/)).toBeInTheDocument();
    expect(title).toHaveFocus();
    await user.click(screen.getByRole("button", { name: copy.card.next }));
    expect(onNext).toHaveBeenCalledWith(5011);
  });

  it("sends an edited reply as an edit, and can undo the changes", async () => {
    const user = userEvent.setup();
    renderPane(anaReady);
    decide.mockResolvedValue(RESULT);

    await user.click(await screen.findByRole("button", { name: copy.reply.edit }));
    const box = screen.getByRole("textbox", { name: copy.reply.title });
    expect(box).toHaveValue(anaReady.draft?.text);
    await user.clear(box);
    await user.type(box, "Hi Ana, done.");
    expect(screen.getByText(copy.reply.counter(13))).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: copy.reply.undo }));
    expect(box).toHaveValue(anaReady.draft?.text);
    await user.clear(box);
    await user.type(box, "Hi Ana, all done.");
    await user.click(screen.getByRole("button", { name: "Refund $35 and send reply" }));

    expect(decide).toHaveBeenCalledWith(5012, expect.any(String), {
      run_id: RUN_ID,
      action: "edit",
      reply_text: "Hi Ana, all done.",
      reason: null,
    });
  });

  it.each([
    ["Don't refund", anaReady],
    ["Refund anyway", recommendNoRefund],
  ])("%s needs a reason of 10 characters or more, and its own reply", async (label, view) => {
    const user = userEvent.setup();
    renderPane(view);
    decide.mockResolvedValue({ ...RESULT, refunded: label === "Refund anyway" });

    await user.click(await screen.findByRole("button", { name: label }));
    const confirm = screen.getByRole("button", { name: label });
    const reply = screen.getByRole("textbox", { name: copy.reply.title });
    const reason = screen.getByRole("textbox", { name: copy.reason.label });
    expect(reply).toHaveValue(""); // the draft says the opposite, so Luis writes this one
    expect(confirm).toBeDisabled();
    await user.type(reply, "Hi Ana, here's what we decided.");
    await user.type(reason, "Too short");
    expect(confirm).toBeDisabled();
    await user.type(reason, "!");
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    expect(decide).toHaveBeenCalledWith(view.id, expect.any(String), {
      run_id: RUN_ID,
      action: "reject",
      reply_text: "Hi Ana, here's what we decided.",
      reason: "Too short!",
    });
  });

  it("goes back to the recommendation when Luis cancels", async () => {
    const user = userEvent.setup();
    renderPane(anaReady);

    await user.click(await screen.findByRole("button", { name: "Don't refund" }));
    await user.click(screen.getByRole("button", { name: copy.reason.cancel }));

    expect(screen.queryByRole("textbox", { name: copy.reason.label })).toBeNull();
    expect(screen.getByText(anaReady.draft?.text ?? "")).toBeInTheDocument();
  });

  it("asks for a reply when there is no recommendation to follow", async () => {
    const user = userEvent.setup();
    renderPane(feeQuestion);
    decide.mockResolvedValue({ ...RESULT, refunded: false, amount: null });

    const send = await screen.findByRole("button", { name: copy.actions.sendReply });
    expect(send).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: copy.reply.title }), "Hi Daniel, ...");
    await user.click(send);

    expect(decide).toHaveBeenCalledWith(feeQuestion.id, expect.any(String), {
      run_id: RUN_ID,
      action: "reply_only",
      reply_text: "Hi Daniel, ...",
      reason: null,
    });
  });

  it("shows the API's message when the case was decided elsewhere, and reloads it", async () => {
    const user = userEvent.setup();
    renderPane(anaReady);
    decide.mockRejectedValue(
      new ApiError("Luis already decided this case at 10:42.", 409, "already_decided"),
    );

    await user.click(await screen.findByRole("button", { name: "Refund $35 and send reply" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Luis already decided this case at 10:42.",
    );
    expect(getCase.mock.calls.length).toBeGreaterThan(1);
  });
});

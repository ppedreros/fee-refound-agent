import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, type CaseView } from "../../api/client";
import { copy } from "../../copy/en";
import { anaReady, checking } from "../../test/caseFixtures";
import { renderWithClient } from "../../test/render";
import { CasePane } from "./CasePane";

vi.mock("../../api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("../../api/client")>();
  return { ...original, api: { listCases: vi.fn(), getCase: vi.fn(), runCase: vi.fn() } };
});

const getCase = vi.mocked(api.getCase);
const runCase = vi.mocked(api.runCase);
const anaNotChecked: CaseView = {
  ...anaReady,
  status: "not_checked",
  summary: null,
  recommendation: { action: "none", amount: null },
  draft: null,
  run: null,
  actions: [],
};

beforeEach(() => {
  vi.mocked(api.listCases).mockResolvedValue({ items: [], next_cursor: null });
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderPane() {
  renderWithClient(<CasePane caseId={5012} onBack={vi.fn()} onNext={vi.fn()} />);
}

describe("Case pane", () => {
  it("checks the case and shows the result once the check is done", async () => {
    const user = userEvent.setup();
    getCase
      .mockResolvedValueOnce(anaNotChecked)
      .mockResolvedValueOnce(checking)
      .mockResolvedValue(anaReady);
    runCase.mockResolvedValue({ run_id: "bf5975f1-b419-4d2b-bc60-5328e5909ced" });
    renderPane();

    await user.click(await screen.findByRole("button", { name: copy.actions.checkCase }));

    expect(runCase).toHaveBeenCalledWith(5012, undefined);
    expect(await screen.findByRole("heading", { name: copy.status.checking })).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: copy.status.ready_to_refund }, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(screen.getByText(anaReady.summary ?? "")).toBeInTheDocument();
  });

  it("follows a check that is already running instead of showing an error", async () => {
    const user = userEvent.setup();
    getCase.mockResolvedValueOnce(anaNotChecked).mockResolvedValue(checking);
    runCase.mockRejectedValue(
      new ApiError("This case is being checked right now.", 409, "run_in_progress", "abc"),
    );
    renderPane();

    await user.click(await screen.findByRole("button", { name: copy.actions.checkCase }));

    expect(await screen.findByRole("heading", { name: copy.status.checking })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows why a case can't be checked", async () => {
    const user = userEvent.setup();
    getCase.mockResolvedValue(anaNotChecked);
    runCase.mockRejectedValue(
      new ApiError("This conversation is closed.", 409, "case_not_running"),
    );
    renderPane();

    await user.click(await screen.findByRole("button", { name: copy.actions.checkCase }));

    expect(await screen.findByRole("alert")).toHaveTextContent("This conversation is closed.");
  });

  it("says when a conversation can't be found", async () => {
    getCase.mockRejectedValue(
      new ApiError("We couldn't find that conversation.", 404, "not_found"),
    );
    renderPane();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We couldn't find that conversation.",
    );
  });

  it("shows the member, the latest message and the masked accounts", async () => {
    getCase.mockResolvedValue(anaReady);
    renderPane();

    expect(
      await screen.findByRole("heading", { name: "Ana Torres · Overdraft fee" }),
    ).toBeInTheDocument();
    const quoted = screen.getAllByText(anaReady.conversation.messages[0]?.body ?? "")[0];
    expect(quoted?.tagName).toBe("Q"); // the header quotes it; the thread below has it too
    expect(
      screen.getByText("Primary Savings, Everyday Checking ••4210 · Vacation Savings ••4211"),
    ).toBeInTheDocument();
  });

  it("opens an evidence section on request", async () => {
    const user = userEvent.setup();
    getCase.mockResolvedValue(anaReady);
    renderPane();

    const section = await screen.findByRole("button", { name: "What happened on Sep 14" });
    expect(section).toHaveAttribute("aria-expanded", "false");
    await user.click(section);

    expect(section).toHaveAttribute("aria-expanded", "true");
  });
});

import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, type CaseView } from "../../api/client";
import { copy } from "../../copy/en";
import { anaReady, checking, spanish } from "../../test/caseFixtures";
import { FakeEventSource } from "../../test/eventSource";
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
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

function renderPane() {
  renderWithClient(<CasePane caseId={5012} onBack={vi.fn()} onNext={vi.fn()} />);
}

describe("Case pane", () => {
  it("checks the case, shows the steps as they happen, then the result", async () => {
    const user = userEvent.setup();
    getCase
      .mockResolvedValueOnce(anaNotChecked)
      .mockResolvedValueOnce(checking)
      .mockResolvedValue(anaReady);
    runCase.mockResolvedValue({ run_id: checking.checking_run_id ?? "" });
    renderPane();

    await user.click(await screen.findByRole("button", { name: copy.actions.checkCase }));

    expect(runCase).toHaveBeenCalledWith(5012, undefined);
    expect(await screen.findByRole("heading", { name: copy.status.checking })).toBeInTheDocument();
    const source = FakeEventSource.latest();
    expect(source.url).toContain(checking.checking_run_id);
    act(() => {
      source.send({ event: "step", node: "load_conversation", state: "started" });
    });
    const card = screen.getByRole("region", { name: copy.status.checking });
    expect(within(card).getByText(copy.steps.load_conversation)).toBeInTheDocument();
    act(() => {
      source.send({ event: "done", status: "ready_to_refund" });
    });
    expect(
      await screen.findByRole("heading", { name: copy.status.ready_to_refund }),
    ).toBeInTheDocument();
    expect(source.closed).toBe(true);
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
    expect(FakeEventSource.latest().url).toContain(checking.checking_run_id);
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

  it("tags a reply written in Spanish, and only that one", async () => {
    getCase.mockResolvedValueOnce(spanish);
    renderPane();

    expect(await screen.findByText(copy.reply.spanish)).toBeInTheDocument();
  });

  it("doesn't tag a reply in English", async () => {
    getCase.mockResolvedValue(anaReady);
    renderPane();

    await screen.findByRole("heading", { name: copy.status.ready_to_refund });
    expect(screen.queryByText(copy.reply.spanish)).toBeNull();
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

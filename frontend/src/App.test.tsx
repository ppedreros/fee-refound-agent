import { screen } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { api, type CaseView } from "./api/client";
import { copy } from "./copy/en";
import { anaReady, done, notChecked } from "./test/caseFixtures";
import { FakeEventSource } from "./test/eventSource";
import { ana, daniel, marcus } from "./test/fixtures";
import { renderWithClient } from "./test/render";

vi.mock("./api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("./api/client")>();
  return {
    ...original,
    api: {
      listCases: vi.fn(),
      getCase: vi.fn(),
      health: vi.fn(),
      runCase: vi.fn(),
      decide: vi.fn(),
      revealAccount: vi.fn(),
    },
  };
});

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  vi.mocked(api.listCases).mockResolvedValue({ items: [], next_cursor: null });
  vi.mocked(api.health).mockResolvedValue({
    status: "ok",
    database: "ok",
    provider_mode: { jev: "live", openai: "live" },
    version: "dev",
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function render(ui: Parameters<typeof renderWithClient>[0]) {
  return renderWithClient(ui);
}

function allCopyStrings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (value !== null && typeof value === "object")
    return Object.values(value).flatMap(allCopyStrings);
  return [];
}

function visibleTexts(container: HTMLElement): string[] {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const texts: string[] = [];
  for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
    const text = node.textContent?.trim() ?? "";
    if (text !== "") texts.push(text);
  }
  return texts;
}

describe("App shell", () => {
  it("shows the app title as the page heading", () => {
    render(<App />);

    expect(screen.getByRole("heading", { level: 1, name: copy.app.title })).toBeInTheDocument();
  });

  it("has a labelled queue pane and a case pane", () => {
    render(<App />);

    expect(screen.getByRole("navigation", { name: copy.queue.label })).toBeInTheDocument();
    expect(screen.getByRole("main", { name: copy.case.label })).toBeInTheDocument();
  });

  it("asks Luis to pick a conversation when none is selected", () => {
    render(<App />);

    expect(screen.getByText(copy.case.empty)).toBeInTheDocument();
  });

  it("only shows text that comes from the copy file", async () => {
    const { container } = render(<App />);
    await screen.findByText(copy.queue.empty);
    const allowed = new Set(allCopyStrings(copy));

    for (const text of visibleTexts(container)) {
      expect(allowed).toContain(text);
    }
  });
});

/** Tab forward until `target` has the focus, as someone without a mouse would. */
async function tabTo(user: UserEvent, target: HTMLElement) {
  for (let presses = 0; presses < 50 && document.activeElement !== target; presses++) {
    await user.tab();
  }
  expect(target).toHaveFocus();
}

describe("Keyboard only (SPEC-ui AC9)", () => {
  it("opens Ana from the queue, approves her refund, then moves to the next case", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.mocked(api.listCases).mockResolvedValue({ items: [ana, marcus, daniel], next_cursor: null });
    let anaNow: CaseView = anaReady;
    vi.mocked(api.getCase).mockImplementation((id) =>
      Promise.resolve(id === anaReady.id ? anaNow : { ...notChecked, id }),
    );
    vi.mocked(api.decide).mockImplementation(() => {
      anaNow = done;
      return Promise.resolve({
        decision_id: "6c1f3c2e-8a51-4b8e-9d3a-2f4f0b7c9e10",
        refunded: true,
        amount: "35.00",
        case_status: "done",
      });
    });
    render(<App />);

    const anaRow = await screen.findByRole("button", { name: /Ana T\./ });
    await tabTo(user, anaRow);
    await user.keyboard("{ArrowDown}{ArrowUp}{Enter}"); // the queue's own keys, then open

    const approve = await screen.findByRole("button", { name: "Refund $35 and send reply" });
    await tabTo(user, approve);
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("heading", { name: copy.status.done })).toHaveFocus();
    await tabTo(user, screen.getByRole("button", { name: copy.card.next }));
    await user.keyboard("{Enter}");

    expect(window.location.search).toContain(`case=${String(marcus.id)}`);
    expect(api.decide).toHaveBeenCalledTimes(1);
  });
});

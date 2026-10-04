import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../../App";
import { ApiError, api } from "../../api/client";
import { copy } from "../../copy/en";
import { ana, daniel, marcus, NOW } from "../../test/fixtures";
import { renderWithClient } from "../../test/render";

vi.mock("../../api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("../../api/client")>();
  return { ...original, api: { listCases: vi.fn(), getCase: vi.fn(), health: vi.fn() } };
});

const listCases = vi.mocked(api.listCases);

beforeEach(() => {
  vi.useFakeTimers({ now: NOW, toFake: ["Date"] });
  window.history.replaceState(null, "", "/");
  listCases.mockImplementation((view) =>
    Promise.resolve({ items: view === "open" ? [ana, marcus, daniel] : [], next_cursor: null }),
  );
  vi.mocked(api.getCase).mockReturnValue(new Promise(() => undefined));
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

function queueItem(name: string): HTMLElement {
  return screen.getByRole("button", { name: new RegExp(name) });
}

describe("Queue", () => {
  it("lists each conversation with its name, what it's about, status, amount and time", async () => {
    renderWithClient(<App />);

    const item = await screen.findByRole("button", { name: /Ana T\./ });
    expect(within(item).getByText(copy.topic.fee_refund_request)).toBeInTheDocument();
    expect(within(item).getByText(copy.status.ready_to_refund)).toBeInTheDocument();
    expect(within(item).getByText("$35")).toBeInTheDocument();
    expect(within(item).getByText("2 h ago")).toBeInTheDocument();
    const notChecked = queueItem("Marcus R\\.");
    expect(within(notChecked).getByText("Card not working")).toBeInTheDocument(); // the subject
    expect(within(notChecked).getByText(copy.status.not_checked)).toBeInTheDocument();
    expect(within(notChecked).getByText("Sep 14")).toBeInTheDocument();
  });

  it("selecting a conversation puts it in the URL and marks it", async () => {
    const user = userEvent.setup();
    renderWithClient(<App />);

    await user.click(await screen.findByRole("button", { name: /Marcus R\./ }));

    expect(window.location.search).toBe("?view=open&case=5011");
    expect(queueItem("Marcus R\\.")).toHaveAttribute("aria-current", "true");
    expect(queueItem("Ana T\\.")).not.toHaveAttribute("aria-current");
  });

  it("restores the selection from the URL after a refresh", async () => {
    window.history.replaceState(null, "", "/?view=open&case=5008");

    renderWithClient(<App />);

    expect(await screen.findByRole("button", { name: /Daniel O\./ })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("moves through the queue with the arrow keys or j and k, and opens with Enter", async () => {
    const user = userEvent.setup();
    renderWithClient(<App />);
    (await screen.findByRole("button", { name: /Ana T\./ })).focus();

    await user.keyboard("{ArrowDown}");
    expect(queueItem("Marcus R\\.")).toHaveFocus();
    await user.keyboard("j");
    expect(queueItem("Daniel O\\.")).toHaveFocus();
    await user.keyboard("k");
    await user.keyboard("{Enter}");

    expect(window.location.search).toBe("?view=open&case=5011");
  });

  it("shows the done conversations in their own tab", async () => {
    const user = userEvent.setup();
    renderWithClient(<App />);

    await user.click(await screen.findByRole("tab", { name: copy.queue.tabs.done }));

    expect(await screen.findByText(copy.queue.empty)).toBeInTheDocument();
    expect(listCases).toHaveBeenLastCalledWith("done");
    expect(window.location.search).toBe("?view=done");
    expect(screen.getByRole("tab", { name: copy.queue.tabs.done })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("says when the server can't be reached, and tries again on request", async () => {
    const user = userEvent.setup();
    listCases.mockRejectedValueOnce(new ApiError(copy.errors.network, null, null));
    renderWithClient(<App />);

    await user.click(await screen.findByRole("button", { name: copy.errors.tryAgain }));

    expect(await screen.findByRole("button", { name: /Ana T\./ })).toBeInTheDocument();
  });
});

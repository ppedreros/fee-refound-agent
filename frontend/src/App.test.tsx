import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { api } from "./api/client";
import { copy } from "./copy/en";
import { renderWithClient } from "./test/render";

vi.mock("./api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("./api/client")>();
  return { ...original, api: { listCases: vi.fn(), getCase: vi.fn(), health: vi.fn() } };
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

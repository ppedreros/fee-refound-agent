import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import App from "./App";
import { copy } from "./copy/en";

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

  it("only shows text that comes from the copy file", () => {
    const { container } = render(<App />);
    const allowed = new Set(allCopyStrings(copy));

    for (const text of visibleTexts(container)) {
      expect(allowed).toContain(text);
    }
  });
});

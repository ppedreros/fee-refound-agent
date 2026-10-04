import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CaseView } from "../api/client";
import { CaseContent } from "../features/case/CasePane";
import { ALL_STATUSES } from "../test/caseFixtures";

// SPEC-ui AC6: whatever the status, Luis never sees a code, a placeholder or a broken value.
const FORBIDDEN = [/\b[a-z]+_[a-z_]+\b/, /\bundefined\b/, /\bnull\b/, /\bNaN\b/, /\[ACCOUNT/];

function visibleText(container: HTMLElement): string {
  return Array.from(container.querySelectorAll("*"))
    .flatMap((element) => Array.from(element.childNodes))
    .filter((node) => node.nodeType === Node.TEXT_NODE)
    .map((node) => node.textContent)
    .join("\n");
}

describe.each<[string, CaseView]>(ALL_STATUSES)("The case page: %s", (_name, view) => {
  it("shows no internal codes, placeholders or broken values", () => {
    const { container } = render(
      <CaseContent view={view} running={false} onRun={vi.fn()} onSubmit={vi.fn()} />,
    );
    const text = visibleText(container);

    for (const pattern of FORBIDDEN) {
      expect(text).not.toMatch(pattern);
    }
  });
});

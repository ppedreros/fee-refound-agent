import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { copy } from "../../copy/en";
import { FakeEventSource } from "../../test/eventSource";
import { LiveSteps } from "./LiveSteps";

const RUN = "7a1c2e9d-3b4f-4c5a-8d6e-0f1a2b3c4d5e";

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderSteps() {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <LiveSteps caseId={5012} runId={RUN} />
    </QueryClientProvider>,
  );
  return { invalidate, source: FakeEventSource.latest() };
}

function send(source: FakeEventSource, node: string, state: string) {
  act(() => {
    source.send({ event: "step", node, state });
  });
}

function rows(): string[] {
  return screen.getAllByRole("listitem").map((row) => row.textContent);
}

describe("LiveSteps", () => {
  it("follows the check's own event stream", () => {
    const { source } = renderSteps();

    expect(source.url).toBe(`/api/cases/5012/runs/${RUN}/events`);
  });

  it("shows each step as it starts, in order, with its plain label", () => {
    const { source } = renderSteps();

    send(source, "load_conversation", "started");
    send(source, "load_conversation", "finished");
    send(source, "triage", "started");

    expect(rows()).toEqual([
      copy.steps.load_conversation + copy.live.finished,
      copy.steps.triage + copy.live.running,
    ]);
  });

  it("puts the three reads on one line, done when all three are", () => {
    const { source } = renderSteps();

    send(source, "load_accounts", "started");
    send(source, "load_transactions", "started");
    send(source, "load_accounts", "finished");
    expect(rows()).toEqual([copy.steps.load + copy.live.running]);

    send(source, "load_transactions", "finished");
    expect(rows()).toEqual([copy.steps.load + copy.live.finished]);
  });

  it("says plainly when a step didn't finish", () => {
    const { source } = renderSteps();

    send(source, "triage", "started");
    send(source, "triage", "failed");

    expect(rows()).toEqual([copy.steps.triage + copy.live.failed]);
  });

  it("stops listening when the check is done and fetches the case again", () => {
    const { source, invalidate } = renderSteps();

    act(() => {
      source.send({ event: "done", status: "ready_to_refund" });
    });

    expect(source.closed).toBe(true);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["case", 5012] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["cases"] });
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, type DecisionRequest } from "../../api/client";
import { copy } from "../../copy/en";
import { useDecision } from "./useDecision";

vi.mock("../../api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("../../api/client")>();
  return { ...original, api: { decide: vi.fn(), getCase: vi.fn(), listCases: vi.fn() } };
});

const decide = vi.mocked(api.decide);
const APPROVE: DecisionRequest = {
  run_id: "bf5975f1-b419-4d2b-bc60-5328e5909ced",
  action: "approve",
  reply_text: "Hi Ana, we've refunded the fee.",
  reason: null,
};
const RESULT = {
  decision_id: "118de9ba-cb7d-419a-8c3f-8fed9a385dd3",
  refunded: true,
  amount: "35.00",
  case_status: "done" as const,
};

function renderDecision() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useDecision(5012), { wrapper });
}

async function send(hook: ReturnType<typeof renderDecision>, decision: DecisionRequest) {
  await act(async () => {
    await hook.result.current.mutateAsync(decision).catch(() => undefined);
  });
}

function keys(): string[] {
  return decide.mock.calls.map(([, key]) => key);
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("useDecision", () => {
  it("retries with the same key after a network error, so the refund can't happen twice", async () => {
    decide
      .mockRejectedValueOnce(new ApiError(copy.errors.network, null, null))
      .mockResolvedValueOnce(RESULT);
    const hook = renderDecision();

    await send(hook, APPROVE);
    await send(hook, APPROVE);

    expect(keys()).toHaveLength(2);
    expect(keys()[0]).toBe(keys()[1]);
    expect(keys()[0]).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });

  it("keeps the key when the server failed on its side", async () => {
    decide
      .mockRejectedValueOnce(new ApiError(copy.errors.unexpected, 500, null))
      .mockResolvedValueOnce(RESULT);
    const hook = renderDecision();

    await send(hook, APPROVE);
    await send(hook, APPROVE);

    expect(keys()[0]).toBe(keys()[1]);
  });

  it("uses a new key once the server has answered", async () => {
    decide
      .mockRejectedValueOnce(
        new ApiError("That action isn't available.", 422, "action_not_allowed"),
      )
      .mockResolvedValueOnce(RESULT);
    const hook = renderDecision();

    await send(hook, APPROVE);
    await send(hook, APPROVE);

    expect(keys()[0]).not.toBe(keys()[1]);
  });

  it("uses a new key when Luis changes the details", async () => {
    decide.mockRejectedValueOnce(new ApiError(copy.errors.network, null, null));
    decide.mockResolvedValueOnce(RESULT);
    const hook = renderDecision();

    await send(hook, APPROVE);
    await send(hook, { ...APPROVE, action: "edit", reply_text: "Hi Ana, all done." });

    expect(keys()[0]).not.toBe(keys()[1]);
  });
});

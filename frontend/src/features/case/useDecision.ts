// Sending Luis's decision (SPEC-ui, "Data and state"). One Idempotency-Key per attempt: a retry
// after a network error or a server failure reuses it, so the API answers it as the same request
// and money can't move twice. Once the server has answered, or the details change, a new attempt
// gets a new key.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import { ApiError, api, type DecisionRequest } from "../../api/client";
import { queryKeys } from "../../api/hooks";

export function useDecision(caseId: number) {
  const client = useQueryClient();
  const attempt = useRef<{ key: string; body: string } | null>(null);

  return useMutation({
    mutationFn: (decision: DecisionRequest) => {
      const body = JSON.stringify(decision);
      if (attempt.current?.body !== body) attempt.current = { key: newIdempotencyKey(), body };
      return api.decide(caseId, attempt.current.key, decision);
    },
    onSuccess: () => {
      attempt.current = null;
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status !== null && error.status < 500) {
        attempt.current = null; // the server answered: this attempt is over
      }
    },
    onSettled: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.case(caseId) }),
        client.invalidateQueries({ queryKey: queryKeys.allCases }),
      ]);
    },
  });
}

/** A random (version 4) UUID. `crypto.randomUUID` needs a secure context; this doesn't. */
export function newIdempotencyKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join("-");
}

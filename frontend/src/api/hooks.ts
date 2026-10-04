// TanStack Query hooks over the client (SPEC-ui, "Data and state").
import { QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, type View } from "./client";

export const queryKeys = {
  cases: (view: View) => ["cases", view] as const,
  allCases: ["cases"] as const,
  case: (id: number) => ["case", id] as const,
};

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A 4xx won't change by asking again; a network blip or a 5xx might.
        retry: (failures, error) => !isClientError(error) && failures < 2,
      },
    },
  });
}

function isClientError(error: unknown): boolean {
  return error instanceof ApiError && error.status !== null && error.status < 500;
}

/** Read once: the modes don't change while the app runs. */
export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: Infinity, retry: false });
}

export function useCases(view: View) {
  return useQuery({ queryKey: queryKeys.cases(view), queryFn: () => api.listCases(view) });
}

export function useCase(id: number) {
  return useQuery({
    queryKey: queryKeys.case(id),
    queryFn: () => api.getCase(id),
    staleTime: 5000, // a check in progress is followed live (useRunEvents), not polled
  });
}

/** "Check this case": start a check (optionally with the fee Luis picked), then follow it. A
 * check that is already running is followed the same way. */
export function useRunCase(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (feeTxnId?: number) => api.runCase(id, feeTxnId),
    onSettled: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.case(id) }),
        client.invalidateQueries({ queryKey: queryKeys.allCases }),
      ]);
    },
  });
}

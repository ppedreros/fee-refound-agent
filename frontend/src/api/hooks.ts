// TanStack Query hooks over the client (SPEC-ui, "Data and state").
import { QueryClient, useQuery } from "@tanstack/react-query";

import { ApiError, api, type View } from "./client";

export const queryKeys = {
  cases: (view: View) => ["cases", view] as const,
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

export function useCases(view: View) {
  return useQuery({ queryKey: queryKeys.cases(view), queryFn: () => api.listCases(view) });
}

// The API client: one thin function per endpoint, typed by the generated schema. Tests stub this
// module (vi.mock), so components never call fetch themselves.
import { copy } from "../copy/en";
import type { components } from "./schema";

type Schemas = components["schemas"];
export type Action = Schemas["Action"];
export type CaseStatus = Schemas["CaseStatus"];
export type Topic = Schemas["Topic"];
export type QueueItem = Schemas["QueueItem"];
export type QueuePage = Schemas["QueuePage"];
export type CaseView = Schemas["CaseView"];
export type RunStarted = Schemas["RunStarted"];
export type DecisionRequest = Schemas["DecisionRequest"];
export type DecisionResult = Schemas["DecisionResult"];
export type Health = Schemas["HealthResponse"];
export type View = "open" | "done";

/** A request that failed, with a message Luis can read. `code` is for UI logic only. */
export class ApiError extends Error {
  readonly status: number | null; // null when the server couldn't be reached
  readonly code: string | null;
  readonly runId: string | null; // the active check, on a 409 run_in_progress

  constructor(message: string, status: number | null, code: string | null, runId?: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.runId = runId ?? null;
  }
}

/** What to show for any error: the API's own message, or a calm generic one. */
export function messageOf(error: unknown): string {
  return error instanceof ApiError ? error.message : copy.errors.unexpected;
}

const BASE = "/api";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(BASE + path, { ...init, headers });
  } catch {
    throw new ApiError(copy.errors.network, null, null);
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw errorFrom(response.status, body);
  return body as T;
}

interface ErrorBody {
  error: { code: string; message: string };
  run_id?: unknown;
}

function isErrorBody(body: unknown): body is ErrorBody {
  if (typeof body !== "object" || body === null || !("error" in body)) return false;
  const { error } = body;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { message?: unknown }).message === "string" &&
    typeof (error as { code?: unknown }).code === "string"
  );
}

function errorFrom(status: number, body: unknown): ApiError {
  if (!isErrorBody(body)) return new ApiError(copy.errors.unexpected, status, null);
  const runId = typeof body.run_id === "string" ? body.run_id : null;
  return new ApiError(body.error.message, status, body.error.code, runId);
}

export const api = {
  listCases: (view: View) => request<QueuePage>(`/cases?view=${view}`),
  getCase: (id: number) => request<CaseView>(`/cases/${String(id)}`),
  runCase: (id: number, feeTxnId?: number) =>
    request<RunStarted>(`/cases/${String(id)}/run`, {
      method: "POST",
      ...(feeTxnId === undefined ? {} : { body: JSON.stringify({ fee_txn_id: feeTxnId }) }),
    }),
  decide: (id: number, idempotencyKey: string, decision: DecisionRequest) =>
    request<DecisionResult>(`/cases/${String(id)}/decision`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(decision),
    }),
  health: () => request<Health>("/health"),
};

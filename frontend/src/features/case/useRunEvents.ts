// A check's live steps (SPEC-ui, "Live steps"): the API's event stream for one run, read with
// EventSource. On `done` the stream is closed, and the case and the queue are fetched again.
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { queryKeys } from "../../api/hooks";

export type StepState = "started" | "finished" | "failed";

export interface StepEvent {
  event: "step";
  node: string;
  state: StepState;
}

type RunEvent = StepEvent | { event: "done"; status: string };

function parse(data: string): RunEvent | null {
  try {
    const event = JSON.parse(data) as Partial<RunEvent>;
    return event.event === "step" || event.event === "done" ? (event as RunEvent) : null;
  } catch {
    return null;
  }
}

/** The steps so far, in the order they happened. Mount it per run (a `key`), so each check
 * starts from an empty list. */
export function useRunEvents(caseId: number, runId: string): StepEvent[] {
  const client = useQueryClient();
  const [steps, setSteps] = useState<StepEvent[]>([]);

  useEffect(() => {
    const source = new EventSource(`/api/cases/${String(caseId)}/runs/${runId}/events`);
    source.onmessage = (message: MessageEvent<string>) => {
      const event = parse(message.data);
      if (event?.event === "step") {
        setSteps((earlier) => [...earlier, event]);
      } else if (event?.event === "done") {
        source.close();
        void client.invalidateQueries({ queryKey: queryKeys.case(caseId) });
        void client.invalidateQueries({ queryKey: queryKeys.allCases });
      }
    };
    return () => {
      source.close();
    };
  }, [caseId, runId, client]);

  return steps;
}

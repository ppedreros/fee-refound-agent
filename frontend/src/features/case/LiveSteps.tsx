import { copy } from "../../copy/en";
import { stepLabel } from "./steps";
import { useRunEvents, type StepEvent } from "./useRunEvents";

type RowState = "running" | "finished" | "failed";

interface Row {
  label: string;
  state: RowState;
}

/** The check as it happens: each step appears when it starts and gets a check when it finishes.
 * A thin Terracotta line shows that work is going on; it is not a percentage. */
export function LiveSteps({ caseId, runId }: { caseId: number; runId: string }) {
  const rows = liveRows(useRunEvents(caseId, runId));

  return (
    <div className="space-y-3">
      <div className="h-0.5 overflow-hidden rounded bg-grey-100">
        <div className="h-full w-1/3 animate-pulse bg-terracotta motion-reduce:animate-none" />
      </div>
      <ol aria-live="polite" className="space-y-1 text-sm">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center gap-2 motion-safe:animate-rise">
            <Mark state={row.state} />
            <span className={row.state === "running" ? "text-grey-800" : "text-grey-700"}>
              {row.label}
            </span>
            <span className={row.state === "failed" ? "text-grey-600" : "sr-only"}>
              {copy.live[row.state]}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** One row per label, in the order steps started. The three reads share a label, so their row
 * is done when all of them are. */
function liveRows(steps: StepEvent[]): Row[] {
  const nodes = new Map<string, Map<string, StepEvent["state"]>>();
  for (const step of steps) {
    const label = stepLabel(step.node);
    const states = nodes.get(label) ?? new Map<string, StepEvent["state"]>();
    states.set(step.node, step.state);
    nodes.set(label, states);
  }
  return [...nodes].map(([label, states]) => {
    const all = [...states.values()];
    const state: RowState = all.includes("failed")
      ? "failed"
      : all.every((s) => s === "finished")
        ? "finished"
        : "running";
    return { label, state };
  });
}

function Mark({ state }: { state: RowState }) {
  if (state === "finished") {
    return (
      <svg aria-hidden="true" viewBox="0 0 16 16" className="size-3.5 shrink-0 text-success">
        <path d="M3 8.5l3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
    );
  }
  return (
    <span
      aria-hidden="true"
      className={`mx-1 size-1.5 shrink-0 rounded-full ${
        state === "failed"
          ? "bg-grey-400"
          : "animate-pulse bg-terracotta motion-reduce:animate-none"
      }`}
    />
  );
}

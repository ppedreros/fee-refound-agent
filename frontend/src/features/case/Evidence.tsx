import { useId, useState, type ReactNode } from "react";

import type { CaseView } from "../../api/client";
import type { components } from "../../api/schema";
import { copy } from "../../copy/en";
import {
  formatCost,
  formatDateTime,
  formatDay,
  formatDayWithYear,
  formatDuration,
  formatLatency,
  formatMoney,
  formatShortDate,
} from "../../lib/format";
import { EvidenceDay } from "./EvidenceDay";

type StepView = components["schemas"]["StepView"];

const { evidence: text } = copy;

/** The evidence, one click away: each section is collapsed, and its header carries the summary. */
export function Evidence({ view }: { view: CaseView }) {
  const { fee_day: day, refunds_in_window: refunds, standing } = view.evidence;
  const messages = view.conversation.messages;
  const run = view.run;

  return (
    <div className="divide-y divide-grey-200 border-y border-grey-200">
      {day && (
        <Section title={text.feeDay(formatDay(day.date))}>
          <EvidenceDay day={day} />
        </Section>
      )}
      {refunds && (
        <Section title={text.refunds(refunds.count, refunds.max_allowed)}>
          <p className="mb-2 text-sm text-grey-600">
            {text.refundsWindow(formatDayWithYear(refunds.start), formatDayWithYear(refunds.end))}
          </p>
          {refunds.items.length === 0 ? (
            <p>{text.refundsNone}</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {refunds.items.map((item) => (
                <li key={`${item.date}-${item.amount}`} className="flex gap-4">
                  <span className="w-16 tabular-nums text-grey-600">{formatDay(item.date)}</span>
                  <span className="flex-1">{item.fee_type}</span>
                  <span className="tabular-nums">{formatMoney(item.amount)}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
      {standing && (
        <Section
          title={text.titled(
            text.standing,
            standing.ok ? text.standingOk : text.standingBelow(standing.below_zero.length),
          )}
        >
          {standing.ok ? (
            <p>{text.standingOk}</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {standing.below_zero.map((sub) => (
                <li key={sub.name} className="flex gap-4">
                  <span className="flex-1">{sub.name}</span>
                  <span className="tabular-nums">{formatMoney(sub.available)}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
      {view.clause && (
        <Section title={text.policy(view.clause.doc_title, sectionNumber(view.clause.section))}>
          <blockquote className="border-l-2 border-grey-300 pl-3 font-serif text-grey-800">
            {view.clause.text}
          </blockquote>
        </Section>
      )}
      <Section title={text.conversation(messages.length)}>
        <ol className="space-y-3">
          {messages.map((message) => (
            <li
              key={`${message.created_at}-${message.author_name}`}
              className={`max-w-[85%] rounded-lg px-3 py-2 ${
                message.author === "staff" ? "ml-auto bg-clay" : "bg-grey-50 ring-1 ring-grey-200"
              }`}
            >
              <p className="text-xs text-grey-600">
                {text.titled(message.author_name, formatShortDate(message.created_at))}
              </p>
              <p className="whitespace-pre-wrap">{message.body}</p>
            </li>
          ))}
        </ol>
      </Section>
      {run && (
        <Section
          title={text.titled(
            text.prepared,
            ...(run.duration_ms !== null ? [formatDuration(run.duration_ms)] : []),
            ...(run.cost_usd !== null ? [formatCost(run.cost_usd)] : []),
          )}
        >
          <ol className="space-y-1 text-sm">
            {preparedSteps(run.steps).map((step) => (
              <li key={step.label} className="flex gap-4">
                <span className="flex-1">
                  {step.failed ? text.titled(step.label, text.stepFailed) : step.label}
                </span>
                <span className="tabular-nums text-grey-600">{formatLatency(step.latencyMs)}</span>
              </li>
            ))}
          </ol>
          <div className="mt-3 space-y-1 text-sm text-grey-600">
            {run.provider_mode["jev"] === "replay" && <p>{text.replay}</p>}
            {run.checked_at && <p>{text.checkedAt(formatDateTime(run.checked_at))}</p>}
          </div>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div>
      <h3>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => {
            setOpen(!open);
          }}
          className="flex w-full items-center gap-2 py-3 text-left font-medium"
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 16 16"
            className={`size-3 shrink-0 text-grey-600 transition-transform duration-150 motion-reduce:transition-none ${
              open ? "rotate-90" : ""
            }`}
          >
            <path d="M6 3l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
          {title}
        </button>
      </h3>
      <div
        id={id}
        inert={!open}
        className={`grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none ${
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div className="overflow-hidden">
          <div className="pb-4 pl-5">{children}</div>
        </div>
      </div>
    </div>
  );
}

/** "4. Same-day deposits" is section 4. */
function sectionNumber(section: string): string {
  return /^\d+/.exec(section)?.[0] ?? section;
}

interface PreparedStep {
  label: string;
  latencyMs: number;
  failed: boolean;
}

/** Steps with plain labels. The three reads run side by side, so they share one line, with the
 * time of the slowest. */
function preparedSteps(steps: StepView[]): PreparedStep[] {
  const merged = new Map<string, PreparedStep>();
  for (const step of steps) {
    const label = stepLabel(step.node);
    const known = merged.get(label);
    merged.set(label, {
      label,
      latencyMs: Math.max(known?.latencyMs ?? 0, step.latency_ms),
      failed: (known?.failed ?? false) || step.state === "failed",
    });
  }
  return [...merged.values()];
}

function stepLabel(node: string): string {
  if (node.startsWith("load_") && node !== "load_conversation") return copy.steps.load;
  return node in copy.steps ? copy.steps[node as keyof typeof copy.steps] : copy.steps.other;
}

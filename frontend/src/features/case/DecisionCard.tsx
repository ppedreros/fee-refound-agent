import { useId, useState } from "react";

import type { Action, CaseView } from "../../api/client";
import { copy } from "../../copy/en";
import { formatDateTime, formatMoney } from "../../lib/format";
import { cardButtons, type CardButton } from "./cardButtons";
import { StatusDot } from "../queue/Queue";

export interface CardProps {
  view: CaseView;
  running: boolean;
  runError?: string | null;
  onRun: (feeTxnId?: number) => void;
  onDecide: (action: Action) => void;
}

const PRIMARY =
  "rounded-md bg-navy px-4 py-2 font-medium text-white transition-opacity duration-150 disabled:opacity-60";
const SECONDARY =
  "rounded-md px-3 py-2 font-medium text-navy underline-offset-4 hover:underline disabled:opacity-60";

export function DecisionCard({ view, running, runError, onRun, onDecide }: CardProps) {
  const titleId = useId();
  const { primary, secondary } = cardButtons(view);
  const amount = view.status === "done" ? null : view.recommendation.amount;
  const press = (button: CardButton) => {
    if (button.run) onRun(undefined);
    else onDecide(button.action);
  };

  return (
    <section
      aria-labelledby={titleId}
      className="rounded-lg bg-white p-5 shadow-sm ring-1 ring-grey-200"
    >
      <div aria-live="polite" className="flex items-center gap-2">
        <StatusDot status={view.status} />
        <h3 id={titleId} className="font-serif text-xl">
          {copy.status[view.status]}
        </h3>
        {amount !== null && (
          <span className="ml-auto text-lg tabular-nums">{formatMoney(amount)}</span>
        )}
      </div>

      <div className="mt-2 space-y-2 text-grey-800">
        <CardBody view={view} />
      </div>
      {view.notes.map((note) => (
        <p key={note.message} className="mt-2 text-sm text-grey-600">
          {note.message}
        </p>
      ))}

      {view.can_pick_fee && <FeePicker view={view} disabled={running} onRun={onRun} />}
      {runError && (
        <p role="alert" className="mt-3 text-sm text-error">
          {runError}
        </p>
      )}

      {(primary !== null || secondary.length > 0) && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          {primary !== null && (
            <button
              type="button"
              disabled={primary.run && running}
              onClick={() => {
                press(primary);
              }}
              className={view.can_pick_fee ? SECONDARY : PRIMARY}
            >
              {primary.label}
            </button>
          )}
          {secondary.map((button) => (
            <button
              key={button.label}
              type="button"
              disabled={button.run && running}
              onClick={() => {
                press(button);
              }}
              className={SECONDARY}
            >
              {button.label}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function CardBody({ view }: { view: CaseView }) {
  switch (view.status) {
    case "not_checked":
      return <p>{copy.card.notChecked}</p>;
    case "checking":
      return (
        <>
          <div className="h-0.5 overflow-hidden rounded bg-grey-100">
            <div className="h-full w-1/3 animate-pulse bg-terracotta motion-reduce:animate-none" />
          </div>
          <p>{copy.card.checking}</p>
        </>
      );
    case "ready_to_refund":
      return view.summary ? <p>{view.summary}</p> : null;
    case "recommend_no_refund":
      return (
        <>
          {view.summary && <p>{view.summary}</p>}
          {view.clause && (
            <blockquote className="border-l-2 border-grey-300 pl-3 font-serif text-grey-700">
              {view.clause.text}
            </blockquote>
          )}
        </>
      );
    case "needs_supervisor":
      return (
        <>
          {view.summary && <p>{view.summary}</p>}
          <p>{copy.card.supervisor}</p>
        </>
      );
    case "needs_your_call":
      return (
        <>
          <ul className="space-y-2">
            {view.reasons.map((reason) => (
              <li key={reason.message}>
                <p>{reason.message}</p>
                {reason.next_step && (
                  <p className="text-sm font-medium text-grey-700">{reason.next_step}</p>
                )}
              </li>
            ))}
          </ul>
          {view.recommendation.action !== "none" && (
            <p className="text-grey-700">
              {view.recommendation.action === "refund"
                ? copy.card.wouldRefund(formatMoney(view.recommendation.amount ?? "0"))
                : copy.card.wouldNotRefund}
            </p>
          )}
        </>
      );
    case "not_about_fee":
      return view.topic ? <p>{copy.topic[view.topic]}</p> : null;
    case "done": {
      const decision = view.decision;
      if (decision === null) return null;
      const what =
        decision.refunded && decision.amount !== null
          ? copy.card.refundedAndReplied(formatMoney(decision.amount))
          : copy.card.repliedWithoutRefund;
      return <p>{copy.card.decidedBy(what, decision.by, formatDateTime(decision.at))}</p>;
    }
  }
}

function FeePicker({
  view,
  disabled,
  onRun,
}: {
  view: CaseView;
  disabled: boolean;
  onRun: (feeTxnId?: number) => void;
}) {
  const [picked, setPicked] = useState<number | null>(null);
  const name = useId();
  return (
    <div className="mt-4 space-y-3">
      <div role="radiogroup" aria-label={copy.card.pickFee} className="space-y-1">
        {view.candidates.map((candidate) => (
          <label
            key={candidate.fee_txn_id}
            className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 hover:bg-grey-50"
          >
            <input
              type="radio"
              name={name}
              value={candidate.fee_txn_id}
              checked={picked === candidate.fee_txn_id}
              onChange={() => {
                setPicked(candidate.fee_txn_id);
              }}
              className="accent-navy"
            />
            <span className="tabular-nums">{candidate.label}</span>
          </label>
        ))}
      </div>
      <button
        type="button"
        disabled={picked === null || disabled}
        onClick={() => {
          if (picked !== null) onRun(picked);
        }}
        className={PRIMARY}
      >
        {copy.actions.checkWithFee}
      </button>
    </div>
  );
}

import { useId, useState } from "react";

import type { CaseView } from "../../api/client";
import { copy } from "../../copy/en";

/** "Pick the fee": one radio row per candidate, each told apart by the payment that caused
 * it, and a button that checks the case again with the fee Luis picked (SPEC-ui). */
export function FeePicker({
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
        className="rounded-md bg-navy px-4 py-2 font-medium text-white transition-opacity duration-150 motion-reduce:transition-none disabled:opacity-60"
      >
        {copy.actions.checkWithFee}
      </button>
    </div>
  );
}

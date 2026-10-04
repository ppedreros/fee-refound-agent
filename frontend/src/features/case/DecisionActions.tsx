import { useId } from "react";

import { copy } from "../../copy/en";
import { REASON_MAX } from "./limits";

interface ConfirmProps {
  label: string; // the same words as the button that opened it: "Don't refund"
  askReason: boolean;
  reason: string;
  canSubmit: boolean;
  busy: boolean;
  onReasonChange: (reason: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}

/** Acting against the recommendation, or replying only: an inline step with a required reason
 * where it applies. The button stays disabled until what Luis wrote will be accepted. */
export function ConfirmDecision({
  label,
  askReason,
  reason,
  canSubmit,
  busy,
  onReasonChange,
  onSubmit,
  onCancel,
}: ConfirmProps) {
  const reasonId = useId();
  return (
    <div className="mt-4 space-y-3">
      {askReason && (
        <div className="space-y-1">
          <label htmlFor={reasonId} className="block text-sm font-medium">
            {copy.reason.label}
          </label>
          <textarea
            id={reasonId}
            value={reason}
            rows={2}
            maxLength={REASON_MAX}
            onChange={(event) => {
              onReasonChange(event.target.value);
            }}
            className="w-full rounded-md border border-grey-300 bg-white p-2"
          />
        </div>
      )}
      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={!canSubmit || busy}
          onClick={onSubmit}
          className="rounded-md bg-navy px-4 py-2 font-medium text-white transition-opacity duration-150 disabled:opacity-60"
        >
          {label}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md px-3 py-2 font-medium text-navy hover:underline"
        >
          {copy.reason.cancel}
        </button>
      </div>
    </div>
  );
}

import { useId } from "react";

import type { CaseView } from "../../api/client";
import { copy } from "../../copy/en";

/** The reply we drafted, with the first name already filled in. Editing comes with the actions. */
export function Reply({ view }: { view: CaseView }) {
  const titleId = useId();
  if (view.draft === null) return null;
  return (
    <section aria-labelledby={titleId} className="space-y-2">
      <div className="flex items-center gap-2 border-b border-grey-200 pb-1">
        <h3 id={titleId} className="font-medium">
          {copy.reply.title}
        </h3>
        {view.language === "es" && (
          <span className="rounded-full bg-clay px-2 py-0.5 text-xs text-grey-700">
            {copy.reply.spanish}
          </span>
        )}
      </div>
      <p className="whitespace-pre-wrap text-grey-800">{view.draft.text}</p>
    </section>
  );
}

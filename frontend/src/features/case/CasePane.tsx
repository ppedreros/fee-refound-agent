import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { ApiError, messageOf, type Action, type CaseView } from "../../api/client";
import { queryKeys, useCase, useRunCase } from "../../api/hooks";
import { ErrorBanner } from "../../components/ErrorBanner";
import { copy } from "../../copy/en";
import { formatShortDate } from "../../lib/format";
import { DecisionCard } from "./DecisionCard";
import { Evidence } from "./Evidence";
import { Reply } from "./Reply";

/** One case: loads it, starts checks and follows them until they finish. */
export function CasePane({ caseId, onBack }: { caseId: number; onBack: () => void }) {
  const query = useCase(caseId);
  const run = useRunCase(caseId);
  useQueueRefreshAfterCheck(query.data);

  if (query.isPending) return <CaseSkeleton />;
  if (query.isError) {
    return (
      <div className="p-6">
        <ErrorBanner message={messageOf(query.error)} onRetry={() => void query.refetch()} />
      </div>
    );
  }
  // A check that is already running is simply followed; any other failure is shown.
  const following = run.error instanceof ApiError && run.error.code === "run_in_progress";
  return (
    <CaseContent
      view={query.data}
      running={run.isPending}
      runError={run.error && !following ? messageOf(run.error) : null}
      onRun={(feeTxnId) => {
        run.mutate(feeTxnId);
      }}
      onDecide={() => undefined}
      onBack={onBack}
    />
  );
}

export interface CaseContentProps {
  view: CaseView;
  running: boolean;
  runError?: string | null;
  onRun: (feeTxnId?: number) => void;
  onDecide: (action: Action) => void;
  onBack?: () => void;
}

export function CaseContent({
  view,
  running,
  runError,
  onRun,
  onDecide,
  onBack,
}: CaseContentProps) {
  const latest = view.conversation.messages.filter((m) => m.author === "member").at(-1);
  const checkAgainInHeader =
    view.can_run && view.status !== "not_checked" && view.status !== "not_about_fee";

  return (
    <article className="mx-auto w-full max-w-3xl space-y-6 p-6 motion-safe:animate-rise">
      {onBack && (
        <button
          type="button"
          onClick={onBack}
          className="text-sm font-medium text-navy underline underline-offset-4 lg:hidden"
        >
          {copy.case.back}
        </button>
      )}
      <header className="space-y-1">
        <div className="flex items-start gap-4">
          <h2 className="min-w-0 font-serif text-2xl">
            {copy.case.title(view.member.name, view.conversation.subject)}
          </h2>
          {checkAgainInHeader && (
            <button
              type="button"
              disabled={running}
              onClick={() => {
                onRun(undefined);
              }}
              className="ml-auto shrink-0 rounded-md px-3 py-1.5 text-sm font-medium text-navy ring-1 ring-grey-300 hover:bg-grey-50 disabled:opacity-60"
            >
              {copy.actions.checkAgain}
            </button>
          )}
        </div>
        {latest && (
          <p className="flex gap-4 text-grey-700">
            <q className="min-w-0 truncate">{latest.body}</q>
            <time dateTime={latest.created_at} className="ml-auto shrink-0 text-sm text-grey-600">
              {formatShortDate(latest.created_at)}
            </time>
          </p>
        )}
        {view.member.accounts.length > 0 && (
          <p className="text-sm text-grey-600">
            {copy.evidence.titled(
              ...view.member.accounts.map((account) =>
                copy.case.account(
                  account.sub_accounts.map((sub) => sub.name).join(", "),
                  account.masked_number,
                ),
              ),
            )}
          </p>
        )}
      </header>

      <DecisionCard
        view={view}
        running={running}
        runError={runError}
        onRun={onRun}
        onDecide={onDecide}
      />
      {view.status !== "done" && <Reply view={view} />}
      <Evidence view={view} />
    </article>
  );
}

/** When a check finishes, the queue's status and amount change too. */
function useQueueRefreshAfterCheck(view: CaseView | undefined) {
  const client = useQueryClient();
  const previous = useRef(view?.status);
  useEffect(() => {
    if (previous.current === "checking" && view?.status !== "checking") {
      void client.invalidateQueries({ queryKey: queryKeys.allCases });
    }
    previous.current = view?.status;
  }, [client, view?.status]);
}

function CaseSkeleton() {
  return (
    <div aria-hidden="true" className="mx-auto w-full max-w-3xl space-y-6 p-6">
      <div className="h-7 w-72 rounded bg-grey-100" />
      <div className="h-4 w-96 rounded bg-grey-100" />
      <div className="h-40 rounded-lg bg-grey-100" />
      <div className="h-24 rounded bg-grey-100" />
    </div>
  );
}

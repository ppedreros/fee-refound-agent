import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  messageOf,
  type Action,
  type CaseView,
  type DecisionRequest,
} from "../../api/client";
import { queryKeys, useCase, useCases, useRunCase } from "../../api/hooks";
import { ErrorBanner } from "../../components/ErrorBanner";
import { copy } from "../../copy/en";
import { formatShortDate } from "../../lib/format";
import { cardButtons } from "./cardButtons";
import { ConfirmDecision } from "./DecisionActions";
import { DecisionCard } from "./DecisionCard";
import { Evidence } from "./Evidence";
import { reasonIsValid, replyIsValid } from "./limits";
import { ReplyEditor } from "./ReplyEditor";
import { useDecision } from "./useDecision";

interface CasePaneProps {
  caseId: number;
  onBack: () => void;
  onNext: (id: number) => void;
}

/** One case: loads it, starts checks and follows them, and sends Luis's decision. */
export function CasePane({ caseId, onBack, onNext }: CasePaneProps) {
  const query = useCase(caseId);
  const run = useRunCase(caseId);
  const decision = useDecision(caseId);
  const open = useCases("open");
  const [decided, setDecided] = useState(false);
  useQueueRefreshAfterCheck(query.data);

  if (query.isPending) return <CaseSkeleton />;
  if (query.isError) {
    return (
      <div className="p-6">
        <ErrorBanner message={messageOf(query.error)} onRetry={() => void query.refetch()} />
      </div>
    );
  }
  const view = query.data;
  // A check that is already running is simply followed; any other failure is shown.
  const following = run.error instanceof ApiError && run.error.code === "run_in_progress";
  const nextId = open.data?.items.find((item) => item.id !== caseId)?.id;
  return (
    <CaseContent
      key={view.run?.run_id ?? "unchecked"} // a new check starts a new decision
      view={view}
      running={run.isPending}
      runError={run.error && !following ? messageOf(run.error) : null}
      onRun={(feeTxnId) => {
        run.mutate(feeTxnId);
      }}
      deciding={decision.isPending}
      decideError={decision.error ? messageOf(decision.error) : null}
      onSubmit={(body) => {
        decision.mutate(body, {
          onSuccess: () => {
            setDecided(true);
          },
        });
      }}
      focusTitle={decided}
      onNext={
        view.status === "done" && nextId !== undefined
          ? () => {
              onNext(nextId);
            }
          : null
      }
      onBack={onBack}
    />
  );
}

export interface CaseContentProps {
  view: CaseView;
  running: boolean;
  runError?: string | null;
  onRun: (feeTxnId?: number) => void;
  deciding?: boolean;
  decideError?: string | null;
  onSubmit?: (decision: DecisionRequest) => void;
  focusTitle?: boolean;
  onNext?: (() => void) | null;
  onBack?: () => void;
}

/** "follow" sends what we recommend (approve, or edit with Luis's text). "reject" and
 * "reply_only" first ask for Luis's own reply, and for "reject" a reason. */
type Mode = "follow" | "reject" | "reply_only";

export function CaseContent({
  view,
  running,
  runError,
  onRun,
  deciding = false,
  decideError,
  onSubmit,
  focusTitle = false,
  onNext,
  onBack,
}: CaseContentProps) {
  const draft = view.draft?.text ?? "";
  const [mode, setMode] = useState<Mode>("follow");
  const [reply, setReply] = useState(draft);
  const [editing, setEditing] = useState(view.draft === null);
  const [reason, setReason] = useState("");
  const titleRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (focusTitle && view.status === "done") titleRef.current?.focus();
  }, [focusTitle, view.status]);

  const { primary, secondary } = cardButtons(view);
  const followsPrimary = primary !== null && !primary.run;
  const latest = view.conversation.messages.filter((m) => m.author === "member").at(-1);
  const checkAgainInHeader =
    view.can_run && view.status !== "not_checked" && view.status !== "not_about_fee";

  const submit = (action: Action) => {
    if (view.run === null || onSubmit === undefined) return;
    onSubmit({
      run_id: view.run.run_id,
      action,
      reply_text: reply,
      reason: action === "reject" ? reason : null,
    });
  };
  const decide = (action: Action) => {
    if (action === "approve" || action === "edit") {
      submit(view.actions.includes("approve") && reply === draft ? "approve" : "edit");
    } else if (followsPrimary && primary.action === action) {
      submit(action); // "Send reply" with no recommendation to follow
    } else {
      setMode(action === "reject" ? "reject" : "reply_only");
      setReply(""); // our draft says the opposite, so Luis writes this reply
      setEditing(true);
      setReason("");
    }
  };
  const cancel = () => {
    setMode("follow");
    setReply(draft);
    setEditing(view.draft === null);
    setReason("");
  };

  const confirming =
    mode === "follow" ? undefined : secondary.find((b) => !b.run && b.action === mode);
  const footer = confirming && (
    <ConfirmDecision
      label={confirming.label}
      askReason={mode === "reject"}
      reason={reason}
      canSubmit={replyIsValid(reply) && (mode !== "reject" || reasonIsValid(reason))}
      busy={deciding}
      onReasonChange={setReason}
      onSubmit={() => {
        submit(mode === "reject" ? "reject" : "reply_only");
      }}
      onCancel={cancel}
    />
  );

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
        onDecide={decide}
        busy={deciding}
        primaryDisabled={!replyIsValid(reply)}
        decideError={decideError}
        footer={footer}
        titleRef={titleRef}
        onNext={onNext}
      />
      {(followsPrimary || mode !== "follow") && (
        <ReplyEditor
          text={reply}
          editing={editing}
          spanish={view.language === "es"}
          canEdit={mode === "follow" && view.actions.includes("edit")}
          changed={mode === "follow" && view.draft !== null && reply !== draft}
          onEdit={() => {
            setEditing(true);
          }}
          onChange={setReply}
          onUndo={() => {
            setReply(draft);
          }}
        />
      )}
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

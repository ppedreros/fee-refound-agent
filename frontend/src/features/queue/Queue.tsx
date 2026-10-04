import type { KeyboardEvent } from "react";

import { messageOf, type CaseStatus, type QueueItem, type View } from "../../api/client";
import { useCases } from "../../api/hooks";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Bone, Skeleton } from "../../components/Skeleton";
import { copy } from "../../copy/en";
import { formatMoney, formatReceived } from "../../lib/format";

interface QueueProps {
  view: View;
  selectedId: number | null;
  onViewChange: (view: View) => void;
  onSelect: (id: number) => void;
}

const VIEWS: View[] = ["open", "done"];

export function Queue({ view, selectedId, onViewChange, onSelect }: QueueProps) {
  const cases = useCases(view);
  const now = new Date();

  return (
    <div className="flex flex-col text-sm">
      <div role="tablist" aria-label={copy.queue.tabsLabel} className="flex gap-4 px-4 pt-3">
        {VIEWS.map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={tab === view}
            onClick={() => {
              onViewChange(tab);
            }}
            className={`border-b-2 pb-2 font-medium transition-colors duration-150 motion-reduce:transition-none ${
              tab === view ? "border-navy text-navy" : "border-transparent text-grey-600"
            }`}
          >
            {copy.queue.tabs[tab]}
          </button>
        ))}
      </div>
      <div className="border-t border-grey-200">
        {cases.isPending ? (
          <QueueSkeleton />
        ) : cases.isError ? (
          <div className="m-4">
            <ErrorBanner message={messageOf(cases.error)} onRetry={() => void cases.refetch()} />
          </div>
        ) : cases.data.items.length === 0 ? (
          <p className="p-6 text-grey-600">{copy.queue.empty}</p>
        ) : (
          <ul onKeyDown={moveFocus}>
            {cases.data.items.map((item) => (
              <QueueRow
                key={item.id}
                item={item}
                now={now}
                selected={item.id === selectedId}
                onSelect={onSelect}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function QueueRow({
  item,
  now,
  selected,
  onSelect,
}: {
  item: QueueItem;
  now: Date;
  selected: boolean;
  onSelect: (id: number) => void;
}) {
  return (
    <li className="border-b border-grey-200">
      <button
        type="button"
        data-queue-item
        aria-current={selected ? "true" : undefined}
        onClick={() => {
          onSelect(item.id);
        }}
        className={`relative block w-full px-4 py-3 text-left transition-colors duration-150 motion-reduce:transition-none ${
          selected
            ? "bg-white before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-terracotta"
            : "hover:bg-grey-50"
        }`}
      >
        <span className="flex items-center gap-2">
          <StatusDot status={item.status} />
          <span className="font-medium">{item.member_name}</span>
          {item.amount !== null && (
            <span className="ml-auto tabular-nums">{formatMoney(item.amount)}</span>
          )}
        </span>
        <span className="mt-0.5 block truncate text-grey-700">
          {item.topic !== null ? copy.topic[item.topic] : item.subject}
        </span>
        <span className="mt-0.5 flex justify-between gap-2 text-grey-600">
          <span>{copy.status[item.status]}</span>
          <time dateTime={item.received_at}>{formatReceived(item.received_at, now)}</time>
        </span>
      </button>
    </li>
  );
}

const DOT: Record<CaseStatus, string> = {
  not_checked: "border border-grey-400",
  checking: "bg-grey-400 animate-pulse motion-reduce:animate-none",
  ready_to_refund: "bg-success",
  recommend_no_refund: "bg-navy",
  needs_supervisor: "bg-terracotta",
  needs_your_call: "bg-terracotta",
  not_about_fee: "bg-grey-400",
  done: "bg-success",
};

export function StatusDot({ status }: { status: CaseStatus }) {
  return <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${DOT[status]}`} />;
}

function QueueSkeleton() {
  return (
    <Skeleton>
      {[0, 1, 2].map((row) => (
        <div key={row} className="space-y-2 border-b border-grey-200 px-4 py-3">
          <Bone className="h-3 w-24" />
          <Bone className="h-3 w-40" />
        </div>
      ))}
    </Skeleton>
  );
}

/** ↑/↓ or j/k move focus through the queue; Enter opens the focused case (it is a button). */
function moveFocus(event: KeyboardEvent<HTMLUListElement>) {
  const step = { ArrowDown: 1, j: 1, ArrowUp: -1, k: -1 }[event.key];
  if (step === undefined) return;
  const items = [...event.currentTarget.querySelectorAll<HTMLElement>("[data-queue-item]")];
  const current = items.findIndex((item) => item === document.activeElement);
  const next = items[Math.min(items.length - 1, Math.max(0, current + step))];
  event.preventDefault();
  next?.focus();
}

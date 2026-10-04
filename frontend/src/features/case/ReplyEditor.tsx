import { useId } from "react";

import { copy } from "../../copy/en";

interface ReplyEditorProps {
  text: string;
  editing: boolean;
  spanish: boolean;
  canEdit: boolean; // "Edit" is offered while the reply follows the recommendation
  changed: boolean; // the text differs from our draft, so "Undo my changes" can restore it
  onEdit: () => void;
  onChange: (text: string) => void;
  onUndo: () => void;
}

/** The reply: our draft with the first name filled in, or the text Luis writes. */
export function ReplyEditor({
  text,
  editing,
  spanish,
  canEdit,
  changed,
  onEdit,
  onChange,
  onUndo,
}: ReplyEditorProps) {
  const titleId = useId();
  const counterId = useId();
  return (
    <section aria-labelledby={titleId} className="space-y-2">
      <div className="flex items-center gap-2 border-b border-grey-200 pb-1">
        <h3 id={titleId} className="font-medium">
          {copy.reply.title}
        </h3>
        {spanish && (
          <span className="rounded-full bg-clay px-2 py-0.5 text-xs text-grey-700">
            {copy.reply.spanish}
          </span>
        )}
        <span className="ml-auto flex gap-3 text-sm">
          {editing && changed && (
            <button
              type="button"
              onClick={onUndo}
              className="font-medium text-navy hover:underline"
            >
              {copy.reply.undo}
            </button>
          )}
          {!editing && canEdit && (
            <button
              type="button"
              onClick={onEdit}
              className="font-medium text-navy hover:underline"
            >
              {copy.reply.edit}
            </button>
          )}
        </span>
      </div>
      {editing ? (
        <>
          <textarea
            aria-labelledby={titleId}
            aria-describedby={counterId}
            value={text}
            rows={8}
            onChange={(event) => {
              onChange(event.target.value);
            }}
            className="w-full resize-y rounded-md border border-grey-300 bg-white p-3 text-grey-800"
          />
          <p id={counterId} className="text-right text-xs tabular-nums text-grey-600">
            {copy.reply.counter(text.trim().length)}
          </p>
        </>
      ) : (
        <p className="whitespace-pre-wrap text-grey-800">{text}</p>
      )}
    </section>
  );
}

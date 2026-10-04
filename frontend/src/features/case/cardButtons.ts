import type { Action, CaseView } from "../../api/client";
import { copy } from "../../copy/en";
import { formatMoney } from "../../lib/format";

export type CardButton =
  { label: string; run: true } | { label: string; run: false; action: Action };

/** The card's buttons, from the API's `actions`, `can_run` and status only (SPEC-ui). `edit` is
 * not a button of its own: editing the reply turns the primary action into `edit` (T25). */
export function cardButtons(view: CaseView): {
  primary: CardButton | null;
  secondary: CardButton[];
} {
  const run = (label: string): CardButton => ({ label, run: true });
  if (view.status === "not_checked") {
    return { primary: view.can_run ? run(copy.actions.checkCase) : null, secondary: [] };
  }
  if (view.status === "not_about_fee") {
    return { primary: null, secondary: view.can_run ? [run(copy.actions.checkAgain)] : [] };
  }

  const recommendation = view.recommendation.action;
  const amount = formatMoney(view.recommendation.amount ?? "0");
  const decide = (action: Action): CardButton => {
    const labels: Record<Action, string> = {
      approve:
        recommendation === "refund" ? copy.actions.refundAndReply(amount) : copy.actions.sendReply,
      edit:
        recommendation === "refund" ? copy.actions.refundAndReply(amount) : copy.actions.sendReply,
      reject: recommendation === "refund" ? copy.actions.dontRefund : copy.actions.refundAnyway,
      reply_only:
        view.status === "needs_supervisor" ? copy.actions.replyOnly : copy.actions.sendReply,
    };
    return { label: labels[action], run: false, action };
  };

  const { actions } = view;
  const primary: Action | null = actions.includes("approve")
    ? "approve"
    : actions.includes("edit")
      ? "edit"
      : view.status !== "needs_supervisor" && actions.includes("reply_only")
        ? "reply_only"
        : null;
  return {
    primary: primary === null ? null : decide(primary),
    secondary: actions.filter((a) => a !== primary && a !== "edit").map(decide),
  };
}

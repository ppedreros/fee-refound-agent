import { copy } from "../../copy/en";

/** A step's plain label (SPEC-ui, "Step labels"). The three reads run side by side, so they share
 * one label: "Looking at accounts and transactions". */
export function stepLabel(node: string): string {
  if (node.startsWith("load_") && node !== "load_conversation") return copy.steps.load;
  return node in copy.steps ? copy.steps[node as keyof typeof copy.steps] : copy.steps.other;
}

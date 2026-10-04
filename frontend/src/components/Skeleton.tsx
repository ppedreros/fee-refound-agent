import type { ReactNode } from "react";

import { copy } from "../copy/en";

/** Loading: grey blocks shaped like what is coming, never a spinner. Screen readers hear one
 * "Loading…" instead of the blocks. */
export function Skeleton({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div role="status" className={className}>
      <span className="sr-only">{copy.loading}</span>
      <div aria-hidden="true">{children}</div>
    </div>
  );
}

/** One block; it breathes gently, unless Luis asked for reduced motion. */
export function Bone({ className }: { className: string }) {
  return <div className={`rounded bg-grey-200 motion-safe:animate-pulse ${className}`} />;
}

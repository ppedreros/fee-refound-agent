import { useId } from "react";

import { useHealth } from "../api/hooks";
import { copy } from "../copy/en";

/** The app title, and a discreet note when a model answers from recordings (D10). */
export function Header() {
  const health = useHealth();
  const descriptionId = useId();
  const replay =
    health.data !== undefined && Object.values(health.data.provider_mode).includes("replay");

  return (
    <header className="flex h-14 items-center border-b border-grey-200 bg-white px-6">
      <h1 className="font-serif text-lg">{copy.app.title}</h1>
      {replay && (
        <p
          title={copy.app.replayTooltip}
          aria-describedby={descriptionId}
          className="ml-auto flex items-center gap-2 text-sm text-grey-600"
        >
          <span aria-hidden="true" className="size-2 rounded-full bg-terracotta" />
          {copy.app.replay}
          <span id={descriptionId} hidden>
            {copy.app.replayTooltip}
          </span>
        </p>
      )}
    </header>
  );
}

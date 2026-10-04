// The page's state lives in the URL (`?view=open&case=5012`), so refreshing or sharing the link
// restores it. No router: one search string, read with useSyncExternalStore.
import { useCallback, useSyncExternalStore } from "react";

import type { View } from "../api/client";

export interface UrlState {
  view: View;
  caseId: number | null;
}

const CHANGE = "urlstatechange";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(CHANGE, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(CHANGE, onChange);
  };
}

function search(): string {
  return window.location.search;
}

export function parseUrlState(query: string): UrlState {
  const params = new URLSearchParams(query);
  const id = Number(params.get("case"));
  return {
    view: params.get("view") === "done" ? "done" : "open",
    caseId: Number.isInteger(id) && id > 0 ? id : null,
  };
}

export function useUrlState(): [UrlState, (next: UrlState) => void] {
  const query = useSyncExternalStore(subscribe, search);
  const navigate = useCallback((next: UrlState) => {
    const params = new URLSearchParams({ view: next.view });
    if (next.caseId !== null) params.set("case", String(next.caseId));
    window.history.pushState(null, "", `?${params.toString()}`);
    window.dispatchEvent(new Event(CHANGE));
  }, []);
  return [parseUrlState(query), navigate];
}

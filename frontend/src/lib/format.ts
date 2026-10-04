// Money and times the way Luis reads them. Amounts arrive from the API as decimal strings.
import { copy } from "../copy/en";

const WHOLE = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const CENTS = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const DAY = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });

/** "$35" for whole dollars, "$35.50" otherwise, "−$35" below zero. */
export function formatMoney(amount: string): string {
  const value = Number(amount);
  const absolute = Math.abs(value);
  const text = Number.isInteger(absolute) ? WHOLE.format(absolute) : CENTS.format(absolute);
  return `${value < 0 ? "−" : ""}$${text}`;
}

/** "Sep 15", or how long ago when it was today: "2 h ago", "15 min ago", "Just now". */
export function formatReceived(iso: string, now: Date): string {
  const at = new Date(iso);
  if (at.toDateString() !== now.toDateString()) return DAY.format(at);
  const minutes = Math.max(0, Math.floor((now.getTime() - at.getTime()) / 60_000));
  if (minutes < 1) return copy.time.justNow;
  if (minutes < 60) return copy.time.minutesAgo(minutes);
  return copy.time.hoursAgo(Math.floor(minutes / 60));
}

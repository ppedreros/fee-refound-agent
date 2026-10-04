// Money, dates and times the way Luis reads them. Amounts arrive from the API as decimal strings.
import { copy } from "../copy/en";

const WHOLE = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const CENTS = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const SMALL = new Intl.NumberFormat("en-US", { maximumSignificantDigits: 2 });
const DAY = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const DAY_YEAR = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
});
const DAY_TIME = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** "$35" for whole dollars, "$35.50" otherwise, "−$35" below zero. */
export function formatMoney(amount: string): string {
  const value = Number(amount);
  const absolute = Math.abs(value);
  const text = Number.isInteger(absolute) ? WHOLE.format(absolute) : CENTS.format(absolute);
  return `${value < 0 ? "−" : ""}$${text}`;
}

/** What a check cost, which is often a fraction of a cent: "$0.004", "$0.000032". */
export function formatCost(usd: string): string {
  return `$${SMALL.format(Number(usd))}`;
}

/** "0.5 s", "2.8 s". */
export function formatDuration(ms: number): string {
  return `${(ms / 1000).toFixed(1)} s`;
}

/** One step's time: "306 ms" below a second, so the fast steps still show theirs; "1.2 s" above. */
export function formatLatency(ms: number): string {
  return ms < 1000 ? `${String(ms)} ms` : formatDuration(ms);
}

/** A calendar date from the API ("2026-09-14"), read as that day wherever Luis is. */
function calendarDay(iso: string): Date {
  const [year = 0, month = 1, day = 1] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
}

/** "Sep 14". */
export function formatDay(iso: string): string {
  return DAY.format(calendarDay(iso));
}

/** "Sep 15, 2025". */
export function formatDayWithYear(iso: string): string {
  return DAY_YEAR.format(calendarDay(iso));
}

/** "Sep 15", from a timestamp. */
export function formatShortDate(iso: string): string {
  return DAY.format(new Date(iso));
}

/** "Oct 3, 10:42". */
export function formatDateTime(iso: string): string {
  return DAY_TIME.format(new Date(iso));
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

// What the decision endpoint accepts (SPEC-api, "Validation"), so buttons enable only when it will.
export const REPLY_MAX = 2000;
export const REASON_MIN = 10;
export const REASON_MAX = 500;

export function replyIsValid(reply: string): boolean {
  const length = reply.trim().length;
  return length >= 1 && length <= REPLY_MAX;
}

export function reasonIsValid(reason: string): boolean {
  const length = reason.trim().length;
  return length >= REASON_MIN && length <= REASON_MAX;
}

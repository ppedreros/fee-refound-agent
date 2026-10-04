import { describe, expect, it } from "vitest";

import { formatCost, formatLatency, formatMoney } from "./format";

describe("format", () => {
  it.each([
    ["35.00", "$35"],
    ["35.50", "$35.50"],
    ["1360.00", "$1,360"],
    ["-60.00", "\u2212$60"],
  ])("money %s reads %s", (amount, text) => {
    expect(formatMoney(amount)).toBe(text);
  });

  it.each([
    [0, "0 ms"],
    [306, "306 ms"],
    [1234, "1.2 s"],
  ])("a step of %i ms reads %s, so a fast step still shows its time", (ms, text) => {
    expect(formatLatency(ms)).toBe(text);
  });

  it("shows what a check cost, even a fraction of a cent", () => {
    expect(formatCost("0.000032")).toBe("$0.000032");
    expect(formatCost("0.004")).toBe("$0.004");
  });
});

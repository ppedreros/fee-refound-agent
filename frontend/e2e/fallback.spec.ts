import { expect, test } from "@playwright/test";

// Scenario 18: Ana's pattern for another member, whose model answers are never recorded, so in
// replay mode both classifiers miss and the case falls back to Luis with its evidence.
test("with no classifier answer, Luis still gets the case and its evidence", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Liam N\./ }).click();
  await page.getByRole("button", { name: "Check this case" }).click();

  await expect(page.getByRole("heading", { name: "Needs your call" })).toBeVisible();
  await expect(page.getByText("The automatic check isn't available right now.")).toBeVisible();
  await expect(page.getByRole("button", { name: /^What happened on/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Account standing/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Refunds in the last 12 months/ })).toBeVisible();
});

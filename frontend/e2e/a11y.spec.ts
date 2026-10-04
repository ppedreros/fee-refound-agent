import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/** axe's serious and critical findings on the page as it is now (SPEC-delivery: none allowed). */
async function seriousProblems(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => `${violation.id}: ${violation.help}`);
}

test("the queue", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: /Ana T\./ })).toBeVisible();

  expect(await seriousProblems(page)).toEqual([]);
});

test("Ana's case, as it opens", async ({ page }) => {
  await page.goto("/?view=open&case=5012");
  await expect(page.getByRole("heading", { name: "Not checked yet" })).toBeVisible();

  expect(await seriousProblems(page)).toEqual([]);
});

test("a checked case, with its reply and every evidence section open", async ({ page }) => {
  await page.goto("/?view=open&case=5113"); // scenario 13: ready to refund, a reply in Spanish
  await page.getByRole("button", { name: "Check this case" }).click();
  await expect(page.getByRole("heading", { name: "Ready to refund" })).toBeVisible();
  const closed = page.locator("button[aria-expanded=false]");
  for (let opened = 0; opened < 10 && (await closed.count()) > 0; opened++) {
    await closed.first().click();
  }

  expect(await seriousProblems(page)).toEqual([]);
});

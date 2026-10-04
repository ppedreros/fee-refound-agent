import { expect, test } from "@playwright/test";

// The step labels Luis reads, in the order the graph runs them (SPEC-ui, "Step labels").
const STEPS = [
  "Reading the conversation",
  "Understanding the message",
  "Looking at accounts and transactions",
  "Finding the fee",
  "Checking the rules",
  "Making a recommendation",
  "Finding the policy that applies",
  "Writing a reply",
];

test("Luis checks Ana's case and approves her refund, once", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Ana T\./ }).click();
  await page.getByRole("button", { name: "Check this case" }).click();

  await expect(page.getByRole("heading", { name: "Ready to refund" })).toBeVisible();
  // In replay a check takes about a second, so the order is read from the steps the page keeps
  // under "How this was prepared", which the same step events fill.
  const prepared = page.getByRole("button", { name: /^How this was prepared/ });
  await prepared.click();
  const section = page.locator(`[id="${(await prepared.getAttribute("aria-controls")) ?? ""}"]`);
  const labels = await section.locator("li > span:first-child").allTextContents();
  expect(labels.filter((label) => STEPS.includes(label))).toEqual(STEPS);

  const approve = page.getByRole("button", { name: "Refund $35 and send reply" });
  await approve.click();

  await expect(page.getByRole("heading", { name: "Done" })).toBeVisible();
  await expect(page.getByText(/^Refunded \$35 and replied/)).toBeVisible();
  await expect(approve).toHaveCount(0); // no second click: the button is gone
});

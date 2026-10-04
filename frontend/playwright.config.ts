import { defineConfig, devices } from "@playwright/test";

// End-to-end tests against the compose stack in replay mode (SPEC-delivery, "End-to-end tests").
// `npm run e2e` with the stack up: `PROVIDER_MODE=replay docker compose up -d --build`.
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  // One database: the specs check and decide cases, so they run one at a time.
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Locally the installed Chrome (no browser download); CI installs Playwright's Chromium.
        ...(process.env.CI ? {} : { channel: "chrome" }),
      },
    },
  ],
});

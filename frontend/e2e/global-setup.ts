import { execSync } from "node:child_process";
import path from "node:path";

import type { FullConfig } from "@playwright/test";

const repo = path.resolve(import.meta.dirname, "..", "..");

interface Health {
  provider_mode: Record<string, string>;
}

/** The demo state, then a check that the stack answers in replay mode: these tests must never
 * spend tokens, and recorded answers make them repeatable. */
export default async function globalSetup(config: FullConfig) {
  // The owner role, through the migrate job: it resets the brief's tables too.
  execSync("docker compose run --rm migrate python -m backend.bootstrap --reset", {
    cwd: repo,
    stdio: "ignore",
  });
  const baseURL = config.projects[0]?.use.baseURL ?? "http://localhost:8080";
  const health = (await (await fetch(`${baseURL}/api/health`)).json()) as Health;
  const modes = Object.values(health.provider_mode);
  if (modes.length === 0 || modes.some((mode) => mode !== "replay")) {
    throw new Error(
      "The end-to-end tests run in replay mode: PROVIDER_MODE=replay docker compose up -d backend",
    );
  }
}

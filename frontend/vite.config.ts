import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // In development the API is the local backend, under /api as in the container (nginx).
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    include: ["src/**/*.test.{ts,tsx}"], // e2e/ is Playwright's (npm run e2e)
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});

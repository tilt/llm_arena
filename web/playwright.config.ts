import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests/browser",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  webServer: [
    { command: "node tests/browser/server.mjs", url: "http://127.0.0.1:4174/", reuseExistingServer: false },
    // The built site (run `make web` first) for the claim end-to-end test.
    { command: "node tests/browser/dist-server.mjs", url: "http://127.0.0.1:4175/", reuseExistingServer: false },
  ],
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});

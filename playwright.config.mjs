import { defineConfig } from "@playwright/test";

const baseURL = process.env.VIBESTACK_BASE_URL || "http://127.0.0.1:18080";

export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL,
    serviceWorkers: "allow",
    // An authenticated trace can contain session cookies and credentials.
    trace: process.env.VIBESTACK_BROWSER_CREDENTIAL_FILE ? "off" : "retain-on-failure",
    screenshot: "only-on-failure"
  },
  projects: [
    {
      name: "desktop-chromium",
      use: { browserName: "chromium", viewport: { width: 1440, height: 900 } }
    },
    {
      name: "ipad-sized-chromium",
      use: {
        browserName: "chromium",
        hasTouch: true,
        isMobile: true,
        viewport: { width: 1024, height: 1366 }
      }
    }
  ]
});

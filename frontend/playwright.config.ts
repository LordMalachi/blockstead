import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:5173", trace: "retain-on-failure" },
  webServer: [
    {
      command: "cd .. && BLOCKSTEAD_DATA_DIR=$(mktemp -d /tmp/blockstead-e2e.XXXXXX) BLOCKSTEAD_SERVER_ROOT=./fixtures/servers .venv/bin/uvicorn blockstead.app:app --app-dir backend/src --host 127.0.0.1 --port 8765",
      url: "http://127.0.0.1:8765/api/v1/health",
      reuseExistingServer: false,
    },
    { command: "npm run dev", url: "http://127.0.0.1:5173", reuseExistingServer: false },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});

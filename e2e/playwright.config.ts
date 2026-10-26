import { defineConfig, devices } from "@playwright/test";

// Runs against scripts/dev_stack.py: the real API and worker (real ffmpeg and
// rubberband), the built UI, a fake MeTube, and the two webm fixtures. Tests
// share one stack and reset it, so they run one at a time.
const port = Number(process.env.E2E_PORT ?? 8089);
const python = process.env.PYTHON ?? "python3";

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    viewport: { width: 1400, height: 900 },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1400, height: 900 },
        launchOptions: { args: ["--autoplay-policy=no-user-gesture-required"] } },
    },
  ],
  webServer: {
    command: `${python} ../scripts/dev_stack.py --port ${port} --root /tmp/songbook-e2e`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});

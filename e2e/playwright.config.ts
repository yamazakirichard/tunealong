import { defineConfig, devices } from "@playwright/test";

// Default: runs against scripts/dev_stack.py (the real API and worker with real
// ffmpeg and rubberband, the built UI, a fake MeTube, the two webm fixtures).
// Tests share one stack and reset it, so they run one at a time.
//
// With E2E_BASE_URL set (scripts/compose_test.sh), only the smoke spec runs,
// against already-running containers, with no dev-only reset hook.
const port = Number(process.env.E2E_PORT ?? 8089);
const python = process.env.PYTHON ?? "python3";
const external = process.env.E2E_BASE_URL;

export default defineConfig({
  testDir: "./tests",
  ...(external ? { testMatch: "smoke.spec.ts" } : { testIgnore: "smoke.spec.ts" }),
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: external ?? `http://127.0.0.1:${port}`,
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
  webServer: external ? undefined : {
    command: `${python} ../scripts/dev_stack.py --port ${port} --root /tmp/songbook-e2e`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});

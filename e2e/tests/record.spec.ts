import { expect, type Page, test } from "@playwright/test";

import { card, jobs, reset, sb } from "./helpers";

// Headless Chromium has no share dialog, so getDisplayMedia is replaced with a
// synthetic "tab": an animated canvas plus a 440 Hz tone. Everything after it
// (MediaRecorder, Stop, upload, the server's remux, playback) is the real thing.
async function fakeTabShare(page: Page, { audio = true } = {}) {
  await page.addInitScript((withAudio) => {
    navigator.mediaDevices.getDisplayMedia = async () => {
      const canvas = Object.assign(document.createElement("canvas"), { width: 320, height: 180 });
      const g = canvas.getContext("2d")!;
      let n = 0;
      setInterval(() => {
        g.fillStyle = `hsl(${(n += 7) % 360} 70% 50%)`;
        g.fillRect(0, 0, 320, 180);
      }, 33);
      const stream = canvas.captureStream(30);
      if (withAudio) {
        const ctx = new AudioContext();
        const osc = ctx.createOscillator();
        const dest = ctx.createMediaStreamDestination();
        osc.connect(dest);
        osc.start();
        stream.addTrack(dest.stream.getAudioTracks()[0]);
      }
      (window as any).__fakeShare = stream;
      return stream;
    };
  }, audio);
}

async function openRecorder(page: Page) {
  await page.goto("./");
  await page.getByRole("button", { name: "Add song" }).click();
  await page.getByRole("radio", { name: "Record a tab" }).click();
}

test.beforeEach(async ({ request }) => reset(request));

test("Record, Stop, Add: the recording becomes a seekable local video song", async ({ page, request }) => {
  await fakeTabShare(page);
  await openRecorder(page);
  await page.getByRole("button", { name: "Record" }).click();
  await expect(page.getByTestId("record-timer")).toContainText("Recording 0:0");
  // Add waits for Stop; the source switch is locked while recording.
  await expect(page.getByRole("button", { name: "Add", exact: true })).toBeDisabled();
  await expect(page.getByRole("radio", { name: "YouTube URL" })).toBeDisabled();
  await page.waitForTimeout(3000);
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByTestId("record-summary")).toContainText("0:03");
  await expect(page.getByTestId("record-preview")).toBeVisible();

  await page.locator("input[name=title]").fill("Take one");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(card(page, "Take one")).toBeVisible();
  await expect(card(page, "Take one").getByTestId("local-marker")).toBeVisible();

  // The server's remux gives it a duration, so the player can seek it.
  await card(page, "Take one").getByRole("button", { name: "Play Take one" }).click();
  await expect.poll(async () => (await sb(page)).length).toBeGreaterThan(2.5);
  expect((await sb(page)).length).toBeLessThan(4);
  await page.getByTestId("seek").fill("2");
  await expect.poll(async () => (await sb(page)).currentTime).toBeGreaterThanOrEqual(1.9);
  expect(await jobs(request, "render")).toHaveLength(0);
});

test("'Stop sharing' in the browser's bar stops the recording too", async ({ page }) => {
  await fakeTabShare(page);
  await openRecorder(page);
  await page.getByRole("button", { name: "Record" }).click();
  await page.waitForTimeout(1500);
  await page.evaluate(() => {
    const track = (window as any).__fakeShare.getVideoTracks()[0] as MediaStreamTrack;
    track.stop();
    track.dispatchEvent(new Event("ended")); // what the browser fires when sharing ends
  });
  await expect(page.getByTestId("record-summary")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add", exact: true })).toBeEnabled();
});

test("sharing without tab audio is refused before recording starts", async ({ page }) => {
  await fakeTabShare(page, { audio: false });
  await openRecorder(page);
  await page.getByRole("button", { name: "Record" }).click();
  await expect(page.getByRole("alert")).toContainText("Also share tab audio");
  await expect(page.getByTestId("record-timer")).toHaveCount(0);
});

// Smoke subset against the real containers (compose + fake MeTube). No reset
// hook here, so each run adds a fresh, randomly named song.
import { expect, test } from "@playwright/test";

import { card, sb } from "./helpers";

const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_";
const yid = "S" + Array.from({ length: 10 }, () => alphabet[Math.floor(Math.random() * alphabet.length)]).join("");
const title = `YouTube title ${yid}`;

test.describe.configure({ mode: "serial" });

test("the UI loads", async ({ page, request }) => {
  await page.goto("./");
  await expect(page.getByRole("heading", { name: "Songbook" })).toBeVisible();
  expect((await request.get("api/health")).ok()).toBeTruthy();
});

test("adding a URL downloads through MeTube into Unsorted", async ({ page }) => {
  await page.goto("./");
  await page.getByRole("button", { name: "Add song" }).click();
  await page.getByLabel("YouTube URL").fill(`https://youtu.be/${yid}`);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const c = page.locator("[data-testid=group][data-group-name='Unsorted']").locator(`[data-testid=song-card][data-name="${title}"]`);
  await expect(c).toBeVisible({ timeout: 30_000 });
  await expect(c.getByTestId("song-reference")).toContainText("Fake Uploader");
});

test("the song plays in the modal, and a +2 default preset renders and is used", async ({ page, context }) => {
  await page.goto("./");
  const url = page.url();
  await card(page, title).getByRole("button", { name: `Play ${title}` }).click();
  await expect(page.getByTestId("player")).toBeVisible();
  await expect.poll(async () => (await sb(page)).currentTime).toBeGreaterThan(0.2);
  expect(page.url()).toBe(url);
  expect(context.pages()).toHaveLength(1);
  expect((await sb(page)).graph).toBe("worklet");

  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await page.getByRole("button", { name: "Save as…" }).click();
  const dlg = page.getByRole("dialog", { name: "Save preset" });
  await dlg.getByLabel("Name").fill("Smoke +2");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("render-badge")).toHaveText("cached", { timeout: 60_000 });
  await expect.poll(async () => (await sb(page)).src).toContain("media/renders/");

  // The render file is served (with Range) from under the same base URL.
  const src: string = (await sb(page)).src;
  const r = await page.request.get(src, { headers: { Range: "bytes=0-99" } });
  expect(r.status()).toBe(206);

  await page.keyboard.press("Escape");
  await page.reload();
  await card(page, title).getByRole("button", { name: `Play ${title}` }).click();
  await expect(page.getByTestId("render-badge")).toHaveText("cached");
  await expect(page.getByTestId("preset-badge")).toHaveText("Smoke +2");
});

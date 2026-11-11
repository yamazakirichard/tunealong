import { fileURLToPath } from "node:url";

import { expect, type Page, test } from "@playwright/test";

import { card, closePlayer, jobs, presets, reset, saveAs, sb } from "./helpers";

// A two-bar C major scale written for these tests (fixtures/scale.musicxml).
const SCALE = fileURLToPath(new URL("../../fixtures/scale.musicxml", import.meta.url));
const TITLE = "Fixture Scale";
// The same scale on a notation staff over a TAB staff (fixtures/scale-staves.musicxml).
const STAVES = fileURLToPath(new URL("../../fixtures/scale-staves.musicxml", import.meta.url));
const STAVES_TITLE = "Fixture Scale Staves";

test.beforeEach(async ({ request }) => reset(request));

async function uploadScale(page: Page) {
  await page.goto("./");
  await page.getByRole("button", { name: "Add song" }).click();
  await page.getByRole("radio", { name: "Tab file" }).click();
  await page.locator("input[name=tab-file]").setInputFiles(SCALE);
  // Artist and title come from the file's own metadata.
  await expect(page.locator("input[name=title]")).toHaveValue(TITLE);
  await expect(page.locator("input[name=artist]")).toHaveValue("Songbook Fixtures");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(card(page, TITLE)).toBeVisible();
}

async function openTab(page: Page) {
  await card(page, TITLE).getByRole("button", { name: `Play ${TITLE}` }).click();
  await expect(page.getByTestId("player-tab")).toBeVisible();
  await expect.poll(async () => (await sb(page)).length, { message: "tab loaded" }).toBeGreaterThan(3);
}

test("a tab file is added from the dialog and shows the tab marker", async ({ page, request }) => {
  await uploadScale(page);
  await expect(card(page, TITLE).getByTestId("tab-marker")).toBeVisible();
  await expect(card(page, TITLE).getByTestId("local-marker")).toHaveCount(0);

  // Same bytes again: a duplicate, not a second song.
  await page.getByRole("button", { name: "Add song" }).click();
  await page.getByRole("radio", { name: "Tab file" }).click();
  await page.locator("input[name=tab-file]").setInputFiles(SCALE);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("Already in library")).toBeVisible();
  const lib = await (await request.get("api/library")).json();
  expect(lib.groups.flatMap((g: { songs: unknown[] }) => g.songs)).toHaveLength(3); // two webm fixtures + the tab
});

test("a tab song plays in alphaTab, with live tempo and pitch, and saving renders nothing", async ({ page, request }) => {
  await uploadScale(page);
  await openTab(page);
  let s = await sb(page);
  expect(s.kind).toBe("tab");
  expect(s.graph).toBe("tab");
  expect(s.badge).toBe("tab");
  expect(s.errors).toEqual([]);
  // Two bars of 4/4 at 120 bpm.
  expect(s.length).toBeGreaterThan(3.5);
  expect(s.length).toBeLessThan(4.5);
  await expect(page.locator(".player-tab svg, .player-tab canvas").first()).toBeVisible();
  await expect.poll(async () => (await sb(page)).currentTime, { message: "tab plays" }).toBeGreaterThan(0.2);

  // Half steps don't exist for tabs: the synth transposes whole semitones.
  await expect(page.getByRole("button", { name: "Pitch up 0.5" })).toHaveCount(0);
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await page.getByTestId("tempo").fill("0.73");
  await page.getByTestId("tempo").press("Enter");
  s = await sb(page);
  expect(s.pitch).toBe(2);
  expect(s.playbackRate).toBe(0.73);
  const length = s.length;

  await saveAs(page, "slow");
  expect((await sb(page)).length).toBeCloseTo(length, 2); // speed doesn't stretch the song timeline
  expect(await jobs(request, "render")).toHaveLength(0);
  const id = (await (await request.get("api/library")).json()).groups
    .flatMap((g: { songs: { id: number; title: string }[] }) => g.songs)
    .find((x: { title: string }) => x.title === TITLE).id;
  const [p] = await presets(request, id);
  expect([p.name, p.semitones, p.tempo, p.is_default]).toEqual(["slow", 2, 0.73, true]);

  // Reopening brings the preset back.
  await closePlayer(page);
  await openTab(page);
  s = await sb(page);
  expect([s.presetName, s.pitch, s.playbackRate]).toEqual(["slow", 2, 0.73]);
  expect(await jobs(request, "render")).toHaveLength(0);
});

test("player controls stay clickable over the score", async ({ page }) => {
  // A short window puts the score under the control bar, as a long song does.
  // alphaTab gives its score chunks z-index 1 and its cursors 1000.
  await uploadScale(page);
  await page.setViewportSize({ width: 1000, height: 300 });
  await openTab(page);
  const buttons = await page.evaluate(() => {
    document.querySelector<HTMLElement>("[data-testid=player-tab]")!.scrollTop = 0;
    const chunks = [...document.querySelectorAll<HTMLElement>(".player-tab .at-surface > div")].map((c) => c.getBoundingClientRect());
    return [...document.querySelectorAll<HTMLElement>("[data-testid=player-controls] button")].map((b) => {
      const r = b.getBoundingClientRect();
      const x = r.left + r.width / 2;
      const y = r.top + r.height / 2;
      const hit = document.elementFromPoint(x, y);
      return {
        label: b.getAttribute("aria-label") ?? b.textContent,
        overScore: chunks.some((c) => x >= c.left && x <= c.right && y >= c.top && y <= c.bottom),
        // A toast may cover a corner; what matters is the score never does.
        underScore: !!hit?.closest(".player-tab"),
      };
    });
  });
  expect(buttons.some((b) => b.overScore), "the score reaches under the controls").toBe(true);
  expect(buttons.filter((b) => b.underScore)).toEqual([]);

  const before = (await sb(page)).pitch;
  await page.getByRole("button", { name: "Pitch up 1" }).click({ timeout: 2000 });
  expect((await sb(page)).pitch).toBe(before + 1);
});

test("zoom scales the score and is remembered", async ({ page }) => {
  await uploadScale(page);
  await openTab(page);
  const height = () => page.locator(".player-tab .at-surface").evaluate((e) => e.getBoundingClientRect().height);
  await expect.poll(height, { message: "score drawn" }).toBeGreaterThan(50);
  const before = await height();
  await expect(page.getByTestId("zoom")).toHaveText("100%");

  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect(page.getByTestId("zoom")).toHaveText("150%");
  await expect.poll(height, { message: "score grew" }).toBeGreaterThan(before * 1.3);
  expect((await sb(page)).errors).toEqual([]);

  // Per browser: the next tab opens at the same zoom.
  await closePlayer(page);
  await openTab(page);
  await expect(page.getByTestId("zoom")).toHaveText("150%");
  await expect.poll(height).toBeGreaterThan(before * 1.3);

  // The percentage resets to 100%.
  await page.getByTestId("zoom").click();
  await expect(page.getByTestId("zoom")).toHaveText("100%");
  await expect.poll(height).toBeLessThan(before * 1.1);
});

test("a tab-only track has no score/tab switch", async ({ page }) => {
  await uploadScale(page); // a single TAB staff
  await openTab(page);
  expect((await sb(page)).switchable).toBe(false);
  await expect(page.getByRole("combobox", { name: "Show" })).toHaveCount(0);
});

test("score + tab, tab only or score only, remembered", async ({ page }) => {
  await page.goto("./");
  await page.getByRole("button", { name: "Add song" }).click();
  await page.getByRole("radio", { name: "Tab file" }).click();
  await page.locator("input[name=tab-file]").setInputFiles(STAVES);
  await expect(page.locator("input[name=title]")).toHaveValue(STAVES_TITLE);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await card(page, STAVES_TITLE).getByRole("button", { name: `Play ${STAVES_TITLE}` }).click();
  await expect.poll(async () => (await sb(page)).length, { message: "tab loaded" }).toBeGreaterThan(3);
  expect((await sb(page)).switchable, "notation staff + TAB staff").toBe(true);
  const height = () => page.locator(".player-tab .at-surface").evaluate((e) => e.getBoundingClientRect().height);
  await expect.poll(height, { message: "score drawn" }).toBeGreaterThan(50);
  const both = await height();
  const show = page.getByRole("combobox", { name: "Show" });
  await expect(show).toHaveValue("both");

  // One staff fewer per system each way.
  await show.selectOption("tab");
  await expect.poll(height, { message: "tab only is shorter" }).toBeLessThan(both * 0.85);
  const tab = await height();
  await show.selectOption("score");
  await expect.poll(height, { message: "score only is shorter" }).toBeLessThan(both * 0.85);
  await expect.poll(height, { message: "score is not the tab layout" }).not.toBeCloseTo(tab, 0);
  expect((await sb(page)).errors).toEqual([]);

  // Per browser: the next tab opens the same way.
  await closePlayer(page);
  await card(page, STAVES_TITLE).getByRole("button", { name: `Play ${STAVES_TITLE}` }).click();
  await expect.poll(async () => (await sb(page)).length, { message: "tab loaded" }).toBeGreaterThan(3);
  await expect(show).toHaveValue("score");
  await expect.poll(height).toBeLessThan(both * 0.85);
  await show.selectOption("both");
  await expect.poll(height).toBeCloseTo(both, 0);
});

test("an A/B loop on a tab song stays between A and B", async ({ page }) => {
  await uploadScale(page);
  await openTab(page);
  await page.keyboard.press(" "); // pause
  await page.getByTestId("seek").fill("1");
  await page.getByTitle("Set loop start (A)").click();
  await page.getByTestId("seek").fill("2");
  await page.getByTitle("Set loop end (B)").click();
  const s = await sb(page);
  expect(s.loopOn).toBe(true);
  expect(s.loop_a).toBeCloseTo(1, 0);
  expect(s.loop_b).toBeCloseTo(2, 0);
  await page.keyboard.press(" "); // play
  // Long enough to pass B several times.
  for (let i = 0; i < 12; i++) {
    await page.waitForTimeout(250);
    const t = (await sb(page)).currentTime;
    expect(t).toBeGreaterThanOrEqual(s.loop_a - 0.15);
    expect(t).toBeLessThan(s.loop_b + 0.3);
  }
});

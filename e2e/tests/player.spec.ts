import { expect, test } from "@playwright/test";

import { A, closePlayer, jobs, openSong, presets, reset, saveAs, sb, songId } from "./helpers";

test.beforeEach(async ({ request }) => reset(request));

test("clicking a song opens the modal: same URL, no new page", async ({ page, context }) => {
  await page.goto("./");
  const url = page.url();
  await openSong(page, A);
  expect(page.url()).toBe(url);
  expect(context.pages()).toHaveLength(1);
  const box = await page.getByTestId("player").boundingBox();
  expect(box!.width).toBeGreaterThan(1400 * 0.9);
  expect(box!.height).toBeGreaterThan(900 * 0.9);
});

test("Esc, ✕ and a backdrop click each close the modal and stop playback", async ({ page }) => {
  await page.goto("./");
  const allPaused = () => page.evaluate(() => [...document.querySelectorAll("video")].every((v) => v.paused));

  await openSong(page, A);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("player")).toBeHidden();
  expect(await allPaused()).toBe(true);
  expect((await sb(page)).open).toBe(false);

  await openSong(page, A);
  await page.getByTestId("player-close").click();
  await expect(page.getByTestId("player")).toBeHidden();
  expect(await allPaused()).toBe(true);

  await openSong(page, A);
  await page.getByTestId("player-backdrop").click({ position: { x: 5, y: 5 } });
  await expect(page.getByTestId("player")).toBeHidden();
  expect(await allPaused()).toBe(true);
});

test("no auto-shift: a song without presets opens at rate 1 and pitch 0, and creates no job", async ({ page, request }) => {
  await page.goto("./");
  await openSong(page, A);
  const s = await sb(page);
  expect(s.graph).toBe("worklet");
  expect(s.playbackRate).toBe(1);
  expect(s.pitch).toBe(0);
  expect(s.badge).toBe("original");
  expect(await jobs(request, "render")).toHaveLength(0);
});

test("setting the tempo to 0.75 sets video.playbackRate", async ({ page }) => {
  await page.goto("./");
  await openSong(page, A);
  await page.getByLabel("Tempo", { exact: true }).fill("0.75");
  await expect.poll(async () => (await sb(page)).playbackRate).toBe(0.75);
  // Shortcuts: ] adds 0.05, - lowers the pitch.
  await page.getByTestId("player").focus();
  await page.keyboard.press("]");
  await expect.poll(async () => (await sb(page)).playbackRate).toBe(0.8);
  await page.keyboard.press("-");
  await expect.poll(async () => (await sb(page)).pitch).toBe(-1);
});

test("the tempo can be typed and nudged by 0.01", async ({ page }) => {
  await page.goto("./");
  await openSong(page, A);
  const field = page.getByLabel("Tempo value");
  await field.fill("0.95");
  await field.press("Enter");
  await expect.poll(async () => (await sb(page)).playbackRate).toBe(0.95);
  await page.getByRole("button", { name: "Tempo down 0.01" }).click();
  await expect.poll(async () => (await sb(page)).playbackRate).toBe(0.94);
  await expect(field).toHaveValue("0.94");
  await field.fill("5");
  await field.press("Enter");
  await expect(field).toHaveValue("2.00"); // clamped
  await field.fill("1.3");
  await field.press("Escape"); // reverts, and the player stays open
  await expect(field).toHaveValue("2.00");
  await expect(page.getByTestId("player")).toBeVisible();
});

test("moving sliders then closing without saving changes nothing", async ({ page, request }) => {
  await page.goto("./");
  const id = await songId(request, A);
  const before = await (await request.get(`api/songs/${id}`)).json();
  await openSong(page, A);
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await page.getByLabel("Tempo", { exact: true }).fill("0.6");
  await expect.poll(async () => (await sb(page)).pitch).toBe(2);
  await closePlayer(page);
  expect(await (await request.get(`api/songs/${id}`)).json()).toEqual(before);
  expect((await jobs(request)).filter((j: { kind: string }) => j.kind !== "scan")).toEqual([]);
});

test("+2 saved as default: rendering… → cached, src switches to the render, and a reload plays it directly", async ({ page, request }) => {
  await page.goto("./");
  await openSong(page, A);
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await saveAs(page, "Up two");
  const badge = page.getByTestId("render-badge");
  await expect(badge).toHaveText("rendering…");
  await expect.poll(async () => (await sb(page)).pitch).toBe(2); // live while pending
  await expect(badge).toHaveText("cached", { timeout: 30_000 });
  await expect.poll(async () => (await sb(page)).src).toContain("/media/renders/");
  await expect.poll(async () => (await sb(page)).pitch).toBe(0); // the render carries the shift
  expect((await sb(page)).paused).toBe(false);

  await page.reload();
  await openSong(page, A);
  await expect(badge).toHaveText("cached");
  await expect(page.getByTestId("preset-badge")).toHaveText("Up two");
  const s = await sb(page);
  expect(s.src).toContain("/media/renders/");
  expect(s.pitch).toBe(0);
  expect(s.playbackRate).toBe(1);
  expect(await jobs(request, "render")).toHaveLength(1);
});

test("the most recently saved or picked preset is what the song opens with; 'Open at original' undoes that", async ({ page, request }) => {
  await page.goto("./");
  const id = await songId(request, A);
  await openSong(page, A);
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await saveAs(page, "Up two");
  await expect(page.getByTestId("render-badge")).toHaveText("cached", { timeout: 30_000 });
  await page.getByRole("button", { name: "Pitch down 1" }).click();
  await page.getByRole("button", { name: "Pitch down 1" }).click();
  await page.getByRole("button", { name: "Pitch down 1" }).click();
  await saveAs(page, "Down one");
  await expect(page.getByTestId("render-badge")).toHaveText("cached", { timeout: 30_000 });
  const ps = await presets(request, id);
  expect(ps.map((p: { name: string; is_default: boolean }) => [p.name, p.is_default])).toEqual([
    ["Down one", true],
    ["Up two", false],
  ]);
  await closePlayer(page);

  await openSong(page, A);
  await expect(page.getByTestId("preset-badge")).toHaveText("Down one");
  await expect(page.getByTestId("render-badge")).toHaveText("cached");
  expect((await sb(page)).semitones).toBe(-1);

  // Picking an older preset makes it the default again, with no save.
  await page.getByLabel("Preset", { exact: true }).selectOption({ label: "Up two" });
  await expect(page.getByTestId("unsaved")).toBeHidden();
  await expect.poll(async () => (await presets(request, id)).find((p: { is_default: boolean }) => p.is_default)?.name).toBe("Up two");

  // Save updates the selected preset in place, with no dialog; nothing new is added.
  await page.getByRole("button", { name: "Pitch up 0.5" }).click();
  await expect(page.getByTestId("unsaved")).toBeVisible();
  await page.getByRole("button", { name: "Save preset" }).click();
  await expect(page.getByRole("dialog", { name: "Save as new preset" })).toHaveCount(0);
  await expect.poll(async () => (await presets(request, id)).map((p: { name: string; semitones: number }) => [p.name, p.semitones])).toEqual([
    ["Down one", -1],
    ["Up two", 2.5],
  ]);
  await expect(page.getByTestId("unsaved")).toBeHidden();

  await page.getByRole("button", { name: "Open at original" }).click();
  await expect.poll(async () => (await presets(request, id)).some((p: { is_default: boolean }) => p.is_default)).toBe(false);
  await closePlayer(page);
  await openSong(page, A);
  const s = await sb(page);
  expect([s.pitch, s.playbackRate, s.badge, s.presetName]).toEqual([0, 1, "original", null]);
  expect(s.src).toContain(`/media/originals/${id}`);
});

test("the song reopens with the preset last picked, or the original if that was picked", async ({ page, request }) => {
  await page.goto("./");
  const id = await songId(request, A);
  await openSong(page, A);
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await saveAs(page, "One");
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await saveAs(page, "Two");
  const preset = page.getByLabel("Preset", { exact: true });
  const defaultName = async () => (await presets(request, id)).find((p: { is_default: boolean }) => p.is_default)?.name ?? null;

  await preset.selectOption({ label: "One" });
  await expect.poll(defaultName).toBe("One");
  await closePlayer(page);
  await openSong(page, A);
  await expect(page.getByTestId("preset-badge")).toHaveText("One");
  expect((await sb(page)).semitones).toBe(1);

  await preset.selectOption({ label: "(original)" });
  await expect.poll(defaultName).toBeNull();
  await closePlayer(page);
  await openSong(page, A);
  const s = await sb(page);
  expect([s.semitones, s.presetName]).toEqual([0, null]);
  expect((await presets(request, id)).map((p: { name: string }) => p.name)).toEqual(["One", "Two"]); // nothing deleted
});

test("the trash can deletes the selected preset after a confirm, and playback goes back to the original", async ({ page, request }) => {
  await page.goto("./");
  const id = await songId(request, A);
  await openSong(page, A);
  await expect(page.getByRole("button", { name: "Delete preset" })).toBeHidden(); // nothing selected
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await saveAs(page, "Keep");
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await saveAs(page, "Drop");

  // Cancel stores nothing.
  await page.getByRole("button", { name: "Delete preset" }).click();
  const dlg = page.getByRole("dialog", { name: "Delete preset" });
  await expect(dlg).toContainText('Delete "Drop"?');
  await dlg.getByRole("button", { name: "Cancel" }).click();
  await expect(dlg).toBeHidden();
  await expect(page.getByTestId("player")).toBeVisible();
  expect((await presets(request, id)).map((p: { name: string }) => p.name)).toEqual(["Drop", "Keep"]);

  // Escape closes only the confirm, not the player.
  await page.getByRole("button", { name: "Delete preset" }).click();
  await page.keyboard.press("Escape");
  await expect(dlg).toBeHidden();
  await expect(page.getByTestId("player")).toBeVisible();

  await page.getByRole("button", { name: "Delete preset" }).click();
  await dlg.getByRole("button", { name: "Delete" }).click();
  await expect(dlg).toBeHidden();
  await expect.poll(async () => (await presets(request, id)).map((p: { name: string; is_default: boolean }) => [p.name, p.is_default])).toEqual([
    ["Keep", false],
  ]);
  const s = await sb(page);
  expect([s.pitch, s.badge, s.presetName]).toEqual([0, "original", null]);
  await expect(page.getByLabel("Preset", { exact: true }).locator("option")).toHaveText(["(original)", "Keep"]);
  await expect(page.getByRole("button", { name: "Delete preset" })).toBeHidden();
});

test("the seek bar shows the position and jumps through the track", async ({ page }) => {
  await page.goto("./");
  await openSong(page, A);
  await expect(page.getByTestId("length")).toHaveText("0:10");
  const seek = page.getByLabel("Position", { exact: true });
  await seek.fill("6");
  await expect.poll(async () => (await sb(page)).currentTime).toBeGreaterThanOrEqual(6);
  await expect(page.getByTestId("position")).toHaveText(/0:0[67]/);
  // Arrow keys jump 5 s, Home goes back to the start.
  await page.getByTestId("player").focus();
  await page.keyboard.press("Home");
  await expect.poll(async () => (await sb(page)).currentTime).toBeLessThan(1);
  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => (await sb(page)).currentTime).toBeGreaterThanOrEqual(5);
  await page.keyboard.press("ArrowLeft");
  await expect.poll(async () => (await sb(page)).currentTime).toBeLessThan(2);
});

test("on a slowed-down render the seek bar still uses the song's own timeline", async ({ page }) => {
  await page.goto("./");
  await openSong(page, A);
  await page.getByLabel("Tempo", { exact: true }).fill("0.5");
  await saveAs(page, "Half");
  await expect(page.getByTestId("render-badge")).toHaveText("cached", { timeout: 30_000 });
  await expect(page.getByTestId("length")).toHaveText("0:10"); // the song is 10 s, the file 20 s
  await page.getByLabel("Position", { exact: true }).fill("4");
  await expect.poll(async () => (await sb(page)).currentTime).toBeGreaterThanOrEqual(8); // 4 s of song = 8 s of render
  expect((await sb(page)).position).toBeGreaterThanOrEqual(4);
});

test("volume: the slider sets the gain, M mutes, and the level is remembered on reopen", async ({ page }) => {
  await page.goto("./");
  await openSong(page, A);
  await expect.poll(async () => (await sb(page)).gain).toBe(1);
  const slider = page.getByRole("slider", { name: "Volume" });
  await slider.fill("0.5");
  await expect.poll(async () => (await sb(page)).gain).toBeCloseTo(0.25, 3); // squared
  expect((await sb(page)).graph).toBe("worklet");

  await page.getByTestId("player").focus();
  await page.keyboard.press("m");
  await expect.poll(async () => (await sb(page)).gain).toBe(0);
  await expect(page.getByRole("button", { name: "Unmute (M)" })).toBeVisible();
  await page.keyboard.press("m");
  await expect.poll(async () => (await sb(page)).gain).toBeCloseTo(0.25, 3);

  await closePlayer(page);
  await openSong(page, A);
  await expect(slider).toHaveValue("0.5");
  await expect.poll(async () => (await sb(page)).gain).toBeCloseTo(0.25, 3);
});

test("volume: past the 100% mark it boosts linearly up to 200%", async ({ page }) => {
  await page.goto("./");
  await openSong(page, A);
  const slider = page.getByRole("slider", { name: "Volume" });
  await expect(slider).toHaveAttribute("max", "2");
  await expect(page.getByTestId("volume-100")).toBeVisible();
  await slider.fill("1.5");
  await expect.poll(async () => (await sb(page)).gain).toBeCloseTo(1.5, 3);
  await expect(slider).toHaveAttribute("aria-valuetext", "150%");
  await slider.fill("2");
  await expect.poll(async () => (await sb(page)).gain).toBeCloseTo(2, 3);
});

test("a preset keeps its own volume; the original keeps the browser's", async ({ page, request }) => {
  await page.goto("./");
  await openSong(page, A);
  const slider = page.getByRole("slider", { name: "Volume" });
  const preset = page.getByLabel("Preset", { exact: true });
  await page.getByRole("button", { name: "Pitch up 1" }).click();
  await slider.fill("0.4");
  await saveAs(page, "Quiet");
  expect((await presets(request, await songId(request, A)))[0].volume).toBe(0.4);

  await preset.selectOption({ label: "(original)" });
  await expect(slider).toHaveValue("0.4"); // set before the preset existed, so also the browser's
  await slider.fill("0.8");
  await expect.poll(async () => (await sb(page)).gain).toBeCloseTo(0.64, 3);
  await preset.selectOption({ label: "Quiet" });
  await expect(slider).toHaveValue("0.4");
  await slider.fill("0.6");
  await expect(page.getByTestId("unsaved")).toBeVisible();

  await closePlayer(page); // unsaved: the preset still has 0.4, and the browser still 0.8
  await openSong(page, A);
  await expect(slider).toHaveValue("0.4");
  await preset.selectOption({ label: "(original)" });
  await expect(slider).toHaveValue("0.8");
});

test("F toggles fullscreen on the modal, not a new tab", async ({ page, context }) => {
  await page.goto("./");
  await openSong(page, A);
  await page.getByTestId("player").focus();
  await page.keyboard.press("f");
  await expect.poll(() => page.evaluate(() => document.fullscreenElement?.getAttribute("data-testid") ?? null)).toBe("player");
  await page.keyboard.press("f");
  await expect.poll(() => page.evaluate(() => document.fullscreenElement)).toBeNull();
  expect(context.pages()).toHaveLength(1);
});

test("closing and reopening three times plays audio each time, without InvalidStateError", async ({ page }) => {
  await page.goto("./");
  for (let i = 0; i < 3; i++) {
    await openSong(page, A);
    await expect.poll(async () => (await sb(page)).audioState).toBe("running");
    const s = await sb(page);
    expect(s.graph).toBe("worklet");
    expect(s.paused).toBe(false);
    await closePlayer(page);
  }
  expect((await sb(page)).errors).toEqual([]);
});

test("A/B loop keeps playback between the points", async ({ page }) => {
  await page.goto("./");
  await openSong(page, A);
  await page.getByTestId("player").focus();
  await expect.poll(async () => (await sb(page)).currentTime).toBeGreaterThan(1);
  await page.keyboard.press("a");
  await expect.poll(async () => (await sb(page)).currentTime).toBeGreaterThan((await sb(page)).loop_a + 1);
  await page.keyboard.press("b");
  const s = await sb(page);
  expect(s.loopOn).toBe(true);
  // After a few more seconds we're still inside [A, B].
  await page.waitForTimeout(2500);
  const t = (await sb(page)).currentTime;
  expect(t).toBeGreaterThanOrEqual(s.loop_a - 0.05);
  expect(t).toBeLessThanOrEqual(s.loop_b + 0.1);
});

test("a preset's A/B don't carry over to (original), and come back with the preset", async ({ page }) => {
  await page.goto("./");
  await openSong(page, A);
  await page.getByTestId("player").focus();
  await expect.poll(async () => (await sb(page)).currentTime).toBeGreaterThan(1);
  await page.keyboard.press("a");
  await expect.poll(async () => (await sb(page)).currentTime).toBeGreaterThan((await sb(page)).loop_a + 1);
  await page.keyboard.press("b");
  const saved = await sb(page);
  await saveAs(page, "Solo");

  const preset = page.getByLabel("Preset", { exact: true });
  await preset.selectOption({ label: "(original)" });
  let s = await sb(page);
  expect([s.loop_a, s.loop_b, s.loopOn]).toEqual([null, null, false]);
  await expect(page.getByTitle("Set loop start (A)")).toHaveText("A");

  await preset.selectOption({ label: "Solo" });
  s = await sb(page);
  expect([s.loop_a, s.loop_b, s.loopOn]).toEqual([saved.loop_a, saved.loop_b, true]);
});

test("a saved A alone is the start point: the song reopens at A", async ({ page }) => {
  await page.goto("./");
  await openSong(page, A);
  await page.getByTestId("player").focus();
  await expect.poll(async () => (await sb(page)).currentTime).toBeGreaterThan(2);
  await page.keyboard.press("a");
  await saveAs(page, "Late start");
  const a = (await sb(page)).loop_a;
  expect((await sb(page)).loop_b).toBeNull();
  await closePlayer(page);

  await openSong(page, A);
  await expect.poll(async () => (await sb(page)).loop_a).toBe(a);
  await expect.poll(async () => (await sb(page)).position).toBeGreaterThanOrEqual(a - 0.05);
});

test("with the loop on, seeking before A is pulled back into [A, B]", async ({ page }) => {
  await page.goto("./");
  await openSong(page, A);
  await page.getByTestId("player").focus();
  await expect.poll(async () => (await sb(page)).currentTime).toBeGreaterThan(2);
  await page.keyboard.press("a");
  await expect.poll(async () => (await sb(page)).currentTime).toBeGreaterThan((await sb(page)).loop_a + 1.5);
  await page.keyboard.press("b");
  const { loop_a: a, loop_b: b } = await sb(page);
  await page.keyboard.press("Home");
  await page.waitForTimeout(300);
  const p = (await sb(page)).position;
  expect(p).toBeGreaterThanOrEqual(a - 0.05);
  expect(p).toBeLessThanOrEqual(b + 0.1);
});

test("a saved tempo is rendered by Rubber Band: the render plays at rate 1, timeline mapped", async ({ page }) => {
  await page.goto("./");
  await openSong(page, A);
  await page.getByLabel("Tempo", { exact: true }).fill("0.75");
  await expect.poll(async () => (await sb(page)).playbackRate).toBe(0.75); // live preview first
  await saveAs(page, "Slow");
  await expect(page.getByTestId("render-badge")).toHaveText("cached", { timeout: 30_000 });
  await expect.poll(async () => (await sb(page)).src).toContain("/media/renders/");
  let s = await sb(page);
  expect(s.playbackRate).toBe(1); // the slowdown is in the file now
  expect(s.time_scale).toBeCloseTo(1 / 0.75, 3);
  expect(s.pitch).toBe(0);
  expect(s.paused).toBe(false);

  await page.reload();
  await openSong(page, A);
  await expect(page.getByTestId("render-badge")).toHaveText("cached");
  s = await sb(page);
  expect(s.playbackRate).toBe(1);
  expect(s.tempo).toBe(0.75);
  // The rendered file is a third longer than the 10 s original.
  const dur = await page.evaluate(() => (document.querySelector("video") as HTMLVideoElement).duration);
  expect(dur).toBeGreaterThan(13);
  expect(dur).toBeLessThan(13.7);
});

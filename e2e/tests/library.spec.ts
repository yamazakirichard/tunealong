import { expect, test } from "@playwright/test";

import { A, B, card, createArtist, jobs, reset, songId, songs } from "./helpers";

test.beforeEach(async ({ request }) => reset(request));

test("artists render as groups; columns=2 lays items out in 2 columns", async ({ page, request }) => {
  const two = await createArtist(request, "Two Columns", { columns: 2, style: "row" });
  await createArtist(request, "Empty Artist");
  for (const yid of [A, B]) await request.patch(`api/songs/${await songId(request, yid)}`, { data: { artist_id: two } });

  await page.goto("./");
  // Artists without a manual order sort by name; Unsorted is always last.
  const groups = page.getByTestId("group");
  await expect(groups).toHaveCount(3);
  expect(await groups.evaluateAll((els) => els.map((e) => e.getAttribute("data-group-name")))).toEqual([
    "Empty Artist",
    "Two Columns",
    "Unsorted",
  ]);

  const items = page.locator("[data-testid=group][data-group-name='Two Columns'] [data-testid=song-card]");
  await expect(items).toHaveCount(2);
  const [a, b] = [await items.nth(0).boundingBox(), await items.nth(1).boundingBox()];
  expect(Math.abs(a!.y - b!.y)).toBeLessThan(2); // same row
  expect(b!.x).toBeGreaterThan(a!.x + a!.width - 2); // side by side
  expect(a!.width).toBeGreaterThan(400); // two columns of a ~1370px page, not four
});

test("an artist TheAudioDB knows gets its picture beside the name", async ({ page, request }) => {
  await createArtist(request, "Black Sabbath"); // known to the fake TheAudioDB
  await createArtist(request, "Unknown To AudioDB");
  await page.goto("./");
  const pic = page.locator("[data-testid=group][data-group-name='Black Sabbath'] [data-testid=artist-image]");
  // The worker looks artists up when idle; reload until it has.
  await expect(async () => {
    await page.reload();
    await expect(pic).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 30_000 });
  expect(await pic.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  await expect(page.locator("[data-testid=group][data-group-name='Unknown To AudioDB'] [data-testid=artist-image]")).toHaveCount(0);
});

test("pasting an existing song's URL shows the duplicate toast and creates no job", async ({ page, request }) => {
  await page.goto("./");
  await page.getByRole("button", { name: "Add song" }).click();
  await page.getByLabel("YouTube URL").fill(`https://www.youtube.com/watch?v=${A}&t=42s`);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const toast = page.getByTestId("toast").filter({ hasText: "Already in library" });
  await expect(toast).toBeVisible();
  expect(await jobs(request, "download")).toHaveLength(0);
  expect((await (await request.get("__dev/calls")).json()).calls).toHaveLength(0);
  // The toast's link opens the song.
  await toast.getByRole("button", { name: "Open" }).click();
  await expect(page.getByTestId("player")).toBeVisible();
});

test("a URL with no artist lands in Unsorted with the YouTube title as reference", async ({ page, request }) => {
  await page.goto("./");
  await page.getByRole("button", { name: "Add song" }).click();
  await page.getByLabel("YouTube URL").fill("https://youtu.be/E0ozmU9cJDg?si=abc");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByTestId("toast").filter({ hasText: "Added" })).toBeVisible();

  const unsorted = page.locator("[data-testid=group][data-group-name='Unsorted']");
  const c = unsorted.locator("[data-testid=song-card][data-name='YouTube title E0ozmU9cJDg']");
  await expect(c).toBeVisible({ timeout: 20_000 });
  await expect(c.getByTestId("song-reference")).toHaveText("YouTube title E0ozmU9cJDg · Fake Uploader");
  const s = (await songs(request)).find((x: { youtube_id: string }) => x.youtube_id === "E0ozmU9cJDg");
  expect(s.artist_id).toBeNull();
});

test("creating a category inline while adding assigns it; Group by Category shows it", async ({ page, request }) => {
  await page.goto("./");
  await page.getByRole("button", { name: "Add song" }).click();
  await page.getByLabel("YouTube URL").fill("https://youtu.be/E0ozmU9cJDg");
  await page.getByLabel("New category").fill("Backing tracks");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("checkbox", { name: "Backing tracks" })).toBeChecked();
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByTestId("toast").filter({ hasText: "Added" })).toBeVisible();

  await page.getByRole("button", { name: "Category", exact: true }).click();
  const group = page.locator("[data-testid=group][data-group-name='Backing tracks']");
  await expect(group.getByTestId("song-card")).toHaveCount(1, { timeout: 20_000 });
  await expect(group.getByTestId("category-chip")).toHaveText("Backing tracks");
  // The choice is remembered.
  await page.reload();
  await expect(page.getByRole("button", { name: "Category", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(await jobs(request, "render")).toHaveLength(0);
});

test("moving a song to another artist sticks after a reload", async ({ page, request }) => {
  await createArtist(request, "Black Sabbath");
  await page.goto("./");
  await card(page, A).getByRole("button", { name: `Actions for ${A}` }).click();
  await page.getByRole("menuitem", { name: "Set artist…" }).click();
  const dlg = page.getByRole("dialog", { name: "Edit song" });
  await dlg.getByLabel("Artist").fill("Black Sabbath");
  await dlg.getByRole("button", { name: "Save" }).click();
  await page.reload();
  const group = page.locator("[data-testid=group][data-group-name='Black Sabbath']");
  await expect(group.locator(`[data-testid=song-card][data-name='${A}']`)).toBeVisible();
});

test("the artist field suggests artists already in the library", async ({ page, request }) => {
  await createArtist(request, "Black Sabbath");
  await page.goto("./");
  await page.getByRole("button", { name: "Add song" }).click();
  const dlg = page.getByRole("dialog", { name: "Add song" });

  // The best match shows greyed after the cursor; Tab takes it.
  const artist = dlg.getByLabel("Artist");
  await artist.pressSequentially("black s");
  await expect(dlg.getByTestId("suggest-ghost")).toContainText("abbath");
  await artist.press("Tab");
  await expect(artist).toHaveValue("Black Sabbath");

  // Escape closes the list but not the dialog; arrows and Enter pick from it.
  await artist.fill("");
  await artist.pressSequentially("sabb");
  await expect(dlg.getByRole("option", { name: "Black Sabbath" })).toBeVisible();
  await artist.press("Escape");
  await expect(dlg.getByRole("listbox")).toBeHidden();
  await expect(dlg.getByLabel("YouTube URL")).toBeVisible();
  await artist.press("ArrowDown");
  await artist.press("Enter");
  await expect(artist).toHaveValue("Black Sabbath");
});

test("pasting a URL guesses artist and title from the YouTube title", async ({ page }) => {
  await page.goto("./");
  await page.getByRole("button", { name: "Add song" }).click();
  const dlg = page.getByRole("dialog", { name: "Add song" });
  const url = dlg.getByLabel("YouTube URL");
  const artist = dlg.getByLabel("Artist");
  const title = dlg.getByLabel("Title");

  // The fake oEmbed calls Pzzzzzzzzzz "Black Sabbath - Paranoid (Official Video)".
  await url.fill("https://youtu.be/Pzzzzzzzzzz");
  await expect(dlg.getByTestId("youtube-title")).toHaveText("YouTube: Black Sabbath - Paranoid (Official Video) · BlackSabbathVEVO");
  await expect(artist).toHaveValue("Black Sabbath");
  await expect(title).toHaveValue("Paranoid");

  // A title you typed yourself survives a new lookup; a guessed artist is replaced.
  await title.fill("My Paranoid");
  await url.fill("https://youtu.be/E0ozmU9cJDg");
  await expect(dlg.getByTestId("youtube-title")).toContainText("YouTube title E0ozmU9cJDg");
  await expect(artist).toHaveValue("");
  await expect(title).toHaveValue("My Paranoid");

  await dlg.getByRole("button", { name: "Add", exact: true }).click();
  await expect(card(page, "My Paranoid")).toBeVisible({ timeout: 20_000 });
});

test("dragging a song onto another artist group moves it", async ({ page, request }) => {
  await createArtist(request, "Target");
  await page.goto("./");
  const target = page.locator("[data-testid=group][data-group-name='Target']");
  await card(page, B).dragTo(target);
  await expect(target.locator(`[data-testid=song-card][data-name='${B}']`)).toBeVisible();
  await page.reload();
  await expect(target.locator(`[data-testid=song-card][data-name='${B}']`)).toBeVisible();
});

test("drag-reordering songs survives a reload", async ({ page }) => {
  await page.goto("./");
  const unsorted = page.locator("[data-testid=group][data-group-name='Unsorted'] [data-testid=song-card]");
  await expect(unsorted).toHaveCount(2);
  await expect(unsorted.first()).toHaveAttribute("data-name", A);
  await card(page, B).dragTo(card(page, A));
  await expect(unsorted.first()).toHaveAttribute("data-name", B);
  await page.reload();
  await expect(unsorted.first()).toHaveAttribute("data-name", B);
  await expect(unsorted.nth(1)).toHaveAttribute("data-name", A);
});

test("the menu alternative to dragging: Move down", async ({ page }) => {
  await page.goto("./");
  await card(page, A).getByRole("button", { name: `Actions for ${A}` }).click();
  await page.getByRole("menuitem", { name: "Move down" }).click();
  const unsorted = page.locator("[data-testid=group][data-group-name='Unsorted'] [data-testid=song-card]");
  await expect(unsorted.first()).toHaveAttribute("data-name", B);
});

import { type APIRequestContext, expect, type Page } from "@playwright/test";

export const A = "AAAAAAAAAAA";
export const B = "BBBBBBBBBBB";

export async function reset(request: APIRequestContext) {
  expect((await request.post("__dev/reset")).ok()).toBeTruthy();
}

export async function songs(request: APIRequestContext) {
  const lib = await (await request.get("api/library")).json();
  return lib.groups.flatMap((g: { songs: { id: number; youtube_id: string }[] }) => g.songs);
}

export async function songId(request: APIRequestContext, yid: string): Promise<number> {
  return (await songs(request)).find((s: { youtube_id: string }) => s.youtube_id === yid).id;
}

export async function jobs(request: APIRequestContext, kind?: string) {
  const all = await (await request.get("api/jobs?limit=1000")).json();
  return kind ? all.filter((j: { kind: string }) => j.kind === kind) : all;
}

export async function presets(request: APIRequestContext, id: number) {
  return (await request.get(`api/songs/${id}/presets`)).json();
}

export async function createArtist(request: APIRequestContext, name: string, extra: Record<string, unknown> = {}) {
  const r = await request.post("api/artists", { data: { name, ...extra } });
  expect(r.status()).toBe(201);
  return (await r.json()).id as number;
}

/** The player's test hook, snapshotted (getters evaluated in the page). */
export async function sb(page: Page): Promise<Record<string, any>> {
  return page.evaluate(() => {
    const h = (window as any).__songbook ?? {};
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(h)) out[k] = h[k];
    return out;
  });
}

export function card(page: Page, title: string) {
  return page.locator(`[data-testid=song-card][data-name="${title}"]`);
}

/** Open a song from the library and wait until it is actually playing. */
export async function openSong(page: Page, title: string) {
  await card(page, title).getByRole("button", { name: `Play ${title}` }).click();
  await expect(page.getByTestId("player")).toBeVisible();
  await expect.poll(async () => (await sb(page)).currentTime, { message: "video plays" }).toBeGreaterThan(0.2);
}

export async function closePlayer(page: Page) {
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("player")).toBeHidden();
}

/** Save as a new preset; it becomes the song's default (the latest save always does). */
export async function saveAs(page: Page, name: string) {
  await page.getByRole("button", { name: "Save as…" }).click();
  const dlg = page.getByRole("dialog", { name: "Save as new preset" });
  await dlg.getByLabel("Name").fill(name);
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(dlg).toBeHidden();
}

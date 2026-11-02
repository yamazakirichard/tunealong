// Thin client for the Songbook API. Every URL is relative ("api/…", "media/…")
// so the UI works at / or under any subpath.

export interface Preset {
  id: number;
  song_id: number;
  name: string;
  semitones: number;
  tempo: number;
  bake_tempo: boolean;
  loop_a: number | null;
  loop_b: number | null;
  is_default: boolean;
  cache_key: string | null;
  volume: number | null; // null = the browser's
}

export interface Song {
  id: number;
  youtube_id: string | null;
  artist_id: number | null;
  title: string;
  yt_title: string | null;
  uploader: string | null;
  sort_order: number | null;
  status: "queued" | "downloading" | "ready" | "error";
  error: string | null;
  notes: string | null;
  added_at: string;
  kind: "media" | "tab"; // tab = a Guitar Pro / MusicXML file played by alphaTab
  tab_track: number | null;
  media_url: string | null;
  categories: number[];
  default_preset: Preset | null;
  presets?: Preset[];
}

export interface Group {
  id: number | null;
  name: string;
  columns: number;
  style: "row" | "column";
  sort_order: number | null;
  colour?: string | null;
  image_url?: string | null; // artist groups: a picture from TheAudioDB, once the worker has one
  songs: Song[];
}

export interface Library {
  group_by: "artist" | "category";
  groups: Group[];
}

export interface Artist {
  id: number;
  name: string;
  sort_order: number | null;
  columns: number;
  style: "row" | "column";
}

export interface Category {
  id: number;
  name: string;
  colour: string | null;
  sort_order: number | null;
}

export interface Playback {
  preset_id: number | null;
  source: "original" | "pending" | "render" | "tab";
  url: string;
  live_semitones: number;
  live_tempo: number;
  time_scale: number;
  loop_a: number | null;
  loop_b: number | null;
  render_error: string | null;
}

export interface Job {
  id: number;
  kind: "download" | "render" | "scan";
  status: "pending" | "running" | "done" | "error";
  error: string | null;
  payload: Record<string, unknown>;
}

export interface YoutubeInfo {
  youtube_id: string;
  yt_title: string | null;
  uploader: string | null;
  in_library: boolean;
  artist: string | null;
  title: string | null;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: { detail?: unknown; song?: Song } & Record<string, unknown>,
  ) {
    super(typeof body?.detail === "string" ? body.detail : `HTTP ${status}`);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 204) return undefined as T;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, data);
  return data as T;
}

export const api = {
  library: (p: { group_by: string; category?: number | null; q?: string }) => {
    const qs = new URLSearchParams({ group_by: p.group_by });
    if (p.category != null) qs.set("category", String(p.category));
    if (p.q) qs.set("q", p.q);
    return call<Library>("GET", `api/library?${qs}`);
  },
  addSong: (body: { url: string; artist?: string; title?: string }) =>
    fetch("api/songs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(async (r) => ({ status: r.status, data: await r.json() })),
  /** Upload a tab file. 201 = added, 409 = these bytes are already a song (data.song). */
  addTab: (file: File, fields: { artist?: string; title?: string }) => {
    const form = new FormData();
    form.append("file", file);
    if (fields.artist) form.append("artist", fields.artist);
    if (fields.title) form.append("title", fields.title);
    return fetch("api/songs/tab", { method: "POST", body: form }).then(async (r) => ({
      status: r.status,
      data: await r.json().catch(() => ({})),
    }));
  },
  youtube: (url: string) => call<YoutubeInfo>("GET", `api/youtube?${new URLSearchParams({ url })}`),
  song: (id: number) => call<Song>("GET", `api/songs/${id}`),
  patchSong: (id: number, body: Partial<{ artist_id: number | null; artist_name: string; title: string; notes: string | null; tab_track: number | null }>) =>
    call<Song>("PATCH", `api/songs/${id}`, body),
  deleteSong: (id: number, deleteFile: boolean) => call<void>("DELETE", `api/songs/${id}?delete_file=${deleteFile}`),
  linkSong: (id: number, url: string) => call<Song>("POST", `api/songs/${id}/link`, { url }),
  setCategories: (id: number, ids: number[]) => call<Song>("PUT", `api/songs/${id}/categories`, ids),
  songPlayback: (id: number) => call<Playback>("GET", `api/songs/${id}/playback`),
  presetPlayback: (id: number) => call<Playback>("GET", `api/presets/${id}/playback`),
  createPreset: (songId: number, body: Omit<Preset, "id" | "song_id" | "cache_key">) =>
    call<Preset>("POST", `api/songs/${songId}/presets`, body),
  patchPreset: (id: number, body: Partial<Omit<Preset, "id" | "song_id" | "cache_key">>) =>
    call<Preset>("PATCH", `api/presets/${id}`, body),
  deletePreset: (id: number) => call<void>("DELETE", `api/presets/${id}`),
  artists: () => call<Artist[]>("GET", "api/artists"),
  createArtist: (name: string) => call<Artist>("POST", "api/artists", { name }),
  patchArtist: (id: number, body: Partial<Omit<Artist, "id">>) => call<Artist>("PATCH", `api/artists/${id}`, body),
  deleteArtist: (id: number) => call<void>("DELETE", `api/artists/${id}`),
  categories: () => call<Category[]>("GET", "api/categories"),
  createCategory: (body: { name: string; colour?: string | null }) => call<Category>("POST", "api/categories", body),
  patchCategory: (id: number, body: Partial<Omit<Category, "id">>) => call<Category>("PATCH", `api/categories/${id}`, body),
  deleteCategory: (id: number) => call<void>("DELETE", `api/categories/${id}`),
  reorder: (body: { scope: "artists" | "categories" | "songs"; group_id?: number | null; ids: number[] }) =>
    call<unknown>("POST", "api/reorder", body),
  rescan: () => call<{ queued: boolean }>("POST", "api/library/rescan"),
  jobs: (status: string) => call<Job[]>("GET", `api/jobs?status=${status}`),
};

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.body?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? String(x)).join("; ");
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

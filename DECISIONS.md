# Decisions

Judgement calls made during implementation, newest last.

## Phase 1

- **Licence is GPL-3.0-or-later.** It's compatible with Homepage's GPL-3.0. `LICENSE` is the canonical FSF text.
- **Migrations.** `schema.sql` is version 1. Later migrations go in `api/songbook/migrations/NNNN_name.sql`, applied in filename order. Each runs in its own `BEGIN IMMEDIATE` transaction, and the version is re-checked under the lock, so `api` and `worker` can start at the same time. Statements run one by one rather than via `executescript()`, because `executescript()` commits first and would break the rollback.
- **Connections use autocommit** (`isolation_level=None`), with explicit transactions through `db.transaction()`. This avoids the implicit-BEGIN behaviour of Python's `sqlite3`.
- **`busy_timeout` defaults to 5000 ms**, overridable with `SONGBOOK_DB_BUSY_TIMEOUT_MS`.
- **Paths in the DB are relative to `SONGBOOK_ROOT`** (`original_path`, `renders.path`), so the data dir can move.
- **`original_sha256` is UNIQUE**, which gives content dedup for local imports.
- **Extra schema checks**: `bake_tempo` and `is_default` are restricted to 0/1, and there's an index on `presets(cache_key)` for GC.
- **`create_app()` is a factory** (`uvicorn --factory`), so importing the module never touches the filesystem.
- **`/api/health` runs `SELECT 1`**, so a broken DB makes the health check fail.
- **Fixtures** use ffmpeg `smptebars` with `drawtext` (frame number) and fontconfig's default font, so no font path is hardcoded. The webm files are VP9/Opus and the mp4 is H.264/AAC. Each is written to a temp name and then renamed, and existing files are kept.
- **`make test-web`, `make e2e` and `make build` print a no-op message** until `web/` and `e2e/` exist (Phase 6).
- **The dev venv lives at `api/.venv`**, inside `Songbook/`.

## Phase 2

- **Real MeTube folder sample** (17 files): none has an `[id]` suffix. Extensions are mp3 ×7, webm ×5, mkv ×2, m4a ×2 and mp4 ×1, and several titles exist as both an audio file and a video file. Titles often put the song before the artist (`Into The Void - Black Sabbath - …`), and names contain Unicode (`｜`, `⧸`, emoji).
- **Accepted media extensions** everywhere (ingest regexes and the importer): `webm, mp4, mkv, mp3, m4a`, defined once in `media.py`. Audio-only songs are allowed: the player plays them without a picture, and Phase 5 renders must skip the video map for them. mkv isn't guaranteed to play in every browser.
- **A/V twins**: when an audio file (mp3/m4a) and a video file (webm/mp4/mkv) share a stem, the importer imports the video and reports the audio as `twin-skipped`.
- **Artist guess** splits the stem (minus any `[id]` suffix) on the first `" - "`, as specified. It's often wrong on real names, which is why `--dry-run` prints every guess for review. A stem with no separator, or an empty side, gives no artist (Unsorted). This is the one exception to "no automatic categorisation".
- **The importer reads the top level only**, because the real folder is flat. Hidden and partial files are reported as `unsupported`.
- **Importer actions**: `import-yt`, `import-local`, `duplicate` (the sha or ID is already in the library, or appears earlier in the same folder), `twin-skipped`, `unsupported`, and `conflict` (the destination path exists with different bytes, which is skipped).
- **Placement**: hardlink with `os.link`, falling back to a copy to `.<name>.tmp` plus `os.replace` on EXDEV/EPERM/EMLINK/ENOTSUP. The source is never moved or deleted.
- **`--dry-run` with no DB** plans against an in-memory DB, so a dry run never creates `songbook.sqlite`.
- **Accepted URL hosts**: `youtube.com`, `www.`, `m.`, `music.youtube.com`, `youtube-nocookie.com` (+`www.`), and `youtu.be`. The forms are `watch?v=`, `/shorts/`, `/embed/`, `/live/`, `/v/` and `youtu.be/<id>`, plus a URL with no scheme or a bare ID. Hostnames are matched exactly, so `notyoutube.com` is rejected.
- **`.info.json`**: `yt_title` (`title`) and `uploader` (`uploader`, else `channel`) are reference fields and are refreshed on every scan. The display `title` is set from them only when the song is created. An orphan or invalid `.info.json` is ignored.
- **Scan cost**: sha256 is computed only for a new row or when a song's file or status changes, so a periodic rescan doesn't re-hash every file.
- **Scan sha collisions**: if a file's bytes already belong to another song (`original_sha256` is UNIQUE), the scan logs and skips it rather than failing the whole scan.
- **Scan also flips `error` songs to `ready`** when their file appears, and clears `error`.

## Phase 3

- **MeTube contract** (read from the `ghcr.io/alexta69/metube:2026.09.26` image, `app/main.py`, and checked live against a throwaway container):
  - `POST /add` takes JSON `{url, download_type, quality, format, codec}`. Songbook sends `video` / `best` / `any` / `auto`.
  - It answers HTTP 200 `{"status": "ok"|"error", "msg"?}` as soon as the URL is **queued**. Re-adding a URL that's already queued or finished also returns `ok`.
  - A download that fails later is visible only in `GET /history`: `done[]` holds an entry with `id`, `url`, `status: "error"` and yt-dlp's `msg`.
  - `POST /delete {ids: [url], where: "done"}` clears history entries, which are keyed by URL.
  - MeTube's cross-origin guard only rejects requests that carry a foreign `Origin`. Server-to-server calls send none, so no `CORS_ALLOWED_ORIGINS` setting is needed.
  - A failed download still leaves an orphan `<id>.info.json`, which ingest already ignores.
- **Songbook always sends the canonical `watch?v=<id>` URL**, because MeTube turns `&t=` into a clip and `&list=` into a playlist.
- **The download job waits on both the filesystem and `/history`**. It succeeds when a strict `<id>.<ext>` file appears, fails at once on a MeTube error entry, and fails on timeout (`SONGBOOK_DOWNLOAD_TIMEOUT_S`, default 900; polling every `SONGBOOK_DOWNLOAD_POLL_S`, default 2).
- **Before each `/add`, the worker clears stale failed history entries for that ID**, so a retry isn't judged by an old error. If the file is already on disk, MeTube isn't called at all.
- **Retries**: `attempts` is incremented on claim. A failed attempt puts the job back to `pending` and the song back to `queued`. After 3 attempts the job and song become `error`, with the message stored on both. Retries are immediate (no backoff column) and run as the next job.
- **Re-adding a song in `error`** resets it to `queued`, clears `error`, enqueues a new job and returns 202, as the plan says.
- **Placeholder title**: a song added by URL without a title gets its ID as the title. A scan replaces it with `yt_title` while the title still equals the ID. A title the user gives, or edits later, is never overwritten.
- **`/api/songs` uses one DB connection per request** (a FastAPI dependency), because sync endpoints run in a thread pool and transactions on a shared connection would interleave. The add check-and-insert runs in `BEGIN IMMEDIATE`, and the `one_active_job` index catches anything that slips past.
- **Enqueue** is `INSERT … ON CONFLICT DO NOTHING RETURNING id`. A duplicate in-flight job is a no-op, not an error. `POST /api/library/rescan` returns `{"queued": bool}`.
- **Scan schedule**: the worker enqueues a scan at startup and every `SONGBOOK_SCAN_INTERVAL_S` (default 300). An idle worker sleeps `SONGBOOK_WORKER_IDLE_S` (default 1).
- **`METUBE_URL`** defaults to `http://metube:8081`, the compose service name.
- **`httpx` is now a runtime dependency** (the MeTube client).
- **Fake MeTube** (`tests/fake_metube.py`) is a Starlette app served by uvicorn on a free `127.0.0.1` port in a thread, so the worker's sync client talks to it unchanged. It mimics `/add` validation, `/history` error entries and `/delete`. Nothing leaves the machine.
- **The artist get-or-create is shared** (`artists.py`) between the API and the importer.

## Phase 4

- **Routes are split by area** in `api/songbook/routes/`: `songs`, `presets`, `groups` (artists, categories, reorder), `library` (library, rescan, jobs) and `media`. `main.py` only builds the app. The read-side shaping lives in `library.py`.
- **Deleting a song but keeping its file** records the path in a new `ignored_paths` table (migration 0002), which the scan skips. Without it, the next periodic rescan would bring the song straight back. Re-adding the URL or re-importing the file removes the entry. With `?delete_file=true` the file is deleted, and only if it resolves inside `originals/`. Either way `renders/<song_id>/` is removed, and a pending download job for the song is marked `error: cancelled: song deleted`.
- **`GET /api/songs/{id}/playback`** (not in the plan's table) answers "what plays when this song opens": the default preset's pitch, tempo and loop, else `semitones=0, tempo=1.0`. It covers the Gate 4 "no presets" test. In Phase 4 the source is always `original`; Phase 5 adds renders and `/api/presets/{id}/playback`. It returns 409 for a song that isn't `ready`.
- **Snapping**: both `tempo` and `semitones` snap to 0.01 on save, and `-0.0` is stored as `0.0`. `cache_key` is computed from the snapped values. `cache.py` holds the key function, and `fixtures/cache_keys.json` is the shared case table (Phase 6's vitest reads it too).
- **Preset PATCH** merges the stored preset with the patch, then validates the result as a whole, so `loop_a`/`loop_b` ordering is checked against the stored values. Validation errors are 422 and change nothing. A duplicate preset name per song is 409.
- **Duplicate names**: an artist or category name is unique regardless of case, and a clash returns 409.
- **Request bodies reject unknown fields** (`extra=forbid`) and strip whitespace.
- **`PATCH /api/songs`** accepts `artist_id` (an unknown id is 422) or `artist_name` (get-or-create, empty means Unsorted), not both. `title` can't be empty or null. Moving a song to another group clears its `sort_order`, since a manual position belongs to the old group.
- **`/api/library`** returns `{group_by, groups: [{id, name, columns, style, sort_order, songs}]}`. Groups are ordered by `sort_order` first, then name (case-insensitive). The pseudo-group (`Unsorted` or `Uncategorised`) has `id: null` and always comes last.
  - Unfiltered, empty groups are kept, so there's somewhere to drop songs. With `q` or `category`, empty groups are dropped.
  - Search is a case-insensitive substring match (`instr`, not `LIKE`, so `%` and `_` are literal) on title, artist name, `yt_title` and `uploader`.
  - Category groups have no columns or style of their own, so they use 4 / `row`.
- **`/api/reorder`** sets `sort_order` to each id's position, in one transaction. Every id must exist and, for songs, have `artist_id = group_id` (null means Unsorted). Duplicates are 422. `group_id` with `artists` or `categories` is 422. A partial list is allowed. Song order is per song, so `group_by=category` shows the same relative order.
- **`/media/*`** takes a numeric id as a string, so traversal attempts are 404, not 422. The path comes from the DB, is resolved strictly, and must stay inside `originals/` or `renders/`.
  - Range, If-Range and 416 are handled by Starlette's `FileResponse`.
  - Content types are set explicitly: webm, mp4, mkv (`video/x-matroska`), mp3 and m4a (`audio/mp4`).
  - Serving a render updates its `last_used_at`.
- **`GET /api/jobs`** returns newest first, with `?status=` and `?limit=` (default 100, max 1000). The payload is decoded.

## Phase 5

- **The test environment is Docker.** `rubberband-cli` isn't installed in the code-server dev container, and installing it there wouldn't survive a recreate. The `Dockerfile` therefore has a `runtime` stage (python:3.12-slim, ffmpeg, rubberband-cli 3.3.0, `fonts-dejavu-core` for the fixtures' `drawtext`) that Phase 7 builds on, plus a `test` stage. `make test-docker` builds it and runs the whole backend suite. `test_render.py` skips when rubberband is missing, so `make test-api` still works locally. **The gate counts only when run with `make test-docker`.**
- **Rubber Band flags**: `-3 -q`, then `-p <semitones>` for pitch. `-T <tempo>` is a tempo multiple (`-T 0.5` plays twice as long), used only when tempo is baked. There's no formant preservation (`-F`) by default; that's left for a future preset option.
- **Output container follows the original**, so the video can be stream-copied: webm → webm/Opus, mp4 → mp4/AAC, mkv → mkv/Opus. Audio-only originals (mp3, m4a) render to m4a/AAC. mp4 and m4a get `+faststart`.
- **"Has video"** means a video stream that isn't an attached picture, so an mp3's cover art doesn't count. Audio-only renders map no video.
- **Pitch-only renders stream-copy video** (`-map 0:v:0 -c:v copy`), which keeps it bit-identical (tested for webm, mp4 and mkv). Metadata and chapters are dropped.
- **Baked tempo re-encodes video** with `setpts=PTS/<tempo>`: VP9 (CRF 32, `good`, cpu-used 4) for webm, otherwise H.264 (`veryfast`, CRF 20).
- **Atomic output**: the work files go in `renders/<song_id>/.<key>.work/`, the muxed file is written to `.<key>.tmp.<ext>`, then `os.replace` puts it at `<key>.<ext>`. Leftovers for the key are removed before and after every attempt, so a hard crash's partial files are cleaned on the retry, and `gc` sweeps any others.
- **The render job payload** carries the snapped values and the key (`dedupe_key = rn:<song_id>:<key>`). It's retried 3 times, like downloads. A song deleted mid-render drops the file, because the insert of the render row fails on the foreign key. `SONGBOOK_RENDER_TIMEOUT_S` (default 3600) is the per-tool timeout.
- **Enqueue rules** (`cache.ensure_render`):
  - Nothing is enqueued for identity settings, a song that isn't `ready`, or a key whose file is cached.
  - A `renders` row whose file is gone is deleted and re-enqueued.
  - It runs on preset create and update, and on playback.
- **Playback** (`cache.playback`) is shared by `/api/presets/{id}/playback` and `/api/songs/{id}/playback`:
  - It returns `{preset_id, source, url, live_semitones, live_tempo, time_scale, loop_a, loop_b, render_error}`.
  - The key is recomputed from the preset's values. If `ENGINE_VERSION` changed, the stored `cache_key` is updated, so the old render is ignored and GC sees it as unreferenced.
  - **A failed render is not retried on every open**: playback returns `source: "original"` with live pitch and `render_error` set. Saving the preset again retries it.
  - A song that isn't `ready` returns 409.
- **GC** (`cache.gc`, `python -m songbook.cache gc --max-gb N`):
  - First it removes stray files under `renders/` that have no row, and stale work dirs.
  - Then it evicts unreferenced renders (no preset with that song and key), LRU first by `coalesce(last_used_at, created_at)`, then plain LRU, until the cache is under budget.
  - A row whose path resolves outside `renders/` is never deleted. Empty song dirs are removed.
  - Hourly scheduling from the worker is Phase 7.
- **numpy is a dev dependency** for the FFT tests. Each test takes the middle 60% of the audio, applies a Hann window, and interpolates the FFT peak.

## Phase 6

- **Live pitch: `@soundtouchjs/audio-worklet` 2.1.1.** Its licence is **MPL-2.0, not LGPL**. MPL-2.0 is GPL-3.0-compatible (§3.3, no "Incompatible With Secondary Licenses" notice in the package), so it qualifies under the plan's "or another GPL-3.0-compatible licence".
  - Its README documents `createMediaElementSource → SoundTouchNode`, and the node exposes a `pitchSemitones` AudioParam. The default `lanczos` interpolation is built into the processor bundle, which Vite emits via `?url`.
  - The package recommends `preservesPitch = false` plus SoundTouch compensating for the rate. We use the plan's split instead: the browser keeps pitch at any `playbackRate` (`preservesPitch = true`), and SoundTouch shifts pitch only. Its 128-sample blocks then never have to stretch time.
- **AudioWorklet needs a secure context** (HTTPS or localhost). Over plain HTTP on a LAN, the player falls back to playing the `<video>` directly and shows "live pitch unavailable". Cached renders still play shifted. The README in Phase 7 will say so.
- **Live pitch and tempo are relative to what's loaded.** Worklet pitch = wanted semitones − semitones baked into the current source. `playbackRate` = wanted tempo ÷ baked tempo (if tempo is baked). So moving the controls while a render is loaded just works, with no source swap.
- **Homepage fork: v2.7.0** (`2e5f1013`), recorded in NOTICE with every ported file. Each ported file has a header naming its upstream file and what changed.
  - Ported: the services group, list and item components, `columnMap` (per-group columns and row/column style), the colour themes, light/dark mode with the colour toggle, and the globals.
  - The quick-search bar follows quicklaunch's behaviour (type anywhere, Enter opens the top hit, Escape clears) as an always-visible field over the server-side search, not a modal with web search.
  - Stripped: widgets, stats, pings, icons, config loading, Next.js and i18n.
  - Tailwind v4 config is inlined in CSS (`@theme`, `@custom-variant dark`, `@plugin "@tailwindcss/forms"`). The Manrope webfont isn't bundled; a system font stack is used instead.
- **Cards open the player.** The title area is a `<button>`; there's no `<a>` and no navigation. Cards that aren't ready are disabled, with the status or error as a tooltip.
  - Every card shows the YouTube title and uploader as grey reference text, not only in Unsorted, because covers and re-uploads are hard to tell apart otherwise.
  - Chips: "local", the download status, the default preset's name, and categories.
- **"Inline edit" is an edit dialog** (title, artist with autocomplete, notes, categories with inline create), reached from each card's ⋯ menu. The menu items "Edit…", "Set artist…" and "Set categories…" focus the relevant field.
  - Deleting asks whether to also delete the original file.
  - Linking shows the 409 owner as a toast with an "Open" link.
- **Drag and drop uses native HTML5 DnD**:
  - A song dropped on a card goes before that card. If the card is in another artist group, the song also moves to that artist.
  - A song dropped on a group goes to the end of that group.
  - Group headers have a drag handle, and dropping one before another group reorders the groups.
  - Keyboard and menu alternatives: "Move up/down" in the card menu, and "Move earlier/later" in the group settings.
  - In category view, song drag is off, because `sort_order` is per song and grouping by category would make "the group" ambiguous. Category groups can still be reordered.
- **Artist settings** (a gear on the group header): rename, columns (1–8), style (row/column), move earlier/later, delete. The category manager (toolbar) does create, rename, recolour (`<input type=color>`), reorder and delete.
- **Toolbar**: search, Group by Artist/Category, a category filter, Add song, Categories, Rescan library, a job indicator (it polls `/api/jobs` and refreshes the library whenever the active count changes), and the colour and theme toggles. Group-by, the filter, theme and colour are remembered in `localStorage`, behind try/catch.
- **Player**:
  - Every open mounts a fresh `<video>` (React `key`) and builds a new AudioContext and graph. Close pauses, drops `src`, disconnects, closes the context, unlocks body scroll and restores focus.
  - **No `<StrictMode>`**: its double-run of effects in development would call `createMediaElementSource` twice on one element.
  - Save dialog: name, "Make this the default for this song" (unchecked for a new preset; for "Save preset" on an existing one it starts at that preset's current state, so a plain re-save doesn't silently drop the default), and "Bake tempo into the render (slow)", off by default.
  - "Save preset" with no preset selected creates one. "Reset to original" goes back to 0 / 1.0× and the original file with no A/B (2026-11-01: a preset's loop points used to carry over), and stores nothing. Picking "(original)" does the same.
  - While a render is pending, the player polls `api/presets/{id}/playback` every second. When the render is ready, it swaps `src`, mapping the position by `time_scale`, and keeps playing.
  - The loop is checked every frame with `requestVideoFrameCallback`, or `requestAnimationFrame` for audio-only media or when paused. Setting A/B divides the current time by `time_scale`, so loop points stay in original-timeline seconds.
  - The controls auto-hide after 2 s without mouse movement (by opacity, not removal), and stay up while hovered or focused. F toggles fullscreen on the modal itself.
  - Shortcuts are ignored while typing in a text field or select. Space on a focused button toggles play without also clicking the button.
  - `window.__songbook` exposes read-only state (getters for live values) plus `graph`, `audioState` and `errors` (any `createMediaElementSource` failure) for Playwright.
- **API URLs are relative** (`media/originals/1`, not `/media/…`), in the API's own responses too, and Vite builds with `base: './'`, so the UI works under any subpath. The API serves `web/dist` with `StaticFiles(html=True)` when `SONGBOOK_WEB_DIR` points at it. It's mounted after the API routes, so they win.
- **`scripts/dev_stack.py`** runs the API, the worker thread, the fake MeTube and the built UI in one process over a scratch root seeded with the two webm fixtures. It backs both `make dev` and Playwright.
  - The fake writes `.info.json` and tags each copy with its ID (an ffmpeg remux), so a fake download doesn't collide with a seeded fixture on `original_sha256`.
  - Dev-only `POST /__dev/reset` and `GET /__dev/calls` are added to the API app by this script only.
  - **The root is wiped on start and on every reset, so the script refuses any non-empty folder without its `.songbook-dev-root` marker.** `make dev` uses `.dev-data/` (gitignored), never `data/`.
- **Where things run.** vitest and the Vite build run locally (code-server has Node 22) and also inside the Dockerfile's `web` stage. Playwright runs in the `e2e` stage: `mcr.microsoft.com/playwright:v1.64.1-noble` plus python3, ffmpeg and rubberband-cli, against `dev_stack.py`, one test at a time, with Chromium launched with `--autoplay-policy=no-user-gesture-required`.
- **Pinned versions**: React 19.3.1, Vite 8.3.5, Tailwind 4.3.3, vitest 5.0.5, `@headlessui/react` 2.2.10, Playwright 1.64.1. TypeScript is held at 5.9.3, not the new 7.x.

## Phase 7

- **MeTube user and group** (from the image's `docker-entrypoint.sh`, 2026.09.26): it reads `PUID`/`PGID` natively (`UID`/`GID` are legacy aliases that win if set). Started as root, it chowns its dirs (`CHOWN_DIRS`, default true) and drops to `PUID:PGID` with gosu. So compose passes our `PUID`/`PGID` straight through, with no mapping. `CHOWN_DIRS` stays on, because Docker creates missing bind-mount dirs as root and MeTube must be able to write them.
- **MeTube paths**: `STATE_DIR=/state` (its own `data/metube-state/`, out of `originals/`). `TEMP_DIR=/downloads/.metube-tmp`, on the same filesystem so finished files are renamed in; the scan ignores subdirectories and partial names anyway. `OUTPUT_TEMPLATE` and `YTDL_OPTIONS` as in §1, with no `download_archive`. The MeTube image is pinned to `2026.09.26` (`METUBE_VERSION`).
- **The Songbook image entrypoint** (`docker/entrypoint.sh`) starts as root:
  - It creates `originals/local` and `renders`, chowns only those top-level dirs and the sqlite files (never a recursive walk of the library), then re-runs itself as `PUID:PGID` via `setpriv` (in Debian's util-linux, so no gosu).
  - `api` runs uvicorn on 8080, `worker` runs the worker, and anything else is run as given (e.g. `python -m songbook.import_legacy`).
  - The worker waits for the api to be healthy, so the dirs and migrations are in place first.
- **`SONGBOOK_BASE_PATH` is read at runtime.** When set, the FastAPI app is mounted under it in a small Starlette wrapper, which also forwards the lifespan, because mounted apps don't get lifespan events. `/songbook` redirects (308) to `/songbook/`, and nothing is served at `/`. The proxy must pass the prefix through, not strip it. Paths are normalised (`songbook/` becomes `/songbook`), and `..` or empty segments are rejected at startup.
- **Built-in auth** is a pure ASGI middleware (so streaming isn't buffered), on only when both `SONGBOOK_AUTH_USER` and `SONGBOOK_AUTH_PASSWORD_HASH` are set.
  - `<base>/api/health` stays open, and everything else, including the UI and media, needs credentials.
  - bcrypt is checked once per distinct `Authorization` header, then remembered in memory by SHA-256 (at most 64 entries), because the player makes many Range requests. The username compare is constant-time. A malformed hash denies rather than crashes.
  - `bcrypt` is now a runtime dependency.
- **Healthchecks** (`python -m songbook.healthcheck api|worker`):
  - The api check fetches `<base>/api/health`, which runs a DB query.
  - The worker touches `SONGBOOK_HEARTBEAT` (`/tmp/songbook-worker.heartbeat` in the image) from a thread every 15 s, so a long render doesn't look like a hang. The check wants it younger than 60 s.
  - MeTube is checked with curl on its own port.
- **Hourly cache GC from the worker** (`SONGBOOK_CACHE_MAX_GB`, default 20 in compose and unset, meaning off, outside it; `SONGBOOK_GC_INTERVAL_S`, default 3600). It runs between jobs, never during a render. GC now leaves hidden temp files and `.work` dirs alone unless they're older than twice the render timeout, so a manual `python -m songbook.cache gc` can't delete a render in progress.
- **Ports**: only the api is published (`SONGBOOK_BIND:SONGBOOK_PORT`, default `0.0.0.0:8080`). MeTube's own UI is opt-in via `compose.metube-ui.yml`, which binds `127.0.0.1:8081`.
- **`compose.fake-metube.yml`** swaps MeTube for the fake from `api/tests`, run as `PUID:PGID` from the `test` image with `volumes: !override` (Compose 2.24+), for the containerised smoke run. `python -m tests.fake_metube` serves it.
- **Gate 7 runs as `scripts/compose_test.sh`** (`make compose-test`):
  - It works from a clean copy of the checkout (tracked plus new, non-ignored files) in `.compose-test/`, so a real `.env` or `data/` is never touched, and it refuses to run while a `songbook` compose project is up.
  - It checks:
    - defaults reach healthy, the UI is served, there's no auth, and the tools are in the image, with ownership at 1000:1000
    - the Playwright smoke subset passes against the containers with the fake MeTube
    - PUID/PGID 1234 plus `SONGBOOK_BASE_PATH=/songbook` passes the smoke subset under the subpath, and every file written is owned by 1234:1234
    - auth, with the hash written with `$$` in `.env`
    - the static checks
  - HTTP probes run in a `--network host` container (`scripts/http_probe.py`), because code-server is on its own bridge network. Playwright's smoke run uses host networking too, so the page is on `localhost`, a secure context where the audio worklet is available.
- **Playwright smoke subset** (`e2e/tests/smoke.spec.ts`): it runs only when `E2E_BASE_URL` is set, with no dev reset hook. It adds a song with a random ID through the UI, plays it in the modal, and saves a +2 default preset until "cached". It then fetches the render with a Range request and reopens after a reload.
- **Static checks** (`scripts/check_self_contained.py`):
  - Outside docs, every domain must be on a short allowlist (the YouTube hosts the parser accepts, plus credit URLs).
  - Nowhere, docs included, may `*.local`/`*.lan`/`*.home`/`*.internal` names or private IPs appear.
  - There are no symlinks, and every `../` path in a file must resolve inside `Songbook/`.
  - The checker was itself checked with a planted file (a `.local` URL, a private IP, a `../` escape and an unlisted domain), and all four were flagged.
- **The `app` stage comes right after `runtime`**, ahead of `test` and `e2e`. The classic builder (no BuildKit, as on the first deploy host) builds every stage before `--target`, so with `app` last a production build pulled Playwright and built the test image too. Always build with `--target`. Compose builds `target: app` and tags it `SONGBOOK_IMAGE` (default `songbook:latest`).
- **Shell variables beat `.env` in Compose.** The first Gate 7 run "passed" PUID 1234 into `.env`, but the containers ran as 1000, because the calling shell (a linuxserver-style container) exports `PUID`/`PGID`. `compose_test.sh` now runs compose with every `.env.example` key unset, so `.env` is the only source. The README and `.env.example` warn about this precedence.

## After Phase 7

- **The definition of done's legacy-import review was waived by the owner** ("No import needed", 2026-10-26). The dry run against the real MeTube folder was shown in Phase 2. The importer stays available (`python -m songbook.import_legacy`) but hasn't been run on real data.
- **Rubber Band now renders tempo too, for every saved preset** (the owner's call, 2026-10-26, for quality). This supersedes the plan's "bake_tempo is allowed but never the default".
  - `bake_tempo` defaults to true in the API, and the UI always sends true, so the "Bake tempo" checkbox is gone. The API still accepts `bake_tempo: false` (live-only tempo), for scripts and compatibility.
  - Rendering at a tempo no longer re-encodes video: the packets are stream-copied, and the `setts` bitstream filter divides their timestamps by the tempo (`-avoid_negative_ts make_zero`, without which an H.264 MP4's unscaled edit list dropped the first two frames). Every frame is bit-identical and the render is as fast as a pitch-only one. Tested for webm and mp4 at 0.5× and 1.25× (packets, decoded frames, frame count and stream duration), plus pitch and tempo together and audio-only.
  - Tempo-only presets (0 semitones) now render too, so a slowed-down song is Rubber Band quality rather than the browser's time-stretch.
  - The live controls remain a preview (SoundTouch pitch, browser tempo) until the render is ready. Then the player switches to the render at `playbackRate` 1, mapping the position by `time_scale`.
  - The cost: each distinct pitch-and-tempo pair is its own render, so the cache grows faster. GC still caps it at `SONGBOOK_CACHE_MAX_GB`.
- **Seek bar** (owner's request, 2026-10-26): a full-width position slider is the first row of the player controls, with `m:ss` position and length, and markers for A/B.
  - Position and length are on the **original timeline**, like loop points, so a spot in the song has the same time whichever render is playing. A half-tempo render of a 10 s song shows 0:10.
  - Dragging scrubs, seeking as it moves. The display updates on `timeupdate` (about 4 Hz), which is enough for a clock and avoids re-rendering the player every frame.
  - Keys: ← and → jump 5 s, and Home goes to the start. These are added to the tested shortcut reducer. They're ignored while a slider (position or tempo) has focus, so its own arrow keys still work.
- **The most recently saved preset becomes the song's default** (owner's request, 2026-10-26). This supersedes the plan's "Make this the default" checkbox, unchecked by default.
  - Both "Save preset" and "Save as…" send `is_default: true`, and the API's existing one-default rule clears the previous one. The checkbox is gone.
  - So the song never gets stuck opening shifted, an **"Open at original"** button appears next to the preset selector whenever the song has a default. It clears the default (`is_default: false`) and stores nothing else.
  - The API itself still defaults `is_default` to false for other clients.
  - **"Save preset" updates the loaded preset only if its name is kept** (owner's report, 2026-11-01). Since a song opens with its default, a preset is nearly always loaded, so typing a new name in "Save preset" renamed and overwrote it: A Tout Le Monde lost its earlier presets that way. A new name now creates a new preset, the same as "Save as…".
- **A trash can after the Preset selector deletes the selected preset** (owner's request, 2026-11-01). It shows only while a preset is selected, sits away from the save buttons, and asks first.
  - The confirm is an overlay inside the player, like the Save dialog. A Headless UI dialog would portal outside the player and be invisible in fullscreen.
  - After a delete, the player goes back to the original. Deleting the default leaves the song with none; no older preset is promoted. The render stays cached until GC.
  - No keyboard shortcut. Escape in either dialog closes only the dialog (it stops propagation, since React re-renders before the player's document listener sees the key).
- **The artist field suggests as you type** (owner's request, 2026-10-26). This replaces the native `<datalist>`, which some browsers barely show (Firefox, phones).
  - `SuggestInput` is used for the artist field in the Add and Edit dialogs. The best prefix match shows greyed after the cursor, and Tab or → takes it. A list shows up to 6 matches, prefix matches first and then word matches ("sabb" finds "Black Sabbath"). Pick one with ↑/↓ and Enter, or click it. Matching ignores case and accents. Free text still works.
  - Enter only picks a suggestion you've moved to with the arrows, so typing a new artist that's a prefix of an existing one ("Black" when "Black Sabbath" exists) and pressing Enter submits what you typed.
  - Escape closes the list without closing the dialog. Headless UI's Dialog ignores an Escape whose default was prevented.
  - Titles were suggested from the library at first. The owner replaced that the same day with the guess below, so the title field is plain text again.
- **Add song guesses artist and title from the URL** (owner's request, 2026-10-26).
  - Once a URL is typed or pasted (300 ms debounce), the UI calls `GET /api/youtube?url=`. The api asks YouTube's oEmbed endpoint for the video's title and channel. It needs no API key and doesn't start a download.
  - `songbook/guess.py` does the guessing. It drops "(Official Video)"-style asides, and suffixes like "Guitar Backing Track" or "Lesson", since categories record those better. It splits on " - ", " – ", " — " or " | ". It uses the library's artists, then the channel name, to tell "Artist - Title" from "Title - Artist" and to fix spelling ("BLACK SABBATH" → "Black Sabbath"). A colon only splits when the left side is a known artist or matches the channel, so "Lesson 1: …" doesn't count. A "<artist> - Topic" channel gives the artist when the title has none.
  - A guess only fills a field that's blank or still holds the previous guess. Anything you've typed stays. The video's YouTube title and channel show under the URL, with "already in your library" for duplicates.
  - The lookup is best effort. If YouTube is unreachable or refuses (private or non-embeddable video), the fields are null and adding works as before. `SONGBOOK_OEMBED_URL=` (empty) turns it off, so the api never contacts YouTube. Answers are cached in memory (256 videos), failures aren't.
  - Tests never reach YouTube: the fake MeTube also serves `/oembed`, and the dev stack and `compose.fake-metube.yml` point there.
- **Artist pictures from TheAudioDB** (owner's request, 2026-10-26), shown as a small round icon left of the artist's name in artist grouping.
  - The worker does the lookups, only when its queue is idle, so they never delay a download or render. An artist is "pending" when `artists.image_checked_at` is NULL (migration 3). That covers new artists and every artist that existed before (the backfill) the same way, with no separate backfill step. `python -m songbook.artist_images` runs the pending lookups by hand, but the worker gets to them anyway.
  - One lookup every 2 s at most (the free key `123` allows 30 requests a minute). With nothing pending, the worker checks again every 10 s, so a new artist's picture appears within seconds.
  - TheAudioDB's search is fuzzy ("Sabbath" finds Black Sabbath), so a result is only taken when its name or an alternate name matches ours, ignoring case, accents and punctuation (the guess's `_squash`, so "AC/DC" matches "ACDC").
  - The `/small` thumbnail (about 250 px, about 12 KB) is saved as `artist-images/<id>.<ext>`, falling back to the full image if there's no small one. Only JPEG, PNG or WebP up to 2 MB is accepted.
  - No match, or a broken image, is recorded as a miss (`image_path` NULL, `image_checked_at` set) and retried after 30 days, since TheAudioDB's catalogue grows. When TheAudioDB is unreachable, rate-limiting or answering 5xx, nothing is recorded and the worker waits 10 minutes.
  - The api serves the file at `media/artists/<id>` (path from the DB, never the URL). The library's `image_url` carries `?v=<fetch time>`, so the browser caches it for 30 days, and a new picture gets a new URL.
  - A rename to a different name (not just a different case or punctuation) clears the picture, so the worker looks the new name up. Deleting an artist deletes its file. If the artist is renamed or deleted while a lookup runs, the result is dropped.
  - `artist-images/` belongs in backups (it's small). The database records that an artist was looked up, so restoring the database without the files would leave artists without pictures until they're renamed.
  - Tests never reach TheAudioDB: `conftest.py` sets `SONGBOOK_AUDIODB_URL=` (off), and the fake MeTube also serves a fake `/audiodb/search.php` with generated PNGs, used by `test_artist_images.py`, the dev stack and `compose.fake-metube.yml`.

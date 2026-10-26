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

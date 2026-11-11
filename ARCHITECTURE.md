# TuneAlong architecture

How TuneAlong is put together: its components, how they talk to each other,
and where each kind of data lives. For why things are the way they are, see
[DECISIONS.md](DECISIONS.md); for setup and configuration, see
[README.md](README.md).

Last reviewed 2026-11-11.

## Overview

TuneAlong is a self-hosted play-along library. It stores songs from YouTube,
local files, browser-tab recordings and Guitar Pro / MusicXML tab files, and
plays them back at any pitch and tempo with A/B looping. It is one Docker
Compose project of three containers that share a SQLite database and a data
folder.

| Component | Runs as | Job |
| --- | --- | --- |
| `api` | uvicorn + FastAPI (Python 3.12), port 8080 | JSON API, the built web UI, and media files with Range support |
| `worker` | the same image, `worker` command | Job queue: downloads, library scans, Rubber Band renders, cache GC; idle-time H.264 copies and artist pictures |
| `metube` | `ghcr.io/alexta69/metube:2026.09.26` | yt-dlp behind an HTTP API; only the worker talks to it, no published port |
| Web UI | React 19 + Vite 8 + Tailwind 4, served by `api` | Library grid (ported from Homepage v2.7.0), add-song dialog, player |
| SQLite | `data/tunealong.sqlite`, WAL | Songs, artists, categories, presets, renders, jobs |

```
                    Browser: the TuneAlong web UI
        (library, player, SoundTouch pitch worklet, alphaTab for tabs)
                                  |
                                  | HTTPS
                                  v
                 Reverse proxy (TLS, optional auth)
                                  |
                                  v
     +-----------------+                     +------------------+  /add  +------------+
     |       api       |                     |      worker      | -----> |   metube   |
     | JSON API, UI,   |                     | jobs: downloads, |        | yt-dlp,    |
     | media (Range)   |                     | scans, renders;  |        | to YouTube |
     +-----------------+                     | idle: H.264,     |        +------------+
       | queues jobs,                        | artist images    |              |
       | reads state                         +------------------+              |
       |                        claims jobs |          | writes files          |
  +----|------------------------------------|----------|-----------------------|----+
  |    v              data/                 v          v                       v    |
  |  +--------------------------------------+   +------------------------------+   |
  |  | tunealong.sqlite                      |   | originals/   playback/       |   |
  |  | songs, artists, categories, presets, |   | renders/     artist-images/  |   |
  |  | renders, jobs (WAL)                  |   +------------------------------+   |
  |  +--------------------------------------+                                      |
  +--------------------------------------------------------------------------------+
```

The api and worker never call each other: the api writes jobs to SQLite and
the worker claims them. Outside calls are few: the api asks YouTube oEmbed for
titles, the worker asks TheAudioDB for artist pictures, and MeTube downloads
from YouTube. Each can be turned off (see `.env.example`).

The project is self-contained: nothing in it names a particular deployment,
which `scripts/check_self_contained.py` enforces. Site-specific wiring (reverse
proxy, DNS, backups) belongs outside this folder.

Three design rules run through every part:

- **Originals are never altered.** Pitch and tempo changes are either applied
  live in the browser or rendered to a separate cached file.
- **Positions are on the original timeline.** Loop points, the seek bar and
  saved positions are seconds of the unmodified song, so they mean the same
  spot whichever render or speed is playing.
- **Every judgement call is written down** in [DECISIONS.md](DECISIONS.md),
  newest last. Read it before changing behaviour.

## Deployment

`docker compose up -d` runs the three containers from `compose.yml`. Only the
api is published (`TUNEALONG_BIND:TUNEALONG_PORT`, default `0.0.0.0:8080`);
MeTube's own UI is opt-in through `compose.metube-ui.yml`. Every setting is an
environment variable with a default, listed in `.env.example`.

**Put it behind HTTPS.** The live pitch shifter is an AudioWorklet and screen
recording uses `getDisplayMedia`; browsers allow both only on a secure origin
(HTTPS or localhost). Over plain HTTP on a LAN the player still works, but
pitch changes only through cached renders, and "Record a tab" is disabled.

**Authentication** is the reverse proxy's job in most deployments. For a
setup without one, built-in basic auth turns on when both
`TUNEALONG_AUTH_USER` and `TUNEALONG_AUTH_PASSWORD_HASH` (bcrypt) are set;
`/api/health` stays open.

**Subpaths.** `TUNEALONG_BASE_PATH=/tunealong` serves the whole app under that
prefix, read at runtime, so the same image works at `/` or under a subpath.
The proxy must pass the prefix through, not strip it.

**Healthchecks**

| Container | Check |
| --- | --- |
| `api` | `python -m tunealong.healthcheck api`: fetches `/api/health`, which runs a DB query |
| `worker` | `python -m tunealong.healthcheck worker`: a heartbeat file the worker touches every 15 s must be under 60 s old |
| `metube` | curl on its own port |

The worker waits for the api to be healthy before starting, because the api
creates the data folders and applies migrations.

**Data on disk** (`TUNEALONG_DATA`, default `./data`, owned by `PUID:PGID`)

| Path | Holds | Back it up? |
| --- | --- | --- |
| `tunealong.sqlite` | The curated library, presets, jobs | Yes |
| `originals/` | Downloads, `local/` (imports and recordings), `tabs/` | Yes |
| `artist-images/` | TheAudioDB thumbnails | Yes (small) |
| `renders/` | Rubber Band render cache, capped by `TUNEALONG_CACHE_MAX_GB` (default 20) | No, rebuilt on demand |
| `playback/` | H.264 playback copies | No, rebuilt from originals |
| `metube-state/` | MeTube's queue | No |

## Data model

All state is one SQLite file, opened per request in autocommit mode with
explicit `BEGIN IMMEDIATE` transactions, WAL and a 5 s busy timeout, so the api
and worker can write side by side. Every file path in it is relative to
`TUNEALONG_ROOT`, so the data folder can move.

| Table | One row per | Key columns and rules |
| --- | --- | --- |
| `songs` | Song in the library | `kind` media or tab; `youtube_id` (NULL = local); `status` queued → downloading → ready, or error; `original_path`, `original_sha256` (UNIQUE, so the same bytes are never added twice); `playback_path` + `playback_state`; `tab_track`; `sort_order` within its group |
| `artists` | Artist group | Name unique ignoring case; `columns` 1–8 and `style` row/column for the grid; `image_path`, `image_checked_at` |
| `categories`, `song_categories` | Tag, and its songs | Many-to-many; a colour and an order per category |
| `presets` | Saved pitch/tempo setting for a song | `semitones` −12..12, `tempo` 0.25–2.0, `loop_a`/`loop_b` (original-timeline seconds, A < B), `volume` 0–2, `bake_tempo`, `cache_key`; name unique per song; at most one `is_default` per song (partial unique index) |
| `renders` | Cached rendered file | `(song_id, cache_key)` unique, `path`, `bytes`, `last_used_at` for LRU |
| `jobs` | Unit of worker work | `kind` download / render / scan, JSON `payload`, `status`, `attempts`; `dedupe_key` is unique among pending and running jobs, so a duplicate enqueue is a no-op |
| `ignored_paths` | Deleted song whose file was kept | Stops the periodic scan from re-adding it |

**Migrations.** `api/tunealong/schema.sql` is version 1;
`api/tunealong/migrations/NNNN_*.sql` apply in filename order, each in its own
transaction with the version re-checked under the lock, so both containers can
start at once.

| # | Adds |
| --- | --- |
| 7 | `songs.playback_path`, `playback_state` (existing songs set to `skip`) |
| 6 | `songs.kind`, `songs.tab_track` |
| 5 | Widens `presets.volume` to 0–2 (copy-and-rename, since SQLite can't alter a CHECK) |
| 4 | `presets.volume` |
| 3 | `artists.image_path`, `image_checked_at` |
| 2 | `ignored_paths` |

**What the default preset means.** A song opens with its `is_default` preset,
or at the original pitch and tempo when it has none. Saving a preset or picking
one in the player's selector makes it the default; picking "(original)" or
"Open at original" clears it.

## API service

The api is a FastAPI app built by a factory (`create_app()`, run with
`uvicorn --factory`) and does no slow work itself: anything that takes longer
than a request (downloading, rendering, scanning) becomes a row in `jobs` for
the worker. Routes are split by area in `api/tunealong/routes/`; `main.py` only
assembles them and mounts the built UI last, so API routes always win.

| Area | Endpoints | Notes |
| --- | --- | --- |
| Songs | `POST /api/songs` (YouTube URL), `POST /api/songs/tab`, `POST /api/songs/recording`, `GET`/`PATCH`/`DELETE /api/songs/{id}`, `POST .../link`, `PUT .../categories` | Adding by URL queues a download job and returns 202; uploads stream to a temp file with a size cap, hash as they go and 409 on known bytes |
| Presets | `GET`/`POST /api/songs/{id}/presets`, `PATCH`/`DELETE /api/presets/{id}` | Values snap to 0.01; the merged result is validated as a whole (422); a duplicate name is 409 |
| Playback | `GET /api/songs/{id}/playback`, `GET /api/presets/{id}/playback` | "What plays when this opens" (below) |
| Library | `GET /api/library`, `POST /api/library/rescan`, `GET /api/jobs` | Grouped by artist or category, with search and a category filter |
| Groups | `/api/artists`, `/api/categories` (CRUD), `POST /api/reorder` | Reorder sets `sort_order` from list position in one transaction |
| YouTube | `GET /api/youtube?url=` | oEmbed title and channel for the add dialog, plus the artist/title guess; cached for 256 videos, best effort |
| Media | `GET /media/originals/{id}`, `/media/renders/{id}`, `/media/artists/{id}` | Paths come from the DB, never the URL, and must resolve inside the data folder; Range requests via Starlette `FileResponse` |
| Health | `GET /api/health` | Runs `SELECT 1`, so a broken DB fails the healthcheck |

**Playback resolution** (`cache.playback`) answers
`{preset_id, source, url, live_semitones, live_tempo, time_scale, loop_a, loop_b, render_error}`:

1. Recompute the preset's cache key from its values (and the render engine
   version).
2. If a render for that key is on disk, return `source: "render"` with live
   pitch and tempo relative to what is baked in, and `time_scale` = the baked
   tempo.
3. Otherwise queue the render (`ensure_render`) and return
   `source: "original"` with the full pitch and tempo to apply live; the
   player polls until the render appears.
4. A failed render is not retried on every open: it returns the original with
   `render_error` set, and saving the preset again retries.
5. Tab songs always get `source: "tab"`; nothing is rendered for them.

`/media/originals/{id}` serves the H.264 playback copy when one exists and
falls back to the original, so URLs never change when a copy is made.

**Cross-cutting**

- Every URL the api returns is relative (`media/originals/1`), which is what
  makes `TUNEALONG_BASE_PATH` work.
- The built-in basic auth is a pure ASGI middleware, so media streaming is
  never buffered; it caches checked headers because the player makes many
  Range requests.
- Request bodies reject unknown fields and strip whitespace; each request gets
  its own DB connection.

## Worker

The worker is a single-threaded loop (`api/tunealong/worker.py`) that takes one
job at a time from the `jobs` table, so a render never competes with another
for CPU. Each pass of the loop does the first thing that applies:

1. Queue a library scan if one is due (at startup and every
   `TUNEALONG_SCAN_INTERVAL_S`, default 300 s).
2. Run cache GC if due (hourly, never during a render).
3. Claim and run the oldest pending job: download, render or scan.
4. Queue empty: make one song's H.264 playback copy.
5. Still idle: look up one artist picture.
6. Nothing to do: sleep 1 s.

A separate heartbeat thread touches a file every 15 s, so a 20-minute render
does not look like a hung container.

| Job | What it does | Failure handling |
| --- | --- | --- |
| `download` | Sends the canonical `watch?v=<id>` URL to MeTube's `POST /add`, then waits for a strict `<id>.<ext>` file to appear while watching `/history` for an error entry; then scans that one ID | Up to 3 attempts; then the job and song become `error` with yt-dlp's message. Times out after `TUNEALONG_DOWNLOAD_TIMEOUT_S` (900 s) |
| `scan` | Walks `originals/` (top level, plus `local/` and `tabs/`): creates songs for new files, refreshes `yt_title`/`uploader` from `.info.json`, flips `error` songs to `ready` when their file appears | Hashes only new or changed files; a file whose bytes belong to another song is logged and skipped |
| `render` | Runs ffmpeg + Rubber Band for one `(song, cache_key)` (Media pipeline, below) | Up to 3 attempts; a failed render is reported through playback, not retried on each open |

**Idle work is not queued.** H.264 copies and artist pictures are picked by
one query each (`playback_state = 'pending'`, `image_checked_at IS NULL`)
rather than enqueued, so a new song, scan, recording or import is covered
without extra wiring, and downloads and renders always go first.

**Artist pictures** come from TheAudioDB's free API, at most one lookup every
2 s. A result counts only when its name matches ours ignoring case, accents
and punctuation. The thumbnail is saved as `artist-images/<id>.<ext>`; a miss
is retried after 30 days, and an outage backs off 10 minutes.

**Enqueueing is idempotent:** `INSERT … ON CONFLICT DO NOTHING` against the
`one_active_job` index on `dedupe_key` (for example `rn:<song_id>:<key>`), so
a render asked for twice runs once.

## Media pipeline

A song has up to three kinds of file. The original is kept exactly as
received, the H.264 copy makes it play in every browser, and renders hold
saved pitch/tempo settings at studio quality.

| File | Path | Made by | Lifetime |
| --- | --- | --- | --- |
| Original | `originals/<youtube_id>.<ext>`, `originals/local/…`, `originals/tabs/<sha16>.<ext>` | MeTube, the importer, an upload or a recording | Permanent; back it up |
| Playback copy | `playback/<song_id>.mp4` | Worker, when idle | Permanent until re-queued; rebuilt from the original |
| Render | `renders/<song_id>/<cache_key>.<ext>` | `render` job | Cache; LRU-evicted by GC |

**Originals.** Downloads keep YouTube's best format (often AV1 or VP9),
because the rule is to always store the highest quality. Accepted media is
webm, mp4, mkv, mp3 and m4a; audio-only songs play without a picture. A
browser recording is remuxed with ffmpeg (`+bitexact`) on upload to add the
duration and cues MediaRecorder leaves out.

**Playback copies.** Safari will not play AV1, so each new song gets an H.264
copy beside the original: libx264 CRF 18, preset medium, same resolution, a
keyframe every 2 s for clean seeks and A/B loops, AAC 256k, `+faststart`.
Copies run several times larger than AV1 (one went from 107 MB to 378 MB).
Songs from before this change are `skip` and converted on request with
`python -m tunealong.playback queue <id>` (or `queue all`). Making a copy drops
that song's renders, which re-render on demand.

**Renders.** A preset that changes pitch or tempo gets a render, made with
Rubber Band (`rubberband -3 -q -p <semitones> -T <tempo>`) on the audio:

1. Decode the original's audio and run Rubber Band on it.
2. Take the video from the playback copy when there is one (else the
   original) and stream-copy it. The bits are untouched; for a tempo change,
   ffmpeg's `setts` filter divides the timestamps by the tempo.
3. Mux into a work file, then `os.replace` it into place, so a crash never
   leaves a half file under the real name.

Video is never re-encoded, so a render takes about as long as its audio
processing. Audio-only songs render to m4a.

**Cache keys** name a render by its settings: `p+2.00_t0.850_bt1_rb3-v1` is
+2 semitones at 0.85× tempo with tempo baked in. Values snap to 0.01 first.
Bumping `ENGINE_VERSION` in `cache.py` gives every preset a new key, so stale
renders are simply never asked for again and GC removes them. The same key
function is tested from Python and TypeScript against one shared table,
`fixtures/cache_keys.json`.

**`time_scale`** is the tempo baked into whatever is playing. The player
divides positions by it, so loop points, the seek bar and saved positions stay
in original-timeline seconds across renders: a half-speed render of a 10 s
song still shows 0:10.

**GC** (`cache.gc`) runs hourly with a `TUNEALONG_CACHE_MAX_GB` budget. It
removes stray files and stale work folders first, then evicts renders that no
preset references (oldest use first), then plain LRU until under budget. It
never deletes outside `renders/`, and it never touches a work folder younger
than twice the render timeout.

## Web UI

The UI is a single-page React 19 app (`web/`, Vite 8, Tailwind 4, TypeScript
5.9) built into `web/dist` and served by the api. It never navigates: the
library is the page, and a song opens in a modal player. All URLs are relative
and Vite builds with `base: './'`, so it works under any subpath.

| Part | Files (under `web/src/`) | What it does |
| --- | --- | --- |
| Library grid | `components/services/*`, `lib/columns.ts`, `lib/library.tsx` | Groups by artist or category, with per-group columns and row/column style; ported from Homepage v2.7.0 (credited in NOTICE) |
| Toolbar | `components/toolbar.tsx`, `quicksearch.tsx`, `jobIndicator.tsx` | Type-anywhere search, group-by, category filter, rescan, theme/colour toggles; the job indicator polls `/api/jobs` and refreshes the library when the active count changes |
| Add song | `components/addSong.tsx`, `recordPanel.tsx`, `suggestInput.tsx` | Three modes (YouTube URL, tab file, record a tab); URL lookup guesses artist and title; artist field autocompletes |
| Edit and organise | `songDialogs.tsx`, `categoryManager.tsx`, `categoryPicker.tsx` | Edit dialog, categories, native drag and drop to reorder songs and groups |
| Player | `components/player.tsx` | Playback, pitch, tempo, volume, presets, A/B loop, seek bar, fullscreen |
| Audio | `lib/audioGraph.ts` | Live pitch and volume chain |
| Tabs | `lib/tabMedia.ts`, `lib/tabTime.ts` | alphaTab dressed as a media element (Tab songs, below) |
| Logic with tests | `lib/shortcuts.ts`, `lib/loop.ts`, `lib/cacheKey.ts` | Pure functions unit-tested with vitest |

Per-browser settings (group-by, filter, theme, mute, tab zoom and view) go
through `lib/prefs.ts`, which wraps every `localStorage` access in try/catch.

### The player

Every open mounts a fresh `<video>` and a new audio graph; close tears both
down. The audio runs:

```
<video> → MediaElementSource → SoundTouch AudioWorklet (pitch only) → GainNode (volume, up to 200%) → speakers
```

The browser handles tempo with `playbackRate` and `preservesPitch = true`, so
the worklet never has to stretch time. Without a secure origin there is no
worklet: the video plays directly, a red "live pitch unavailable" badge shows,
and only cached renders change the pitch.

**Live first, then the render.** Moving the pitch or tempo applies at once
through the worklet and `playbackRate`, as a preview. Saving a preset queues a
Rubber Band render; the player polls `/api/presets/{id}/playback` every second
and, when the render is ready, swaps `src`, maps the position by `time_scale`
and keeps playing. Live pitch is always *wanted minus baked*, so the controls
keep working while a render is loaded.

**Presets.** A selector lists the song's presets. Save updates the selected
one in place (a dot marks unsaved changes), Save as… always creates a new one,
and a trash can deletes it. Picking or saving a preset makes it the song's
default. Presets store pitch, tempo, A/B loop points and volume.

**Loop and seek.** A and B are set from the current position and stored on
the original timeline. The loop is checked every frame
(`requestVideoFrameCallback`, or `requestAnimationFrame` for audio and while
paused). A rewind button plays from A while the loop is on, otherwise from
0:00.

**Keyboard.** Space play/pause, `[`/`]` tempo, `-`/`=` pitch, A/B/L loop, M
mute, F fullscreen, ←/→ 5 s, Home start. Ignored while typing in a field. The
controls auto-hide after 2 s without mouse movement.

**Test hook.** `window.__tunealong` exposes live read-only player state for
Playwright.

## Tab songs

Guitar Pro (gp, gp3–gp5, gpx) and MusicXML (musicxml, xml, mxl) files play
natively in the browser through alphaTab 1.8.4, which draws the notation and
plays it with its own synthesizer and SoundFont. Nothing is rendered on the
server: pitch, tempo and volume are applied live by the synth.

**Storage.** `POST /api/songs/tab` streams the upload
(`TUNEALONG_TAB_MAX_MB`, default 10) into `originals/tabs/<sha256[:16]>.<ext>`
and creates a song with `kind = 'tab'`. The add dialog reads the artist and
title from the file itself in the browser. `songs.tab_track` remembers which
track the player shows; playback always plays every track.

**`TabMedia` is the adapter.** `lib/tabMedia.ts` implements the small part of
`HTMLMediaElement` the player uses: `currentTime`, `duration`, `paused`,
`play`/`pause`, `playbackRate` and the media events. Its `graph()` returns the
same `Graph` interface as the video's audio chain. So the loop, seek bar,
keyboard, presets and volume code work on tabs unchanged; the score is drawn
in a white scrolling panel where the video would be.

| Concern | How it is handled |
| --- | --- |
| Pitch | `changeTrackTranspositionPitch` on every track; whole semitones only (the synth offsets MIDI keys), so the ½ buttons are hidden |
| Tempo | `playbackSpeed` |
| Volume | `masterVolume`, no upper clamp, so 200% works |
| Timeline | alphaTab reports milliseconds of stretched playback; `lib/tabTime.ts` converts each report at the speed it carries into original-timeline seconds |
| Seeks | The synth runs in a Web Worker and can deliver a stale position after a seek; for 1 s after a seek only plausible positions are believed |
| Clicking a note | Seeks there (`enableUserInteraction`) |
| Zoom | `display.scale`, 50–200% in 10% steps, per browser |
| Score / tab view | `staveProfile` Default, Tab or Score; offered only when the shown track has both a notation staff and a tab staff, per browser |

**Layering.** alphaTab gives its score chunks `z-index: 1` and its cursor
`1000`. The tab scroller is `isolate` (its own stacking context), so those
layers can never cover the player controls, and no title strip is drawn over a
tab: the score prints its own title.

**Loading.** alphaTab is lazy-loaded with a dynamic `import()` (about 1.2 MB of
JavaScript plus a 2.3 MB worker and a 2.3 MB worklet), so a library without
tabs never downloads it. The Vite plugin bundles the worker and worklet and
copies the Bravura font and Sonivox SoundFont into `dist/`; nothing comes from
a CDN.

**Known upstream bug.** In 1.8.x, subscribing to `api.midiLoaded` recurses
forever in the worker synth. `TabMedia` never subscribes; it takes the song's
end time from the first position report after a MIDI loads. Recheck when
upgrading.

## Recording a browser tab

"Record a tab" is the third Add song mode: it captures another browser tab's
picture and sound and adds the result as an ordinary local song, so presets
render it with Rubber Band like any video.

1. The browser asks which tab to share (`getDisplayMedia`, with tab audio
   required).
2. `MediaRecorder` writes WebM (VP9 or VP8 video, Opus audio) in the page
   (`lib/tabRecorder.ts`, `components/recordPanel.tsx`).
3. The user presses play in the other tab, then Stop here (or the browser's
   "Stop sharing"). A preview shows before Add.
4. `POST /api/songs/recording` streams the upload
   (`TUNEALONG_RECORDING_MAX_MB`, default 1024). `api/tunealong/remux.py` checks
   with ffprobe that there is an audio stream, then ffmpeg copies the streams
   into a new WebM with `+bitexact`, adding the duration and cues MediaRecorder
   leaves out.
5. The file lands in `originals/local/<sha256[:16]>.webm`; the same recording
   uploaded twice is a 409.

**Manual by design.** TuneAlong never opens, controls or reads the other tab.
Fully automated capture of a tab site was declined, because driving another
site to copy its content is scraping its terms forbid; the user shares, plays
and stops. The mode is disabled without a secure context, `getDisplayMedia`,
or WebM recording (Safari).

## Testing

Tests never reach the internet. A fake MeTube (`api/tests/fake_metube.py`,
Starlette) stands in for MeTube, YouTube oEmbed and TheAudioDB, and test media
is generated with ffmpeg.

| Suite | Command | Runs where | Covers |
| --- | --- | --- | --- |
| API | `make test-api` (local) or `make test-docker` (the one that counts) | Docker `test` stage, with real ffmpeg and Rubber Band | pytest, 15 files: CRUD, ingest, downloads, renders (FFT pitch checks with numpy), playback, tabs, recordings, artist images, the deploy files |
| Web unit | `make test-web` | Locally (Node 22) and in the Docker `web` stage | vitest: shortcuts reducer, loop logic, cache keys against the shared table, tab timeline |
| End to end | `make e2e` | Docker `e2e` stage (`mcr.microsoft.com/playwright:v1.64.1-noble`) | Playwright in Chromium: library, player, recording (a canvas + oscillator stream replaces `getDisplayMedia`), tabs |
| Compose | `make compose-test` | Host, from a clean copy of the checkout | Defaults reach healthy; smoke subset against real containers; PUID/PGID 1234 + `TUNEALONG_BASE_PATH=/tunealong`; built-in auth; static checks |

**The dev stack.** `scripts/dev_stack.py` runs the api, a worker thread, the
fake MeTube and the built UI in one process over a scratch root seeded with
fixtures. It backs both `make dev` and Playwright, and adds dev-only
`POST /__dev/reset` so each test starts clean. It wipes its root on start, so
it refuses any folder without its `.tunealong-dev-root` marker.

**Fixtures.** `scripts/make_fixtures.sh` generates SMPTE-bars webm and mp4
clips with a frame counter. Two hand-written MusicXML files cover tabs:
`fixtures/scale.musicxml` (a two-bar C major scale on one TAB staff) and
`fixtures/scale-staves.musicxml` (the same scale on a notation staff over a
TAB staff). `fixtures/cache_keys.json` is the shared cache-key table both
languages test against.

**Static check.** `scripts/check_self_contained.py` keeps the repo shareable:
only allowlisted domains outside docs, no private hostnames or IPs anywhere,
no symlinks, and no `../` path that escapes the project folder.

## Operations

**Image stages** (`Dockerfile`): `runtime` (python:3.12-slim, ffmpeg,
rubberband-cli) → `app` (the production image, with `web/dist`) → `test` →
`e2e`. `app` sits right after `runtime` because the classic builder builds
every stage before `--target`; always build with `--target`. Compose builds
`target: app` and tags it `TUNEALONG_IMAGE` (default `tunealong:latest`).

**Entrypoint.** `docker/entrypoint.sh` starts as root, creates and chowns only
the top-level data folders and the SQLite files (never a recursive walk of the
library), then drops to `PUID:PGID` with `setpriv` and runs `api`, `worker` or
any given command.

| Task | How |
| --- | --- |
| Logs | `docker compose logs -f api worker` |
| Convert older songs to H.264 | `docker compose exec -u 1000 api python -m tunealong.playback queue <id>` (or `queue all`) |
| Run cache GC by hand | `docker compose exec api python -m tunealong.cache gc --max-gb N` |
| Look up artist pictures now | `docker compose exec api python -m tunealong.artist_images` |
| Import an existing MeTube folder | `docker compose run --rm -v <folder>:/import:ro api python -m tunealong.import_legacy /import --dry-run` |
| Database | `data/tunealong.sqlite` (`/data/tunealong.sqlite` in the containers) |

**Gotchas**

- Shell variables beat `.env` in Compose. If the calling shell exports
  `PUID`/`PGID` (linuxserver-style containers do), unset them;
  `compose_test.sh` unsets every key itself.
- `make compose-test` refuses to run while another compose project named
  `tunealong` is up.
- After upgrading, check that every `skip` song with a non-H.264 codec gets
  queued for a playback copy, or Safari will not play it.
- alphaTab is pinned at 1.8.4 because of the `midiLoaded` bug; recheck when
  upgrading.
- Anything specific to one deployment belongs outside this folder, or the
  static check fails.

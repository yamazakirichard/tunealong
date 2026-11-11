> Renamed Songbook → TuneAlong on 2026-11-11 (the name collided with ~1450 GitHub repos). This plan is kept as written, under the old name.

Songbook — Implementation Plan
> Instructions for Claude Code: work through the phases **in order**. Each phase ends with a **Gate**. Do not start the next phase until every test in the gate passes and you have shown me the test output. When a gate passes, commit that phase (only files under `Songbook/`) and push. If a decision isn't covered here, make the simplest choice, write it down in `DECISIONS.md`, and keep going. Ask me only about things that are hard to reverse.
---
0. Context
I'm a guitarist. I download songs from YouTube with MeTube and play along to them. I want a self-hosted web app that:
shows my songs in a grid grouped by artist, using a visual style forked from gethomepage/homepage
plays a song in a near-full-screen modal that I close with ✕ or Esc. It never opens a new tab.
lets me change pitch (semitones) and tempo per song, saved as named presets
never downloads the same video twice
also holds local files that have no YouTube ID (older downloads, custom tracks), which can be linked to a YouTube URL later
caches every rendered pitch/tempo version after I save it, so it's never computed twice
lets me organise everything by hand. These are covers, custom backing tracks and tab videos, not official releases, so YouTube metadata is unreliable. Artist, title, categories and ordering are mine to set.
Guiding principle: the user is in control
The app never changes pitch or tempo on its own. A song with no default preset always opens at its original pitch and tempo.
No guessing or suggesting shifts, and no automatic renders. A render happens only when the user saves a preset.
When the user saves a shifted preset, they get the option to make it this song's default. Only then does the song open shifted.
No automatic categorisation. New songs land in Unsorted unless the user picks an artist when adding them. The YouTube title is kept only as a reference.
Constraints
License: GPL-3.0. Homepage is GPL-3.0 and we fork parts of it. Keep its copyright notices on lifted files, and credit it in `NOTICE` and `README`.
Backend: Python 3.12, FastAPI, SQLite (WAL mode), plain `sqlite3` or SQLAlchemy Core. No ORM magic, no Redis, no Celery.
Frontend: Vite + React + TypeScript + Tailwind, built to static files. Node is a build-time tool only: `vite build` compiles React/TS into static JS/CSS bundles, which FastAPI serves. There is no Node server process in production; all interactivity (UI, player, live pitch via Web Audio AudioWorklet) runs as JavaScript in the user's browser. Port only the Homepage components we need.
Audio: `rubberband` CLI (R3 engine, `-3`) for offline renders, `ffmpeg` for extract and remux, and SoundTouch AudioWorklet (`@soundtouchjs/audio-worklet` or equivalent LGPL) for live preview.
Deployment target: a single `docker compose up` on any Linux host. The project is meant to be reusable by anyone, so it must not depend on any particular reverse proxy, identity provider, CA, or config-management tool. The API container serves the built frontend itself on one port, so there's no separate web server. Anything else (TLS, SSO, a reverse proxy) is the user's choice and is documented, not required.
Configuration: environment variables only, with sensible defaults and documented in `.env.example`. No hardcoded hostnames, domains, or paths outside `SONGBOOK_ROOT`.
Tests: `pytest` for the backend and `vitest` for frontend units. `playwright` for end-to-end tests, using headless Chromium.
No network in tests. Never hit YouTube or a real MeTube in automated tests. Use generated fixtures and a fake MeTube.
Repo: for now the project lives in my infra repo at `infrastructure/application/Songbook/`. Treat that directory as its own repo so it can be split out later:
fully self-contained: its own `compose.yml`, `Dockerfile`, `Makefile`, `README.md`, `LICENSE` (GPL-3.0), `NOTICE`, `.env.example` and tests
no imports, symlinks or relative paths reaching outside `Songbook/`; no dependencies on my Ansible roles, Caddy, Authelia or CA
all commands (`make test`, `make e2e`, `docker compose up`) run from inside `Songbook/`
commits touching `Songbook/` contain nothing else, so `git subtree split` or `git filter-repo` can extract it cleanly
any deploy wiring for my homelab (a caddy_app playbook etc.) lives outside `Songbook/`, in the normal infra layout
Paths: always pass absolute paths to `ffmpeg` and `rubberband`. YouTube IDs can start with `-`, which a relative path would turn into an option.
---
1. Architecture
```
            ┌────────────────────────────────────┐
  browser ─▶│ api (FastAPI) :8080                │
            │   /api/*   /media/*   / (static UI) │
            └──────┬─────────────────────────────┘
                   │ sqlite (WAL)
            ┌──────▼──────┐        ┌─────────┐
            │ worker       │──────▶│ MeTube  │ (HTTP /add)
            │ (jobs table) │        └────┬────┘
            └──────┬──────┘             │ writes
                   ▼                    ▼
        /srv/songbook/renders   /srv/songbook/originals
```
Storage layout
```
/srv/songbook/
├── originals/<youtube_id>.<ext>                  # immutable; written by MeTube
├── originals/local/<sha256[:16]>.<ext>           # immutable; imported/local files with no YouTube ID
├── renders/<song_id>/<cache_key>.<ext>           # disposable cache
└── songbook.sqlite
```
The internal song `id` is the key everywhere (renders, media URLs, jobs). `youtube_id` is optional and only used for dedup and downloads. A local song keeps its file in `originals/local/` even after it is linked to a YouTube URL; `original_path` is authoritative.
MeTube is configured with `OUTPUT_TEMPLATE=%(id)s.%(ext)s` and `YTDL_OPTIONS={"writeinfojson": true, "merge_output_format": "mp4"}`. There is no `download_archive`: the app does its own dedup, and an archive would silently block re-downloading a song the user deleted. The `.info.json` is used only to show the original YouTube title and uploader as reference.
Cache key: `p{semitones:+.2f}_t{tempo:.3f}_bt{bake_tempo}_{engine}-{engine_version}`, for example `p+2.00_t1.000_bt0_rb3-v1`.
When `bake_tempo=0`, tempo is applied live in the browser, so the key always uses `t1.000`: `+2 / 0.8×` and `+2 / 1.0×` share one render.
`-0.00` is normalised to `+0.00`.
The API snaps tempo to 0.01 steps before storing it, so Python and JS formatting can't disagree.
Repo layout (relative to `Songbook/`)
```
Songbook/
├── plan/                 # this plan
├── api/                  # FastAPI app
│   ├── songbook/
│   │   ├── main.py
│   │   ├── db.py
│   │   ├── schema.sql
│   │   ├── models.py     # pydantic
│   │   ├── youtube.py    # URL → id parsing
│   │   ├── metube.py     # client
│   │   ├── ingest.py     # scan originals/, link to songs
│   │   ├── importer.py   # legacy MeTube folder import
│   │   ├── render.py     # rubberband/ffmpeg pipeline
│   │   ├── cache.py
│   │   └── worker.py
│   └── tests/
├── web/                  # Vite + React
│   ├── src/components/   # forked from Homepage
│   └── tests/
├── e2e/                  # playwright
├── compose.yml
├── Dockerfile
├── .env.example
├── fixtures/             # generated media gitignored; make target; cache_keys.json committed
├── DECISIONS.md
├── LICENSE               # GPL-3.0
├── NOTICE
├── README.md
└── Makefile
```
---
2. Data model (`api/songbook/schema.sql`)
`foreign_keys = ON`, `journal_mode = WAL` and `busy_timeout` are set per connection in `db.py`, not in `schema.sql`. `foreign_keys` is per connection, and `journal_mode` can't be changed inside the migration transaction. `schema.sql` is migration 1.
```sql
CREATE TABLE artists (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL COLLATE NOCASE,
  sort_order INTEGER,
  columns INTEGER NOT NULL DEFAULT 4 CHECK (columns BETWEEN 1 AND 8),
  style TEXT NOT NULL DEFAULT 'row' CHECK (style IN ('row', 'column'))
);

CREATE TABLE songs (
  id INTEGER PRIMARY KEY,
  youtube_id TEXT UNIQUE CHECK (youtube_id IS NULL OR length(youtube_id) = 11),  -- NULL = local song
  artist_id INTEGER REFERENCES artists(id) ON DELETE SET NULL,  -- NULL = "Unsorted"
  title TEXT NOT NULL,           -- user-editable display title
  yt_title TEXT,                 -- original YouTube title, reference only
  uploader TEXT,                 -- YouTube channel, reference only
  sort_order INTEGER,            -- manual order within its group
  original_path TEXT,            -- relative to SONGBOOK_ROOT
  original_sha256 TEXT UNIQUE,
  status TEXT NOT NULL CHECK (status IN ('queued', 'downloading', 'ready', 'error')),
  error TEXT,
  notes TEXT,
  added_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE presets (
  id INTEGER PRIMARY KEY,
  song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  semitones REAL NOT NULL DEFAULT 0 CHECK (semitones BETWEEN -12 AND 12),
  tempo REAL NOT NULL DEFAULT 1.0 CHECK (tempo BETWEEN 0.25 AND 2.0),
  bake_tempo INTEGER NOT NULL DEFAULT 0 CHECK (bake_tempo IN (0, 1)),
  loop_a REAL,                   -- seconds in the ORIGINAL timeline
  loop_b REAL,
  is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
  cache_key TEXT,                -- NULL for identity presets; written by the API on save
  UNIQUE (song_id, name),
  CHECK (loop_a IS NULL OR loop_b IS NULL OR loop_a < loop_b)
);

-- at most one default preset per song
CREATE UNIQUE INDEX one_default_preset
  ON presets(song_id) WHERE is_default = 1;
-- no default preset => song opens at original pitch/tempo

-- user-defined categories, e.g. "Tabs", "Backing tracks", "Covers", "Learning", "Set list"
CREATE TABLE categories (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL COLLATE NOCASE,
  colour TEXT,
  sort_order INTEGER
);

CREATE TABLE song_categories (
  song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
  category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  PRIMARY KEY (song_id, category_id)
);

CREATE TABLE renders (
  id INTEGER PRIMARY KEY,
  song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,  -- files removed by the delete handler
  cache_key TEXT NOT NULL,
  path TEXT NOT NULL,            -- relative to SONGBOOK_ROOT
  bytes INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  last_used_at TEXT,
  UNIQUE (song_id, cache_key)
);

CREATE TABLE jobs (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('download', 'render', 'scan')),
  dedupe_key TEXT,
  payload TEXT NOT NULL,     -- JSON
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'running', 'done', 'error')),
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  started_at TEXT,
  finished_at TEXT
);

-- no duplicate in-flight jobs
CREATE UNIQUE INDEX one_active_job
  ON jobs(dedupe_key) WHERE status IN ('pending', 'running');
```
Use a `schema_version` table and a tiny forward-only migration runner. Don't bring in Alembic.
---
Phase 1 — Skeleton, DB, fixtures
Tasks
Scaffold the repo layout above, plus a `Makefile` with these targets: `test`, `test-api`, `test-web`, `e2e`, `fixtures`, `dev`, `build`.
Write `db.py`. It opens the DB, applies `schema.sql` and migrations, and sets WAL, `foreign_keys` and `busy_timeout` on every connection.
Add `LICENSE` (GPL-3.0 text), a stub `NOTICE`, a stub `README.md`, `DECISIONS.md`, and a `.gitignore` for generated fixtures, `data/`, venvs and `node_modules`.
Write `make fixtures`, which uses ffmpeg to generate:
`fixtures/originals/AAAAAAAAAAA.webm` ("tone440"): 10 s, 320×240 colour bars with a frame counter burned in (`drawtext`), VP9 video and Opus audio as a 440 Hz sine.
`fixtures/originals/BBBBBBBBBBB.webm`: same, with a 330 Hz tone.
`fixtures/originals/CCCCCCCCCCC.mp4`: H.264/AAC, to prove the backend handles mp4 and webm. Backend tests only: Playwright's Chromium can't play it, so e2e uses webm only.
Add `api/tests/conftest.py`, which provides a temp `SONGBOOK_ROOT`, a fresh DB per test, and copies of the fixtures.
Add a `/api/health` endpoint.
Gate 1 tests (`api/tests/test_db.py`)
[ ] The schema applies cleanly to an empty DB, and applying it twice is a no-op.
[ ] `journal_mode` is `wal`, `foreign_keys` is on and `busy_timeout` is set, on every new connection.
[ ] Inserting a song with a 10-character `youtube_id` fails.
[ ] Inserting a duplicate `youtube_id` fails. Two songs with a NULL `youtube_id` (local songs) are allowed.
[ ] A second `is_default=1` preset for the same song fails.
[ ] A preset with `semitones=13`, `tempo=3`, or `loop_a >= loop_b` fails.
[ ] Deleting a song cascades to its presets and render rows. Deleting an artist sets songs' `artist_id` to NULL.
[ ] Two `pending` jobs with the same `dedupe_key` fail, but a new one is allowed after the first becomes `done`.
[ ] A `scan` job can be inserted; an unknown job kind fails.
[ ] `GET /api/health` returns 200.
---
Phase 2 — YouTube ID parsing and ingest of existing files
Tasks
Write `youtube.py: parse_id(url_or_id) -> str`. It accepts:
`watch?v=`, `youtu.be/`, `shorts/`, `embed/`, `music.youtube.com`
URLs with extra params (`&t=`, `&list=`)
a bare 11-character ID
It raises `ValueError` on anything else.
Write `ingest.scan(youtube_id=None)`. It walks the top level of `originals/` and only considers names matching `^[A-Za-z0-9_-]{11}\.(webm|mp4)$`. That rejects `.part`, `.ytdl`, `.temp`, yt-dlp intermediates like `<id>.f137.mp4`, and `.info.json`. For each match it:
computes sha256
upserts the song by `youtube_id`: creates it with `status='ready'` and `artist_id=NULL` if missing, or sets `original_path` and `status='ready'` if the song was `queued`, `downloading` or `error`
reads `<id>.info.json` if present into `yt_title` and `uploader`. The display `title` starts as `yt_title`, or the ID if there's none, and is only set on creation, never overwritten after the user edits it.
never assigns an artist or category: new songs land in Unsorted
It also walks `originals/local/`, matching `^[0-9a-f]{16}\.<ext>$`. It links files to existing songs by `original_path`, and creates a local song (NULL `youtube_id`) for any unknown file.
`.info.json` files are not media and must not create songs. It is idempotent.
Before writing the importer: `ls` a sample of my real MeTube folder and report what the filenames look like (ID suffixes, containers, audio-only files). Decide from that which extensions the importer and the `originals/local/` regex accept, and record it in `DECISIONS.md`.
Write `importer.py` and a CLI, `python -m songbook.import_legacy <dir>`. It handles my existing MeTube downloads, which use arbitrary names like `Artist - Title [id].webm` or just `Title.mp4`. For each media file:
if it has a `[id]` suffix with a valid ID, it becomes a YouTube song at `originals/<id>.<ext>`
otherwise it becomes a local song at `originals/local/<sha256[:16]>.<ext>` with `youtube_id=NULL`
it hardlinks when on the same filesystem, otherwise copies. It never deletes the source.
a file whose sha256 or ID is already in the library is skipped and reported as a duplicate
it guesses the artist and title by splitting the stem (minus the `[id]` suffix) on the first `" - "`. This is an explicit, user-run import step, so it's the one exception to "no automatic categorisation". Note it in `DECISIONS.md`.
files with an unsupported extension are skipped and reported
it has a `--dry-run` flag that prints a plan without touching anything
Gate 2 tests
[ ] `test_youtube.py`: a table-driven test with at least 12 URL forms (valid and invalid), including tracking params and `music.youtube.com`.
[ ] `test_ingest.py`:
[ ] Scanning the fixtures creates 3 songs with `status='ready'` and the correct sha256.
[ ] Scanning twice produces no duplicates, and `added_at` is unchanged.
[ ] `.part`, `.temp` and `<id>.f137.mp4` files are ignored.
[ ] An unknown file in `originals/local/` creates a local song with NULL `youtube_id`.
[ ] An `.info.json` file sets `yt_title` and `uploader`, and doesn't create a song by itself.
[ ] After the user renames a song, a rescan does not overwrite the title.
[ ] New songs from a scan have no artist and no categories.
[ ] A pre-existing `queued` row is flipped to `ready` when its file appears.
[ ] `test_import_legacy.py`:
[ ] `Metallica - Master of Puppets [E0ozmU9cJDg].webm` gives artist "Metallica", title "Master of Puppets", and the file at `originals/E0ozmU9cJDg.webm`.
[ ] `Metallica - One.mp4` (no ID) gives a local song with artist "Metallica", title "One", `youtube_id=NULL`, and the file at `originals/local/<sha256[:16]>.mp4`.
[ ] Importing the same folder twice creates no duplicates.
[ ] The source files are untouched.
[ ] `--dry-run` changes nothing on disk or in the DB.
[ ] A file with an unsupported extension is skipped and reported.
---
Phase 3 — Add-by-URL with dedup, via MeTube
Tasks
Write `metube.py`, a client for MeTube's `POST /add`. Read the MeTube source first to confirm the exact payload fields, then record them in `DECISIONS.md`. The base URL comes from the `METUBE_URL` env var.
Add `POST /api/songs {url, artist?, title?}`:
Parse the ID. On an invalid ID, return 422.
If the song exists with `status='ready'`, return 200 with the existing song and `"duplicate": true`. MeTube must not be called.
If it exists as `queued` or `downloading`, return 202 with the existing song. MeTube is not called again.
If it exists as `error`, clear the error, reset it to `queued`, enqueue a new `download` job, and return 202.
Otherwise, create the artist if given (case-insensitive match), insert the song as `queued`, and enqueue a `download` job with `dedupe_key="dl:<youtube_id>"`. Return 201.
Write `worker.py`, a single-process loop. There is exactly one worker.
Claim a job atomically (`UPDATE … SET status='running', started_at=now WHERE id = (SELECT … LIMIT 1) AND status='pending' RETURNING`). Claiming a `download` job sets the song to `downloading`.
`download` jobs call MeTube, then poll the filesystem until a file matching the strict ingest regex for that ID exists, then run `ingest.scan(youtube_id)`.
Use a timeout (configurable, default 15 min), give up after 3 attempts, and record the error on the song.
On startup, reset all `running` jobs back to `pending`. With a single worker, anything `running` at startup was orphaned by a crash.
`scan` jobs run `ingest.scan()`. The worker enqueues one at startup and every 5 minutes (configurable). `POST /api/library/rescan` enqueues one with `dedupe_key="scan"` and returns 202.
Build `tests/fake_metube.py`, a tiny ASGI app that records calls and, after a short delay, copies a fixture to `originals/<id>.webm`.
Gate 3 tests
[ ] Adding a new URL returns 201, the fake MeTube is called once, the worker completes, and the song becomes `ready`.
[ ] Adding the same URL again in a different URL form returns 200 with `duplicate: true`, and the fake MeTube is still called only once.
[ ] Adding twice rapidly before the download finishes calls the fake MeTube once and creates a single job.
[ ] When the fake MeTube returns 500, the job retries up to 3 times, then the song becomes `status='error'` with the message stored.
[ ] Re-adding a song in `error` returns 202, resets it to `queued`, and calls the fake MeTube again.
[ ] A `running` job left by a crash is reclaimed on worker restart.
[ ] `POST /api/library/rescan` twice in a row creates a single pending `scan` job.
[ ] An artist given as "metallica" matches the existing "Metallica".
---
Phase 4 — CRUD API
Endpoints
Method	Path
GET	`/api/library?group_by=artist|category&category=<id>&q=<search>` (groups in `sort_order`, each with songs and their default preset; plus an `Unsorted` / `Uncategorised` pseudo-group)
GET, PATCH, DELETE	`/api/songs/{id}`
POST	`/api/songs/{id}/link` (body: `{url}`; sets `youtube_id` on a local song)
GET, POST	`/api/artists`
PATCH, DELETE	`/api/artists/{id}` (`name`, `sort_order`, `columns`, `style`)
GET, POST	`/api/songs/{id}/presets`
PATCH, DELETE	`/api/presets/{id}`
GET	`/api/jobs?status=`
GET	`/media/originals/{song_id}` (with HTTP Range support)
GET	`/media/renders/{render_id}` (with HTTP Range support)
GET, POST	`/api/categories`
PATCH, DELETE	`/api/categories/{id}`
PUT	`/api/songs/{id}/categories` (body: list of category IDs)
POST	`/api/reorder` (body: `{scope: "artists" | "categories" | "songs", group_id?, ids: [...]}`)
POST	`/api/library/rescan`
Behaviour:
PATCH on a song can change `artist_id` (or `artist_name`, which creates the artist if needed), `title`, and `notes`.
`/api/library` supports two groupings:
`group_by=artist` (the default) groups by artist, with Unsorted last.
`group_by=category` groups by category. A song in several categories appears in each, and uncategorised songs go to an "Uncategorised" group.
Within a group, songs are ordered by `sort_order`, then title. Search matches `title`, artist name, `yt_title`, and `uploader`.
`/api/reorder` writes `sort_order` in one transaction. Unknown IDs or IDs from another group return 422.
DELETE on a song removes the DB row, its presets, its render rows and the `renders/<song_id>/` directory. It deletes the original file only with `?delete_file=true`.
`POST /api/songs/{id}/link` parses the URL (422 if invalid). If another song already has that `youtube_id`, it returns 409 with that song. Otherwise it sets `youtube_id` and leaves the file where it is. From then on dedup applies: adding that URL returns `duplicate: true`.
Preset create and update snap `tempo` to 0.01 and write `cache_key` (NULL for identity presets).
Setting `is_default` on a preset clears it on the song's other presets in the same transaction.
`/media/*` streams with Range support, which is required for video seeking. Paths are resolved from the DB, never from user input.
Gate 4 tests
[ ] `/api/library` groups and orders correctly. Unsorted songs appear in the `Unsorted` group, which comes last.
[ ] Moving a song to a new artist name auto-creates that artist.
[ ] Setting a second default preset unsets the first, and there's no constraint error.
[ ] A preset whose values break the rules returns 422, and the DB is unchanged.
[ ] A Range request returns 206 with a correct `Content-Range`, and seeking to the middle works.
[ ] Path traversal attempts on `/media` return 404.
[ ] Deleting a song without `delete_file` leaves the original on disk. With `delete_file=true`, the original is removed. Either way, its render files are gone.
[ ] Linking a local song to a URL sets `youtube_id`. Adding that URL afterwards returns `duplicate: true`. Linking a second song to the same ID returns 409.
[ ] A preset saved with `tempo=0.8333` is stored as `0.83`.
[ ] Assigning 2 categories to a song puts it in both groups when `group_by=category`. Deleting a category leaves the songs intact.
[ ] Reordering songs within an artist persists, and `/api/library` returns them in the new order.
[ ] Reordering with an ID from another group returns 422, and nothing changes.
[ ] Search finds a song by its `uploader` even when the user's title is different.
[ ] A song with no presets returns playback `semitones=0` and `tempo=1.0`.
---
Phase 5 — Render pipeline and cache
Pipeline (`render.py`)
Before this phase: install `rubberband-cli` in the dev environment so the FFT pitch tests can run, and check `rubberband --version`.
Pitch-only (`bake_tempo=0`):
Extract audio with `ffmpeg -i orig -vn -ac 2 -ar 48000 tmp.wav`.
Shift it with `rubberband -3 -p <semitones> tmp.wav shifted.wav`.
Remux: `ffmpeg -i orig -i shifted.wav -map 0:v -map 1:a -c:v copy -c:a libopus out.webm`. For an mp4 original, use AAC in mp4.
`bake_tempo=1`: Apply tempo in Rubber Band too (`-T <tempo>`, check the flag semantics), and re-encode video with `setpts=PTS/<tempo>`. This is slow, so it's allowed but never the default.
Identity (`semitones == 0` and `tempo == 1`, or `semitones == 0` and `bake_tempo == 0`) produces no render. The player uses the original.
Atomic writes: render to `renders/<song_id>/.<key>.tmp`, then `rename`. Partial files never become visible.
Saving and enqueueing
On preset create or update, use the stored `cache_key`. If a `renders` row exists and the file exists, do nothing. Otherwise enqueue a `render` job with `dedupe_key="rn:<song_id>:<key>"`.
`GET /api/presets/{id}/playback` returns:
`{source: "render" | "original" | "pending", url, live_semitones, live_tempo, time_scale}`
If the bake is ready, `live_semitones=0`.
While a bake is pending, the original is played with live pitch and live tempo.
Tempo is live unless baked. For a ready baked-tempo render: `live_tempo=1`, and `time_scale=1/tempo`, the factor that maps original-timeline seconds to render seconds. It is 1 for everything else.
Touch `last_used_at` when a render is served.
`ENGINE_VERSION` is a constant. Bumping it changes every cache key, so old renders are ignored.
Add a `python -m songbook.cache gc --max-gb N` command. It first deletes the least-recently-used renders whose `cache_key` no preset references (a join on `presets.cache_key`), then falls back to plain LRU, until under budget. It never touches originals.
Gate 5 tests
Pitch correctness is the important one. Analyse the output with numpy FFT on decoded audio.
[ ] Rendering `tone440` at `+2` semitones gives a dominant frequency of 493.9 Hz ± 3 Hz.
[ ] Rendering at `-12` gives 220 Hz ± 2 Hz.
[ ] Pitch-only renders keep their duration within ±50 ms of the original.
[ ] Pitch-only renders have a video stream that is bit-identical to the original's (compare `ffmpeg -map 0:v -c copy -f md5`).
[ ] With `bake_tempo=1` and `tempo=0.5`, the duration is about 2× and the frequency is still 440 Hz ± 3 Hz.
Caching:
[ ] Saving the same preset twice produces exactly one render job and one file.
[ ] Two presets with identical settings share one render.
[ ] `+2 / 0.8× / bt0` and `+2 / 1.0× / bt0` have the same cache key and share one render.
[ ] A preset at `-0` semitones gets a key with `p+0.00`.
[ ] The cache key cases in `fixtures/cache_keys.json` all match.
[ ] Deleting the render file on disk causes the next save or playback to re-enqueue it.
[ ] Bumping `ENGINE_VERSION` (monkeypatched) gives a new cache key and a new render.
[ ] An identity preset produces no job and `source: "original"`.
[ ] A crash mid-render (simulated by killing the subprocess) leaves no visible file, and the retry succeeds.
[ ] `gc` evicts unreferenced renders first and never deletes originals.
Playback endpoint:
[ ] While a render is pending, it returns `source: "pending"` with live pitch equal to the preset's semitones.
[ ] Once the render is done, it returns `source: "render"` with `live_semitones=0`.
[ ] A ready baked render at `tempo=0.5` returns `live_tempo=1` and `time_scale=2`.
---
Phase 6 — Frontend
Fork from Homepage
Before this phase: confirm that `@soundtouchjs/audio-worklet` exists on npm, check its licence (it must be LGPL or another GPL-3.0-compatible licence), and confirm it can shift pitch on a live `MediaElementSource` stream. If it can't, pick an equivalent and record it in `DECISIONS.md`.
Fork from gethomepage/homepage, GPL-3.0, at the latest release tag. Record the tag in `NOTICE`.
Port: the services group and item components, the Tailwind config, the colour themes, light/dark mode, the per-group `columns` / `style` behaviour, and the quick-search bar.
Strip: widgets, config loading, Next.js-specific code, and i18n (unless trivial).
Replace: group data comes from `/api/library`. Clicking an item opens the modal: no `<a target>`, no navigation.
Modal player
An overlay at about 92 vw × 92 vh that dims the background.
Closes with the ✕ button, Esc, or a backdrop click. Closing stops playback and tears down the audio graph. Every open creates a fresh `<video>` element, because a `MediaElementSource` can only be created once per element.
Locks body scroll while open, and traps focus inside.
Controls:
preset selector
semitones: − / + in 1-step increments and a fine 0.5 step
tempo slider across the full 0.25–2.0 range in 0.01 steps, with a tick mark at 1.0 and a reset button
A/B loop buttons, which set the points to the current time
"Save preset" and "Save as…". The save dialog has a "Make this the default for this song" checkbox, unchecked by default.
"Reset to original", which returns to 0 semitones and 1.0 tempo for this session without changing anything saved
Opening behaviour: if the song has a default preset, apply it and show its name in the badge. Otherwise play at the original pitch and tempo. Moving sliders without saving never changes anything stored and never starts a render.
Readability for tab videos: the video is `object-fit: contain` at the largest size the overlay allows. A fullscreen toggle (`F`) uses the Fullscreen API on the modal. The control bar auto-hides after 2 s of no mouse movement, so it doesn't cover the tab.
a badge showing the render status: `original` / `rendering…` / `cached`
Audio graph: `<video>` → `MediaElementSource` → SoundTouch worklet (pitch only) → destination. Tempo comes from `video.playbackRate` with `preservesPitch=true`.
When `source` becomes `render`, swap `src`, set the worklet's pitch to 0, and map the position: `currentTime_render = currentTime_original × time_scale`. For a baked-tempo render (`time_scale = 1/tempo`) also set `playbackRate = 1`. Poll or use SSE for the status change.
A/B loop: checked every frame with `requestVideoFrameCallback`, falling back to `requestAnimationFrame`, not `timeupdate` (which fires only about every 250 ms). If `t >= loop_b × time_scale`, seek to `loop_a × time_scale`. Loop points are always stored in original-timeline seconds; setting A/B on a baked render divides by `time_scale`.
Keyboard shortcuts: Space toggles play/pause, `[` and `]` change tempo by 0.05, `-` and `=` change pitch, `A`/`B` set the loop points, `L` toggles the loop.
Base path: the UI must work under any subpath. Build with Vite `base: './'`, and make every API and media URL relative (`api/library`, not `/api/library`). This works because the app has no client-side routes.
Test hook: expose `window.__songbook` with read-only player state (worklet pitch, `playbackRate`, `source`, `time_scale`, loop points) for Playwright.
Library management UI
An "Add song" box with a URL field plus optional artist (autocomplete from existing artists), title, and categories (multi-select, with "create new" inline). Anything left blank, the song goes to Unsorted for sorting later. A duplicate shows a toast like "Already in library" with a link that opens the song.
Unsorted works as an inbox. Each card shows the YouTube title and uploader as grey reference text, so you can tell custom uploads apart, plus quick "set artist" and "set categories" actions.
Local songs (no YouTube ID) show a small "local" marker and a "Link YouTube URL" action. A 409 on that action shows a toast with a link to the existing song.
Inline edit of artist, title, and notes.
Drag to reorder songs within a group, drag a song to another artist group to move it, and drag groups to reorder them. Every drag also has a keyboard or menu alternative.
A category manager to create, rename, recolour, reorder, and delete categories. Category chips show on cards.
A toolbar with a Group by: Artist / Category toggle, a category filter, and search. The choice is remembered in `localStorage`.
Artist settings: columns, style, and sort order.
A "Rescan library" button.
A job indicator showing downloads and renders in progress.
Gate 6 tests
vitest:
[ ] The cache-key helper matches the backend's output for a shared table of cases. Put the table in `fixtures/cache_keys.json` and have both test suites read it.
[ ] The keyboard shortcut reducer handles each shortcut correctly. `]` from 1.00 gives 1.05, and tempo is clamped to 0.25–2.0.
[ ] Loop logic: given `loop_a=2`, `loop_b=4`, and `t=4.01`, it seeks to 2. With `time_scale=2` and `t=8.01`, it seeks to 4.
[ ] Position mapping when swapping to a baked render at `tempo=0.5`: original `t=3` gives render `t=6`.
playwright (against `make dev` with the fake MeTube and webm fixtures only; Chromium launched with `--autoplay-policy=no-user-gesture-required`; player state read through `window.__songbook`):
[ ] The library renders the artists as groups. A group with `columns=2` lays its items out in 2 columns (check the bounding boxes).
[ ] Clicking a song opens the modal, the page URL is unchanged, and no new page or tab is opened (assert `context.pages().length === 1`).
[ ] Esc closes the modal and the video is paused. ✕ and a backdrop click also close it.
[ ] Setting the tempo to 0.75 gives `video.playbackRate === 0.75`.
[ ] Setting +2 and saving makes the badge go from `rendering…` to `cached`, and the `src` switches to `/media/renders/…`. After a reload, it plays the cached render directly.
[ ] Pasting an existing song's URL shows the duplicate toast and creates no new job.
[ ] Moving a song to another artist makes it appear in that group after a reload.
[ ] No auto-shift: opening a song with no presets gives `playbackRate === 1` and worklet pitch 0, and no render job is created.
[ ] Moving sliders and then closing without saving leaves the DB unchanged, and there's no new job.
[ ] Saving +2 with "Make default" unchecked creates the preset and render, but reopening the song plays at 0.
[ ] Saving +2 with "Make default" checked means reopening the song plays the +2 render, and the badge shows the preset name.
[ ] Adding a URL with no artist puts the song in Unsorted, with the YouTube title shown as reference.
[ ] Creating a category inline while adding a song assigns it, and switching to "Group by: Category" shows the song there.
[ ] Drag-reordering songs survives a reload.
[ ] Fullscreen toggle: `F` enters and exits fullscreen on the modal, not a new tab.
[ ] Closing and reopening the modal three times plays audio each time, with no `InvalidStateError` from `MediaElementSource`.
---
Phase 7 — Packaging and deployment
Tasks
Before this phase: check MeTube's source for how it takes its user and group IDs (`PUID`/`PGID` or `UID`/`GID`), and map our `PUID`/`PGID` onto whatever it uses. Record it in `DECISIONS.md`.
Write one Dockerfile, multi-stage:
Stage 1 is a Node build of `web/` into `dist/`.
Stage 2 is Debian slim with Python, `ffmpeg` and `rubberband-cli`, with `dist/` copied in and served by FastAPI `StaticFiles` (SPA fallback to `index.html`).
The same image runs as `api` or `worker` depending on the command.
Build gate: `rubberband --version` must succeed.
Write `compose.yml` at the repo root, with the services `api`, `worker`, and `metube`:
one bind-mounted data dir (`./data` by default, overridable via `SONGBOOK_DATA`)
MeTube mounts `data/originals` as `/downloads`
`PUID`/`PGID` env vars applied to all containers
healthchecks on everything
only `api` publishes a port (default `8080`). MeTube stays internal-only unless the user opts in.
Add optional built-in auth, off by default. Set `SONGBOOK_AUTH_USER` and `SONGBOOK_AUTH_PASSWORD_HASH` (bcrypt) to enable HTTP Basic on everything except `/api/health`. Users who run their own reverse proxy or SSO can just leave it off.
`SONGBOOK_BASE_PATH` is read at runtime: the same image serves at `/` or under a subpath, with no rebuild.
Add `.env.example` documenting every variable. It must warn that every `$` in the bcrypt hash has to be written as `$$`, or Compose's variable interpolation mangles it (`$2b$12$…` → `$$2b$$12$$…`).
Schedule cache GC from the worker itself (`SONGBOOK_CACHE_MAX_GB`, checked hourly), so there's no host cron dependency.
Write `README.md` covering:
quick start (`cp .env.example .env && docker compose up -d`)
the legacy import walkthrough
the backup note: back up `data/originals/` and `songbook.sqlite`, and exclude `data/renders/`
a short "Running behind a reverse proxy" section with generic notes (forward the `Range` header, don't buffer media, and an optional subpath via `SONGBOOK_BASE_PATH`), plus a one-line example each for Caddy, nginx, and Traefik
a "Using an existing MeTube" section: point `METUBE_URL` at it, set its output template and `YTDL_OPTIONS` as described in §1, and don't enable `download_archive`
Gate 7 tests
[ ] On a clean checkout, `docker compose up` with only `.env.example` defaults reaches healthy, and the UI loads at `http://localhost:8080`.
[ ] `docker compose up` with the fake MeTube override passes the playwright smoke subset against the containers.
[ ] Inside the image, `rubberband --version` and `ffmpeg -version` succeed.
[ ] Files written by the containers are owned by the configured `PUID`/`PGID`.
[ ] With auth env vars set (hash written with `$$` in `.env`), unauthenticated requests get 401 and authenticated ones get 200, and `/api/health` stays open. With them unset, there's no auth.
[ ] With `SONGBOOK_BASE_PATH=/songbook`, the UI, API, and media all work under the subpath.
[ ] `grep` the repo for hardcoded hostnames and domains: none outside docs examples.
[ ] Nothing in `Songbook/` references a path outside it (no `../..` escapes, no symlinks out).
---
Definition of done
[ ] `make test` (api + web) and `make e2e` are green.
[ ] The legacy import has been run on a copy of my real MeTube folder with `--dry-run`, and the output has been reviewed by me.
[ ] No test touches the network.
[ ] `DECISIONS.md` lists every judgement call made along the way.
[ ] `NOTICE` credits Homepage (GPL-3.0) with the upstream tag.
[ ] Every commit touching `Songbook/` touches nothing outside it.
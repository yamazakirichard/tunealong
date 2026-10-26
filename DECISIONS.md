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

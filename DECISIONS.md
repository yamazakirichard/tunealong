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

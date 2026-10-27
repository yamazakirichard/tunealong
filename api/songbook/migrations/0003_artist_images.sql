-- Artist pictures from TheAudioDB, fetched by the worker and kept on disk.
ALTER TABLE artists ADD COLUMN image_path TEXT;        -- relative to SONGBOOK_ROOT; NULL = none (yet)
ALTER TABLE artists ADD COLUMN image_checked_at TEXT;  -- NULL = not looked up yet

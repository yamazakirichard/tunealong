-- Originals the user deleted from the library but kept on disk. The scan
-- skips them, so a deleted song doesn't come back on the next rescan.
CREATE TABLE ignored_paths (
  path TEXT PRIMARY KEY,         -- relative to TUNEALONG_ROOT
  added_at TEXT NOT NULL DEFAULT (datetime('now'))
);

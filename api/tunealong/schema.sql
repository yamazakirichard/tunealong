-- Migration 1: initial schema.
-- Connection pragmas (foreign_keys, journal_mode, busy_timeout) live in db.py:
-- foreign_keys is per connection, and journal_mode can't change inside the
-- migration transaction.

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
  original_path TEXT,            -- relative to TUNEALONG_ROOT
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

CREATE INDEX presets_cache_key ON presets(cache_key);

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
  path TEXT NOT NULL,            -- relative to TUNEALONG_ROOT
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

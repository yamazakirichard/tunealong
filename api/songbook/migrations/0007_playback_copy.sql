-- Originals stay exactly as downloaded (the best quality on offer, often AV1 or VP9,
-- which Safari may refuse). A song in another codec gets an H.264 copy in playback/,
-- which is what the player and new renders use.
-- pending = not looked at yet, done = looked at (playback_path NULL if it needs no
-- copy), error = encode failed (see the worker log), skip = left as it is.
ALTER TABLE songs ADD COLUMN playback_path TEXT;
ALTER TABLE songs ADD COLUMN playback_state TEXT NOT NULL DEFAULT 'pending'
  CHECK (playback_state IN ('pending', 'done', 'error', 'skip'));
-- Only new songs convert by themselves. `python -m songbook.playback queue` does older ones.
UPDATE songs SET playback_state = 'skip';

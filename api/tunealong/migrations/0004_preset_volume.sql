-- A preset's own volume (0-1, the slider's value); NULL = use the browser's.
ALTER TABLE presets ADD COLUMN volume REAL CHECK (volume IS NULL OR volume BETWEEN 0 AND 1);

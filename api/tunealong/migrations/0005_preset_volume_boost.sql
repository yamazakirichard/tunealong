-- Volume goes to 2 (200%, a boost past the original level). SQLite can't alter a
-- CHECK, so copy into a new column and swap it in; RENAME rewrites the CHECK too.
ALTER TABLE presets ADD COLUMN volume_new REAL CHECK (volume_new IS NULL OR volume_new BETWEEN 0 AND 2);
UPDATE presets SET volume_new = volume;
ALTER TABLE presets DROP COLUMN volume;
ALTER TABLE presets RENAME COLUMN volume_new TO volume;

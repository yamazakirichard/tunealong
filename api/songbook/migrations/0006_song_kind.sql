-- Tab songs: a Guitar Pro / MusicXML file played in the browser with alphaTab.
-- They never get renders: pitch, tempo and volume are applied by alphaTab's synth.
ALTER TABLE songs ADD COLUMN kind TEXT NOT NULL DEFAULT 'media' CHECK (kind IN ('media', 'tab'));
-- Index of the track the player shows; NULL = the first track.
ALTER TABLE songs ADD COLUMN tab_track INTEGER CHECK (tab_track IS NULL OR tab_track >= 0);

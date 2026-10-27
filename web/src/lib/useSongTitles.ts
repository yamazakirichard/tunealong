import { useEffect, useMemo, useState } from "react";

import { api, type Artist, type Song } from "./api";
import { fold, titleCandidates } from "./suggest";

/**
 * Title suggestions for a song dialog. The page's library may be filtered by
 * search or category, so this loads the whole library each time the dialog opens.
 */
export function useSongTitles(open: boolean, artists: Artist[], artistName: string): string[] {
  const [songs, setSongs] = useState<Song[]>([]);
  useEffect(() => {
    if (!open) return;
    let live = true;
    api
      .library({ group_by: "artist" })
      .then((lib) => live && setSongs(lib.groups.flatMap((g) => g.songs)))
      .catch(() => {}); // suggestions are a nicety; the dialog works without them
    return () => {
      live = false;
    };
  }, [open]);
  const artistId = artists.find((a) => fold(a.name) === fold(artistName.trim()))?.id;
  return useMemo(() => titleCandidates(songs, artistId), [songs, artistId]);
}

import { useCallback, useEffect, useMemo, useState } from "react";

import AddSong from "./components/addSong";
import CategoryManager from "./components/categoryManager";
import Player from "./components/player";
import ServicesGroup from "./components/services/group";
import { DeleteSongDialog, EditSongDialog, LinkSongDialog } from "./components/songDialogs";
import { useToast } from "./components/toasts";
import Toolbar from "./components/toolbar";
import { api, type Artist, type Category, errorText, type Group, type Library, type Song } from "./lib/api";
import { LibraryContext, type LibraryCtx } from "./lib/library";
import { load, save } from "./lib/prefs";

export default function App() {
  const toast = useToast();
  const [library, setLibrary] = useState<Library | null>(null);
  const [artists, setArtists] = useState<Artist[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [groupBy, setGroupBy] = useState<"artist" | "category">(() => load("groupBy", "artist"));
  const [category, setCategory] = useState<number | null>(() => load("category", null));
  const [q, setQ] = useState("");
  const [playing, setPlaying] = useState<{ song: Song; n: number } | null>(null);
  const [editing, setEditing] = useState<{ song: Song; focus: "artist" | "categories" | "title" } | null>(null);
  const [linking, setLinking] = useState<Song | null>(null);
  const [deleting, setDeleting] = useState<Song | null>(null);
  const [adding, setAdding] = useState(false);
  const [managingCats, setManagingCats] = useState(false);

  useEffect(() => save("groupBy", groupBy), [groupBy]);
  useEffect(() => save("category", category), [category]);

  const refresh = useCallback(async () => {
    try {
      const [lib, a, c] = await Promise.all([
        api.library({ group_by: groupBy, category, q: q.trim() }),
        api.artists(),
        api.categories(),
      ]);
      setLibrary(lib);
      setArtists(a);
      setCategories(c);
      if (category !== null && !c.some((x) => x.id === category)) setCategory(null);
    } catch (e) {
      toast({ text: `Couldn't load the library: ${errorText(e)}`, kind: "error" });
    }
  }, [groupBy, category, q, toast]);

  useEffect(() => {
    const t = setTimeout(() => void refresh(), q ? 200 : 0);
    return () => clearTimeout(t);
  }, [refresh, q]);

  // Keep refreshing while anything is still on its way in. A fast download can
  // finish between two job-indicator polls, so that alone isn't enough.
  const inFlight = library?.groups.some((g) => g.songs.some((s) => s.status === "queued" || s.status === "downloading"));
  useEffect(() => {
    if (!inFlight) return;
    const t = setInterval(() => void refresh(), 1500);
    return () => clearInterval(t);
  }, [inFlight, refresh]);

  const realGroups = useMemo(() => library?.groups.filter((g) => g.id !== null) ?? [], [library]);

  const ctx: LibraryCtx = useMemo(() => {
    const songsOf = (group: Group) => group.songs.map((s) => s.id);
    const run = async (f: () => Promise<unknown>) => {
      try {
        await f();
      } catch (e) {
        toast({ text: errorText(e), kind: "error" });
      }
      await refresh();
    };
    const groupScope = groupBy === "artist" ? "artists" : "categories";
    return {
      library,
      artists,
      categories,
      groupBy,
      refresh,
      openSong: (song) => {
        if (song.status !== "ready") {
          toast({ text: `"${song.title}" isn't downloaded yet (${song.status})` });
          return;
        }
        setPlaying((p) => ({ song, n: (p?.n ?? 0) + 1 }));
      },
      editSong: (song, focus = "title") => setEditing({ song, focus }),
      linkSong: setLinking,
      deleteSong: setDeleting,
      retrySong: (song) => void run(() => api.addSong({ url: song.youtube_id! })),
      moveSong: (songId, group, beforeId) =>
        run(async () => {
          const from = library?.groups.find((g) => g.songs.some((s) => s.id === songId));
          if (from?.id !== group.id) await api.patchSong(songId, { artist_id: group.id });
          const ids = songsOf(group).filter((id) => id !== songId);
          const at = beforeId === null ? ids.length : Math.max(0, ids.indexOf(beforeId));
          ids.splice(at, 0, songId);
          await api.reorder({ scope: "songs", group_id: group.id, ids });
        }),
      nudgeSong: (song, group, delta) =>
        run(async () => {
          const ids = songsOf(group);
          const i = ids.indexOf(song.id);
          [ids[i], ids[i + delta]] = [ids[i + delta], ids[i]];
          await api.reorder({ scope: "songs", group_id: group.id, ids });
        }),
      moveGroup: (id, beforeId) =>
        run(async () => {
          const ids = realGroups.map((g) => g.id!).filter((x) => x !== id);
          const at = beforeId === null ? ids.length : Math.max(0, ids.indexOf(beforeId));
          ids.splice(at, 0, id);
          await api.reorder({ scope: groupScope, ids });
        }),
      nudgeGroup: (group, delta) =>
        run(async () => {
          const ids = realGroups.map((g) => g.id!);
          const i = ids.indexOf(group.id!);
          [ids[i], ids[i + delta]] = [ids[i + delta], ids[i]];
          await api.reorder({ scope: groupScope, ids });
        }),
    };
  }, [library, artists, categories, groupBy, refresh, realGroups, toast]);

  const openFirst = () => {
    const first = library?.groups.flatMap((g) => g.songs).find((s) => s.status === "ready");
    if (first) ctx.openSong(first);
  };

  return (
    <LibraryContext.Provider value={ctx}>
      <div className="min-h-screen">
        <Toolbar
          groupBy={groupBy}
          setGroupBy={setGroupBy}
          category={category}
          setCategory={setCategory}
          q={q}
          setQ={setQ}
          onAdd={() => setAdding(true)}
          onCategories={() => setManagingCats(true)}
          onOpenFirst={openFirst}
        />
        <main className="flex flex-wrap px-4 pb-8 gap-y-4" data-testid="library">
          {library?.groups.map((g) => {
            const i = realGroups.indexOf(g);
            return <ServicesGroup key={`${groupBy}-${g.id ?? "none"}`} group={g} index={i} count={realGroups.length} />;
          })}
          {library && library.groups.every((g) => g.songs.length === 0) && (
            <p className="basis-full text-center text-theme-500 py-12">
              {q || category !== null ? "Nothing matches." : "No songs yet. Use “Add song” to paste a YouTube URL."}
            </p>
          )}
        </main>
      </div>

      <AddSong open={adding} onClose={() => setAdding(false)} onCategoryCreated={() => void refresh()} />
      <CategoryManager open={managingCats} onClose={() => setManagingCats(false)} />
      <EditSongDialog
        song={editing?.song ?? null}
        focus={editing?.focus ?? "title"}
        onClose={() => setEditing(null)}
        onCategoryCreated={() => void refresh()}
      />
      <LinkSongDialog song={linking} onClose={() => setLinking(null)} />
      <DeleteSongDialog song={deleting} onClose={() => setDeleting(null)} />
      {playing && <Player key={playing.n} song={playing.song} onClose={() => setPlaying(null)} />}
    </LibraryContext.Provider>
  );
}

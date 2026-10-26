import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, ApiError, errorText, type Song } from "../lib/api";
import { useLibrary } from "../lib/library";
import CategoryPicker from "./categoryPicker";
import SmallDialog, { buttonClass, inputClass, plainButtonClass } from "./dialog";
import { useToast } from "./toasts";

export function EditSongDialog({ song, focus, onClose, onCategoryCreated }: {
  song: Song | null;
  focus: "artist" | "categories" | "title";
  onClose: () => void;
  onCategoryCreated: () => void;
}) {
  const lib = useLibrary();
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [notes, setNotes] = useState("");
  const [cats, setCats] = useState<number[]>([]);
  const artistRef = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!song) return;
    setTitle(song.title);
    setArtist(lib.artists.find((a) => a.id === song.artist_id)?.name ?? "");
    setNotes(song.notes ?? "");
    setCats(song.categories);
    setTimeout(() => (focus === "artist" ? artistRef : titleRef).current?.focus(), 50);
  }, [song, focus, lib.artists]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!song) return;
    try {
      await api.patchSong(song.id, { title: title.trim(), artist_name: artist.trim(), notes: notes.trim() || null });
      await api.setCategories(song.id, cats);
      onClose();
      await lib.refresh();
    } catch (err) {
      toast({ text: errorText(err), kind: "error" });
    }
  };

  return (
    <SmallDialog title="Edit song" open={song !== null} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        {song?.yt_title && (
          <p className="text-xs text-theme-500">
            YouTube: {song.yt_title}
            {song.uploader ? ` · ${song.uploader}` : ""}
          </p>
        )}
        <label className="text-sm flex flex-col gap-1">
          Title
          <input ref={titleRef} name="title" required className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="text-sm flex flex-col gap-1">
          Artist <span className="text-xs text-theme-500">blank = Unsorted; a new name creates the artist</span>
          <input ref={artistRef} name="artist" list="edit-artist-names" className={inputClass} value={artist} onChange={(e) => setArtist(e.target.value)} />
          <datalist id="edit-artist-names">
            {lib.artists.map((a) => (
              <option key={a.id} value={a.name} />
            ))}
          </datalist>
        </label>
        <label className="text-sm flex flex-col gap-1">
          Notes
          <textarea name="notes" rows={3} className={inputClass} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        <CategoryPicker categories={lib.categories} value={cats} onChange={setCats} onCreated={onCategoryCreated} />
        <div className="flex justify-end gap-2">
          <button type="button" className={plainButtonClass} onClick={onClose}>Cancel</button>
          <button type="submit" className={buttonClass} disabled={!title.trim()}>Save</button>
        </div>
      </form>
    </SmallDialog>
  );
}

export function LinkSongDialog({ song, onClose }: { song: Song | null; onClose: () => void }) {
  const lib = useLibrary();
  const toast = useToast();
  const [url, setUrl] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!song) return;
    try {
      await api.linkSong(song.id, url.trim());
      toast({ text: "Linked" });
      setUrl("");
      onClose();
      await lib.refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.body.song) {
        const other = err.body.song;
        toast({ text: `Already linked to "${other.title}"`, action: { label: "Open", run: () => lib.openSong(other) } });
      } else {
        toast({ text: errorText(err), kind: "error" });
      }
    }
  };
  return (
    <SmallDialog title={`Link "${song?.title ?? ""}" to YouTube`} open={song !== null} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <input autoFocus required className={inputClass} placeholder="YouTube URL" value={url} onChange={(e) => setUrl(e.target.value)} />
        <p className="text-xs text-theme-500">The file stays where it is. Adding this URL later will say it's already in the library.</p>
        <div className="flex justify-end gap-2">
          <button type="button" className={plainButtonClass} onClick={onClose}>Cancel</button>
          <button type="submit" className={buttonClass}>Link</button>
        </div>
      </form>
    </SmallDialog>
  );
}

export function DeleteSongDialog({ song, onClose }: { song: Song | null; onClose: () => void }) {
  const lib = useLibrary();
  const [deleteFile, setDeleteFile] = useState(false);
  const confirm = async () => {
    if (!song) return;
    await api.deleteSong(song.id, deleteFile);
    setDeleteFile(false);
    onClose();
    await lib.refresh();
  };
  return (
    <SmallDialog title={`Delete "${song?.title ?? ""}"?`} open={song !== null} onClose={onClose}>
      <p className="text-sm mb-3">Its presets and cached renders are removed.</p>
      <label className="flex items-center gap-2 text-sm mb-4">
        <input type="checkbox" checked={deleteFile} onChange={(e) => setDeleteFile(e.target.checked)} />
        Also delete the original file from disk
      </label>
      <div className="flex justify-end gap-2">
        <button type="button" className={plainButtonClass} onClick={onClose}>Cancel</button>
        <button type="button" className="rounded px-3 py-1.5 text-sm font-medium bg-red-600 text-white" onClick={confirm}>Delete</button>
      </div>
    </SmallDialog>
  );
}

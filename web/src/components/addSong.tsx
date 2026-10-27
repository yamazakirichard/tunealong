import { type FormEvent, useState } from "react";

import { api, errorText, type Song } from "../lib/api";
import { useLibrary } from "../lib/library";
import { useSongTitles } from "../lib/useSongTitles";
import CategoryPicker from "./categoryPicker";
import SmallDialog, { buttonClass, inputClass, plainButtonClass } from "./dialog";
import SuggestInput from "./suggestInput";
import { useToast } from "./toasts";

export default function AddSong({ open, onClose, onCategoryCreated }: {
  open: boolean;
  onClose: () => void;
  onCategoryCreated: () => void;
}) {
  const lib = useLibrary();
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [artist, setArtist] = useState("");
  const [title, setTitle] = useState("");
  const [cats, setCats] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const titles = useSongTitles(open, lib.artists, artist);

  const reset = () => {
    setUrl("");
    setArtist("");
    setTitle("");
    setCats([]);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { status, data } = await api.addSong({
        url: url.trim(),
        artist: artist.trim() || undefined,
        title: title.trim() || undefined,
      });
      if (status >= 400) {
        toast({ text: typeof data?.detail === "string" ? data.detail : "Not a YouTube URL", kind: "error" });
        return;
      }
      const song: Song = data.song;
      if (data.duplicate) {
        toast({ text: "Already in library", action: { label: "Open", run: () => lib.openSong(song) } });
      } else {
        if (cats.length) await api.setCategories(song.id, cats);
        toast({ text: status === 201 ? `Added — downloading ${song.youtube_id}` : "Already downloading" });
      }
      reset();
      onClose();
      await lib.refresh();
    } catch (err) {
      toast({ text: errorText(err), kind: "error" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <SmallDialog title="Add song" open={open} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <label className="text-sm flex flex-col gap-1">
          YouTube URL
          <input
            autoFocus
            required
            name="url"
            className={inputClass}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=…"
          />
        </label>
        <label className="text-sm flex flex-col gap-1">
          Artist <span className="text-xs text-theme-500">optional; blank goes to Unsorted</span>
          <SuggestInput name="artist" value={artist} onChange={setArtist} candidates={lib.artists.map((a) => a.name)} />
        </label>
        <label className="text-sm flex flex-col gap-1">
          Title <span className="text-xs text-theme-500">optional; defaults to the YouTube title</span>
          <SuggestInput name="title" value={title} onChange={setTitle} candidates={titles} />
        </label>
        <CategoryPicker categories={lib.categories} value={cats} onChange={setCats} onCreated={onCategoryCreated} />
        <div className="flex justify-end gap-2">
          <button type="button" className={plainButtonClass} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className={buttonClass} disabled={busy || !url.trim()}>
            Add
          </button>
        </div>
      </form>
    </SmallDialog>
  );
}

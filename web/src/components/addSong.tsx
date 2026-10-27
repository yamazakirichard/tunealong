import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, errorText, type Song, type YoutubeInfo } from "../lib/api";
import { useLibrary } from "../lib/library";
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
  const [info, setInfo] = useState<YoutubeInfo | null>(null);
  // What the last lookup filled in. A field still holding it (or blank) gets
  // the next guess; once you've typed your own, it's left alone.
  const guessed = useRef({ artist: "", title: "" });

  // Look the video up as soon as the URL is in, to guess artist and title.
  useEffect(() => {
    const u = url.trim();
    if (!u) {
      setInfo(null);
      return;
    }
    let live = true;
    const t = setTimeout(() => {
      api
        .youtube(u)
        .then((i) => {
          if (!live) return;
          setInfo(i);
          const prev = guessed.current;
          const next = { artist: i.artist ?? "", title: i.title ?? "" };
          guessed.current = next;
          setArtist((a) => (a.trim() === "" || a === prev.artist ? next.artist : a));
          setTitle((x) => (x.trim() === "" || x === prev.title ? next.title : x));
        })
        .catch(() => live && setInfo(null)); // not a YouTube URL (yet); submitting says so
    }, 300);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [url]);

  const reset = () => {
    setUrl("");
    setArtist("");
    setTitle("");
    setCats([]);
    setInfo(null);
    guessed.current = { artist: "", title: "" };
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
        {info?.yt_title && (
          <p data-testid="youtube-title" className="-mt-2 text-xs text-theme-500">
            YouTube: {info.yt_title}
            {info.uploader ? ` · ${info.uploader}` : ""}
            {info.in_library ? " · already in your library" : ""}
          </p>
        )}
        <label className="text-sm flex flex-col gap-1">
          Artist <span className="text-xs text-theme-500">optional; blank goes to Unsorted</span>
          <SuggestInput name="artist" value={artist} onChange={setArtist} candidates={lib.artists.map((a) => a.name)} />
        </label>
        <label className="text-sm flex flex-col gap-1">
          Title <span className="text-xs text-theme-500">guessed from the YouTube title; blank uses it as is</span>
          <input name="title" className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} />
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

import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, errorText, type Song, type YoutubeInfo } from "../lib/api";
import { useLibrary } from "../lib/library";
import { tabMetadata } from "../lib/tabMedia";
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
  const [mode, setMode] = useState<"youtube" | "tab">("youtube");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
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

  // A tab file carries its own artist and title: guess from those, else the file name.
  useEffect(() => {
    if (!file) return;
    let live = true;
    void file.arrayBuffer().then(async (buf) => {
      const meta = await tabMetadata(new Uint8Array(buf));
      if (!live) return;
      const prev = guessed.current;
      const next = { artist: meta?.artist ?? "", title: meta?.title || file.name.replace(/\.[^.]+$/, "") };
      guessed.current = next;
      setArtist((a) => (a.trim() === "" || a === prev.artist ? next.artist : a));
      setTitle((x) => (x.trim() === "" || x === prev.title ? next.title : x));
    });
    return () => {
      live = false;
    };
  }, [file]);

  const reset = () => {
    setUrl("");
    setFile(null);
    setArtist("");
    setTitle("");
    setCats([]);
    setInfo(null);
    guessed.current = { artist: "", title: "" };
  };

  const submitTab = async () => {
    const { status, data } = await api.addTab(file!, { artist: artist.trim(), title: title.trim() });
    if (status === 409 && data.song) {
      toast({ text: "Already in library", action: { label: "Open", run: () => lib.openSong(data.song) } });
    } else if (status >= 400) {
      toast({ text: typeof data?.detail === "string" ? data.detail : `Upload failed (${status})`, kind: "error" });
      return;
    } else {
      if (cats.length) await api.setCategories(data.song.id, cats);
      toast({ text: `Added "${data.song.title}"`, action: { label: "Open", run: () => lib.openSong(data.song) } });
    }
    reset();
    onClose();
    await lib.refresh();
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (mode === "tab") return await submitTab();
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
        <div role="radiogroup" aria-label="Source" className="flex gap-1 text-sm">
          {(["youtube", "tab"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              onClick={() => setMode(m)}
              className={mode === m ? buttonClass : plainButtonClass}
            >
              {m === "youtube" ? "YouTube URL" : "Tab file"}
            </button>
          ))}
        </div>
        {mode === "youtube" ? (
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
        ) : (
          <label className="text-sm flex flex-col gap-1">
            Tab file <span className="text-xs text-theme-500">Guitar Pro (.gp, .gp3–.gp5, .gpx) or MusicXML (.musicxml, .xml, .mxl)</span>
            <input
              required
              name="tab-file"
              type="file"
              accept=".gp,.gp3,.gp4,.gp5,.gpx,.musicxml,.xml,.mxl"
              className="text-sm"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
        )}
        {mode === "youtube" && info?.yt_title && (
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
          Title{" "}
          <span className="text-xs text-theme-500">
            {mode === "youtube" ? "guessed from the YouTube title; blank uses it as is" : "from the file; blank uses the file name"}
          </span>
          <input name="title" className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <CategoryPicker categories={lib.categories} value={cats} onChange={setCats} onCreated={onCategoryCreated} />
        <div className="flex justify-end gap-2">
          <button type="button" className={plainButtonClass} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className={buttonClass} disabled={busy || (mode === "youtube" ? !url.trim() : !file)}>
            Add
          </button>
        </div>
      </form>
    </SmallDialog>
  );
}

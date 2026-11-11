import classNames from "classnames";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  MdClose,
  MdDeleteOutline,
  MdFullscreen,
  MdFullscreenExit,
  MdPause,
  MdPlayArrow,
  MdRepeat,
  MdReplay,
  MdSave,
  MdSaveAs,
  MdVolumeDown,
  MdVolumeOff,
  MdVolumeUp,
  MdZoomIn,
  MdZoomOut,
} from "react-icons/md";

import { api, errorText, type Playback, type Preset, type Song } from "../lib/api";
import { buildGraph, type Graph, graphErrors } from "../lib/audioGraph";
import { isIdentity } from "../lib/cacheKey";
import { useLibrary } from "../lib/library";
import { loopSeek, mapPosition } from "../lib/loop";
import * as prefs from "../lib/prefs";
import { clampPitch, clampTempo, shortcut, TEMPO_MAX, TEMPO_MIN } from "../lib/shortcuts";
import { type MediaLike, TAB_VIEWS, TabMedia, tabErrors, tabPitch, type TabTrack, type TabView } from "../lib/tabMedia";
import { buttonClass, inputClass, plainButtonClass } from "./dialog";
import { useToast } from "./toasts";

/** What the <video> is currently playing. Pitch/tempo baked into it are subtracted from the live values. */
interface Loaded {
  url: string;
  source: "original" | "render";
  bakedSemitones: number;
  bakedTempo: number | null; // set for a baked-tempo render
  timeScale: number;
}

const ORIGINAL = (songId: number): Loaded => ({
  url: `media/originals/${songId}`,
  source: "original",
  bakedSemitones: 0,
  bakedTempo: null,
  timeScale: 1,
});

function fromPlayback(songId: number, pb: Playback, preset: Preset | null): Loaded {
  if (pb.source !== "render" || !preset) return ORIGINAL(songId);
  return {
    url: pb.url,
    source: "render",
    bakedSemitones: preset.semitones,
    bakedTempo: preset.bake_tempo ? preset.tempo : null,
    timeScale: pb.time_scale,
  };
}

const r2 = (x: number) => Math.round(x * 100) / 100;
const browserVolume = () => prefs.load("volume", 1);
// Tab zoom: per browser, since the right size is about the screen, not the song.
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 2;
const clampZoom = (z: number) => Math.round(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z)) * 10) / 10;
// The slider runs to 2 (200%). Up to 1 it's squared, so its middle sounds like half;
// above 1 it's linear, so 2 is double the original level (+6 dB) and may clip.
const VOLUME_MAX = 2;
const gainOf = (v: number) => (v <= 1 ? v * v : v);

/** The tempo readout, typeable: commits on Enter or blur, Escape reverts. */
function TempoField({ tempo, onCommit }: { tempo: number; onCommit: (t: number) => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    const t = Number(draft);
    if (draft !== null && draft.trim() !== "" && Number.isFinite(t)) onCommit(clampTempo(t));
    setDraft(null);
  };
  return (
    <input
      type="number"
      data-testid="tempo"
      aria-label="Tempo value"
      min={TEMPO_MIN}
      max={TEMPO_MAX}
      step={0.01}
      value={draft ?? tempo.toFixed(2)}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
        else if (e.key === "Escape") {
          e.stopPropagation(); // don't close the player
          setDraft(null);
        }
      }}
      className="w-16 rounded bg-white/10 px-1 py-0.5 text-center tabular-nums [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
    />
  );
}

declare global {
  interface Window {
    __songbook?: Record<string, unknown>;
  }
}

export default function Player({ song, onClose }: { song: Song; onClose: () => void }) {
  const lib = useLibrary();
  const toast = useToast();
  const modalRef = useRef<HTMLDivElement>(null);
  // The <video>, or for a tab song an alphaTab player dressed as one (lib/tabMedia.ts).
  const isTab = song.kind === "tab";
  const videoRef = useRef<MediaLike | null>(null);
  const [tracks, setTracks] = useState<TabTrack[]>([]);
  const [trackShown, setTrackShown] = useState(song.tab_track ?? 0);
  const tabRef = useRef<TabMedia | null>(null);
  if (isTab && !tabRef.current) {
    tabRef.current = new TabMedia(song.tab_track, (list, shown) => {
      setTracks(list);
      setTrackShown(shown);
    });
    videoRef.current = tabRef.current;
  }
  const [zoom, setZoom] = useState(() => clampZoom(Number(prefs.load("tabZoom", 1)) || 1));
  useEffect(() => {
    if (!isTab) return;
    tabRef.current?.zoom(zoom);
    prefs.save("tabZoom", zoom);
  }, [isTab, zoom]);
  const [view, setView] = useState<TabView>(() => {
    const v = prefs.load<string>("tabView", "both");
    return (TAB_VIEWS as readonly string[]).includes(v) ? (v as TabView) : "both";
  });
  useEffect(() => {
    if (!isTab) return;
    tabRef.current?.setView(view);
    prefs.save("tabView", view);
  }, [isTab, view]);
  const switchable = tracks.find((t) => t.index === trackShown)?.switchable ?? false;
  const graphRef = useRef<Graph | null>(null);
  // A saved A is where the song starts, B or no B: seek there once the media can take it (original timeline).
  const startAt = useRef<number | null>(null);

  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetId, setPresetId] = useState<number | null>(null);
  const [semitones, setSemitonesRaw] = useState(0);
  // alphaTab's synth transposes by whole semitones only.
  const setSemitones = useCallback(
    (v: number | ((s: number) => number)) =>
      setSemitonesRaw((s) => {
        const next = typeof v === "function" ? v(s) : v;
        return isTab ? tabPitch(next) : next;
      }),
    [isTab],
  );
  const [tempo, setTempo] = useState(1);
  const [loopA, setLoopA] = useState<number | null>(null);
  const [loopB, setLoopB] = useState<number | null>(null);
  const [loopOn, setLoopOn] = useState(false);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [pendingFor, setPendingFor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [controlsVisible, setControlsVisible] = useState(true);
  const [naming, setNaming] = useState(false); // the Save as… dialog is open
  const [confirmDelete, setConfirmDelete] = useState(false);
  // A preset with a volume brings it; otherwise (and for the original) it's this browser's level.
  const [volume, setVolume] = useState(browserVolume);
  const [muted, setMuted] = useState(() => prefs.load("muted", false));
  const [graphKind, setGraphKind] = useState<Graph["kind"] | "none">("none");
  // Position and length on the ORIGINAL timeline (like loop points), so 1:30 is
  // the same spot in the song whichever render is playing.
  const [position, setPosition] = useState(0);
  const [length, setLength] = useState(0);

  // Latest values for callbacks that outlive a render (rAF loop, key handler).
  const live = useRef({ semitones, tempo, loopA, loopB, loopOn, loaded, naming, confirmDelete });
  live.current = { semitones, tempo, loopA, loopB, loopOn, loaded, naming, confirmDelete };

  const preset = presets.find((p) => p.id === presetId) ?? null;
  const badge = isTab ? "tab" : loaded?.source === "render" ? "cached" : pendingFor !== null ? "rendering…" : "original";
  const modified =
    preset !== null &&
    (preset.semitones !== semitones ||
      preset.tempo !== tempo ||
      preset.loop_a !== loopA ||
      preset.loop_b !== loopB ||
      (preset.volume !== null && preset.volume !== volume));

  // --- loading sources ------------------------------------------------------

  const load = useCallback((next: Loaded) => {
    const video = videoRef.current;
    const prev = live.current.loaded;
    setLoaded(next);
    if (!video || (prev && prev.url === next.url)) return;
    const wasPlaying = prev ? !video.paused : true;
    const t = prev ? mapPosition(video.currentTime, prev.timeScale, next.timeScale) : 0;
    video.src = next.url;
    const onMeta = () => {
      video.removeEventListener("loadedmetadata", onMeta);
      if (t > 0) video.currentTime = t;
      if (wasPlaying) void video.play().catch(() => {});
    };
    video.addEventListener("loadedmetadata", onMeta);
  }, []);

  /** Apply a playback answer for `p` (null = original): load the render, or wait for it. */
  const applyPlayback = useCallback(
    (pb: Playback, p: Preset | null) => {
      if (pb.source === "render" && p) {
        setPendingFor(null);
        load(fromPlayback(song.id, pb, p));
      } else {
        setPendingFor(pb.source === "pending" && p ? p.id : null);
        load(ORIGINAL(song.id));
        if (pb.render_error) toast({ text: `Render failed: ${pb.render_error}`, kind: "error" });
      }
    },
    [load, song.id, toast],
  );

  // --- open / close ---------------------------------------------------------

  useEffect(() => {
    let cancelled = false;
    const video = videoRef.current!;
    const prevFocus = document.activeElement as HTMLElement | null;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    modalRef.current?.focus();

    // A <video> calls these through its JSX props; the tab player sends the same events.
    const tab = tabRef.current;
    const onTabEvent = (e: Event) => {
      if (e.type === "play") setPlaying(true);
      else if (e.type === "pause" || e.type === "ended") setPlaying(false);
      else if (e.type === "error") toast({ text: `Tab: ${tabErrors.at(-1) ?? "could not load"}`, kind: "error" });
      else syncTimeRef.current();
    };
    const tabEvents = ["play", "pause", "ended", "error", "timeupdate", "loadedmetadata", "durationchange", "seeked"];
    tabEvents.forEach((t) => tab?.addEventListener(t, onTabEvent));

    (async () => {
      graphRef.current = tab ? tab.graph() : await buildGraph(video as HTMLVideoElement);
      if (cancelled) return;
      setGraphKind(graphRef.current.kind);
      try {
        const [detail, pb] = await Promise.all([api.song(song.id), api.songPlayback(song.id)]);
        if (cancelled) return;
        const list = detail.presets ?? [];
        const p = list.find((x) => x.id === pb.preset_id) ?? null;
        setPresets(list);
        setPresetId(p?.id ?? null);
        setSemitones(pb.preset_id ? (p?.semitones ?? 0) : 0);
        setTempo(p?.tempo ?? 1);
        setVolume(p?.volume ?? browserVolume());
        setLoopA(pb.loop_a);
        setLoopB(pb.loop_b);
        setLoopOn(pb.loop_a !== null && pb.loop_b !== null);
        startAt.current = pb.loop_a;
        applyPlayback(pb, p);
      } catch (e) {
        toast({ text: errorText(e), kind: "error" });
      }
    })();

    return () => {
      cancelled = true;
      tabEvents.forEach((t) => tab?.removeEventListener(t, onTabEvent));
      video.pause();
      video.removeAttribute("src");
      video.load();
      void graphRef.current?.teardown();
      graphRef.current = null;
      document.body.style.overflow = prevOverflow;
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
      window.__songbook = { open: false, errors: graphErrors };
      prevFocus?.focus?.();
    };
  }, [song.id, applyPlayback, toast]);

  // --- live pitch / tempo ---------------------------------------------------

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !loaded) return;
    video.preservesPitch = true;
    video.playbackRate = r2(loaded.bakedTempo ? tempo / loaded.bakedTempo : tempo);
    graphRef.current?.setPitch(r2(semitones - loaded.bakedSemitones));
  }, [semitones, tempo, loaded, graphKind]);

  useEffect(() => {
    graphRef.current?.setVolume(muted ? 0 : gainOf(volume));
  }, [volume, muted, graphKind]);
  // Only a level set without a preset becomes the browser's; a preset's stays with the preset until saved.
  useEffect(() => {
    if (presetId === null) prefs.save("volume", volume);
  }, [volume, presetId]);
  useEffect(() => prefs.save("muted", muted), [muted]);

  // --- waiting for a render -------------------------------------------------

  useEffect(() => {
    if (pendingFor === null) return;
    let stop = false;
    const poll = async () => {
      try {
        const pb = await api.presetPlayback(pendingFor);
        if (stop) return;
        if (pb.source !== "pending") {
          const p = (await api.song(song.id)).presets?.find((x) => x.id === pendingFor);
          if (!stop && p) {
            applyPlayback(pb, p);
            return;
          }
        }
      } catch {
        /* retry */
      }
      if (!stop) setTimeout(poll, 1000);
    };
    const t = setTimeout(poll, 1000);
    return () => {
      stop = true;
      clearTimeout(t);
    };
  }, [pendingFor, song.id, applyPlayback]);

  // --- A/B loop, checked every frame ----------------------------------------

  useEffect(() => {
    const video = videoRef.current!;
    let handle = 0;
    let stop = false;
    const useVfc = "requestVideoFrameCallback" in video;
    const check = () => {
      if (stop) return;
      const { loopOn: on, loopA: a, loopB: b, loaded: l } = live.current;
      // Wait for metadata: until then a new source sits at 0 and would be pulled to A before load() restores its position.
      if (l && video.readyState >= HTMLMediaElement.HAVE_METADATA) {
        if (startAt.current !== null) {
          video.currentTime = startAt.current * l.timeScale;
          startAt.current = null;
        } else if (on) {
          const seek = loopSeek(video.currentTime, a, b, l.timeScale);
          if (seek !== null) video.currentTime = seek;
        }
      }
      schedule();
    };
    const schedule = () => {
      // rVFC only fires while frames are presented: fall back to rAF for audio-only media.
      if (useVfc && video.videoWidth > 0 && !video.paused) handle = (video as HTMLVideoElement).requestVideoFrameCallback(check);
      else handle = requestAnimationFrame(check);
    };
    schedule();
    return () => {
      stop = true;
      cancelAnimationFrame(handle);
      if (useVfc) (video as HTMLVideoElement).cancelVideoFrameCallback?.(handle);
    };
  }, []);

  // --- controls -------------------------------------------------------------

  const setA = () => {
    const l = live.current.loaded;
    const v = videoRef.current;
    if (!v || !l) return;
    const a = r2(v.currentTime / l.timeScale);
    setLoopA(a);
    if (live.current.loopB !== null && live.current.loopB <= a) setLoopB(null);
  };
  const setB = () => {
    const l = live.current.loaded;
    const v = videoRef.current;
    if (!v || !l) return;
    const b = r2(v.currentTime / l.timeScale);
    const a = live.current.loopA;
    if (a !== null && b <= a) {
      toast({ text: "B must be after A", kind: "error" });
      return;
    }
    setLoopB(b);
    if (a !== null) setLoopOn(true);
  };
  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      const { loopA: a, loaded: l } = live.current;
      if (v.ended && a !== null && l) v.currentTime = a * l.timeScale; // replay from A, not 0:00
      void graphRef.current?.ctx?.resume();
      void v.play().catch(() => {});
    } else v.pause();
  };
  /** Start over: from A while the loop is on, else from the top. Plays either way. */
  const rewind = () => {
    const v = videoRef.current;
    const { loopA: a, loopOn: on, loaded: l } = live.current;
    if (!v || !l) return;
    startAt.current = null;
    seekTo(on && a !== null ? a : 0);
    void graphRef.current?.ctx?.resume();
    if (v.paused) void v.play().catch(() => {});
  };
  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void modalRef.current?.requestFullscreen().catch(() => {});
  };
  // The original has no loop points: a preset's A/B don't carry over to it.
  const resetToOriginal = () => {
    setSemitones(0);
    setTempo(1);
    setVolume(browserVolume());
    setLoopA(null);
    setLoopB(null);
    setLoopOn(false);
    startAt.current = null;
    setPresetId(null);
    setPendingFor(null);
    load(ORIGINAL(song.id));
  };
  /** The song reopens with whatever was picked last: make `id` the default (null = the original). */
  const rememberChoice = async (id: number | null) => {
    const current = presets.find((p) => p.is_default)?.id ?? null;
    if (current === id) return;
    try {
      if (id === null) await api.patchPreset(current!, { is_default: false });
      else await api.patchPreset(id, { is_default: true });
      setPresets((await api.song(song.id)).presets ?? []);
      void lib.refresh();
    } catch (e) {
      toast({ text: errorText(e), kind: "error" });
    }
  };
  const selectPreset = async (id: number | null) => {
    if (id === null) {
      resetToOriginal();
      return rememberChoice(null);
    }
    const p = presets.find((x) => x.id === id);
    if (!p) return;
    void rememberChoice(id);
    setPresetId(id);
    setSemitones(p.semitones);
    setTempo(p.tempo);
    setVolume(p.volume ?? browserVolume());
    setLoopA(p.loop_a);
    setLoopB(p.loop_b);
    setLoopOn(p.loop_a !== null && p.loop_b !== null);
    startAt.current = p.loop_a;
    try {
      applyPlayback(await api.presetPlayback(id), p);
    } catch (e) {
      toast({ text: errorText(e), kind: "error" });
    }
  };

  /** Jump to `t` seconds on the original timeline. */
  const seekTo = (t: number) => {
    const v = videoRef.current;
    const l = live.current.loaded;
    if (!v || !l) return;
    const end = Number.isFinite(v.duration) ? v.duration / l.timeScale : t;
    const clamped = Math.min(Math.max(0, t), Math.max(0, end - 0.05));
    v.currentTime = clamped * l.timeScale;
    setPosition(clamped);
  };
  const syncTime = () => {
    const v = videoRef.current;
    const scale = live.current.loaded?.timeScale ?? 1;
    if (!v) return;
    setPosition(v.currentTime / scale);
    if (Number.isFinite(v.duration)) setLength(v.duration / scale);
  };
  const syncTimeRef = useRef(syncTime);
  syncTimeRef.current = syncTime;

  const showTrack = async (index: number) => {
    tabRef.current?.showTrack(index);
    try {
      await api.patchSong(song.id, { tab_track: index });
    } catch (e) {
      toast({ text: errorText(e), kind: "error" });
    }
  };

  /** Stop the song opening shifted: no preset is the default any more. */
  const openAtOriginal = async () => {
    const d = presets.find((p) => p.is_default);
    if (!d) return;
    try {
      await api.patchPreset(d.id, { is_default: false });
      setPresets((await api.song(song.id)).presets ?? []);
      toast({ text: "This song will open at its original pitch and tempo" });
      void lib.refresh();
    } catch (e) {
      toast({ text: errorText(e), kind: "error" });
    }
  };

  // Saving renders pitch AND tempo with Rubber Band; until that's ready the
  // live preview (SoundTouch pitch, browser tempo) keeps playing. The most
  // recently saved preset becomes the song's default. With a name (Save as…) it's
  // a new preset; without one (Save) it updates the selected preset in place.
  const save = async (name?: string) => {
    if (name === undefined && !preset) return;
    const body = {
      name: name ?? preset!.name,
      semitones,
      tempo,
      bake_tempo: true,
      loop_a: loopA,
      loop_b: loopB,
      is_default: true,
      volume,
    };
    try {
      const saved =
        name === undefined ? await api.patchPreset(preset!.id, body) : await api.createPreset(song.id, body);
      const detail = await api.song(song.id);
      setPresets(detail.presets ?? []);
      setPresetId(saved.id);
      setNaming(false);
      const renders = !isTab && !isIdentity(saved.semitones, saved.tempo, saved.bake_tempo);
      toast({ text: `Saved "${saved.name}"${renders ? " — rendering" : ""}` });
      applyPlayback(await api.presetPlayback(saved.id), saved);
      void lib.refresh();
    } catch (e) {
      toast({ text: errorText(e), kind: "error" });
    }
  };

  /** Delete the selected preset and go back to the original. No other preset is promoted to default. */
  const deletePreset = async () => {
    if (!preset) return;
    try {
      await api.deletePreset(preset.id);
      setConfirmDelete(false);
      setPresets((await api.song(song.id)).presets ?? []);
      resetToOriginal();
      toast({ text: `Deleted "${preset.name}"` });
      void lib.refresh();
    } catch (e) {
      toast({ text: errorText(e), kind: "error" });
    }
  };

  // --- keyboard, focus trap, fullscreen, auto-hide --------------------------

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (live.current.naming || live.current.confirmDelete) return; // the dialogs handle their own keys
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "Tab") {
        const nodes = modalRef.current?.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])",
        );
        if (!nodes?.length) return;
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        } else if (!modalRef.current?.contains(document.activeElement)) {
          e.preventDefault();
          first.focus();
        }
        return;
      }
      const t = e.target as HTMLElement;
      if (t.matches("input[type=text], input[type=search], input[type=number], textarea, select") || e.ctrlKey || e.metaKey || e.altKey) return;
      if (t.matches("input[type=range]") && (e.key.startsWith("Arrow") || e.key === "Home" || e.key === "End")) return;
      const { semitones: s, tempo: tp, loopOn: on } = live.current;
      const r = shortcut({ semitones: s, tempo: tp, loopOn: on }, e.key);
      if (!r) return;
      e.preventDefault();
      if (e.key === " " && t.tagName === "BUTTON") t.blur(); // don't also "click" the focused button
      setSemitones(r.state.semitones);
      setTempo(r.state.tempo);
      setLoopOn(r.state.loopOn);
      if (r.effect === "toggle-play") togglePlay();
      if (r.effect === "set-a") setA();
      if (r.effect === "set-b") setB();
      if (r.effect === "fullscreen") toggleFullscreen();
      if (r.effect === "toggle-mute") setMuted((m) => !m);
      if (r.effect && typeof r.effect === "object") {
        const v = videoRef.current;
        const scale = live.current.loaded?.timeScale ?? 1;
        if (v) seekTo("seekTo" in r.effect ? r.effect.seekTo : v.currentTime / scale + r.effect.seekBy);
      }
    };
    document.addEventListener("keydown", onKey);
    const onFs = () => setFullscreen(document.fullscreenElement === modalRef.current);
    document.addEventListener("fullscreenchange", onFs);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("fullscreenchange", onFs);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onClose]);

  const hideTimer = useRef<number>(0);
  const poke = useCallback(() => {
    setControlsVisible(true);
    window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => {
      if (!modalRef.current?.querySelector(".player-controls:hover, .player-controls:focus-within")) setControlsVisible(false);
    }, 2000);
  }, []);
  useEffect(() => {
    poke();
    return () => window.clearTimeout(hideTimer.current);
  }, [poke]);

  // --- test hook --------------------------------------------------------------

  useEffect(() => {
    const v = videoRef.current;
    window.__songbook = {
      open: true,
      songId: song.id,
      get pitch() {
        return graphRef.current?.pitch() ?? 0;
      },
      get playbackRate() {
        return v?.playbackRate;
      },
      zoom,
      view,
      switchable,
      get paused() {
        return v?.paused;
      },
      get currentTime() {
        return v?.currentTime;
      },
      get src() {
        return v?.currentSrc;
      },
      get gain() {
        return graphRef.current?.volume() ?? null;
      },
      volume,
      muted,
      get audioState() {
        return graphRef.current?.ctx?.state ?? "none";
      },
      graph: graphKind,
      kind: song.kind,
      tracks,
      trackShown,
      source: loaded?.source ?? null,
      badge,
      presetName: preset?.name ?? null,
      time_scale: loaded?.timeScale ?? 1,
      position,
      length,
      loop_a: loopA,
      loop_b: loopB,
      loopOn,
      semitones,
      tempo,
      errors: isTab ? tabErrors : graphErrors,
    };
  });

  // --- render -------------------------------------------------------------------

  const ctl = "rounded px-2 py-1 bg-white/10 hover:bg-white/20 disabled:opacity-40";
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
      data-testid="player-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-label={song.title}
        tabIndex={-1}
        data-testid="player"
        onMouseMove={poke}
        className={classNames(
          "relative flex flex-col overflow-hidden rounded-lg bg-black text-white shadow-2xl outline-none",
          fullscreen ? "w-screen h-screen" : "w-[92vw] h-[92vh]",
        )}
      >
        {isTab ? (
          <div
            data-testid="player-tab"
            className="player-tab isolate flex-1 min-h-0 w-full overflow-auto bg-white text-black pt-2 pb-32"
            ref={(scroller) => {
              const host = scroller?.firstElementChild as HTMLElement | null;
              if (scroller && host) tabRef.current?.attach(host, scroller);
            }}
          >
            <div />
          </div>
        ) : (
        <video
          ref={(el) => {
            videoRef.current = el;
          }}
          className="player-video flex-1 min-h-0 w-full h-full bg-black"
          data-testid="player-video"
          playsInline
          autoPlay
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onTimeUpdate={syncTime}
          onLoadedMetadata={syncTime}
          onDurationChange={syncTime}
          onSeeked={syncTime}
          onError={(e) => {
            const code = e.currentTarget.error?.code;
            // A new or just-added song may still be waiting for its H.264 copy.
            if (code === 3 || code === 4) {
              toast({ text: "Can't play this video: the browser may not support its format, or the connection dropped. Try again shortly.", kind: "error" });
            }
          }}
          onClick={togglePlay}
        />
        )}

        {/* Over a video only: a tab's score prints its own title, and a strip there hid the music. */}
        {!isTab && (
        <div className="absolute top-0 left-0 right-12 flex items-center gap-2 px-3 py-2 text-sm pointer-events-none">
          <span className="font-semibold truncate drop-shadow">{song.title}</span>
          <span
            data-testid="render-badge"
            className={classNames(
              "rounded px-2 py-px text-xs pointer-events-auto",
              badge === "cached" ? "bg-emerald-600" : badge === "original" || badge === "tab" ? "bg-white/20" : "bg-amber-600 animate-pulse",
            )}
          >
            {badge}
          </span>
          {preset && (
            <span data-testid="preset-badge" className="rounded px-2 py-px text-xs bg-theme-500">
              {preset.name}
              {modified ? " *" : ""}
            </span>
          )}
          {graphKind === "direct" && (
            <span className="rounded px-2 py-px text-xs bg-red-700" title="Web Audio worklets need HTTPS or localhost">
              live pitch unavailable
            </span>
          )}
        </div>
        )}
        <button
          type="button"
          aria-label="Close"
          data-testid="player-close"
          onClick={onClose}
          className="absolute top-2 right-2 rounded-full p-1.5 bg-black/50 hover:bg-white/20"
        >
          <MdClose className="w-6 h-6" />
        </button>

        <div
          className={classNames(
            "player-controls absolute bottom-0 inset-x-0 flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 text-sm bg-gradient-to-t from-black/90 to-black/40 transition-opacity duration-300",
            controlsVisible ? "opacity-100" : "opacity-0",
          )}
          data-testid="player-controls"
        >
          <div className="basis-full flex items-center gap-3">
            <span className="tabular-nums text-xs w-12 text-right" data-testid="position">{clock(position)}</span>
            <div className="relative flex-1 flex items-center">
              <input
                type="range"
                aria-label="Position"
                data-testid="seek"
                min={0}
                max={length || 0}
                step={0.1}
                value={Math.min(position, length || 0)}
                onChange={(e) => seekTo(Number(e.target.value))}
                disabled={!length}
                className="w-full accent-theme-400"
              />
              {length > 0 &&
                [loopA, loopB].map((m, i) =>
                  m === null ? null : (
                    <span
                      key={i}
                      aria-hidden
                      className={classNames(
                        "pointer-events-none absolute top-1/2 -translate-y-1/2 h-4 w-0.5",
                        loopOn ? "bg-amber-400" : "bg-white/50",
                      )}
                      style={{ left: `${(m / length) * 100}%` }}
                    />
                  ),
                )}
            </div>
            <span className="tabular-nums text-xs w-12" data-testid="length">{clock(length)}</span>
          </div>
          <button type="button" className={ctl} onClick={togglePlay} aria-label={playing ? "Pause" : "Play"}>
            {playing ? <MdPause /> : <MdPlayArrow />}
          </button>
          <button
            type="button"
            className={ctl}
            onClick={rewind}
            aria-label={loopOn && loopA !== null ? "Rewind to A" : "Rewind to start"}
            title={loopOn && loopA !== null ? "Play from A" : "Play from the start"}
          >
            <MdReplay />
          </button>

          <div className="flex items-center gap-1" role="group" aria-label="Volume">
            <button type="button" className={ctl} onClick={() => setMuted((m) => !m)} aria-label={muted ? "Unmute (M)" : "Mute (M)"}>
              {muted || volume === 0 ? <MdVolumeOff /> : volume < 0.5 ? <MdVolumeDown /> : <MdVolumeUp />}
            </button>
            {/* Past the mark at 100% is boost: the zone under it and the thumb go red. */}
            <div className="relative flex items-center" title={`${Math.round((muted ? 0 : volume) * 100)}%`}>
              <input
                type="range"
                aria-label="Volume"
                aria-valuetext={`${Math.round((muted ? 0 : volume) * 100)}%`}
                min={0}
                max={graphRef.current?.boost === false ? 1 : VOLUME_MAX}
                step={0.01}
                value={muted ? 0 : volume}
                onChange={(e) => {
                  setVolume(Number(e.target.value));
                  setMuted(false);
                }}
                className={classNames("w-36", !muted && volume > 1 ? "accent-red-500" : "accent-theme-400")}
              />
              {graphRef.current?.boost !== false && (
                <>
                  <span aria-hidden className="pointer-events-none absolute left-1/2 right-0 -bottom-0.5 h-0.5 rounded bg-red-500/70" />
                  <span
                    aria-hidden
                    data-testid="volume-100"
                    className="pointer-events-none absolute left-1/2 top-1/2 -translate-y-1/2 h-4 w-0.5 bg-white/60"
                  />
                </>
              )}
            </div>
          </div>

          <label className="flex items-center gap-1">
            Preset
            <select
              aria-label="Preset"
              className="rounded bg-white/10 text-white text-sm py-0.5 border-white/20"
              value={presetId ?? ""}
              onChange={(e) => void selectPreset(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="" className="text-black">(original)</option>
              {presets.map((p) => (
                <option key={p.id} value={p.id} className="text-black">
                  {p.name}
                  {p.is_default ? " (default)" : ""}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-center gap-1" role="group" aria-label="Preset actions">
            <button
              type="button"
              className={classNames(ctl, "relative")}
              onClick={() => void save()}
              disabled={!preset}
              aria-label="Save preset"
              title={preset ? `Save changes to "${preset.name}"` : "Pick a preset to save, or use Save as…"}
            >
              <MdSave />
              {modified && <span data-testid="unsaved" aria-hidden className="absolute top-0.5 right-0.5 h-1.5 w-1.5 rounded-full bg-amber-400" />}
            </button>
            <button type="button" className={ctl} onClick={() => setNaming(true)} aria-label="Save as…" title="Save as a new preset">
              <MdSaveAs />
            </button>
            {preset && (
              <button type="button" className={classNames(ctl, "ml-2")} onClick={() => setConfirmDelete(true)} aria-label="Delete preset" title={`Delete "${preset.name}"`}>
                <MdDeleteOutline />
              </button>
            )}
          </div>
          {presets.some((p) => p.is_default) && (
            <button type="button" className={ctl} onClick={openAtOriginal} title="Stop opening this song with a preset">
              Open at original
            </button>
          )}

          <div className="flex items-center gap-1" role="group" aria-label="Pitch">
            <span>Pitch</span>
            <button type="button" className={ctl} aria-label="Pitch down 1" onClick={() => setSemitones((s) => clampPitch(s - 1))}>−1</button>
            {!isTab && <button type="button" className={ctl} aria-label="Pitch down 0.5" onClick={() => setSemitones((s) => clampPitch(s - 0.5))}>−½</button>}
            <output data-testid="semitones" className="w-12 text-center tabular-nums">
              {semitones > 0 ? "+" : ""}
              {semitones}
            </output>
            {!isTab && <button type="button" className={ctl} aria-label="Pitch up 0.5" onClick={() => setSemitones((s) => clampPitch(s + 0.5))}>+½</button>}
            <button type="button" className={ctl} aria-label="Pitch up 1" onClick={() => setSemitones((s) => clampPitch(s + 1))}>+1</button>
          </div>

          <div className="flex items-center gap-2">
            <label htmlFor="tempo">Tempo</label>
            <input
              id="tempo"
              type="range"
              aria-label="Tempo"
              min={TEMPO_MIN}
              max={TEMPO_MAX}
              step={0.01}
              value={tempo}
              onChange={(e) => setTempo(clampTempo(Number(e.target.value)))}
              className="w-56 accent-theme-400"
            />
            <button type="button" className={ctl} aria-label="Tempo down 0.01" onClick={() => setTempo((t) => clampTempo(t - 0.01))}>−</button>
            <TempoField tempo={tempo} onCommit={setTempo} />
            <button type="button" className={ctl} aria-label="Tempo up 0.01" onClick={() => setTempo((t) => clampTempo(t + 0.01))}>+</button>
            <button type="button" className={ctl} onClick={() => setTempo(1)} disabled={tempo === 1}>1.0×</button>
          </div>

          <div className="flex items-center gap-1" role="group" aria-label="Loop">
            <button type="button" className={ctl} onClick={setA} title="Set loop start (A)">A{loopA !== null ? ` ${loopA.toFixed(1)}` : ""}</button>
            <button type="button" className={ctl} onClick={setB} title="Set loop end (B)">B{loopB !== null ? ` ${loopB.toFixed(1)}` : ""}</button>
            <button
              type="button"
              className={classNames(ctl, loopOn && "bg-theme-500")}
              aria-pressed={loopOn}
              aria-label="Loop"
              onClick={() => setLoopOn((x) => !x)}
              disabled={loopA === null || loopB === null}
            >
              <MdRepeat />
            </button>
          </div>

          {tracks.length > 1 && (
            <label className="flex items-center gap-1">
              Track
              <select
                aria-label="Track"
                className="rounded bg-white/10 text-white text-sm py-0.5 border-white/20"
                value={trackShown}
                onChange={(e) => void showTrack(Number(e.target.value))}
              >
                {tracks.map((t) => (
                  <option key={t.index} value={t.index} className="text-black">
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          {switchable && (
            <label className="flex items-center gap-1">
              Show
              <select
                aria-label="Show"
                className="rounded bg-white/10 text-white text-sm py-0.5 border-white/20"
                value={view}
                onChange={(e) => setView(e.target.value as TabView)}
              >
                <option value="both" className="text-black">Score + tab</option>
                <option value="tab" className="text-black">Tab</option>
                <option value="score" className="text-black">Score</option>
              </select>
            </label>
          )}

          {isTab && (
            <div className="flex items-center gap-1" role="group" aria-label="Zoom">
              <button type="button" className={ctl} aria-label="Zoom out" onClick={() => setZoom((z) => clampZoom(z - 0.1))} disabled={zoom <= ZOOM_MIN}>
                <MdZoomOut />
              </button>
              <button type="button" data-testid="zoom" className={classNames(ctl, "w-14 tabular-nums")} onClick={() => setZoom(1)} disabled={zoom === 1} title="Back to 100%">
                {Math.round(zoom * 100)}%
              </button>
              <button type="button" className={ctl} aria-label="Zoom in" onClick={() => setZoom((z) => clampZoom(z + 0.1))} disabled={zoom >= ZOOM_MAX}>
                <MdZoomIn />
              </button>
            </div>
          )}

          <div className="flex items-center gap-1 ml-auto">
            <button type="button" className={ctl} onClick={toggleFullscreen} aria-label="Fullscreen (F)">
              {fullscreen ? <MdFullscreenExit /> : <MdFullscreen />}
            </button>
          </div>
        </div>

        {naming && <SaveDialog isTab={isTab} onCancel={() => setNaming(false)} onSave={save} />}
        {confirmDelete && preset && (
          <DeletePresetDialog name={preset.name} onCancel={() => setConfirmDelete(false)} onDelete={deletePreset} />
        )}
      </div>
    </div>
  );
}

function SaveDialog({ isTab, onCancel, onSave }: { isTab: boolean; onCancel: () => void; onSave: (name: string) => void }) {
  const [name, setName] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) onSave(name.trim());
  };
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/60" onKeyDown={(e) => {
      if (e.key !== "Escape") return;
      e.stopPropagation(); // the player would close on it too
      onCancel();
    }}>
      <form
        onSubmit={submit}
        role="dialog"
        aria-label="Save as new preset"
        className="w-full max-w-sm rounded-lg bg-theme-50 dark:bg-theme-800 text-theme-800 dark:text-theme-100 p-5 flex flex-col gap-3"
      >
        <h2 className="text-lg font-semibold">Save as new preset</h2>
        <label className="text-sm flex flex-col gap-1">
          Name
          <input autoFocus name="preset-name" type="text" className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <p className="text-xs text-theme-500">
          {isTab ? "The tab plays at this pitch and tempo." : "Pitch and tempo are rendered with Rubber Band and cached."} The song opens with its most
          recently saved preset.
        </p>
        <div className="flex justify-end gap-2">
          <button type="button" className={plainButtonClass} onClick={onCancel}>Cancel</button>
          <button type="submit" className={buttonClass} disabled={!name.trim()}>Save</button>
        </div>
      </form>
    </div>
  );
}

function DeletePresetDialog({ name, onCancel, onDelete }: { name: string; onCancel: () => void; onDelete: () => void }) {
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/60" onKeyDown={(e) => {
      if (e.key !== "Escape") return;
      e.stopPropagation(); // the player would close on it too
      onCancel();
    }}>
      <div
        role="dialog"
        aria-label="Delete preset"
        className="w-full max-w-sm rounded-lg bg-theme-50 dark:bg-theme-800 text-theme-800 dark:text-theme-100 p-5 flex flex-col gap-3"
      >
        <h2 className="text-lg font-semibold">Delete "{name}"?</h2>
        <p className="text-sm">The song goes back to its original pitch and tempo. Its render stays cached until cleanup.</p>
        <div className="flex justify-end gap-2">
          <button type="button" autoFocus className={plainButtonClass} onClick={onCancel}>Cancel</button>
          <button type="button" className="rounded px-3 py-1.5 text-sm font-medium bg-red-600 text-white" onClick={onDelete}>Delete</button>
        </div>
      </div>
    </div>
  );
}

function clock(t: number): string {
  if (!Number.isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60);
  const sec = Math.floor(t % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

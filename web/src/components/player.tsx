import classNames from "classnames";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { MdClose, MdFullscreen, MdFullscreenExit, MdPause, MdPlayArrow, MdRepeat } from "react-icons/md";

import { api, errorText, type Playback, type Preset, type Song } from "../lib/api";
import { buildGraph, type Graph, graphErrors } from "../lib/audioGraph";
import { isIdentity } from "../lib/cacheKey";
import { useLibrary } from "../lib/library";
import { loopSeek, mapPosition } from "../lib/loop";
import { clampPitch, clampTempo, shortcut, TEMPO_MAX, TEMPO_MIN } from "../lib/shortcuts";
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

declare global {
  interface Window {
    __songbook?: Record<string, unknown>;
  }
}

export default function Player({ song, onClose }: { song: Song; onClose: () => void }) {
  const lib = useLibrary();
  const toast = useToast();
  const modalRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const graphRef = useRef<Graph | null>(null);

  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetId, setPresetId] = useState<number | null>(null);
  const [semitones, setSemitones] = useState(0);
  const [tempo, setTempo] = useState(1);
  const [loopA, setLoopA] = useState<number | null>(null);
  const [loopB, setLoopB] = useState<number | null>(null);
  const [loopOn, setLoopOn] = useState(false);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [pendingFor, setPendingFor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [controlsVisible, setControlsVisible] = useState(true);
  const [saveMode, setSaveMode] = useState<"save" | "save-as" | null>(null);
  const [graphKind, setGraphKind] = useState<"worklet" | "direct" | "none">("none");
  // Position and length on the ORIGINAL timeline (like loop points), so 1:30 is
  // the same spot in the song whichever render is playing.
  const [position, setPosition] = useState(0);
  const [length, setLength] = useState(0);

  // Latest values for callbacks that outlive a render (rAF loop, key handler).
  const live = useRef({ semitones, tempo, loopA, loopB, loopOn, loaded, saveMode });
  live.current = { semitones, tempo, loopA, loopB, loopOn, loaded, saveMode };

  const preset = presets.find((p) => p.id === presetId) ?? null;
  const badge = loaded?.source === "render" ? "cached" : pendingFor !== null ? "rendering…" : "original";
  const modified =
    preset !== null &&
    (preset.semitones !== semitones || preset.tempo !== tempo || preset.loop_a !== loopA || preset.loop_b !== loopB);

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

    (async () => {
      graphRef.current = await buildGraph(video);
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
        setLoopA(pb.loop_a);
        setLoopB(pb.loop_b);
        setLoopOn(pb.loop_a !== null && pb.loop_b !== null);
        applyPlayback(pb, p);
      } catch (e) {
        toast({ text: errorText(e), kind: "error" });
      }
    })();

    return () => {
      cancelled = true;
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
      if (on && l) {
        const seek = loopSeek(video.currentTime, a, b, l.timeScale);
        if (seek !== null) video.currentTime = seek;
      }
      schedule();
    };
    const schedule = () => {
      // rVFC only fires while frames are presented: fall back to rAF for audio-only media.
      if (useVfc && video.videoWidth > 0 && !video.paused) handle = video.requestVideoFrameCallback(check);
      else handle = requestAnimationFrame(check);
    };
    schedule();
    return () => {
      stop = true;
      cancelAnimationFrame(handle);
      if (useVfc) video.cancelVideoFrameCallback?.(handle);
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
      void graphRef.current?.ctx?.resume();
      void v.play().catch(() => {});
    } else v.pause();
  };
  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void modalRef.current?.requestFullscreen().catch(() => {});
  };
  const resetToOriginal = () => {
    setSemitones(0);
    setTempo(1);
    setPresetId(null);
    setPendingFor(null);
    load(ORIGINAL(song.id));
  };
  const selectPreset = async (id: number | null) => {
    if (id === null) return resetToOriginal();
    const p = presets.find((x) => x.id === id);
    if (!p) return;
    setPresetId(id);
    setSemitones(p.semitones);
    setTempo(p.tempo);
    setLoopA(p.loop_a);
    setLoopB(p.loop_b);
    setLoopOn(p.loop_a !== null && p.loop_b !== null);
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
  // recently saved preset becomes the song's default.
  const save = async (name: string) => {
    const body = {
      name,
      semitones,
      tempo,
      bake_tempo: true,
      loop_a: loopA,
      loop_b: loopB,
      is_default: true,
    };
    try {
      const saved =
        saveMode === "save" && preset ? await api.patchPreset(preset.id, body) : await api.createPreset(song.id, body);
      const detail = await api.song(song.id);
      setPresets(detail.presets ?? []);
      setPresetId(saved.id);
      setSaveMode(null);
      toast({ text: `Saved "${saved.name}"${isIdentity(saved.semitones, saved.tempo, saved.bake_tempo) ? "" : " — rendering"}` });
      applyPlayback(await api.presetPlayback(saved.id), saved);
      void lib.refresh();
    } catch (e) {
      toast({ text: errorText(e), kind: "error" });
    }
  };

  // --- keyboard, focus trap, fullscreen, auto-hide --------------------------

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (live.current.saveMode) return; // the save dialog handles its own keys
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
      if (t.matches("input[type=text], input[type=search], textarea, select") || e.ctrlKey || e.metaKey || e.altKey) return;
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
      get paused() {
        return v?.paused;
      },
      get currentTime() {
        return v?.currentTime;
      },
      get src() {
        return v?.currentSrc;
      },
      get audioState() {
        return graphRef.current?.ctx?.state ?? "none";
      },
      graph: graphKind,
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
      errors: graphErrors,
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
        <video
          ref={videoRef}
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
          onClick={togglePlay}
        />

        <div className="absolute top-2 left-3 right-14 flex items-center gap-2 text-sm pointer-events-none">
          <span className="font-semibold truncate drop-shadow">{song.title}</span>
          <span
            data-testid="render-badge"
            className={classNames(
              "rounded px-2 py-px text-xs pointer-events-auto",
              badge === "cached" ? "bg-emerald-600" : badge === "original" ? "bg-white/20" : "bg-amber-600 animate-pulse",
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
          {presets.some((p) => p.is_default) && (
            <button type="button" className={ctl} onClick={openAtOriginal} title="Stop opening this song with a preset">
              Open at original
            </button>
          )}

          <div className="flex items-center gap-1" role="group" aria-label="Pitch">
            <span>Pitch</span>
            <button type="button" className={ctl} aria-label="Pitch down 1" onClick={() => setSemitones((s) => clampPitch(s - 1))}>−1</button>
            <button type="button" className={ctl} aria-label="Pitch down 0.5" onClick={() => setSemitones((s) => clampPitch(s - 0.5))}>−½</button>
            <output data-testid="semitones" className="w-12 text-center tabular-nums">
              {semitones > 0 ? "+" : ""}
              {semitones}
            </output>
            <button type="button" className={ctl} aria-label="Pitch up 0.5" onClick={() => setSemitones((s) => clampPitch(s + 0.5))}>+½</button>
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
              list="tempo-ticks"
              value={tempo}
              onChange={(e) => setTempo(clampTempo(Number(e.target.value)))}
              className="w-40 accent-theme-400"
            />
            <datalist id="tempo-ticks">
              <option value="1" />
            </datalist>
            <output data-testid="tempo" className="w-12 tabular-nums">{tempo.toFixed(2)}×</output>
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

          <div className="flex items-center gap-1 ml-auto">
            <button type="button" className={ctl} onClick={resetToOriginal}>Reset to original</button>
            <button type="button" className={ctl} onClick={() => setSaveMode("save")}>Save preset</button>
            <button type="button" className={ctl} onClick={() => setSaveMode("save-as")}>Save as…</button>
            <button type="button" className={ctl} onClick={toggleFullscreen} aria-label="Fullscreen (F)">
              {fullscreen ? <MdFullscreenExit /> : <MdFullscreen />}
            </button>
          </div>
        </div>

        {saveMode && (
          <SaveDialog
            initialName={saveMode === "save" && preset ? preset.name : ""}
            onCancel={() => setSaveMode(null)}
            onSave={save}
          />
        )}
      </div>
    </div>
  );
}

function SaveDialog({ initialName, onCancel, onSave }: {
  initialName: string;
  onCancel: () => void;
  onSave: (name: string) => void;
}) {
  const [name, setName] = useState(initialName);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) onSave(name.trim());
  };
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/60" onKeyDown={(e) => e.key === "Escape" && onCancel()}>
      <form
        onSubmit={submit}
        role="dialog"
        aria-label="Save preset"
        className="w-full max-w-sm rounded-lg bg-theme-50 dark:bg-theme-800 text-theme-800 dark:text-theme-100 p-5 flex flex-col gap-3"
      >
        <h2 className="text-lg font-semibold">Save preset</h2>
        <label className="text-sm flex flex-col gap-1">
          Name
          <input autoFocus name="preset-name" type="text" className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <p className="text-xs text-theme-500">Pitch and tempo are rendered with Rubber Band and cached. The song opens with its most recently saved preset.</p>
        <div className="flex justify-end gap-2">
          <button type="button" className={plainButtonClass} onClick={onCancel}>Cancel</button>
          <button type="submit" className={buttonClass} disabled={!name.trim()}>Save</button>
        </div>
      </form>
    </div>
  );
}

function clock(t: number): string {
  if (!Number.isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60);
  const sec = Math.floor(t % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

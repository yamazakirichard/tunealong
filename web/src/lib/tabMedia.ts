// A tab song (Guitar Pro / MusicXML) played by alphaTab, behind the small part
// of the HTMLMediaElement interface the player uses. The player's loop, seek,
// keyboard and preset logic then work unchanged, and pitch/volume go through a
// Graph like the video's do.
//
// Times here are song seconds at speed 1.0 (lib/tabTime.ts converts from the
// synth's stretched milliseconds): the "original timeline" loop points use.
//
// alphaTab itself is loaded on first use (dynamic import), so the main bundle
// stays small for libraries without tab songs.

import type { AlphaTabApi, model } from "@coderline/alphatab";

import type { Graph } from "./audioGraph";
import { songToSynth, synthToSong } from "./tabTime";

export interface TabTrack {
  index: number;
  name: string;
}

/** What the player needs from its media: an HTMLVideoElement satisfies it too. */
export interface MediaLike extends EventTarget {
  currentTime: number;
  readonly duration: number;
  readonly paused: boolean;
  readonly ended: boolean;
  readonly readyState: number;
  readonly videoWidth: number;
  readonly currentSrc: string;
  playbackRate: number;
  preservesPitch: boolean;
  src: string;
  play(): Promise<void>;
  pause(): void;
  load(): void;
  removeAttribute(name: string): void;
}

export const tabErrors: string[] = [];

/** The integer semitones the synth can play: it offsets MIDI keys, so no half steps. */
export const tabPitch = (s: number) => Math.round(s);

export class TabMedia extends EventTarget implements MediaLike {
  private api: AlphaTabApi | null = null;
  private container: HTMLElement | null = null;
  private scroller: HTMLElement | null = null;
  private time = 0; // seconds
  private end = NaN;
  private isEnded = false;
  // For a moment after a seek, only positions that fit it are believed (see playerPositionChanged).
  private seekTarget: number | null = null;
  private seekAt = 0;
  private ready = { score: false, player: false, midi: false };
  private wantPlay = false;
  private rate = 1;
  private semitones = 0;
  private gain = 1;
  private url = "";
  private track: number;
  private destroyed = false;
  readonly videoWidth = 0;
  preservesPitch = true;

  constructor(
    track: number | null,
    private onTracks: (tracks: TabTrack[], shown: number) => void,
  ) {
    super();
    this.track = track ?? 0;
  }

  /** The element the tab is drawn into, and the one that scrolls. Call before setting src. */
  attach(container: HTMLElement, scroller: HTMLElement) {
    this.container = container;
    this.scroller = scroller;
  }

  // --- HTMLMediaElement-like surface ---------------------------------------

  get currentTime() {
    return this.time;
  }
  set currentTime(t: number) {
    this.time = Math.max(0, t);
    this.isEnded = false;
    if (this.api && this.readyState) {
      this.seekTarget = this.time;
      this.seekAt = performance.now();
      this.api.timePosition = songToSynth(this.time, this.rate);
    }
    this.emit("seeked");
    this.emit("timeupdate");
  }
  get duration() {
    return this.end;
  }
  get paused() {
    return !this.api || this.api.playerState !== 1; // PlayerState.Playing
  }
  get ended() {
    return this.isEnded;
  }
  get readyState() {
    const r = this.ready;
    return r.score && r.player && r.midi ? 4 : 0; // HAVE_ENOUGH_DATA, or HAVE_NOTHING
  }
  get currentSrc() {
    return this.url;
  }
  get playbackRate() {
    return this.rate;
  }
  set playbackRate(r: number) {
    this.rate = r;
    if (this.api) this.api.playbackSpeed = r;
  }
  get src() {
    return this.url;
  }
  set src(url: string) {
    this.url = url;
    void this.open(url).catch((e) => this.fail(e as Error));
  }

  play(): Promise<void> {
    this.isEnded = false;
    if (this.readyState) this.api!.play();
    else this.wantPlay = true;
    return Promise.resolve();
  }
  pause() {
    this.wantPlay = false;
    this.api?.pause();
  }
  load() {}
  removeAttribute() {}

  /** Show a different track. Playback still plays every track. */
  showTrack(index: number) {
    const tracks = this.api?.score?.tracks;
    if (!tracks?.[index]) return;
    this.track = index;
    this.api!.renderTracks([tracks[index]]);
    this.onTracks(trackList(tracks), index);
  }

  destroy() {
    this.destroyed = true;
    this.api?.destroy();
    this.api = null;
  }

  /** Pitch and volume for the player, in the shape of the video's audio graph. */
  graph(): Graph {
    return {
      ctx: null,
      node: null,
      kind: "tab",
      setPitch: (s) => {
        this.semitones = tabPitch(s);
        this.applyPitch();
      },
      pitch: () => this.semitones,
      setVolume: (g) => {
        this.gain = g;
        if (this.api) this.api.masterVolume = g;
      },
      volume: () => this.gain,
      boost: true, // alphaTab's master volume has no upper limit
      teardown: async () => this.destroy(),
    };
  }

  // --- internals -------------------------------------------------------------

  private fail(e: Error) {
    console.error("alphaTab:", e);
    tabErrors.push(`${e.name}: ${e.message}`);
    this.emit("error");
  }

  private emit(type: string) {
    this.dispatchEvent(new Event(type));
  }

  private applyPitch() {
    const tracks = this.api?.score?.tracks;
    if (tracks?.length) this.api!.changeTrackTranspositionPitch(tracks, this.semitones);
  }

  private async open(url: string) {
    if (!this.container || !this.scroller) throw new Error("TabMedia: attach() was not called");
    const [at, res] = await Promise.all([import("@coderline/alphatab"), fetch(url)]);
    if (!res.ok) throw new Error(`could not fetch the tab file (${res.status})`);
    const bytes = new Uint8Array(await res.arrayBuffer());
    if (this.destroyed) return;
    this.api?.destroy();
    this.ready = { score: false, player: false, midi: false };
    // Fonts and the SoundFont are copied into the build by the alphaTab Vite
    // plugin, next to index.html. Resolve them against the page, which works
    // under any SONGBOOK_BASE_PATH.
    const asset = (p: string) => new URL(p, document.baseURI).href;
    const api = new at.AlphaTabApi(this.container, {
      core: { fontDirectory: asset("font/"), includeNoteBounds: false },
      display: { layoutMode: at.LayoutMode.Page, staveProfile: at.StaveProfile.Default },
      player: {
        playerMode: at.PlayerMode.EnabledSynthesizer,
        soundFont: asset("soundfont/sonivox.sf2"),
        scrollElement: this.scroller,
        enableCursor: true,
        enableAnimatedBeatCursor: true,
        enableUserInteraction: true, // click a beat to jump there
      },
    });
    this.api = api;
    api.masterVolume = this.gain;
    api.playbackSpeed = this.rate;
    api.error.on((e) => this.fail(e));
    api.scoreLoaded.on((score) => {
      if (!score.tracks[this.track]) this.track = 0;
      this.ready.score = true;
      this.applyPitch();
      this.onTracks(trackList(score.tracks), this.track);
      this.maybeReady();
    });
    api.playerReady.on(() => {
      this.ready.player = true;
      this.maybeReady();
    });
    // Not api.midiLoaded: in 1.8.x subscribing to it recurses forever in the
    // worker synth (AlphaSynthWebWorkerApi.loadedMidiInfo returns itself). The
    // synth reports position 0, with the song's end time, right after a MIDI
    // loads, so the first position that has an end time stands in for it.
    api.playerStateChanged.on((e) => this.emit(e.state === 1 ? "play" : "pause"));
    api.playerPositionChanged.on((e) => {
      if (!(Number.isFinite(e.endTime) && e.endTime > 0)) return;
      const first = !this.ready.midi;
      // The speed this event was computed at: one sent before a speed change can
      // arrive after it, and must not be read at the new speed.
      const speed = e.originalTempo > 0 && e.modifiedTempo > 0 ? e.modifiedTempo / e.originalTempo : this.rate;
      const end = synthToSong(e.endTime, speed);
      // Changing speed re-reports the same end; only a real change is news.
      if (!(Math.abs(this.end - end) < 0.01)) {
        this.end = end;
        this.emit("durationchange");
      }
      if (first) {
        this.ready.midi = true;
        this.applyPitch(); // a new MIDI resets the synth's channel state
        this.maybeReady(); // keeps a position asked for before the song was ready
        return;
      }
      const t = synthToSong(e.currentTime, speed);
      if (this.seekTarget !== null) {
        // The worker answers in order, but a report it queued before our seek
        // (a pause's, say) can still come after the seek's own. For a second,
        // believe only positions that fit the seek: from the target up to how
        // far playback could have got since. A stray seek elsewhere is undone.
        const since = performance.now() - this.seekAt;
        const target = this.seekTarget;
        if (since > 1000) this.seekTarget = null;
        else if (t < target - 0.05 || t > target + (since / 1000) * this.rate + 0.1) {
          if (e.isSeek) this.api!.timePosition = songToSynth(target, this.rate);
          return;
        }
      }
      this.time = t;
      this.emit("timeupdate");
    });
    api.playerFinished.on(() => {
      this.isEnded = true;
      this.emit("ended");
    });
    api.load(bytes, [this.track]);
  }

  private maybeReady() {
    if (!this.readyState) return;
    if (this.time > 0) this.api!.timePosition = songToSynth(this.time, this.rate);
    this.emit("loadedmetadata");
    if (this.wantPlay) {
      this.wantPlay = false;
      this.api!.play();
    }
  }
}

function trackList(tracks: model.Track[]): TabTrack[] {
  return tracks.map((t, i) => ({ index: i, name: t.name || `Track ${i + 1}` }));
}

/** Artist and title from a tab file's own metadata, for the Add song dialog. */
export async function tabMetadata(bytes: Uint8Array): Promise<{ artist: string; title: string } | null> {
  try {
    const at = await import("@coderline/alphatab");
    const score = at.importer.ScoreLoader.loadScoreFromBytes(bytes, new at.Settings());
    // alphaTab's MusicXML importer turns spaces into no-break spaces (U+00A0):
    // store plain ones, so titles search and sort like typed ones.
    const plain = (s: string) => s.replace(/\s+/gu, " ").trim();
    return { artist: plain(score.artist), title: plain(score.title) };
  } catch {
    return null;
  }
}

// Record another browser tab (picture and sound) into a WebM, for Add song.
//
// The user picks the tab in the browser's share dialog, starts playback there
// themselves, and comes back to press Stop. Songbook never touches the other
// tab: it only receives what the browser's own screen sharing gives it.
// Tab audio needs Chrome or Edge, with "Also share tab audio" ticked.

export interface Recording {
  blob: Blob;
  seconds: number;
}

export class RecorderError extends Error {}

/** The best WebM the browser can record, or null when it can't record WebM at all. */
export function pickMimeType(isSupported: (t: string) => boolean): string | null {
  for (const t of ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"]) {
    if (isSupported(t)) return t;
  }
  return null;
}

export function canRecord(): boolean {
  return (
    window.isSecureContext &&
    typeof MediaRecorder !== "undefined" &&
    typeof navigator.mediaDevices?.getDisplayMedia === "function" &&
    pickMimeType((t) => MediaRecorder.isTypeSupported(t)) !== null
  );
}

export class TabRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private startedAt = 0;
  private done: ((r: Recording) => void) | null = null;
  private result: Promise<Recording> | null = null;

  /** Called when recording stops by itself: the user ended sharing from the browser's bar. */
  onEnded: (() => void) | null = null;

  /** Ask for a tab and start recording it. Rejects if nothing was shared, or it has no sound. */
  async start(): Promise<void> {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 30 },
        // Keep the tab's own sound as it is: these processing steps are for voices.
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        // Chrome: offer tabs first, keep audio sharing on, and don't offer Songbook's own tab.
        ...({ preferCurrentTab: false, selfBrowserSurface: "exclude", systemAudio: "include", surfaceSwitching: "exclude" } as object),
      } as DisplayMediaStreamOptions);
    } catch (e) {
      if ((e as Error).name === "NotAllowedError") throw new RecorderError("Sharing was cancelled.");
      throw e;
    }
    if (stream.getAudioTracks().length === 0) {
      stream.getTracks().forEach((t) => t.stop());
      throw new RecorderError('No sound was shared. Pick a browser tab and tick "Also share tab audio".');
    }
    const mimeType = pickMimeType((t) => MediaRecorder.isTypeSupported(t))!;
    const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 4_000_000, audioBitsPerSecond: 192_000 });
    this.stream = stream;
    this.recorder = recorder;
    this.chunks = [];
    this.result = new Promise((resolve) => (this.done = resolve));
    recorder.ondataavailable = (e) => {
      if (e.data.size) this.chunks.push(e.data);
    };
    recorder.onstop = () => {
      const seconds = (performance.now() - this.startedAt) / 1000;
      this.stream?.getTracks().forEach((t) => t.stop());
      this.done?.({ blob: new Blob(this.chunks, { type: "video/webm" }), seconds });
    };
    // "Stop sharing" in the browser's bar ends the video track: treat it as Stop.
    stream.getVideoTracks()[0]?.addEventListener("ended", () => {
      if (recorder.state !== "inactive") {
        recorder.stop();
        this.onEnded?.();
      }
    });
    recorder.start(1000); // a chunk a second, so a long recording isn't one huge buffer at the end
    this.startedAt = performance.now();
  }

  get recording(): boolean {
    return this.recorder?.state === "recording";
  }

  elapsed(): number {
    return this.recording ? (performance.now() - this.startedAt) / 1000 : 0;
  }

  /** Stop and hand back what was recorded. */
  stop(): Promise<Recording> {
    if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
    return this.result ?? Promise.reject(new RecorderError("Nothing was recorded."));
  }

  /** Throw the recording away (dialog closed mid-recording). */
  cancel() {
    this.done = null;
    if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
    this.stream?.getTracks().forEach((t) => t.stop());
  }
}

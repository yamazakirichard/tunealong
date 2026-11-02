import { useEffect, useMemo, useRef, useState } from "react";
import { MdFiberManualRecord, MdStop } from "react-icons/md";

import { type Recording, RecorderError, TabRecorder } from "../lib/tabRecorder";
import { buttonClass, plainButtonClass } from "./dialog";

const clock = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const mb = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(1)} MB`;

/** Record button, timer and Stop; then a preview of what was recorded. The user plays the other tab themselves. */
export default function RecordPanel({ recording, onRecording, onRecordingNow }: {
  recording: Recording | null;
  onRecording: (r: Recording | null) => void;
  onRecordingNow: (on: boolean) => void;
}) {
  const recorder = useRef<TabRecorder | null>(null);
  const [now, setNow] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const setRecordingNow = (on: boolean) => {
    setNow(on);
    onRecordingNow(on);
  };

  // Tick the timer while recording; drop the recorder (and its stream) when the dialog goes.
  useEffect(() => {
    if (!now) return;
    const t = setInterval(() => setElapsed(recorder.current?.elapsed() ?? 0), 250);
    return () => clearInterval(t);
  }, [now]);
  useEffect(() => () => recorder.current?.cancel(), []);

  // One object URL per recording, released when it's replaced or the panel goes.
  const previewUrl = useMemo(() => (recording ? URL.createObjectURL(recording.blob) : null), [recording]);
  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const finish = async () => {
    const r = recorder.current;
    if (!r) return;
    const rec = await r.stop();
    recorder.current = null;
    setRecordingNow(false);
    onRecording(rec.blob.size > 0 ? rec : null);
    if (!rec.blob.size) setError("Nothing was recorded.");
  };

  const start = async () => {
    setError(null);
    onRecording(null);
    const r = new TabRecorder();
    r.onEnded = () => void finish(); // "Stop sharing" in the browser's bar
    try {
      await r.start();
    } catch (e) {
      setError(e instanceof RecorderError ? e.message : `Could not start recording: ${(e as Error).message}`);
      return;
    }
    recorder.current = r;
    setElapsed(0);
    setRecordingNow(true);
  };

  return (
    <div className="text-sm flex flex-col gap-2" data-testid="record-panel">
      {!now && !recording && (
        <ol className="list-decimal pl-5 text-xs text-theme-500 flex flex-col gap-0.5">
          <li>Press Record, pick the tab to record, and tick "Also share tab audio".</li>
          <li>Go to that tab and start playback there.</li>
          <li>Come back and press Stop when it ends (or use "Stop sharing" in the browser's bar).</li>
        </ol>
      )}
      <div className="flex items-center gap-2">
        {now ? (
          <>
            <button type="button" className={buttonClass} onClick={() => void finish()}>
              <MdStop className="inline -mt-0.5" /> Stop
            </button>
            <span className="flex items-center gap-1 tabular-nums" data-testid="record-timer">
              <MdFiberManualRecord className="text-red-600 animate-pulse" aria-hidden /> Recording {clock(elapsed)}
            </span>
          </>
        ) : (
          <button type="button" className={recording ? plainButtonClass : buttonClass} onClick={() => void start()}>
            <MdFiberManualRecord className="inline -mt-0.5 text-red-600" /> {recording ? "Record again" : "Record"}
          </button>
        )}
        {recording && !now && (
          <span className="text-xs text-theme-500" data-testid="record-summary">
            {clock(recording.seconds)} · {mb(recording.blob.size)}
          </span>
        )}
      </div>
      {error && (
        <p role="alert" className="text-xs text-red-600">
          {error}
        </p>
      )}
      {recording && !now && previewUrl && (
        <video src={previewUrl} controls className="w-full max-h-48 rounded bg-black" data-testid="record-preview" />
      )}
    </div>
  );
}

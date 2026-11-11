// alphaTab's synth reports and seeks in milliseconds of playback time, which
// playbackSpeed stretches evenly (at speed 0.5 a 4 s song ends at 8000 ms).
// TuneAlong keeps positions and loop points on the song's own timeline, the
// seconds at speed 1.0, like the original timeline of a video. These convert.

/** Synth milliseconds at `speed` → song seconds. */
export function synthToSong(ms: number, speed: number): number {
  return (ms / 1000) * speed;
}

/** Song seconds → synth milliseconds at `speed`. */
export function songToSynth(seconds: number, speed: number): number {
  return (Math.max(0, seconds) * 1000) / speed;
}

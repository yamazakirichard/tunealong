// Loop points and positions are stored in ORIGINAL-timeline seconds. A baked
// tempo render runs `timeScale` times longer (timeScale = 1 / tempo).

/** Where to seek to, or null to keep playing. */
export function loopSeek(
  t: number,
  loopA: number | null,
  loopB: number | null,
  timeScale = 1,
): number | null {
  if (loopA == null || loopB == null || loopB <= loopA) return null;
  return t >= loopB * timeScale ? loopA * timeScale : null;
}

/** Position on the media being played → original timeline. */
export function toOriginal(t: number, timeScale: number): number {
  return t / timeScale;
}

/** Original timeline → position on media with the given time scale. */
export function toMedia(tOriginal: number, timeScale: number): number {
  return tOriginal * timeScale;
}

/** Keep the same musical position when swapping from one source to another. */
export function mapPosition(t: number, fromScale: number, toScale: number): number {
  return toMedia(toOriginal(t, fromScale), toScale);
}

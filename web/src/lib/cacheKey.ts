// Mirror of api/songbook/cache.py. fixtures/cache_keys.json is the shared truth.

export const ENGINE = "rb3";
export const ENGINE_VERSION = "v1";

/** Round half to even, like Python's round(). */
function roundHalfEven(x: number): number {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

export function snap(value: number, step = 0.01): number {
  return Number((roundHalfEven(value / step) * step).toFixed(2)) + 0; // + 0 turns -0 into 0
}

export function isIdentity(semitones: number, tempo: number, bakeTempo: boolean): boolean {
  return snap(semitones) === 0 && (!bakeTempo || snap(tempo) === 1);
}

export function cacheKey(semitones: number, tempo: number, bakeTempo: boolean): string | null {
  if (isIdentity(semitones, tempo, bakeTempo)) return null;
  const s = snap(semitones);
  const t = bakeTempo ? snap(tempo) : 1;
  const sign = s < 0 ? "-" : "+";
  return `p${sign}${Math.abs(s).toFixed(2)}_t${t.toFixed(3)}_bt${bakeTempo ? 1 : 0}_${ENGINE}-${ENGINE_VERSION}`;
}

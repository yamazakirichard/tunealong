// Per-browser conveniences (group-by, filter, theme). Storage can be missing
// or throw (private windows, blocked site data), so every access is guarded.

// The app was called Songbook until 2026-11-11 and kept its prefs under
// "songbook.*". A pref still stored there moves to "tunealong.*" when first read.
const LEGACY_PREFIX = "songbook.";

function adoptLegacy(key: string): void {
  const old = window.localStorage.getItem(LEGACY_PREFIX + key);
  if (old == null) return;
  if (window.localStorage.getItem(`tunealong.${key}`) == null) {
    window.localStorage.setItem(`tunealong.${key}`, old);
  }
  window.localStorage.removeItem(LEGACY_PREFIX + key);
}

export function load<T>(key: string, fallback: T): T {
  try {
    adoptLegacy(key);
    const raw = window.localStorage.getItem(`tunealong.${key}`);
    return raw == null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function save(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(`tunealong.${key}`, JSON.stringify(value));
  } catch {
    /* not persisted; fine */
  }
}

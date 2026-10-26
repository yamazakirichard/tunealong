// Per-browser conveniences (group-by, filter, theme). Storage can be missing
// or throw (private windows, blocked site data), so every access is guarded.

export function load<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(`songbook.${key}`);
    return raw == null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function save(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(`songbook.${key}`, JSON.stringify(value));
  } catch {
    /* not persisted; fine */
  }
}

// Type-ahead matching for the artist and title fields.

/** Lower-case and strip accents, so "beyo" matches "Beyoncé". */
export function fold(s: string): string {
  return s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/**
 * Candidates matching what's typed so far: those that start with it first,
 * then those with a word that starts with it ("sabb" → "Black Sabbath").
 * Each group keeps the candidates' order. Duplicates and an exact match are
 * dropped, and an empty query suggests nothing.
 */
export function suggest(query: string, candidates: string[], limit = 6): string[] {
  const q = fold(query.trim());
  if (!q) return [];
  const seen = new Set<string>([q]);
  const starts: string[] = [];
  const words: string[] = [];
  for (const c of candidates) {
    const f = fold(c.trim());
    if (!f || seen.has(f)) continue;
    if (f.startsWith(q)) starts.push(c.trim());
    else if (f.split(/[\s\-–—/(&,.]+/).some((w) => w.startsWith(q)) || f.includes(` ${q}`)) words.push(c.trim());
    else continue;
    seen.add(f);
  }
  return [...starts, ...words].slice(0, limit);
}

/** The rest of `match` after `typed`, when `match` starts with it (shown greyed as an inline completion). */
export function completion(typed: string, match: string | undefined): string {
  if (!typed || !match || typed.length >= match.length) return "";
  return fold(match.slice(0, typed.length)) === fold(typed) ? match.slice(typed.length) : "";
}


/*
 * Search bar. Behaviour follows gethomepage/homepage v2.7.0's quick launch
 * (src/components/quicklaunch.jsx): type anywhere to search, Enter opens the
 * top result, Escape clears. Copyright (C) the Homepage contributors.
 * GPL-3.0; see NOTICE. Changes: an always-visible field that filters the
 * library (server-side search) instead of a modal with web search.
 */
import { useEffect, useRef } from "react";
import { MdSearch } from "react-icons/md";

export default function QuickSearch({ value, onChange, onOpenFirst }: {
  value: string;
  onChange: (q: string) => void;
  onOpenFirst: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = t.closest("input, textarea, select, [contenteditable], [role=dialog]");
      if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "/" || (e.key.length === 1 && /\S/.test(e.key))) {
        ref.current?.focus();
        if (e.key === "/") e.preventDefault();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <label className="relative flex items-center flex-1 min-w-48 max-w-md">
      <MdSearch className="absolute left-2 text-theme-500" aria-hidden />
      <input
        ref={ref}
        type="search"
        aria-label="Search"
        placeholder="Search songs, artists, uploaders…"
        className="w-full rounded-md pl-8 text-sm bg-theme-100/20 dark:bg-white/5 border-theme-300 dark:border-theme-600 text-theme-800 dark:text-theme-100"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onOpenFirst();
          if (e.key === "Escape") {
            onChange("");
            ref.current?.blur();
          }
        }}
      />
    </label>
  );
}

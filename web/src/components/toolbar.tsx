import { MdAdd, MdCategory, MdRefresh } from "react-icons/md";

import { api } from "../lib/api";
import { useLibrary } from "../lib/library";
import JobIndicator from "./jobIndicator";
import QuickSearch from "./quicksearch";
import ColorToggle from "./toggles/color";
import ThemeToggle from "./toggles/theme";
import { useToast } from "./toasts";

export default function Toolbar(props: {
  groupBy: "artist" | "category";
  setGroupBy: (g: "artist" | "category") => void;
  category: number | null;
  setCategory: (c: number | null) => void;
  q: string;
  setQ: (q: string) => void;
  onAdd: () => void;
  onCategories: () => void;
  onOpenFirst: () => void;
}) {
  const lib = useLibrary();
  const toast = useToast();
  const btn = "flex items-center gap-1 rounded-md px-2 py-1 text-sm text-theme-800 dark:text-theme-200 hover:bg-theme-300/20";
  return (
    <header className="flex flex-wrap items-center gap-3 px-4 py-3">
      <h1 className="text-2xl font-semibold text-theme-800 dark:text-theme-200 mr-2">Songbook</h1>
      <QuickSearch value={props.q} onChange={props.setQ} onOpenFirst={props.onOpenFirst} />
      <div className="flex rounded-md overflow-hidden border border-theme-400/50 text-sm" role="group" aria-label="Group by">
        {(["artist", "category"] as const).map((g) => (
          <button
            key={g}
            type="button"
            aria-pressed={props.groupBy === g}
            onClick={() => props.setGroupBy(g)}
            className={`px-2 py-1 ${props.groupBy === g ? "bg-theme-500 text-white" : "text-theme-800 dark:text-theme-200"}`}
          >
            {g === "artist" ? "Artist" : "Category"}
          </button>
        ))}
      </div>
      <select
        aria-label="Category filter"
        className="rounded-md text-sm py-1 bg-theme-100/20 dark:bg-white/5 border-theme-400/50 text-theme-800 dark:text-theme-100"
        value={props.category ?? ""}
        onChange={(e) => props.setCategory(e.target.value ? Number(e.target.value) : null)}
      >
        <option value="">All categories</option>
        {lib.categories.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      <button type="button" className={btn} onClick={props.onAdd}>
        <MdAdd /> Add song
      </button>
      <button type="button" className={btn} onClick={props.onCategories}>
        <MdCategory /> Categories
      </button>
      <button
        type="button"
        className={btn}
        onClick={async () => {
          const r = await api.rescan();
          toast({ text: r.queued ? "Rescan queued" : "A rescan is already queued" });
        }}
      >
        <MdRefresh /> Rescan library
      </button>
      <div className="ml-auto flex items-center gap-3">
        <JobIndicator onChange={() => void lib.refresh()} />
        <ColorToggle />
        <ThemeToggle />
      </div>
    </header>
  );
}

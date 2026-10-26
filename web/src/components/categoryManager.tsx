import { useEffect, useState } from "react";

import { api, type Category, errorText } from "../lib/api";
import { useLibrary } from "../lib/library";
import SmallDialog, { buttonClass, inputClass } from "./dialog";
import { useToast } from "./toasts";

export default function CategoryManager({ open, onClose }: { open: boolean; onClose: () => void }) {
  const lib = useLibrary();
  const toast = useToast();
  const [name, setName] = useState("");
  const run = async (f: () => Promise<unknown>) => {
    try {
      await f();
      await lib.refresh();
    } catch (e) {
      toast({ text: errorText(e), kind: "error" });
    }
  };
  const move = (i: number, delta: -1 | 1) => {
    const ids = lib.categories.map((c) => c.id);
    [ids[i], ids[i + delta]] = [ids[i + delta], ids[i]];
    return run(() => api.reorder({ scope: "categories", ids }));
  };
  return (
    <SmallDialog title="Categories" open={open} onClose={onClose}>
      <ul className="flex flex-col gap-2 mb-4 max-h-80 overflow-auto">
        {lib.categories.map((c, i) => (
          <CategoryRow
            key={c.id}
            category={c}
            first={i === 0}
            last={i === lib.categories.length - 1}
            onSave={(body) => run(() => api.patchCategory(c.id, body))}
            onMove={(d) => move(i, d)}
            onDelete={() => window.confirm(`Delete "${c.name}"? Songs stay.`) && run(() => api.deleteCategory(c.id))}
          />
        ))}
        {lib.categories.length === 0 && <li className="text-sm text-theme-500">No categories yet.</li>}
      </ul>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void run(() => api.createCategory({ name: name.trim() })).then(() => setName(""));
        }}
      >
        <input aria-label="Category name" className={inputClass} placeholder="New category" value={name} onChange={(e) => setName(e.target.value)} />
        <button type="submit" className={buttonClass} disabled={!name.trim()}>Add</button>
      </form>
    </SmallDialog>
  );
}

function CategoryRow({ category, first, last, onSave, onMove, onDelete }: {
  category: Category;
  first: boolean;
  last: boolean;
  onSave: (body: Partial<Category>) => void;
  onMove: (d: -1 | 1) => void;
  onDelete: () => void;
}) {
  const [name, setName] = useState(category.name);
  useEffect(() => setName(category.name), [category.name]);
  return (
    <li className="flex items-center gap-1">
      <input
        type="color"
        aria-label={`Colour of ${category.name}`}
        className="h-7 w-8 rounded"
        value={category.colour ?? "#64748b"}
        onChange={(e) => onSave({ colour: e.target.value })}
      />
      <input
        aria-label={`Name of ${category.name}`}
        className={inputClass}
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => name.trim() && name !== category.name && onSave({ name: name.trim() })}
      />
      <button type="button" aria-label="Move up" disabled={first} className="px-1 disabled:opacity-30" onClick={() => onMove(-1)}>↑</button>
      <button type="button" aria-label="Move down" disabled={last} className="px-1 disabled:opacity-30" onClick={() => onMove(1)}>↓</button>
      <button type="button" aria-label={`Delete ${category.name}`} className="px-1 text-red-600" onClick={onDelete}>✕</button>
    </li>
  );
}

import { useState } from "react";

import { api, type Category, errorText } from "../lib/api";
import { inputClass } from "./dialog";
import { useToast } from "./toasts";

/** Multi-select of categories with inline "create new". */
export default function CategoryPicker({
  categories,
  value,
  onChange,
  onCreated,
}: {
  categories: Category[];
  value: number[];
  onChange: (ids: number[]) => void;
  onCreated: (c: Category) => void;
}) {
  const toast = useToast();
  const [name, setName] = useState("");
  const create = async () => {
    try {
      const c = await api.createCategory({ name: name.trim() });
      onCreated(c);
      onChange([...value, c.id]);
      setName("");
    } catch (e) {
      toast({ text: errorText(e), kind: "error" });
    }
  };
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="text-sm mb-1">Categories</legend>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {categories.map((c) => (
          <label key={c.id} className="flex items-center gap-1 text-sm">
            <input
              type="checkbox"
              checked={value.includes(c.id)}
              onChange={(e) => onChange(e.target.checked ? [...value, c.id] : value.filter((i) => i !== c.id))}
            />
            {c.name}
          </label>
        ))}
        {categories.length === 0 && <span className="text-xs text-theme-500">No categories yet</span>}
      </div>
      <div className="flex gap-1 mt-1">
        <input
          aria-label="New category"
          placeholder="New category"
          className={inputClass}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (name.trim()) void create();
            }
          }}
        />
        <button type="button" className="rounded border px-2 text-sm" disabled={!name.trim()} onClick={create}>
          Create
        </button>
      </div>
    </fieldset>
  );
}

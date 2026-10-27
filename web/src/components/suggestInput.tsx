import classNames from "classnames";
import { forwardRef, useId, useMemo, useState } from "react";

import { completion, suggest } from "../lib/suggest";
import { inputClass } from "./dialog";

/**
 * A text field that suggests names already in the library as you type. The
 * best prefix match shows greyed after the cursor (Tab or → takes it), and a
 * list offers the others (↑/↓ and Enter, or click). Free text is still fine.
 */
const SuggestInput = forwardRef<HTMLInputElement, {
  name: string;
  value: string;
  onChange: (v: string) => void;
  candidates: string[];
  required?: boolean;
  placeholder?: string;
}>(function SuggestInput({ name, value, onChange, candidates, required, placeholder }, ref) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [atEnd, setAtEnd] = useState(true);
  const matches = useMemo(() => suggest(value, candidates), [value, candidates]);
  const showList = open && matches.length > 0;
  const ghost = open && atEnd ? completion(value, matches[0]) : "";

  const pick = (v: string) => {
    onChange(v);
    setOpen(false);
    setActive(-1);
  };

  return (
    <div className="relative">
      {/* The field's background, with the greyed completion lined up after the typed text. */}
      <div
        aria-hidden
        data-testid="suggest-ghost"
        className={classNames(inputClass, "absolute inset-0 border px-3 py-2 whitespace-pre overflow-hidden pointer-events-none")}
      >
        <span className="invisible">{value}</span>
        <span className="text-theme-400">{ghost}</span>
      </div>
      <input
        ref={ref}
        name={name}
        required={required}
        placeholder={placeholder}
        autoComplete="off"
        role="combobox"
        aria-autocomplete="both"
        aria-expanded={showList}
        aria-controls={listId}
        aria-activedescendant={showList && active >= 0 ? `${listId}-${active}` : undefined}
        className={classNames(inputClass, "relative bg-transparent! dark:bg-transparent!")}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setActive(-1);
          setAtEnd(e.target.selectionStart === e.target.value.length && e.target.scrollLeft === 0);
        }}
        onSelect={(e) => {
          const t = e.currentTarget;
          setAtEnd(t.selectionStart === t.value.length && t.selectionEnd === t.value.length && t.scrollLeft === 0);
        }}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            if (!matches.length) return;
            e.preventDefault();
            setOpen(true);
            const n = matches.length;
            setActive((i) => (e.key === "ArrowDown" ? (i + 1) % n : (i <= 0 ? n : i) - 1));
          } else if (e.key === "Enter" && showList && active >= 0) {
            e.preventDefault();
            pick(matches[active]);
          } else if ((e.key === "Tab" || e.key === "ArrowRight") && ghost && !e.shiftKey) {
            e.preventDefault();
            pick(matches[0]);
          } else if (e.key === "Escape" && showList) {
            // Close the list, not the dialog around it (Headless UI skips prevented Escapes).
            e.preventDefault();
            setOpen(false);
          }
        }}
      />
      {showList && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-10 mt-1 w-full max-h-56 overflow-auto rounded border border-theme-300 dark:border-theme-600 bg-white dark:bg-theme-700 shadow-lg text-sm"
        >
          {matches.map((m, i) => (
            <li
              key={m}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={classNames("px-3 py-1.5 cursor-pointer", i === active && "bg-theme-200 dark:bg-theme-600")}
              // mousedown, not click: it fires before the input's blur closes the list.
              onMouseDown={(e) => {
                e.preventDefault();
                pick(m);
              }}
              onMouseEnter={() => setActive(i)}
            >
              {m}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
});

export default SuggestInput;

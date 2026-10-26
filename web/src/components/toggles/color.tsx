/*
 * Adapted from gethomepage/homepage v2.7.0 (src/components/toggles/color.jsx).
 * Copyright (C) the Homepage contributors. GPL-3.0; see NOTICE.
 * Changes: Headless UI v2 Popover API, panel opens downwards; TypeScript.
 */
import { Popover, PopoverButton, PopoverPanel } from "@headlessui/react";
import classNames from "classnames";
import { IoColorPalette } from "react-icons/io5";

import { useTheme } from "../../lib/theme";

const colors = [
  "slate", "gray", "zinc", "neutral", "stone", "amber", "yellow", "lime", "green", "emerald", "teal",
  "cyan", "sky", "blue", "indigo", "violet", "purple", "fuchsia", "pink", "rose", "red", "white",
];

export default function ColorToggle() {
  const { color: active, setColor } = useTheme();
  return (
    <Popover id="color" className="relative flex items-center">
      <PopoverButton className="outline-hidden">
        <IoColorPalette className="h-5 w-5 text-theme-800 dark:text-theme-200" aria-hidden="true" />
        <span className="sr-only">Change color</span>
      </PopoverButton>
      <PopoverPanel anchor="bottom end" className="z-30 mt-2">
        <div className="grid gap-2 p-2 grid-cols-11 bg-white/50 dark:bg-white/10 backdrop-blur shadow-black/10 dark:shadow-black/20 rounded-md shadow-md">
          {colors.map((color) => (
            <button type="button" onClick={() => setColor(color)} key={color}>
              <div
                title={color}
                className={classNames(
                  active === color ? "border-2" : "border-0",
                  `rounded-md w-5 h-5 border-black/50 dark:border-white/50 theme-${color} bg-theme-400`,
                )}
              />
              <span className="sr-only">{color}</span>
            </button>
          ))}
        </div>
      </PopoverPanel>
    </Popover>
  );
}

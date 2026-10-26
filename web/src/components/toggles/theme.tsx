/*
 * Adapted from gethomepage/homepage v2.7.0 (src/components/toggles/theme.jsx).
 * Copyright (C) the Homepage contributors. GPL-3.0; see NOTICE.
 * Changes: a real <button> for keyboard use; TypeScript.
 */
import { MdDarkMode, MdLightMode, MdToggleOff, MdToggleOn } from "react-icons/md";

import { useTheme } from "../../lib/theme";

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const Toggle = theme === "dark" ? MdToggleOn : MdToggleOff;
  return (
    <div id="theme" className="rounded-full flex items-center">
      <MdLightMode className="text-theme-800 dark:text-theme-200 w-5 h-5 m-1.5" aria-hidden />
      <button
        type="button"
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
      >
        <Toggle className="text-theme-800 dark:text-theme-200 w-8 h-8 cursor-pointer" />
      </button>
      <MdDarkMode className="text-theme-800 dark:text-theme-200 w-5 h-5 m-1.5" aria-hidden />
    </div>
  );
}

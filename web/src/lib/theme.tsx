/*
 * Theme (light/dark) and colour state. Adapted from gethomepage/homepage v2.7.0
 * (src/utils/contexts/theme.jsx, color.jsx). Copyright (C) the Homepage
 * contributors. GPL-3.0; see NOTICE. Changes: one provider, guarded storage.
 */
import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

import { load, save } from "./prefs";

type Mode = "light" | "dark";

interface ThemeState {
  theme: Mode;
  setTheme: (t: Mode) => void;
  color: string;
  setColor: (c: string) => void;
}

const ThemeContext = createContext<ThemeState | null>(null);

function initialMode(): Mode {
  const stored = load<Mode | null>("theme", null);
  if (stored === "light" || stored === "dark") return stored;
  try {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Mode>(initialMode);
  const [color, setColor] = useState<string>(() => load("color", "slate"));

  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove("light", "dark");
    root.classList.add(theme);
    save("theme", theme);
  }, [theme]);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.forEach((c) => c.startsWith("theme-") && root.classList.remove(c));
    root.classList.add(`theme-${color}`);
    save("color", color);
  }, [color]);

  return <ThemeContext.Provider value={{ theme, setTheme, color, setColor }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme outside ThemeProvider");
  return ctx;
}

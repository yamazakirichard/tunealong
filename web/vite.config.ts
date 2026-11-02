/// <reference types="vitest/config" />
import { alphaTab } from "@coderline/alphatab-vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// base './' plus relative API/media URLs: the same build works at / or under
// any subpath (there are no client-side routes).
export default defineConfig({
  base: "./",
  // alphaTab: bundles its worker and audio worklet, and copies its music font
  // and SoundFont into dist/ (font/, soundfont/), so nothing comes from a CDN.
  plugins: [react(), tailwindcss(), alphaTab()],
  // alphaTab's worker and worklet use import.meta.url, which needs ES module workers.
  worker: { format: "es" },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/media": "http://127.0.0.1:8080",
    },
  },
  test: {
    include: ["tests/**/*.test.ts"],
  },
});

// Shared library state and actions, provided by App.
import { createContext, useContext } from "react";

import type { Artist, Category, Group, Library, Song } from "./api";

export interface LibraryCtx {
  library: Library | null;
  artists: Artist[];
  categories: Category[];
  groupBy: "artist" | "category";
  refresh: () => Promise<void>;
  openSong: (song: Song) => void;
  editSong: (song: Song, focus?: "artist" | "categories" | "title") => void;
  linkSong: (song: Song) => void;
  deleteSong: (song: Song) => void;
  retrySong: (song: Song) => void;
  /** Move a song to `group` (artist id, null = Unsorted), placed before `beforeId` (null = at the end). */
  moveSong: (songId: number, group: Group, beforeId: number | null) => Promise<void>;
  /** Move a song one place up (-1) or down (+1) within its group. */
  nudgeSong: (song: Song, group: Group, delta: -1 | 1) => Promise<void>;
  /** Reorder groups (artists or categories): put `id` before `beforeId` (null = last). */
  moveGroup: (id: number, beforeId: number | null) => Promise<void>;
  nudgeGroup: (group: Group, delta: -1 | 1) => Promise<void>;
}

export const LibraryContext = createContext<LibraryCtx | null>(null);

export function useLibrary(): LibraryCtx {
  const ctx = useContext(LibraryContext);
  if (!ctx) throw new Error("useLibrary outside provider");
  return ctx;
}

export const SONG_MIME = "application/x-tunealong-song";
export const GROUP_MIME = "application/x-tunealong-group";

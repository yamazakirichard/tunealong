/*
 * Song card. Adapted from gethomepage/homepage v2.7.0
 * (src/components/services/item.jsx). Copyright (C) the Homepage contributors.
 * GPL-3.0; see NOTICE. Changes: a service became a song; the card opens the
 * player instead of a link (no <a>, no navigation); widgets, stats and status
 * pings removed; status, "local" and category chips, an actions menu and
 * drag-and-drop added.
 */
import { Menu, MenuButton, MenuItem, MenuItems } from "@headlessui/react";
import classNames from "classnames";
import { type DragEvent, useState } from "react";
import { MdMoreVert } from "react-icons/md";

import type { Group, Song } from "../../lib/api";
import { SONG_MIME, useLibrary } from "../../lib/library";

const STATUS_TEXT: Record<Song["status"], string> = {
  queued: "queued",
  downloading: "downloading…",
  ready: "",
  error: "error",
};

export default function Item({ song, group, index, count }: { song: Song; group: Group; index: number; count: number }) {
  const lib = useLibrary();
  const [dropHint, setDropHint] = useState(false);
  const ready = song.status === "ready";
  const draggable = lib.groupBy === "artist";
  const categories = lib.categories.filter((c) => song.categories.includes(c.id));
  const artist = lib.artists.find((a) => a.id === song.artist_id);
  // Grey reference text: what YouTube called it and who uploaded it (covers and tab videos are often re-uploads).
  const reference = [song.yt_title, song.uploader].filter(Boolean).join(" · ");

  const onDragStart = (e: DragEvent) => {
    e.dataTransfer.setData(SONG_MIME, String(song.id));
    e.dataTransfer.effectAllowed = "move";
  };
  const accepts = (e: DragEvent) => draggable && e.dataTransfer.types.includes(SONG_MIME);
  const onDrop = (e: DragEvent) => {
    setDropHint(false);
    if (!accepts(e)) return;
    e.preventDefault();
    e.stopPropagation();
    const id = Number(e.dataTransfer.getData(SONG_MIME));
    if (id && id !== song.id) void lib.moveSong(id, group, song.id);
  };

  return (
    <li
      className="service"
      data-testid="song-card"
      data-song-id={song.id}
      data-name={song.title}
      draggable={draggable}
      onDragStart={draggable ? onDragStart : undefined}
      onDragOver={(e) => {
        if (accepts(e)) {
          e.preventDefault();
          setDropHint(true);
        }
      }}
      onDragLeave={() => setDropHint(false)}
      onDrop={onDrop}
    >
      <div
        className={classNames(
          "shadow-md shadow-theme-900/10 dark:shadow-theme-900/20",
          "transition-all mb-2 p-1 rounded-md font-medium text-theme-700 dark:text-theme-200 dark:hover:text-theme-300 bg-theme-100/20 hover:bg-theme-300/20 dark:bg-white/5 dark:hover:bg-white/10 relative overflow-clip service-card",
          dropHint && "ring-2 ring-theme-400",
        )}
      >
        <div className="flex select-none z-0 service-title">
          <button
            type="button"
            disabled={!ready}
            onClick={() => lib.openSong(song)}
            aria-label={ready ? `Play ${song.title}` : `${song.title} (${STATUS_TEXT[song.status]})`}
            title={ready ? `Play ${song.title}` : song.error ?? STATUS_TEXT[song.status]}
            className="flex-1 min-w-0 flex items-center justify-between rounded-r-md service-title-text text-left disabled:cursor-default enabled:cursor-pointer"
          >
            <div className="flex-1 min-w-0 px-2 py-2 text-sm z-10 service-name">
              <span className="block truncate" data-testid="song-title">{song.title}</span>
              {lib.groupBy === "category" && artist && (
                <p className="text-theme-500 dark:text-theme-300 text-xs font-light truncate">{artist.name}</p>
              )}
              {reference && (
                <p className="text-theme-500/80 dark:text-theme-400 text-xs font-light truncate service-description" data-testid="song-reference">
                  {reference}
                </p>
              )}
              {categories.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {categories.map((c) => (
                    <span
                      key={c.id}
                      data-testid="category-chip"
                      className="rounded-full px-2 py-px text-[10px] font-semibold text-white bg-theme-500"
                      style={c.colour ? { backgroundColor: c.colour } : undefined}
                    >
                      {c.name}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </button>

          <div className="flex flex-row items-start gap-1 z-10 service-tags pr-1 pt-1">
            {song.kind === "tab" ? (
              <span className="rounded px-1.5 text-[10px] uppercase tracking-wide bg-theme-500/30" data-testid="tab-marker">
                tab
              </span>
            ) : (
              !song.youtube_id && (
                <span className="rounded px-1.5 text-[10px] uppercase tracking-wide bg-theme-500/30" data-testid="local-marker">
                  local
                </span>
              )
            )}
            {!ready && (
              <span
                className={classNames(
                  "rounded px-1.5 text-[10px] uppercase tracking-wide",
                  song.status === "error" ? "bg-red-600 text-white" : "bg-amber-500/40",
                )}
                title={song.error ?? undefined}
              >
                {STATUS_TEXT[song.status]}
              </span>
            )}
            {song.default_preset && (
              <span className="rounded px-1.5 text-[10px] bg-theme-400/30" title="Default preset">
                {song.default_preset.name}
              </span>
            )}
            <Menu as="div" className="relative">
              <MenuButton className="rounded p-0.5 hover:bg-theme-300/30" aria-label={`Actions for ${song.title}`}>
                <MdMoreVert className="w-4 h-4" />
              </MenuButton>
              <MenuItems
                anchor="bottom end"
                className="z-40 w-48 rounded-md bg-theme-50 dark:bg-theme-700 text-theme-800 dark:text-theme-100 shadow-lg p-1 text-sm focus:outline-none"
              >
                <MenuEntry onClick={() => lib.editSong(song, "title")}>Edit…</MenuEntry>
                <MenuEntry onClick={() => lib.editSong(song, "artist")}>Set artist…</MenuEntry>
                <MenuEntry onClick={() => lib.editSong(song, "categories")}>Set categories…</MenuEntry>
                {draggable && index > 0 && <MenuEntry onClick={() => lib.nudgeSong(song, group, -1)}>Move up</MenuEntry>}
                {draggable && index < count - 1 && (
                  <MenuEntry onClick={() => lib.nudgeSong(song, group, 1)}>Move down</MenuEntry>
                )}
                {!song.youtube_id && song.kind !== "tab" && <MenuEntry onClick={() => lib.linkSong(song)}>Link YouTube URL…</MenuEntry>}
                {song.status === "error" && <MenuEntry onClick={() => lib.retrySong(song)}>Retry download</MenuEntry>}
                <MenuEntry onClick={() => lib.deleteSong(song)} danger>
                  Delete…
                </MenuEntry>
              </MenuItems>
            </Menu>
          </div>
        </div>
      </div>
    </li>
  );
}

function MenuEntry({ onClick, children, danger }: { onClick: () => void; children: React.ReactNode; danger?: boolean }) {
  return (
    <MenuItem>
      <button
        type="button"
        onClick={onClick}
        className={classNames(
          "block w-full rounded px-2 py-1 text-left data-[focus]:bg-theme-300/40",
          danger && "text-red-600 dark:text-red-400",
        )}
      >
        {children}
      </button>
    </MenuItem>
  );
}

/*
 * Adapted from gethomepage/homepage v2.7.0 (src/components/services/group.jsx).
 * Copyright (C) the Homepage contributors. GPL-3.0; see NOTICE.
 * Changes: groups are artists or categories from /api/library; per-group
 * columns/style come from the artist; subgroups, icons and the height
 * animation removed; group settings, drop targets and group drag added;
 * artist groups show the artist's picture.
 */
import { Disclosure, DisclosureButton, DisclosurePanel, Popover, PopoverButton, PopoverPanel } from "@headlessui/react";
import classNames from "classnames";
import { type DragEvent, useState } from "react";
import { MdDragIndicator, MdKeyboardArrowDown, MdSettings } from "react-icons/md";

import { api, errorText, type Group } from "../../lib/api";
import { GROUP_MIME, SONG_MIME, useLibrary } from "../../lib/library";
import { useToast } from "../toasts";
import List from "./list";

export default function ServicesGroup({ group, index, count }: { group: Group; index: number; count: number }) {
  const lib = useLibrary();
  const [hint, setHint] = useState(false);
  const real = group.id !== null; // not the Unsorted / Uncategorised pseudo-group
  const songDrop = lib.groupBy === "artist";

  const onDragOver = (e: DragEvent) => {
    const t = e.dataTransfer.types;
    if ((songDrop && t.includes(SONG_MIME)) || (real && t.includes(GROUP_MIME))) {
      e.preventDefault();
      setHint(true);
    }
  };
  const onDrop = (e: DragEvent) => {
    setHint(false);
    const songId = Number(e.dataTransfer.getData(SONG_MIME));
    const groupId = Number(e.dataTransfer.getData(GROUP_MIME));
    if (songDrop && songId) {
      e.preventDefault();
      void lib.moveSong(songId, group, null);
    } else if (real && groupId && groupId !== group.id) {
      e.preventDefault();
      void lib.moveGroup(groupId, group.id);
    }
  };

  return (
    <div
      data-testid="group"
      data-group-id={group.id ?? ""}
      data-group-name={group.name}
      className={classNames(
        "services-group flex-1 p-1 pb-0",
        group.style === "row" ? "basis-full" : "basis-full md:basis-1/2 lg:basis-1/3 xl:basis-1/4",
        hint && "outline-2 outline-dashed outline-theme-400 rounded-md",
      )}
      onDragOver={onDragOver}
      onDragLeave={() => setHint(false)}
      onDrop={onDrop}
    >
      <Disclosure defaultOpen>
        {({ open }) => (
          <>
            <div className="flex w-full items-center group">
              {real && (
                <span
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData(GROUP_MIME, String(group.id));
                    e.dataTransfer.effectAllowed = "move";
                  }}
                  className="cursor-grab text-theme-500 mr-1"
                  title="Drag to reorder groups"
                  data-testid="group-handle"
                >
                  <MdDragIndicator />
                </span>
              )}
              {group.image_url && <ArtistImage key={group.image_url} src={group.image_url} />}
              {group.colour && <span className="mr-2 inline-block w-3 h-3 rounded-full" style={{ backgroundColor: group.colour }} />}
              <DisclosureButton className="flex flex-1 select-none items-center">
                <h2 className="flex text-theme-800 dark:text-theme-300 text-xl font-medium service-group-name">
                  {group.name}
                  <span className="ml-2 self-center text-xs font-normal text-theme-500">{group.songs.length}</span>
                </h2>
                <MdKeyboardArrowDown
                  className={classNames(
                    "transition-all opacity-0 group-hover:opacity-100 ml-auto text-theme-800 dark:text-theme-300 text-xl",
                    open ? "" : "rotate-180",
                  )}
                />
              </DisclosureButton>
              {real && <GroupSettings group={group} index={index} count={count} />}
            </div>
            <DisclosurePanel static={false}>
              <List group={group} />
              {group.songs.length === 0 && (
                <p className="text-xs text-theme-500 px-2 pb-2">{songDrop ? "Drop songs here" : "No songs"}</p>
              )}
            </DisclosurePanel>
          </>
        )}
      </Disclosure>
    </div>
  );
}

function ArtistImage({ src }: { src: string }) {
  const [broken, setBroken] = useState(false);
  if (broken) return null;
  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      data-testid="artist-image"
      className="mr-2 w-7 h-7 shrink-0 rounded-full object-cover bg-theme-200 dark:bg-theme-700"
      onError={() => setBroken(true)}
    />
  );
}

function GroupSettings({ group, index, count }: { group: Group; index: number; count: number }) {
  const lib = useLibrary();
  const toast = useToast();
  const isArtist = lib.groupBy === "artist";
  const [name, setName] = useState(group.name);

  const patch = async (body: Record<string, unknown>) => {
    try {
      if (isArtist) await api.patchArtist(group.id!, body);
      else await api.patchCategory(group.id!, body);
      await lib.refresh();
    } catch (e) {
      toast({ text: errorText(e), kind: "error" });
    }
  };
  const remove = async () => {
    const what = isArtist ? "artist (its songs move to Unsorted)" : "category (its songs stay)";
    if (!window.confirm(`Delete the ${what} "${group.name}"?`)) return;
    if (isArtist) await api.deleteArtist(group.id!);
    else await api.deleteCategory(group.id!);
    await lib.refresh();
  };

  return (
    <Popover className="relative">
      <PopoverButton className="ml-1 rounded p-1 text-theme-500 hover:text-theme-800 dark:hover:text-theme-200" aria-label={`Settings for ${group.name}`}>
        <MdSettings />
      </PopoverButton>
      <PopoverPanel
        anchor="bottom end"
        className="z-40 w-64 rounded-md bg-theme-50 dark:bg-theme-700 text-theme-800 dark:text-theme-100 shadow-lg p-3 text-sm flex flex-col gap-2"
      >
        <label className="flex flex-col gap-1">
          Name
          <div className="flex gap-1">
            <input className="flex-1 rounded text-sm text-theme-900" value={name} onChange={(e) => setName(e.target.value)} />
            <button type="button" className="rounded bg-theme-500 text-white px-2" onClick={() => patch({ name: name.trim() })} disabled={!name.trim()}>
              Rename
            </button>
          </div>
        </label>
        {isArtist && (
          <>
            <label className="flex items-center justify-between gap-2">
              Columns
              <select
                aria-label="Columns"
                className="rounded text-sm text-theme-900"
                value={group.columns}
                onChange={(e) => patch({ columns: Number(e.target.value) })}
              >
                {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </select>
            </label>
            <label className="flex items-center justify-between gap-2">
              Style
              <select
                aria-label="Style"
                className="rounded text-sm text-theme-900"
                value={group.style}
                onChange={(e) => patch({ style: e.target.value })}
              >
                <option value="row">row</option>
                <option value="column">column</option>
              </select>
            </label>
          </>
        )}
        <div className="flex gap-2">
          <button type="button" className="rounded border px-2 disabled:opacity-40" disabled={index === 0} onClick={() => lib.nudgeGroup(group, -1)}>
            Move earlier
          </button>
          <button type="button" className="rounded border px-2 disabled:opacity-40" disabled={index >= count - 1} onClick={() => lib.nudgeGroup(group, 1)}>
            Move later
          </button>
        </div>
        <button type="button" className="self-start text-red-600 dark:text-red-400" onClick={remove}>
          Delete {isArtist ? "artist" : "category"}
        </button>
      </PopoverPanel>
    </Popover>
  );
}

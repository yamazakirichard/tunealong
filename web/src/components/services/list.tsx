/*
 * Adapted from gethomepage/homepage v2.7.0 (src/components/services/list.jsx).
 * Copyright (C) the Homepage contributors. GPL-3.0; see NOTICE.
 * Changes: songs instead of services; TypeScript.
 */
import classNames from "classnames";

import type { Group } from "../../lib/api";
import { columnMap } from "../../lib/columns";
import Item from "./item";

export default function List({ group }: { group: Group }) {
  return (
    <ul
      data-testid="song-list"
      className={classNames(
        group.style === "row" ? `grid ${columnMap[group.columns]} gap-x-2` : "flex flex-col",
        "mt-3 services-list min-h-8",
      )}
    >
      {group.songs.map((song, i) => (
        <Item key={song.id} song={song} group={group} index={i} count={group.songs.length} />
      ))}
    </ul>
  );
}

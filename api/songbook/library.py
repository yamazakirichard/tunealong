"""Read-side helpers: turn rows into API dicts, and build /api/library."""

import sqlite3

SONG_FIELDS = ("id", "youtube_id", "artist_id", "title", "yt_title", "uploader", "sort_order",
               "status", "error", "notes", "added_at")
PRESET_FIELDS = ("id", "song_id", "name", "semitones", "tempo", "bake_tempo", "loop_a", "loop_b",
                 "is_default", "cache_key")
UNSORTED = "Unsorted"
UNCATEGORISED = "Uncategorised"
_ORDER = "sort_order IS NULL, sort_order"  # manual order first, unordered last


def preset_dict(row: sqlite3.Row) -> dict:
    d = {k: row[k] for k in PRESET_FIELDS}
    d["bake_tempo"] = bool(d["bake_tempo"])
    d["is_default"] = bool(d["is_default"])
    return d


def song_dict(row: sqlite3.Row, categories: list[int] | None = None,
              default_preset: dict | None = None) -> dict:
    d = {k: row[k] for k in SONG_FIELDS}
    d["media_url"] = f"media/originals/{row['id']}" if row["original_path"] and row["status"] == "ready" else None
    d["categories"] = categories or []
    d["default_preset"] = default_preset
    return d


def artist_image_url(row: sqlite3.Row) -> str | None:
    """Relative, like media_url. ?v= changes whenever a new picture is fetched."""
    if not row["image_path"]:
        return None
    return f"media/artists/{row['id']}?v={''.join(c for c in row['image_checked_at'] or '' if c.isdigit())}"


def categories_by_song(conn: sqlite3.Connection, song_ids=None) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    q = ("SELECT sc.song_id, sc.category_id FROM song_categories sc"
         " JOIN categories c ON c.id = sc.category_id"
         " ORDER BY c.sort_order IS NULL, c.sort_order, c.name COLLATE NOCASE")
    for r in conn.execute(q):
        if song_ids is None or r[0] in song_ids:
            out.setdefault(r[0], []).append(r[1])
    return out


def default_presets(conn: sqlite3.Connection) -> dict[int, dict]:
    return {r["song_id"]: preset_dict(r) for r in conn.execute("SELECT * FROM presets WHERE is_default = 1")}


def full_song(conn: sqlite3.Connection, song_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    if row is None:
        return None
    presets = [preset_dict(r) for r in conn.execute(
        "SELECT * FROM presets WHERE song_id = ? ORDER BY name COLLATE NOCASE", (song_id,))]
    d = song_dict(row, categories_by_song(conn, {song_id}).get(song_id),
                  next((p for p in presets if p["is_default"]), None))
    d["presets"] = presets
    return d


def build(conn: sqlite3.Connection, group_by: str = "artist", category: int | None = None,
          q: str | None = None) -> dict:
    where, params = [], []
    if category is not None:
        where.append("s.id IN (SELECT song_id FROM song_categories WHERE category_id = ?)")
        params.append(category)
    if q:
        where.append("(" + " OR ".join(f"instr(lower(coalesce({c}, '')), lower(?)) > 0"
                                       for c in ("s.title", "a.name", "s.yt_title", "s.uploader")) + ")")
        params += [q] * 4
    rows = conn.execute(
        "SELECT s.* FROM songs s LEFT JOIN artists a ON a.id = s.artist_id"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY s.sort_order IS NULL, s.sort_order, s.title COLLATE NOCASE, s.id",
        params,
    ).fetchall()
    cats = categories_by_song(conn)
    defaults = default_presets(conn)
    songs = [song_dict(r, cats.get(r["id"]), defaults.get(r["id"])) for r in rows]
    filtered = bool(q) or category is not None

    groups = []
    if group_by == "category":
        for c in conn.execute(f"SELECT * FROM categories ORDER BY {_ORDER}, name COLLATE NOCASE"):
            groups.append(_group(c["id"], c["name"], 4, "row", c["sort_order"],
                                 [s for s in songs if c["id"] in s["categories"]], colour=c["colour"]))
        groups.append(_group(None, UNCATEGORISED, 4, "row", None, [s for s in songs if not s["categories"]]))
    else:
        for a in conn.execute(f"SELECT * FROM artists ORDER BY {_ORDER}, name COLLATE NOCASE"):
            groups.append(_group(a["id"], a["name"], a["columns"], a["style"], a["sort_order"],
                                 [s for s in songs if s["artist_id"] == a["id"]], image_url=artist_image_url(a)))
        groups.append(_group(None, UNSORTED, 4, "row", None, [s for s in songs if s["artist_id"] is None]))
    if filtered:
        groups = [g for g in groups if g["songs"]]
    return {"group_by": group_by, "groups": groups}


def _group(gid, name, columns, style, sort_order, songs, **extra) -> dict:
    return {"id": gid, "name": name, "columns": columns, "style": style,
            "sort_order": sort_order, **extra, "songs": songs}

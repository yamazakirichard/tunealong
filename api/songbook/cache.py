"""Render cache keys (and, from Phase 5, garbage collection).

Key: p{semitones:+.2f}_t{tempo:.3f}_bt{bake_tempo}_{engine}-{engine_version}.
When tempo isn't baked it is applied live in the browser, so the key uses
t1.000 and presets that differ only in live tempo share one render.
"""

import shutil
import time

from . import jobs

ENGINE = "rb3"
ENGINE_VERSION = "v1"


def snap(value: float, step: float = 0.01) -> float:
    """Round to `step` so Python and JS format the stored value identically."""
    return round(round(value / step) * step, 2)


def is_identity(semitones: float, tempo: float, bake_tempo: bool) -> bool:
    return snap(semitones) == 0 and (not bake_tempo or snap(tempo) == 1)


def cache_key(semitones: float, tempo: float, bake_tempo: bool) -> str | None:
    """The render key for these settings, or None when no render is needed."""
    if is_identity(semitones, tempo, bake_tempo):
        return None
    s = snap(semitones) + 0.0  # -0.0 -> 0.0, so it formats as +0.00
    t = snap(tempo) if bake_tempo else 1.0
    return f"p{s:+.2f}_t{t:.3f}_bt{int(bool(bake_tempo))}_{ENGINE}-{ENGINE_VERSION}"


# --- render bookkeeping -------------------------------------------------------

def dedupe_key(song_id: int, key: str) -> str:
    return f"rn:{song_id}:{key}"


def render_row(conn, settings, song_id: int, key: str):
    """The renders row for this key, if its file is really on disk. A row whose
    file is gone is deleted, so it gets rendered again."""
    row = conn.execute("SELECT * FROM renders WHERE song_id = ? AND cache_key = ?", (song_id, key)).fetchone()
    if row is None:
        return None
    if (settings.root / row["path"]).is_file():
        return row
    conn.execute("DELETE FROM renders WHERE id = ?", (row["id"],))
    return None


def ensure_render(conn, settings, song_id: int, semitones: float, tempo: float, bake_tempo: bool) -> int | None:
    """Enqueue a render for these settings unless it's cached or in flight.

    Returns the new job id, or None if nothing was enqueued. Never renders
    identity settings, and never for a song that has no original file yet.
    """
    key = cache_key(semitones, tempo, bake_tempo)
    if key is None or render_row(conn, settings, song_id, key) is not None:
        return None
    song = conn.execute("SELECT status, original_path, kind FROM songs WHERE id = ?", (song_id,)).fetchone()
    if song is None or song["status"] != "ready" or not song["original_path"] or song["kind"] == "tab":
        return None
    payload = {"song_id": song_id, "cache_key": key, "semitones": snap(semitones) + 0.0,
               "tempo": snap(tempo), "bake_tempo": bool(bake_tempo)}
    return jobs.enqueue(conn, "render", payload, dedupe_key(song_id, key))


def playback(conn, settings, song_id: int, preset) -> dict:
    """What the player should load for this song and (optional) preset row."""
    semitones = preset["semitones"] if preset else 0.0
    tempo = preset["tempo"] if preset else 1.0
    bake = bool(preset["bake_tempo"]) if preset else False
    out = {
        "preset_id": preset["id"] if preset else None,
        "source": "original",
        "url": f"media/originals/{song_id}",
        "live_semitones": semitones,
        "live_tempo": tempo,
        "time_scale": 1.0,
        "loop_a": preset["loop_a"] if preset else None,
        "loop_b": preset["loop_b"] if preset else None,
        "render_error": None,
    }
    kind = conn.execute("SELECT kind FROM songs WHERE id = ?", (song_id,)).fetchone()
    if kind is not None and kind["kind"] == "tab":
        # alphaTab plays the file and applies pitch, tempo and volume itself.
        out["source"] = "tab"
        return out
    key = cache_key(semitones, tempo, bake)
    if preset is not None and preset["cache_key"] != key:
        # ENGINE_VERSION changed since the preset was saved.
        conn.execute("UPDATE presets SET cache_key = ? WHERE id = ?", (key, preset["id"]))
    if key is None:
        if bake:  # identity with baked tempo means tempo 1
            out["live_tempo"] = 1.0
        return out
    row = render_row(conn, settings, song_id, key)
    if row is not None:
        out.update(source="render", url=f"media/renders/{row['id']}", live_semitones=0.0)
        if bake:
            out.update(live_tempo=1.0, time_scale=round(1 / tempo, 6))
        return out
    last = conn.execute("SELECT status, error FROM jobs WHERE dedupe_key = ? ORDER BY id DESC LIMIT 1",
                        (dedupe_key(song_id, key),)).fetchone()
    if last is not None and last["status"] == "error":
        # Don't retry a failed render on every open; saving the preset again does.
        out["render_error"] = last["error"]
        return out
    ensure_render(conn, settings, song_id, semitones, tempo, bake)
    out["source"] = "pending"
    return out


# --- garbage collection -------------------------------------------------------

def gc(conn, settings, max_bytes: int) -> list[str]:
    """Delete renders until the cache is at most `max_bytes`. Returns removed paths.

    Order: renders no preset references (least recently used first), then
    plain LRU. Stray files under renders/ that have no row are removed first.
    Only ever deletes inside renders/; originals are never touched.
    """
    renders_dir = settings.renders_dir.resolve()
    removed: list[str] = []
    known = {(settings.root / r[0]).resolve() for r in conn.execute("SELECT path FROM renders")}
    # A render in progress writes hidden temp files with no row yet; leave young ones alone.
    stale = time.time() - max(settings.render_timeout_s, 3600) * 2
    in_flight = lambda p: p.name.startswith(".") and p.stat().st_mtime > stale  # noqa: E731
    for d in sorted(renders_dir.glob("*/.*.work")):
        if not in_flight(d):
            shutil.rmtree(d, ignore_errors=True)
    for p in sorted(renders_dir.rglob("*")):
        if p.is_file() and p.resolve() not in known and p.exists() and not in_flight(p) \
                and not any(part.endswith(".work") for part in p.relative_to(renders_dir).parts):
            p.unlink(missing_ok=True)
            removed.append(str(p.relative_to(settings.root)))
    rows = conn.execute(
        "SELECT r.*, NOT EXISTS (SELECT 1 FROM presets p WHERE p.song_id = r.song_id"
        "   AND p.cache_key = r.cache_key) AS unreferenced"
        " FROM renders r"
        " ORDER BY unreferenced DESC, coalesce(r.last_used_at, r.created_at), r.id").fetchall()
    sizes = {}
    for r in rows:
        path = (settings.root / r["path"]).resolve()
        sizes[r["id"]] = path.stat().st_size if path.is_file() else 0
    total = sum(sizes.values())
    for r in rows:
        if total <= max_bytes:
            break
        path = (settings.root / r["path"]).resolve()
        if not path.is_relative_to(renders_dir):
            continue  # a bad row: never delete outside renders/
        path.unlink(missing_ok=True)
        conn.execute("DELETE FROM renders WHERE id = ?", (r["id"],))
        total -= sizes[r["id"]]
        removed.append(r["path"])
    for d in renders_dir.iterdir():
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return removed


def main(argv: list[str] | None = None) -> int:
    import argparse

    from . import config, db

    ap = argparse.ArgumentParser(prog="python -m songbook.cache")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gc", help="evict renders until the cache fits the budget")
    g.add_argument("--max-gb", type=float, required=True)
    args = ap.parse_args(argv)
    settings = config.load()
    conn = db.open_db(settings.db_path, settings.busy_timeout_ms)
    try:
        removed = gc(conn, settings, int(args.max_gb * 1024 ** 3))
    finally:
        conn.close()
    for p in removed:
        print(f"removed {p}")
    print(f"{len(removed)} file(s) removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

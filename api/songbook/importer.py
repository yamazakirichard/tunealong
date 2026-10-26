"""Import an existing MeTube folder with arbitrary file names.

`Artist - Title [id].ext` becomes a YouTube song at originals/<id>.<ext>;
anything else becomes a local song at originals/local/<sha256[:16]>.<ext>.
Source files are hardlinked or copied, never moved or deleted.

Guessing the artist from the file name is the one exception to "no automatic
categorisation": this is an explicit, user-run step, reviewed via --dry-run.
"""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import artists, db
from .config import Settings
from .media import AUDIO_EXTS, MEDIA_EXTS, VIDEO_EXTS, place_file, sha256_file

ID_SUFFIX_RE = re.compile(r"\s*\[([A-Za-z0-9_-]{11})\]$")

IMPORT_YT = "import-yt"
IMPORT_LOCAL = "import-local"
DUPLICATE = "duplicate"
TWIN = "twin-skipped"
UNSUPPORTED = "unsupported"
CONFLICT = "conflict"


@dataclass
class Action:
    action: str
    source: Path
    youtube_id: str | None = None
    artist: str | None = None
    title: str | None = None
    dest: str | None = None   # relative to SONGBOOK_ROOT
    sha256: str | None = None
    note: str = ""

    @property
    def imports(self) -> bool:
        return self.action in (IMPORT_YT, IMPORT_LOCAL)


def guess(stem: str) -> tuple[str | None, str | None, str]:
    """(youtube_id, artist, title) from a file stem."""
    m = ID_SUFFIX_RE.search(stem)
    yid = m.group(1) if m else None
    if m:
        stem = stem[: m.start()]
    artist, sep, title = stem.partition(" - ")
    if not sep or not artist.strip() or not title.strip():
        return yid, None, stem.strip()
    return yid, artist.strip(), title.strip()


def plan(src_dir: Path, conn: sqlite3.Connection, settings: Settings) -> list[Action]:
    """Decide what to do with each top-level file. Reads only; changes nothing."""
    files = sorted(p for p in src_dir.iterdir() if p.is_file())
    video_stems = {p.stem for p in files if _ext(p) in VIDEO_EXTS}
    seen_sha: set[str] = set()
    seen_ids: set[str] = set()
    actions = []
    for path in files:
        ext = _ext(path)
        if ext not in MEDIA_EXTS:
            actions.append(Action(UNSUPPORTED, path, note=f"extension {path.suffix or '(none)'!r}"))
            continue
        if ext in AUDIO_EXTS and path.stem in video_stems:
            actions.append(Action(TWIN, path, note="a video file with the same name is imported instead"))
            continue
        yid, artist, title = guess(path.stem)
        sha = sha256_file(path)
        a = Action(IMPORT_YT if yid else IMPORT_LOCAL, path, yid, artist, title, sha256=sha)
        a.dest = f"originals/{yid}.{ext}" if yid else f"originals/local/{sha[:16]}.{ext}"
        if sha in seen_sha or (yid and yid in seen_ids):
            a.action, a.note = DUPLICATE, "same file or ID earlier in this folder"
        elif conn.execute("SELECT 1 FROM songs WHERE original_sha256 = ?", (sha,)).fetchone():
            a.action, a.note = DUPLICATE, "same file already in library"
        elif yid and conn.execute("SELECT 1 FROM songs WHERE youtube_id = ?", (yid,)).fetchone():
            a.action, a.note = DUPLICATE, "YouTube ID already in library"
        else:
            target = settings.root / a.dest
            if target.exists() and sha256_file(target) != sha:
                a.action, a.note = CONFLICT, f"{a.dest} exists with different content"
        if a.imports:
            seen_sha.add(sha)
            if yid:
                seen_ids.add(yid)
        actions.append(a)
    return actions


def apply(actions: list[Action], conn: sqlite3.Connection, settings: Settings) -> None:
    """Place files and insert rows for the importing actions, one transaction per file."""
    for a in actions:
        if not a.imports:
            continue
        target = settings.root / a.dest
        if not target.exists():
            a.note = place_file(a.source, target)
        with db.transaction(conn):
            artist_id = artists.get_or_create(conn, a.artist) if a.artist else None
            conn.execute(
                "INSERT INTO songs (youtube_id, artist_id, title, original_path,"
                " original_sha256, status) VALUES (?, ?, ?, ?, ?, 'ready')",
                (a.youtube_id, artist_id, a.title, a.dest, a.sha256),
            )



def _ext(path: Path) -> str:
    return path.suffix[1:].lower()


def format_report(actions: list[Action]) -> str:
    rows = [("ACTION", "SOURCE", "ARTIST", "TITLE", "DEST / NOTE")]
    for a in actions:
        rows.append((a.action, a.source.name, a.artist or "-", a.title or "-",
                     " ".join(x for x in (a.dest if a.imports else None, a.note) if x)))
    widths = [min(max(len(r[i]) for r in rows), 48) for i in range(4)]
    lines = ["  ".join(c[:w].ljust(w) for c, w in zip(r[:4], widths)) + "  " + r[4] for r in rows]
    counts: dict[str, int] = {}
    for a in actions:
        counts[a.action] = counts.get(a.action, 0) + 1
    lines.append("")
    lines.append(", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "no files")
    return "\n".join(lines)

"""Media file naming rules and file helpers shared by ingest and the importer."""

import errno
import hashlib
import os
import re
import shutil
from pathlib import Path

VIDEO_EXTS = ("webm", "mp4", "mkv")
AUDIO_EXTS = ("mp3", "m4a")
MEDIA_EXTS = VIDEO_EXTS + AUDIO_EXTS

_EXT = "|".join(MEDIA_EXTS)
# Exactly <id>.<ext>: rejects .part/.temp/.ytdl, yt-dlp's <id>.f137.mp4 and .info.json.
YT_NAME_RE = re.compile(rf"^([A-Za-z0-9_-]{{11}})\.({_EXT})$")
LOCAL_NAME_RE = re.compile(rf"^[0-9a-f]{{16}}\.({_EXT})$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def place_file(src: Path, dest: Path) -> str:
    """Hardlink src to dest, or copy if that's not possible. Never touches src.

    Returns "link" or "copy". A copy goes to a hidden temp name and is renamed,
    so a partial file is never visible under dest.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dest)
        return "link"
    except OSError as e:
        if e.errno not in (errno.EXDEV, errno.EPERM, errno.EMLINK, errno.ENOTSUP):
            raise
    tmp = dest.with_name(f".{dest.name}.tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dest)
    return "copy"

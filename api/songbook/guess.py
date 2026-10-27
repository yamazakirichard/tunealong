"""Guess artist and song title from a YouTube video's title and channel.

Heuristics only, for pre-filling the Add song form; the user can edit both.
Handles the common shapes:

  "Black Sabbath - Paranoid (Official Video)"   → Black Sabbath / Paranoid
  'Black Sabbath "Paranoid"'                     → Black Sabbath / Paranoid
  "Paranoid - Black Sabbath | Guitar Lesson"     → Black Sabbath / Paranoid, when
                                                   Black Sabbath is already an artist
                                                   (or the channel's name)
  "Black Sabbath: Paranoid" on "Black Sabbath"   → Black Sabbath / Paranoid
  "Paranoid" on "Black Sabbath - Topic"          → Black Sabbath / Paranoid
"""

import re
import unicodedata
from collections.abc import Iterable

# Bracketed asides that describe the upload, not the song.
_NOISE = re.compile(
    r"official|video|audio|lyrics?|visuali[sz]er|remaster|\bhd\b|\bhq\b|\b4k\b|\bm/?v\b|explicit|full song",
    re.I)
_BRACKETS = re.compile(r"\s*[(\[]([^()\[\]]*)[)\]]")
# What a play-along library is full of; categories record it better than the title.
_KIND = re.compile(
    r"\s*[-|:]?\s*\(?\b(?:guitar\s+|bass\s+|drum\s+)?"
    r"(?:backing\s+track|lesson|tutorial|cover|play[- ]?along|with\s+tabs?|tabs?)\b\)?.*$",
    re.I)
_SEPARATORS = (" - ", " – ", " — ", " | ")
_QUOTED = re.compile(r'^(.+?)\s+["“](.+?)["”](.*)$')  # not ' quotes: apostrophes


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def _squash(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", _fold(s))


def _tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" -–—|:")
    if len(s) >= 2 and s[0] in "\"“'‘" and s[-1] in "\"”'’":
        s = s[1:-1]
    return s.strip()


def clean(yt_title: str) -> str:
    """The video title without "(Official Video)"-style asides."""
    s = _BRACKETS.sub(lambda m: "" if _NOISE.search(m.group(1)) else m.group(0), yt_title)
    return _tidy(s)


def _channel(uploader: str | None) -> str | None:
    """The channel's name as an artist name: "Black Sabbath - Topic" and "BlackSabbathVEVO" → as is, minus the tag."""
    if not uploader:
        return None
    if uploader.endswith(" - Topic"):  # YouTube Music's auto-generated artist channels
        return uploader[: -len(" - Topic")].strip() or None
    return re.sub(r"(?i)\s*(vevo|official)$", "", uploader).strip() or None


def _spelling(name: str, names: list[str]) -> str | None:
    """`name` as spelled in `names`, ignoring case, accents, spaces and punctuation."""
    sq = _squash(name)
    return next((n for n in names if _squash(n) == sq), None) if sq else None


def guess(yt_title: str | None, uploader: str | None = None, known_artists: Iterable[str] = ()) -> dict:
    """{"artist": str | None, "title": str | None}. `known_artists` are names already in the library."""
    if not yt_title or not yt_title.strip():
        return {"artist": None, "title": None}
    known = list(known_artists)
    channel = _channel(uploader)
    # The channel's name says which side of "A - B" is the artist ("Numb – Linkin Park").
    names = [*known, *([channel] if channel else [])]

    def respell(artist: str) -> str:
        # The library's spelling, else the channel's when only case or accents differ
        # ("BLACK SABBATH" on "Black Sabbath", but not "BlackSabbath" from "BlackSabbathVEVO").
        if hit := _spelling(artist, known):
            return hit
        return channel if channel and _fold(channel) == _fold(artist) else artist

    s = clean(yt_title)
    for sep in _SEPARATORS:
        if sep in s:
            left, right = (_tidy(_KIND.sub("", p)) for p in s.split(sep, 1))
            if right and left:
                if _spelling(right, names) and not _spelling(left, names):
                    left, right = right, left
                return {"artist": respell(left), "title": _tidy(right.split(sep)[0])}

    # "Metallica: Enter Sandman", only when the left side is known ("Lesson 1: …" isn't an artist).
    left, colon, right = s.partition(": ")
    if colon and right and _spelling(left, names):
        return {"artist": respell(_tidy(left)), "title": _tidy(_KIND.sub("", right)) or _tidy(right)}

    m = _QUOTED.match(s)
    if m:
        return {"artist": respell(_tidy(m.group(1))), "title": _tidy(m.group(2) + m.group(3))}

    # No artist in the title: an auto-generated "<artist> - Topic" channel, or one matching the library.
    title = _tidy(_KIND.sub("", s)) or s
    is_topic = bool(uploader and uploader.endswith(" - Topic"))
    return {"artist": channel if is_topic else (_spelling(channel, known) if channel else None), "title": title}

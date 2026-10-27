"""YouTube URL → video ID parsing, and a video's title from oEmbed."""

import re
from functools import lru_cache
from urllib.parse import parse_qs, urlsplit

import httpx

ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_WATCH_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
_PATH_PREFIXES = ("shorts", "embed", "live", "v")


def parse_id(url_or_id: str) -> str:
    """Return the 11-character video ID, or raise ValueError."""
    s = (url_or_id or "").strip()
    if ID_RE.match(s):
        return s
    if "://" not in s:
        s = "https://" + s
    parts = urlsplit(s)
    host = (parts.hostname or "").lower()
    segments = [p for p in parts.path.split("/") if p]
    candidate = None
    if host in _SHORT_HOSTS:
        candidate = segments[0] if segments else None
    elif host in _WATCH_HOSTS:
        if segments == ["watch"]:
            candidate = (parse_qs(parts.query).get("v") or [None])[0]
        elif len(segments) >= 2 and segments[0] in _PATH_PREFIXES:
            candidate = segments[1]
    if candidate and ID_RE.match(candidate):
        return candidate
    raise ValueError(f"not a YouTube video URL or ID: {url_or_id!r}")


@lru_cache(maxsize=256)
def oembed(endpoint: str, youtube_id: str) -> tuple[str | None, str | None]:
    """(title, channel) from YouTube's oEmbed endpoint, which needs no API key.

    Raises httpx.HTTPError when it's unreachable or refuses (401 for private
    or non-embeddable videos, 404 for missing ones). Failures aren't cached.
    """
    r = httpx.get(endpoint, params={"url": f"https://www.youtube.com/watch?v={youtube_id}", "format": "json"},
                  timeout=5.0, follow_redirects=True)
    r.raise_for_status()
    data = r.json()
    return data.get("title") or None, data.get("author_name") or None

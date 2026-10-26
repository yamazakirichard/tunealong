"""Client for MeTube's HTTP API (checked against MeTube 2026.09.26, app/main.py).

POST /add takes JSON {url, download_type, quality, format, codec}; it answers
200 with {"status": "ok"|"error", "msg"?} as soon as the URL is queued, not
when the download finishes. GET /history lists {queue, pending, done}; a
failed download shows up in `done` with status "error" and yt-dlp's message.
Server-to-server requests send no Origin header, so MeTube's cross-origin
guard lets them through. POST /delete {ids: [url], where: "done"} clears
history entries; `done` is keyed by URL.
"""

import httpx


class MetubeError(Exception):
    pass


def watch_url(youtube_id: str) -> str:
    # Canonical form: a `&t=` would become a clip, a `&list=` a playlist.
    return f"https://www.youtube.com/watch?v={youtube_id}"


class MetubeClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def add(self, youtube_id: str) -> None:
        body = {
            "url": watch_url(youtube_id),
            "download_type": "video",
            "quality": "best",
            "format": "any",
            "codec": "auto",
        }
        data = self._call("POST", "/add", json=body)
        if not isinstance(data, dict) or data.get("status") != "ok":
            msg = data.get("msg") if isinstance(data, dict) else data
            raise MetubeError(f"MeTube refused {youtube_id}: {msg}")

    def failure(self, youtube_id: str) -> str | None:
        """yt-dlp's error message if MeTube's history has this download as failed."""
        for entry in self._failed_entries(youtube_id):
            return entry.get("msg") or entry.get("error") or "download failed in MeTube"
        return None

    def clear_failure(self, youtube_id: str) -> None:
        """Drop stale failed entries for this ID, so a retry isn't judged by an old error."""
        urls = [e["url"] for e in self._failed_entries(youtube_id) if e.get("url")]
        if urls:
            self._call("POST", "/delete", json={"ids": urls, "where": "done"})

    def _failed_entries(self, youtube_id: str) -> list[dict]:
        data = self._call("GET", "/history")
        done = data.get("done", []) if isinstance(data, dict) else []
        return [e for e in done if isinstance(e, dict)
                and e.get("id") == youtube_id and e.get("status") == "error"]

    def _call(self, method: str, path: str, **kw):
        try:
            r = httpx.request(method, self.base_url + path, timeout=self.timeout, **kw)
        except httpx.HTTPError as e:
            raise MetubeError(f"MeTube unreachable at {self.base_url}: {e}") from e
        if r.status_code >= 400:
            raise MetubeError(f"MeTube {method} {path} returned {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise MetubeError(f"MeTube {method} {path} returned non-JSON: {r.text[:200]}") from e

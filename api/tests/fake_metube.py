"""A stand-in for MeTube, speaking the same /add, /history and /delete contract.

It also answers YouTube's /oembed (SONGBOOK_OEMBED_URL points here in tests),
with titles from OEMBED_TITLES or "YouTube title <id>", like its info.json.

It records every /add call and, after a short delay, "downloads" by copying a
fixture to originals/<id>.webm (temp name, then rename, like yt-dlp). It runs as
a real HTTP server on 127.0.0.1 so the worker's sync client talks to it
unchanged; nothing leaves the machine.
"""

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from songbook.youtube import parse_id


# Video ID → (title, channel) for /oembed, for the Add song guess.
OEMBED_TITLES = {
    "Pzzzzzzzzzz": ("Black Sabbath - Paranoid (Official Video)", "BlackSabbathVEVO"),
}


class FakeMetube:
    def __init__(self, originals: Path, fixture: Path, delay: float = 0.1, info_json: bool = False,
                 unique: bool = False):
        self.originals = originals
        self.fixture = fixture
        self.delay = delay
        self.info_json = info_json  # also write <id>.info.json, as MeTube does with writeinfojson
        self.unique = unique  # tag each copy with its ID, so no two downloads share a sha256
        self.calls: list[dict] = []
        self.fail_status: int | None = None  # answer /add with this HTTP status
        self.yt_error: str | None = None     # accept /add, then report a failed download
        self.done: list[dict] = []
        self.app = Starlette(routes=[
            Route("/add", self._add, methods=["POST"]),
            Route("/history", self._history, methods=["GET"]),
            Route("/delete", self._delete, methods=["POST"]),
            Route("/oembed", self._oembed, methods=["GET"]),
        ])

    @property
    def add_calls(self) -> int:
        return len(self.calls)

    async def _add(self, request: Request):
        body = await request.json()
        self.calls.append(body)
        if self.fail_status:
            return JSONResponse({"error": "boom"}, status_code=self.fail_status)
        if not body.get("url") or not body.get("download_type") or not body.get("quality"):
            return JSONResponse({"error": "missing 'url', 'download_type', or 'quality'"}, status_code=400)
        yid = parse_id(body["url"])
        if self.yt_error:
            self.done.append({"id": yid, "url": body["url"], "status": "error", "msg": self.yt_error})
        else:
            threading.Timer(self.delay, self._write, args=(yid,)).start()
        return JSONResponse({"status": "ok"})

    async def _history(self, request: Request):
        return JSONResponse({"queue": [], "pending": [], "done": self.done})

    async def _delete(self, request: Request):
        body = await request.json()
        self.done = [d for d in self.done if d["url"] not in body.get("ids", [])]
        return JSONResponse({"status": "ok"})

    async def _oembed(self, request: Request):
        try:
            yid = parse_id(request.query_params.get("url", ""))
        except ValueError:
            return JSONResponse({"error": "Not Found"}, status_code=404)
        title, author = OEMBED_TITLES.get(yid, (f"YouTube title {yid}", "Fake Uploader"))
        return JSONResponse({"title": title, "author_name": author, "type": "video"})

    def _write(self, yid: str) -> None:
        if self.info_json:
            (self.originals / f"{yid}.info.json").write_text(
                json.dumps({"id": yid, "title": f"YouTube title {yid}", "uploader": "Fake Uploader"}))
        tmp = self.originals / f"{yid}.webm.part"
        if self.unique:
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(self.fixture), "-c", "copy",
                            "-metadata", f"comment={yid}", "-f", "webm", str(tmp)], check=True)
        else:
            shutil.copy(self.fixture, tmp)
        os.replace(tmp, self.originals / f"{yid}.webm")


class Server:
    """Run an ASGI app with uvicorn on a free 127.0.0.1 port, in a thread."""

    def __init__(self, app):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("fake MeTube did not start")
            time.sleep(0.01)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(5)


def main() -> None:
    """Serve the fake on its own, for compose.fake-metube.yml: python -m tests.fake_metube"""
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--originals", type=Path, default=Path("/downloads"))
    ap.add_argument("--fixture", type=Path, default=Path(__file__).resolve().parents[2] / "fixtures" / "originals" / "AAAAAAAAAAA.webm")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8081)
    args = ap.parse_args()
    fake = FakeMetube(args.originals, args.fixture, delay=0.5, info_json=True, unique=True)
    uvicorn.run(fake.app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

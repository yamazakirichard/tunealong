#!/usr/bin/env python3
"""Dev and e2e stack in one process: the API (serving web/dist), the worker and
a fake MeTube, over a scratch TUNEALONG_ROOT seeded with the webm fixtures.

    python scripts/dev_stack.py [--port 8080] [--root DIR]

Dev-only routes on the API port: POST /__dev/reset wipes the library back to
the two fixture songs (Playwright calls it before each test), and GET
/__dev/calls lists what the fake MeTube was asked for. Never point this at
real data: --root is wiped on start and on every reset.
"""

import argparse
import dataclasses
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(HERE / "api")]

import uvicorn  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

from tunealong import config, db, ingest  # noqa: E402
from tunealong.main import create_app  # noqa: E402
from tunealong.worker import Worker  # noqa: E402
from tests.fake_metube import FakeMetube, Server  # noqa: E402

MARKER = ".tunealong-dev-root"
SEED = ("AAAAAAAAAAA.webm", "BBBBBBBBBBB.webm")  # webm only: Chromium can't play the mp4 fixture


def seed(settings: config.Settings, conn) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")
    for table in ("song_categories", "presets", "renders", "songs", "artists", "categories", "jobs", "ignored_paths"):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("PRAGMA foreign_keys = ON")
    for d in (settings.originals_dir, settings.renders_dir, settings.artist_images_dir):
        shutil.rmtree(d, ignore_errors=True)
    config.ensure_dirs(settings)
    for name in SEED:
        shutil.copy(HERE / "fixtures" / "originals" / name, settings.originals_dir / name)
    ingest.scan(conn, settings)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = (args.root or Path(tempfile.mkdtemp(prefix="tunealong-dev-"))).resolve()
    if root.exists() and any(root.iterdir()) and not (root / MARKER).exists():
        sys.exit(f"refusing to wipe {root}: it has files but no {MARKER} marker (not a dev root)")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    (root / MARKER).write_text("scratch root of scripts/dev_stack.py; wiped on every start\n")
    os.environ["TUNEALONG_ROOT"] = str(root)
    settings = config.load()
    config.ensure_dirs(settings)
    conn = db.open_db(settings.db_path)
    seed(settings, conn)

    fake = FakeMetube(settings.originals_dir, HERE / "fixtures" / "originals" / "AAAAAAAAAAA.webm",
                      delay=0.5, info_json=True, unique=True)
    metube = Server(fake.app)
    metube.__enter__()

    web_dir = HERE / "web" / "dist"
    settings = dataclasses.replace(settings, metube_url=metube.url, oembed_url=f"{metube.url}/oembed",
                                   audiodb_url=f"{metube.url}/audiodb", web_dir=web_dir,
                                   download_poll_s=0.1, worker_idle_s=0.1)
    worker = Worker(settings)
    threading.Thread(target=worker.run_forever, daemon=True).start()

    lock = threading.Lock()

    def reset(request):
        with lock:
            # Let a running render or download finish first, so it can't write into the fresh state.
            for _ in range(300):
                if not conn.execute("SELECT 1 FROM jobs WHERE status = 'running'").fetchone():
                    break
                time.sleep(0.05)
            fake.calls.clear()
            fake.done.clear()
            fake.fail_status = None
            seed(settings, conn)
        return JSONResponse({"status": "ok"})

    def calls(request):
        return JSONResponse({"calls": fake.calls})

    app = create_app(settings)
    # Before the static-files mount at "/", which would otherwise answer first.
    app.router.routes[:0] = [Route("/__dev/reset", reset, methods=["POST"]), Route("/__dev/calls", calls)]

    print(f"tunealong dev stack: http://127.0.0.1:{args.port}  root={root}  fake MeTube={metube.url}", flush=True)
    if not (web_dir / "index.html").is_file():
        print("note: web/dist is missing, so only the API is served (run `make build`)", flush=True)
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

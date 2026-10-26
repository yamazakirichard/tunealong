"""Container healthchecks: `python -m songbook.healthcheck api|worker`.

api     GET <base path>/api/health on the local port (the DB must answer).
worker  the heartbeat file was touched recently (a thread beats every 15 s).
"""

import os
import sys
import time
import urllib.request

from . import config


def main(role: str) -> int:
    settings = config.load()
    if role == "api":
        url = f"http://127.0.0.1:{os.environ.get('PORT', '8080')}{settings.base_path}/api/health"
        try:
            with urllib.request.urlopen(url, timeout=4) as r:
                return 0 if r.status == 200 else 1
        except OSError as e:
            print(f"unhealthy: {url}: {e}", file=sys.stderr)
            return 1
    if role == "worker":
        hb = settings.heartbeat_path
        if hb is None:
            print("unhealthy: SONGBOOK_HEARTBEAT is not set", file=sys.stderr)
            return 1
        try:
            age = time.time() - hb.stat().st_mtime
        except OSError as e:
            print(f"unhealthy: {e}", file=sys.stderr)
            return 1
        return 0 if age < 60 else 1
    print(f"usage: python -m songbook.healthcheck api|worker (got {role!r})", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "api"))

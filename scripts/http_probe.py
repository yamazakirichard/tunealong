#!/usr/bin/env python3
"""Tiny HTTP probe for scripts/compose_test.sh (runs in a --network host container).

    http_probe.py URL [--user U --password P] [--expect STATUS] [--contains TEXT]

Exits 0 when the status (and body text, if given) match, else prints why and exits 1.
"""

import argparse
import base64
import sys
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("url")
ap.add_argument("--user")
ap.add_argument("--password")
ap.add_argument("--expect", type=int, default=200)
ap.add_argument("--contains")
a = ap.parse_args()

req = urllib.request.Request(a.url)
if a.user is not None:
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{a.user}:{a.password}".encode()).decode())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


try:
    r = urllib.request.build_opener(NoRedirect).open(req, timeout=10)
    status, body = r.status, r.read().decode(errors="replace")
except urllib.error.HTTPError as e:
    status, body = e.code, e.read().decode(errors="replace")
except OSError as e:
    print(f"{a.url}: {e}")
    sys.exit(1)

ok = status == a.expect and (a.contains is None or a.contains in body)
if not ok:
    print(f"{a.url}: got {status}, want {a.expect}" + (f" containing {a.contains!r}" if a.contains else ""))
sys.exit(0 if ok else 1)

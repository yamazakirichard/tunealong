#!/usr/bin/env python3
"""Static Gate 7 checks over Songbook/ (tracked and new files, not ignored ones):

1. No hardcoded hostnames or IPs: outside docs, every domain found must be on
   a small allowlist (YouTube hosts the URL parser accepts, project and licence
   URLs in comments). Anywhere, docs included, no private-network names
   (*.local, *.lan, *.home, *.internal) and no private IPs.
2. Nothing references a path outside Songbook/: no symlinks, and every
   relative "../" path in a file resolves inside the project.

Exits non-zero on any finding.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = {"README.md", "NOTICE", "DECISIONS.md", "LICENSE", ".env.example"}
SKIP_SUFFIX = {".png", ".jpg", ".webm", ".mp4", ".mkv", ".mp3", ".m4a", ".sqlite"}
SKIP_NAMES = {"package-lock.json"}
ALLOWED_DOMAINS = {
    # parsed or produced by songbook/youtube.py and songbook/metube.py
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be",
    "youtube-nocookie.com", "www.youtube-nocookie.com", "notyoutube.com", "vimeo.com",  # last two: test negatives
    # artist pictures (songbook/config.py)
    "www.theaudiodb.com",
    # credits and references in comments
    "github.com", "registry.npmjs.org", "mcr.microsoft.com", "ghcr.io", "fsf.org", "gnu.org", "www.gnu.org",
    "example.com",
}
DOMAIN = re.compile(r"\b((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|be|dev|local|lan|home|internal|arpa))\b", re.I)
PRIVATE_IP = re.compile(r"\b(?:10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)\b")
PRIVATE_TLD = (".local", ".lan", ".home", ".internal")
RELPATH = re.compile(r"""(?<![\w.])((?:\.\./)+[\w.@-][\w.@/-]*)""")  # a real path after the ../


def files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "."],
                         cwd=ROOT, capture_output=True, check=True).stdout.decode().split("\0")
    return [ROOT / f for f in out if f and (ROOT / f).exists()]


def main() -> int:
    problems = []
    for f in files():
        rel = f.relative_to(ROOT)
        if f.is_symlink():
            problems.append(f"symlink: {rel} -> {f.readlink()}")
            continue
        if f.suffix in SKIP_SUFFIX or f.name in SKIP_NAMES or rel.parts[0] == "plan":
            continue
        try:
            text = f.read_text()
        except UnicodeDecodeError:
            continue
        doc = f.name in DOCS
        for n, line in enumerate(text.splitlines(), 1):
            for d in DOMAIN.findall(line):
                if d.lower().endswith(PRIVATE_TLD):
                    problems.append(f"private-network name {d!r}: {rel}:{n}: {line.strip()[:100]}")
            if PRIVATE_IP.search(line):
                problems.append(f"private IP: {rel}:{n}: {line.strip()[:100]}")
            if not doc:
                for d in DOMAIN.findall(line):
                    if d.lower() not in ALLOWED_DOMAINS:
                        problems.append(f"hostname {d!r}: {rel}:{n}: {line.strip()[:100]}")
            for m in RELPATH.findall(line):
                target = (f.parent / m).resolve()
                if not target.is_relative_to(ROOT):
                    problems.append(f"path outside Songbook/: {rel}:{n}: {m}")
    for p in problems:
        print(p)
    print(f"{len(problems)} problem(s) in {ROOT.name}/")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

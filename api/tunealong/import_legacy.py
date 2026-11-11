"""CLI: python -m tunealong.import_legacy <dir> [--dry-run]"""

import argparse
import sys
from pathlib import Path

from . import config, db, importer


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tunealong.import_legacy", description=__doc__)
    ap.add_argument("dir", type=Path, help="folder of existing MeTube downloads (top level only)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan without touching anything")
    args = ap.parse_args(argv)
    if not args.dir.is_dir():
        ap.error(f"not a directory: {args.dir}")

    settings = config.load()
    if args.dry_run and not settings.db_path.exists():
        # Don't create a DB just to plan: an empty in-memory one has nothing to dedup against.
        conn = db.open_db(":memory:", settings.busy_timeout_ms)
    else:
        config.ensure_dirs(settings)
        conn = db.open_db(settings.db_path, settings.busy_timeout_ms)
    try:
        actions = importer.plan(args.dir.resolve(), conn, settings)
        if not args.dry_run:
            importer.apply(actions, conn, settings)
    finally:
        conn.close()
    print(("DRY RUN: nothing changed\n" if args.dry_run else "") + importer.format_report(actions))
    return 0


if __name__ == "__main__":
    sys.exit(main())

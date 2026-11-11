"""FastAPI dependencies."""

import sqlite3
from collections.abc import Iterator

from fastapi import Request

from . import config, db


def get_settings(request: Request) -> config.Settings:
    return request.app.state.settings


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    # One connection per request: sync endpoints run in a thread pool, and
    # transactions on a shared connection would interleave.
    settings = request.app.state.settings
    conn = db.connect(settings.db_path, settings.busy_timeout_ms)
    try:
        yield conn
    finally:
        conn.close()

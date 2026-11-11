"""The jobs table: enqueue with dedup, claim atomically."""

import json
import sqlite3


def enqueue(conn: sqlite3.Connection, kind: str, payload: dict, dedupe_key: str | None) -> int | None:
    """Insert a pending job. Returns its id, or None if an identical job is already in flight."""
    row = conn.execute(
        "INSERT INTO jobs (kind, dedupe_key, payload) VALUES (?, ?, ?)"
        " ON CONFLICT DO NOTHING RETURNING id",
        (kind, dedupe_key, json.dumps(payload)),
    ).fetchone()
    return row["id"] if row else None


def claim(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Mark the oldest pending job running and return it (attempts already incremented)."""
    return conn.execute(
        "UPDATE jobs SET status = 'running', started_at = datetime('now'), attempts = attempts + 1"
        " WHERE id = (SELECT id FROM jobs WHERE status = 'pending' ORDER BY id LIMIT 1)"
        "   AND status = 'pending'"
        " RETURNING *"
    ).fetchone()
